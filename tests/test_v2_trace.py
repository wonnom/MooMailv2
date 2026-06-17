from __future__ import annotations

from moomail_finance_ai.metrics import calculate_snapshot_metrics
from moomail_finance_ai.mocks import mock_investment_policy, mock_portfolio_packet
from moomail_finance_ai.portfolio_agent import (
    EffectiveCashSummary,
    PortfolioAgentResult,
    PortfolioEvaluation,
    PortfolioHistoryContext,
    build_effective_cash_summary,
    plan_portfolio_context,
)
from moomail_finance_ai.sentiment_agent_stub import V2SentimentAgentStub
from moomail_finance_ai.v2_investment_agent import V2InvestmentAgent
from moomail_finance_ai.v2_schemas import PortfolioTask, TraceEvent
from moomail_finance_ai.v2_trace import sanitize_trace_event, trace_event_to_public_dict
from scripts.investment_agent_v2_review import v2_terminal_summary_lines


def test_trace_sanitizer_removes_sensitive_fields():
    event = TraceEvent(
        event_type="status",
        run_id="v2_trace_test",
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
    agent = V2InvestmentAgent(
        portfolio_agent=TracePortfolioAgent(),
        sentiment_agent=V2SentimentAgentStub(),
        ips=mock_investment_policy(),
    )

    state = agent.run("Review my portfolio.", status_callback=emitted.append)

    statuses = [event.status for event in emitted]
    event_types = [event.event_type for event in emitted]
    tool_events = [event for event in state.status_events if event.event_type == "tool_call"]

    assert "classifying_query" in statuses
    assert "planning_subagent_calls" in statuses
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


def test_trace_sanitizer_runs_before_state_storage():
    event = sanitize_trace_event(
        TraceEvent(
            event_type="status",
            run_id="v2_trace_test",
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


def test_v2_agent_emits_error_trace_when_graph_fails():
    emitted = []
    agent = V2InvestmentAgent(
        portfolio_agent=ExplodingPortfolioAgent(),
        sentiment_agent=V2SentimentAgentStub(),
        ips=mock_investment_policy(),
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


def test_v2_terminal_summary_includes_guardrails_and_trace():
    agent = V2InvestmentAgent(
        portfolio_agent=TracePortfolioAgent(),
        sentiment_agent=V2SentimentAgentStub(),
        ips=mock_investment_policy(),
    )
    state = agent.run("Review my portfolio.")

    output = "\n".join(v2_terminal_summary_lines(state, graph_runtime=agent.graph_runtime))

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
    ) -> PortfolioAgentResult:
        del query, status_callback
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
            context_plan=plan_portfolio_context(
                portfolio_task
                or PortfolioTask(task_type="full_review", source_query="Review")
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


class ExplodingPortfolioAgent:
    def run(self, *args, **kwargs):
        raise RuntimeError("synthetic failure api_key=sk-hidden123456")
