from __future__ import annotations

from datetime import UTC, datetime

from moomail_finance_ai.metrics import calculate_snapshot_metrics
from moomail_finance_ai.mocks import mock_investment_policy, mock_portfolio_packet
from moomail_finance_ai.portfolio_agent import (
    EffectiveCashSummary,
    PortfolioAgentResult,
    PortfolioEvaluation,
    PortfolioHistoryContext,
    build_effective_cash_summary,
)
from moomail_finance_ai.sentiment_agent_stub import SentimentAgentStub
from moomail_finance_ai.schemas import StatusEvent
from moomail_finance_ai.investment_agent import InvestmentAgent
from moomail_finance_ai.agent_schemas import (
    InvestmentAgentState,
    InvestmentPlan,
    PortfolioContextPlan,
    PortfolioEvidencePacket,
    PortfolioRequest,
    PortfolioTask,
    SentimentTask,
    TraceEvent,
)
from moomail_finance_ai.agent_trace import sanitize_trace_event, trace_event_to_public_dict
from moomail_finance_ai.user_trace import build_trace_summary, build_user_progress
from scripts.investment_agent_review import investment_terminal_summary_lines


def test_trace_sanitizer_removes_sensitive_fields():
    event = TraceEvent(
        event_type="status",
        run_id="agent_trace_test",
        status="debug",
        message="api_key=sk-secret123456 should not appear",
        metadata={
            "phase": "debug",
            "chain_of_thought": "hidden reasoning",
            "raw_prompt": "system prompt",
            "broker_account_id": "123456",
            "warning_count": 1,
        },
    )

    public = trace_event_to_public_dict(event)

    assert "sk-secret" not in public["message"]
    assert public["metadata"] == {"phase": "debug", "warning_count": 1}


def test_trace_includes_graph_tool_sentiment_and_guardrail_events():
    emitted = []
    agent = InvestmentAgent(
        portfolio_agent=TracePortfolioAgent(),
        sentiment_agent=SentimentAgentStub(),
        ips=mock_investment_policy(),
        planner=TraceInvestmentPlanner(),
    )

    state = agent.run("Review my portfolio.", status_callback=emitted.append)

    statuses = [event.status for event in emitted]
    event_types = [event.event_type for event in emitted]
    tool_events = [event for event in state.status_events if event.event_type == "tool_call"]

    assert "planning_investment" in statuses
    assert "investment_plan_ready" in statuses
    assert "investment_plan_validated" in statuses
    assert "planned_portfolio_tool" in statuses
    assert "called_portfolio_tool" in statuses
    assert "skipped_portfolio_tool" in statuses
    assert "sentiment_stub_status" in statuses
    assert "guardrails_passed" in statuses
    assert statuses[-1] == "complete"
    assert "tool_call" in event_types
    assert [event.tool_name for event in tool_events] == [
        "opend_get_positions",
        "opend_get_positions",
        "portfolio_sql_latest_state",
    ]
    nested = [event for event in state.status_events if event.child_run_id == "trace_portfolio_run"]
    assert nested
    assert len([event for event in nested if event.status == "planned_portfolio_tool"]) == 1
    assert len([event for event in nested if event.status == "called_portfolio_tool"]) == 1
    assert len([event for event in nested if event.status == "skipped_portfolio_tool"]) == 1


def test_trace_sanitizer_runs_before_state_storage():
    event = sanitize_trace_event(
        TraceEvent(
            event_type="status",
            run_id="agent_trace_test",
            status="debug",
            message="safe message",
            metadata={
                "phase": "debug",
                "api_key": "sk-hidden123456",
                "result": "ok",
            },
        )
    )

    assert event.metadata == {"phase": "debug", "result": "ok"}


def test_trace_sanitizer_allows_v1_5_route_and_llm_metadata():
    event = sanitize_trace_event(
        TraceEvent(
            event_type="llm_call",
            run_id="agent_trace_test",
            phase="llm_call",
            status="llm_call_completed",
            message="Investment planning call completed.",
            subagent="investment_agent",
            group_key="llm.investment_planning",
            metadata={
                "route": "direct_context",
                "route_reasons": ["baseline_sufficient"],
                "coverage_result": "covered",
                "llm_purpose": "investment_planning",
                "provider": "openai",
                "model": "test-model",
                "duration_ms": 25,
                "input_tokens": 100,
                "output_tokens": 20,
                "total_tokens": 120,
                "attempt": 1,
            },
        )
    )

    assert event.group_key == "llm.investment_planning"
    assert event.metadata["route"] == "direct_context"
    assert event.metadata["total_tokens"] == 120


def test_trace_sanitizer_denies_raw_broker_payload_and_account_id():
    event = sanitize_trace_event(
        TraceEvent(
            run_id="agent_trace_test",
            status="debug",
            message="Sanitize metadata.",
            metadata={
                "raw_broker_payload": {"positions": []},
                "account_id": "sensitive-account",
                "result": "ok",
            },
        )
    )

    assert event.metadata == {"result": "ok"}


def test_user_progress_collapses_internal_status_spam_into_plain_ordered_stages():
    run_id = "progress_run"
    events = [
        TraceEvent(run_id=run_id, status="loading_policy", message="internal"),
        TraceEvent(
            run_id=run_id,
            status="portfolio_baseline_ready",
            message="internal",
            phase="baseline_context",
            metadata={"as_of": "2026-08-03T13:55:00+00:00"},
        ),
        TraceEvent(
            event_type="tool_call",
            run_id=run_id,
            status="planned_portfolio_tool",
            message="planned:server:tool",
            phase="deterministic_tool_execution",
            subagent="portfolio_agent",
            tool_name="tool",
        ),
        TraceEvent(
            event_type="tool_call",
            run_id=run_id,
            status="called_portfolio_tool",
            message="server:tool",
            phase="deterministic_tool_execution",
            subagent="portfolio_agent",
            tool_name="tool",
        ),
        TraceEvent(run_id=run_id, status="checking_guardrails", message="internal"),
        TraceEvent(run_id=run_id, status="complete", message="internal"),
    ]

    progress = build_user_progress(events)

    assert [event.stage for event in progress] == [
        "reviewing_request",
        "loading_saved_portfolio",
        "retrieving_portfolio_details",
        "checking_safety",
        "complete",
    ]
    assert len([event for event in progress if event.stage == "retrieving_portfolio_details"]) == 1
    assert all("planned_portfolio_tool" not in event.message for event in progress)
    assert all("_" not in event.message for event in progress)
    assert "as of 2026-08-03" in progress[1].message


def test_trace_summary_groups_tools_and_retains_sanitized_source_detail():
    state = InvestmentAgentState(run_id="trace_summary", user_query="Review")
    state.status_events = [
        TraceEvent(
            event_type="tool_call",
            run_id=state.run_id,
            status=status,
            message=message,
            phase="deterministic_tool_execution",
            subagent="portfolio_agent",
            server_name="portfolio-sql",
            tool_name="history_status",
            child_run_id="portfolio_child",
        )
        for status, message in [
            ("planned_portfolio_tool", "Planned bounded history status read."),
            ("called_portfolio_tool", "Completed bounded history status read."),
            ("skipped_portfolio_tool", "Skipped duplicate history status read."),
        ]
    ]

    summary = build_trace_summary(state)

    assert summary["tools"]["planned"]["count"] == 1
    assert summary["tools"]["actual"]["count"] == 1
    assert summary["tools"]["skipped"]["count"] == 1
    assert len(summary["source_events"]) == len(state.status_events)
    assert summary["source_events"][0]["child_run_id"] == "portfolio_child"
    assert "user_query" not in summary


def test_terminal_failure_progress_is_actionable_and_preserves_dashboard_expectation():
    progress = build_user_progress(
        [
            TraceEvent(
                event_type="error",
                run_id="failure_run",
                status="portfolio_analysis_failed",
                message="internal failure",
                error_type="RuntimeError",
                error_message="provider error",
            )
        ]
    )

    assert len(progress) == 1
    assert progress[0].stage == "failed"
    assert progress[0].status == "failed"
    assert "saved dashboard is unchanged" in progress[0].message


def test_agent_emits_error_trace_when_graph_fails():
    emitted = []
    agent = InvestmentAgent(
        portfolio_agent=ExplodingPortfolioAgent(),
        sentiment_agent=SentimentAgentStub(),
        ips=mock_investment_policy(),
        planner=TraceInvestmentPlanner(),
    )

    try:
        agent.run("Review my portfolio.", status_callback=emitted.append)
    except RuntimeError:
        pass

    error_events = [event for event in emitted if event.event_type == "error"]
    assert error_events
    assert error_events[-1].error_type == "RuntimeError"
    assert "sk-hidden" not in (error_events[-1].error_message or "")
    assert "[redacted]" in (error_events[-1].error_message or "")


def test_terminal_summary_includes_guardrails_and_trace():
    agent = InvestmentAgent(
        portfolio_agent=TracePortfolioAgent(),
        sentiment_agent=SentimentAgentStub(),
        ips=mock_investment_policy(),
        planner=TraceInvestmentPlanner(),
    )
    state = agent.run("Review my portfolio.")

    output = "\n".join(investment_terminal_summary_lines(state, graph_runtime=agent.graph_runtime))

    assert "Guardrails: approved" in output
    assert "Guardrail checks: 6 passed" in output
    assert "Trace:" in output
    assert "planned_portfolio_tool" in output
    assert "sentiment_stub_status" in output


class TracePortfolioAgent:
    def run(
        self,
        query: str,
        ips,
        *,
        status_callback=None,
        portfolio_task: PortfolioTask | None = None,
        portfolio_request: PortfolioRequest | None = None,
    ) -> PortfolioAgentResult:
        del query, portfolio_request
        for status, message in [
            ("planning_portfolio_evidence", "Compiling bounded portfolio evidence."),
            (
                "planned_portfolio_tool",
                "planned:moomail-opend-mcp:opend_get_positions",
            ),
            (
                "called_portfolio_tool",
                "moomail-opend-mcp:opend_get_positions",
            ),
            (
                "skipped_portfolio_tool",
                "skipped:moomail-portfolio-sql-mcp:portfolio_sql_latest_state reason=no_history",
            ),
            ("portfolio_evidence_packet_ready", "Portfolio evidence is ready."),
        ]:
            if status_callback is not None:
                status_callback(
                    StatusEvent(
                        run_id="trace_portfolio_run",
                        status=status,
                        message=message,
                        timestamp=datetime.now(UTC),
                    )
                )
        packet = mock_portfolio_packet()
        metrics = calculate_snapshot_metrics(packet.snapshot, ips)
        effective_cash: EffectiveCashSummary = build_effective_cash_summary(packet.snapshot)
        history_context = PortfolioHistoryContext(
            history_status={"snapshot_count": 1, "data_quality": {"warnings": []}},
            latest_portfolio_state=None,
            portfolio_growth=[],
            allocation_history=[],
        )
        return PortfolioAgentResult(
            run_id="trace_portfolio_run",
            portfolio_id=packet.portfolio_id,
            context_plan=_trace_context_plan(portfolio_task),
            evidence_packet=PortfolioEvidencePacket(
                portfolio_id=packet.portfolio_id,
                task_intent=(portfolio_task.task_type if portfolio_task else "full_review"),
                facts={
                    "snapshot": {
                        "portfolio_id": packet.portfolio_id,
                        "holding_count": len(packet.snapshot.holdings),
                    }
                },
                derived_metrics={
                    "metrics": [metric.model_dump(mode="json") for metric in metrics]
                },
                limitations=[
                    "No sentiment or fundamental evidence was reviewed by Portfolio Agent."
                ],
                tool_refs=[
                    "planned:moomail-opend-mcp:opend_get_positions",
                    "moomail-opend-mcp:opend_get_positions",
                ],
            ),
            snapshot=packet.snapshot,
            portfolio_packet=packet,
            metrics=metrics,
            storage_result={"status": "inserted"},
            metrics_storage_result={"metrics_stored": 0, "weight_rows_stored": 0},
            effective_cash=effective_cash,
            history_status=history_context.history_status,
            history_context=history_context,
            evaluation=PortfolioEvaluation(summary="Trace portfolio evaluation complete."),
            tool_calls=[
                "planned:moomail-opend-mcp:opend_get_positions",
                "moomail-opend-mcp:opend_get_positions",
                "skipped:moomail-portfolio-sql-mcp:portfolio_sql_latest_state reason=no_history",
            ],
            status_events=[],
            warnings=[],
        )


class TraceInvestmentPlanner:
    def plan(self, query: str, ips) -> InvestmentPlan:
        del ips
        return InvestmentPlan(
            mode="review",
            needs_portfolio_agent=True,
            needs_sentiment_agent=True,
            portfolio_request=PortfolioRequest(
                task_intent="full_review",
                output_goals=[
                    "snapshot",
                    "allocation_context",
                    "risk_context",
                    "portfolio_patterns",
                    "sentiment_context_needs",
                ],
                source_query=query,
            ),
            sentiment_task=SentimentTask(key_questions=[query]),
            themes=["portfolio_review"],
        )


def _trace_context_plan(portfolio_task: PortfolioTask | None) -> PortfolioContextPlan:
    return PortfolioContextPlan(
        needs_current_snapshot=True,
        needs_sql_history=True,
        history_queries=[
            "history_status",
            "latest_state",
            "portfolio_growth",
            "allocation_history",
            "position_state_changes",
        ],
        tickers=list(portfolio_task.requested_tickers) if portfolio_task else [],
        metric_groups=["allocation", "concentration", "effective_cash", "risk", "performance"],
        persist_observation=True,
        history_window=portfolio_task.history_window if portfolio_task else "30d",
        row_limit=100,
    )


class ExplodingPortfolioAgent:
    def run(self, *args, **kwargs):
        raise RuntimeError("synthetic failure api_key=sk-hidden123456")
