from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from moomail_finance_ai.metrics import calculate_snapshot_metrics
from moomail_finance_ai.mocks import mock_investment_policy, mock_portfolio_packet
from moomail_finance_ai.portfolio_agent import (
    EffectiveCashSummary,
    PortfolioAnalysisUnavailableError,
    PortfolioAgentResult,
    PortfolioEvaluation,
    PortfolioHistoryContext,
    build_effective_cash_summary,
)
from moomail_finance_ai.portfolio_evidence_planner import (
    PortfolioEvidencePlanValidationError,
)
from moomail_finance_ai.sentiment_agent_stub import SentimentAgentStub
from moomail_finance_ai.investment_agent import (
    InvestmentAgent,
    classify_investment_query,
)
from moomail_finance_ai.agent_schemas import (
    AssetHint,
    BaselineSummary,
    EvidenceRef,
    InvestmentPlan,
    InvestmentTurnDecision,
    LLMCallTrace,
    PortfolioBaselinePacket,
    PortfolioContextPlan,
    PortfolioEvidencePacket,
    PortfolioRequest,
    PortfolioTask,
    SentimentPacket,
    SentimentTask,
)


def test_dependency_strategy_uses_real_langgraph_runtime():
    agent = InvestmentAgent(
        portfolio_agent=FakePortfolioAgent(),
        sentiment_agent=FakeSentimentAgent(),
        ips=mock_investment_policy(),
        planner=FixtureInvestmentPlanner(),
    )

    assert agent.graph_runtime == "langgraph_state_graph"
    assert hasattr(agent.graph, "invoke")


def test_classifier_cash_query_portfolio_only():
    plan = classify_investment_query(
        "How much effective cash do I have?",
        planner=FixtureInvestmentPlanner(),
    )

    assert plan.mode == "portfolio_fact"
    assert plan.needs_portfolio_agent is True
    assert plan.needs_sentiment_agent is False
    assert plan.portfolio_task is not None
    assert plan.portfolio_task.required_outputs == ["snapshot", "effective_cash"]
    assert plan.sentiment_task is None


def test_investment_agent_emits_plan_before_portfolio_call():
    emitted = []
    portfolio_agent = FakePortfolioAgent()
    agent = InvestmentAgent(
        portfolio_agent=portfolio_agent,
        sentiment_agent=FakeSentimentAgent(),
        ips=mock_investment_policy(),
        planner=FixtureInvestmentPlanner(),
    )

    state = agent.run("How much effective cash do I have?", status_callback=emitted.append)

    statuses = [event.status for event in emitted]
    assert state.investment_plan is not None
    assert state.investment_plan.portfolio_request is not None
    assert statuses.index("investment_plan_validated") < statuses.index("calling_portfolio_agent")
    assert portfolio_agent.calls == 1


def test_investment_agent_validates_plan_before_subagent_calls():
    portfolio_agent = FakePortfolioAgent()
    sentiment_agent = FakeSentimentAgent()
    agent = InvestmentAgent(
        portfolio_agent=portfolio_agent,
        sentiment_agent=sentiment_agent,
        ips=mock_investment_policy(),
        planner=InvalidTradeIntentPlanner(),
    )

    state = agent.run("Show my portfolio.", status_callback=lambda _event: None)

    assert portfolio_agent.calls == 0
    assert sentiment_agent.calls == 0
    assert state.final_report is not None
    assert state.final_report.title == "Investment Planning Unavailable"
    assert "No keyword or regex planner" in state.final_report.summary
    assert state.guardrail_review is not None
    assert state.guardrail_review.passed is True


def test_routing_portfolio_only_skips_sentiment():
    portfolio_agent = FakePortfolioAgent()
    sentiment_agent = FakeSentimentAgent()
    agent = InvestmentAgent(
        portfolio_agent=portfolio_agent,
        sentiment_agent=sentiment_agent,
        ips=mock_investment_policy(),
        planner=FixtureInvestmentPlanner(),
    )

    state = agent.run("How much effective cash do I have?")

    assert portfolio_agent.calls == 1
    assert portfolio_agent.last_task is not None
    assert portfolio_agent.last_task.task_type == "portfolio_fact"
    assert sentiment_agent.calls == 0
    assert state.query_plan is not None
    assert state.investment_plan is not None
    assert state.query_plan.mode == "portfolio_fact"
    assert state.investment_plan.portfolio_request is not None
    assert state.investment_plan.portfolio_request.task_intent == "portfolio_fact"
    assert state.query_plan.needs_sentiment_agent is False
    assert state.final_report is not None
    assert state.final_report.sentiment_analysis == {}
    assert "Sentiment Agent GraphRAG retrieval" not in state.final_report.missing_data


def test_full_review_routes_portfolio_then_sentiment_stub():
    portfolio_agent = FakePortfolioAgent()
    sentiment_agent = FakeSentimentAgent()
    agent = InvestmentAgent(
        portfolio_agent=portfolio_agent,
        sentiment_agent=sentiment_agent,
        ips=mock_investment_policy(),
        planner=FixtureInvestmentPlanner(),
    )

    state = agent.run("Review my portfolio and market sentiment.")

    assert portfolio_agent.calls == 1
    assert portfolio_agent.last_task is not None
    assert portfolio_agent.last_task.task_type == "deep_dive"
    assert sentiment_agent.calls == 1
    assert sentiment_agent.last_task is not None
    assert sentiment_agent.last_task.tickers == ["MSFT", "AAPL"]
    assert state.portfolio_packet is not None
    assert state.portfolio_packet.context_plan.persist_observation is True
    assert "fake_portfolio_agent" in state.portfolio_packet.tool_calls
    assert [candidate.ticker for candidate in state.portfolio_packet.sentiment_candidates] == [
        "MSFT",
        "AAPL",
    ]
    assert state.sentiment_packet is not None
    assert state.sentiment_packet.retrieval_status == "not_implemented"


def test_investment_agent_routes_sentiment_without_portfolio_agent_deciding():
    portfolio_agent = FakePortfolioAgent(candidate_weights=False)
    sentiment_agent = FakeSentimentAgent()
    agent = InvestmentAgent(
        portfolio_agent=portfolio_agent,
        sentiment_agent=sentiment_agent,
        ips=mock_investment_policy(),
        planner=FixtureInvestmentPlanner(),
    )

    state = agent.run("Review my portfolio.")

    assert state.investment_plan is not None
    assert state.investment_plan.needs_sentiment_agent is True
    assert sentiment_agent.calls == 1
    assert sentiment_agent.last_task is not None
    assert sentiment_agent.last_task.key_questions == ["Review my portfolio."]


def test_full_review_includes_missing_research_without_fake_citations():
    agent = InvestmentAgent(
        portfolio_agent=FakePortfolioAgent(),
        sentiment_agent=SentimentAgentStub(),
        ips=mock_investment_policy(),
        planner=FixtureInvestmentPlanner(),
    )

    state = agent.run("Review my portfolio.")

    assert state.final_report is not None
    assert "Sentiment Agent GraphRAG retrieval is not implemented." in (
        state.final_report.missing_data
    )
    assert state.final_report.citations == []
    assert state.final_report.sentiment_analysis["retrieval_status"] == "not_implemented"
    assert "GraphRAG is not connected yet" in state.final_report.summary
    assert state.guardrail_review is not None
    assert state.guardrail_review.passed is True


def test_user_named_sentiment_query_scopes_requested_ticker():
    sentiment_agent = FakeSentimentAgent()
    agent = InvestmentAgent(
        portfolio_agent=FakePortfolioAgent(candidate_weights=False),
        sentiment_agent=sentiment_agent,
        ips=mock_investment_policy(),
        planner=FixtureInvestmentPlanner(),
    )

    state = agent.run("What does recent research say about GOOG?")

    assert state.query_plan is not None
    assert state.query_plan.mode == "deep_dive"
    assert sentiment_agent.calls == 1
    assert sentiment_agent.last_task is not None
    assert sentiment_agent.last_task.tickers == ["GOOG"]


def test_golden_recent_purchase_query_uses_bounded_history_request():
    portfolio_agent = FakePortfolioAgent()
    sentiment_agent = FakeSentimentAgent()
    agent = InvestmentAgent(
        portfolio_agent=portfolio_agent,
        sentiment_agent=sentiment_agent,
        ips=mock_investment_policy(),
        planner=FixtureInvestmentPlanner(),
    )

    state = agent.run("What price did I buy my recent AMZN shares at?")

    assert portfolio_agent.calls == 1
    assert portfolio_agent.last_request is not None
    assert portfolio_agent.last_request.task_intent == "what_changed"
    assert portfolio_agent.last_request.asset_hints[0].raw_input == "AMZN"
    assert portfolio_agent.last_request.freshness_requirement == "history_only"
    assert "position_changes" in portfolio_agent.last_request.output_goals
    assert sentiment_agent.calls == 0
    assert state.portfolio_packet is not None
    assert state.portfolio_packet.evidence_packet is not None


def test_streamed_status_events_include_graph_steps():
    emitted = []
    agent = InvestmentAgent(
        portfolio_agent=FakePortfolioAgent(),
        sentiment_agent=FakeSentimentAgent(),
        ips=mock_investment_policy(),
        planner=FixtureInvestmentPlanner(),
    )

    state = agent.run("Review my portfolio.", status_callback=emitted.append)

    statuses = [event.status for event in emitted]
    assert statuses[0] == "loading_policy"
    assert "planning_investment" in statuses
    assert "loading_portfolio_baseline" in statuses
    assert "portfolio_baseline_ready" in statuses
    assert "investment_turn_ready" in statuses
    assert "investment_plan_ready" in statuses
    assert "validating_investment_route" in statuses
    assert "investment_route_validated" in statuses
    assert "investment_plan_validated" in statuses
    assert "loading_policy" in statuses
    assert "calling_portfolio_agent" in statuses
    assert "calling_sentiment_agent" in statuses
    assert "checking_guardrails" in statuses
    assert "guardrails_passed" in statuses
    assert statuses[-1] == "complete"
    assert len(emitted) == len(state.status_events)


def test_investment_planner_trace_is_sanitized():
    emitted = []
    agent = InvestmentAgent(
        portfolio_agent=FakePortfolioAgent(),
        sentiment_agent=FakeSentimentAgent(),
        ips=mock_investment_policy(),
        planner=FixtureInvestmentPlanner(),
    )

    agent.run("What price did I buy my recent AMZN shares at?", status_callback=emitted.append)

    planner_events = [
        event
        for event in emitted
        if event.phase == "investment_planner" and event.status != "investment_plan_ready"
    ]
    assert [event.status for event in planner_events] == [
        "planning_investment",
        "investment_turn_ready",
    ]
    summary = planner_events[-1].metadata
    assert summary["route"] == "delegate_portfolio"
    assert summary["portfolio_task_intent"] == "what_changed"
    assert summary["planner_type"] == "legacy_investment_plan"
    assert "raw_prompt" not in summary


def test_investment_graph_loads_baseline_before_planner():
    baseline = _covered_baseline()
    baseline_service = StaticBaselineService(baseline)
    planner = FixtureTurnPlanner(
        _direct_decision(
            "Give me a general portfolio breakdown.",
            ["latest_snapshot"],
            ["baseline.latest"],
        )
    )
    emitted = []
    agent = InvestmentAgent(
        portfolio_agent=FakePortfolioAgent(),
        sentiment_agent=FakeSentimentAgent(),
        ips=mock_investment_policy(),
        planner=planner,
        portfolio_baseline_service=baseline_service,
    )

    agent.run("Give me a general portfolio breakdown.", status_callback=emitted.append)

    statuses = [event.status for event in emitted]
    assert baseline_service.calls == 1
    assert planner.last_baseline == baseline
    assert statuses.index("portfolio_baseline_ready") < statuses.index("planning_investment")


def test_direct_context_route_skips_all_subagents():
    portfolio_agent = FakePortfolioAgent()
    sentiment_agent = FakeSentimentAgent()
    query = "How has my portfolio changed since last week?"
    planner = FixtureTurnPlanner(
        _direct_decision(
            query,
            ["portfolio_value_trend_7d", "history_freshness"],
            ["baseline.trend.7d", "baseline.history"],
        )
    )
    agent = InvestmentAgent(
        portfolio_agent=portfolio_agent,
        sentiment_agent=sentiment_agent,
        ips=mock_investment_policy(),
        planner=planner,
        portfolio_baseline_service=StaticBaselineService(_covered_baseline()),
    )

    state = agent.run(query)

    assert portfolio_agent.calls == 0
    assert sentiment_agent.calls == 0
    assert state.validated_turn_decision is not None
    assert state.validated_turn_decision.route == "direct_context"
    assert state.evidence_coverage["is_valid"] is True


def test_direct_context_answer_becomes_guarded_final_report():
    query = "How much effective cash do I have?"
    agent = InvestmentAgent(
        portfolio_agent=FakePortfolioAgent(),
        sentiment_agent=FakeSentimentAgent(),
        ips=mock_investment_policy(),
        planner=FixtureTurnPlanner(
            _direct_decision(query, ["effective_cash"], ["baseline.cash"])
        ),
        portfolio_baseline_service=StaticBaselineService(_covered_baseline()),
    )

    state = agent.run(query)

    assert state.final_report is not None
    assert state.final_report.summary.startswith("As of 2026-08-03")
    assert state.final_report.as_of == datetime(2026, 8, 3, 13, 55, tzinfo=UTC)
    assert state.final_report.portfolio_analysis["route"] == "direct_context"
    assert state.final_report.portfolio_analysis["cited_evidence_refs"] == [
        "baseline.cash"
    ]
    assert state.guardrail_review is not None
    assert state.guardrail_review.passed is True


@pytest.mark.parametrize(
    ("query", "capabilities", "refs"),
    [
        ("Give me a general portfolio breakdown.", ["latest_snapshot"], ["baseline.latest"]),
        ("Show my allocation overview.", ["allocation_breakdown"], ["baseline.allocation"]),
        ("How much effective cash do I have?", ["effective_cash"], ["baseline.cash"]),
        (
            "What is the rough trend since last week?",
            ["portfolio_value_trend_7d", "history_freshness"],
            ["baseline.trend.7d", "baseline.history"],
        ),
        (
            "What is the rough trend since last month?",
            ["portfolio_value_trend_30d", "history_freshness"],
            ["baseline.trend.30d", "baseline.history"],
        ),
        (
            "What changed recently?",
            [
                "top_allocation_changes_7d",
                "top_position_changes_7d",
                "history_freshness",
            ],
            ["baseline.allocation_changes", "baseline.position_changes", "baseline.history"],
        ),
    ],
)
def test_golden_baseline_queries_make_exactly_one_llm_call(query, capabilities, refs):
    portfolio_agent = FakePortfolioAgent()
    sentiment_agent = FakeSentimentAgent()
    planner = FixtureTurnPlanner(_direct_decision(query, capabilities, refs))
    agent = InvestmentAgent(
        portfolio_agent=portfolio_agent,
        sentiment_agent=sentiment_agent,
        ips=mock_investment_policy(),
        planner=planner,
        portfolio_baseline_service=StaticBaselineService(_covered_baseline()),
    )

    state = agent.run(query)

    assert planner.calls == 1
    assert state.total_llm_calls == 1
    assert len(state.llm_calls) == 1
    assert state.llm_calls[0].purpose == "investment_planning"
    assert portfolio_agent.calls == 0
    assert sentiment_agent.calls == 0


def test_delegated_route_enforces_two_call_total_budget():
    query = "Explain the detailed concentration risks in my portfolio."
    request = PortfolioRequest(
        task_intent="risk_check",
        freshness_requirement="latest_required",
        output_goals=["snapshot", "risk_context", "portfolio_patterns"],
        analysis_requirement="interpretation_required",
        source_query=query,
    )
    portfolio_agent = LLMReportingPortfolioAgent(call_count=1)
    agent = InvestmentAgent(
        portfolio_agent=portfolio_agent,
        sentiment_agent=FakeSentimentAgent(),
        ips=mock_investment_policy(),
        planner=FixtureTurnPlanner(
            InvestmentTurnDecision(
                route="delegate_portfolio",
                route_reasons=["deeper_risk_required"],
                required_evidence=["latest_snapshot"],
                missing_evidence=["latest_snapshot"],
                portfolio_request=request,
            )
        ),
        portfolio_baseline_service=StaticBaselineService(_covered_baseline()),
    )

    state = agent.run(query)

    assert state.total_llm_calls == 2
    assert [call.purpose for call in state.llm_calls] == [
        "investment_planning",
        "portfolio_analysis",
    ]
    assert state.portfolio_packet is not None
    portfolio_call_event = next(
        event for event in state.status_events if event.status == "portfolio_llm_call_completed"
    )
    assert portfolio_call_event.metadata["expected_call_count"] == 2
    assert portfolio_call_event.metadata["actual_call_count"] == 2


def test_deterministic_only_delegation_keeps_one_call_total():
    query = "Retrieve my scoped position changes for the last 90 days."
    request = PortfolioRequest(
        task_intent="what_changed",
        time_range="90d",
        freshness_requirement="history_only",
        output_goals=["position_changes"],
        analysis_requirement="deterministic_only",
        source_query=query,
    )
    agent = InvestmentAgent(
        portfolio_agent=FakePortfolioAgent(),
        sentiment_agent=FakeSentimentAgent(),
        ips=mock_investment_policy(),
        planner=FixtureTurnPlanner(
            InvestmentTurnDecision(
                route="delegate_portfolio",
                route_reasons=["unsupported_time_window"],
                portfolio_request=request,
            )
        ),
        portfolio_baseline_service=StaticBaselineService(_covered_baseline()),
    )

    state = agent.run(query)

    assert state.total_llm_calls == 1
    assert state.portfolio_packet is not None


def test_duplicate_portfolio_model_call_is_rejected_with_route_context():
    query = "Explain the detailed concentration risks in my portfolio."
    request = PortfolioRequest(
        task_intent="risk_check",
        freshness_requirement="latest_required",
        output_goals=["snapshot", "risk_context", "portfolio_patterns"],
        analysis_requirement="interpretation_required",
        source_query=query,
    )
    agent = InvestmentAgent(
        portfolio_agent=LLMReportingPortfolioAgent(call_count=2),
        sentiment_agent=FakeSentimentAgent(),
        ips=mock_investment_policy(),
        planner=FixtureTurnPlanner(
            InvestmentTurnDecision(
                route="delegate_portfolio",
                route_reasons=["deeper_risk_required"],
                portfolio_request=request,
            )
        ),
        portfolio_baseline_service=StaticBaselineService(_covered_baseline()),
    )

    state = agent.run(query)

    assert state.total_llm_calls == 3
    assert state.portfolio_packet is None
    budget_event = next(
        event for event in state.status_events if event.status == "portfolio_llm_budget_exceeded"
    )
    assert budget_event.metadata["route"] == "delegate_portfolio"
    assert budget_event.metadata["expected_call_count"] == 2
    assert budget_event.metadata["actual_call_count"] == 3
    assert state.portfolio_baseline == _covered_baseline()


def test_portfolio_failure_propagates_with_route_context_and_preserves_baseline():
    query = "Explain the detailed concentration risks in my portfolio."
    request = PortfolioRequest(
        task_intent="risk_check",
        freshness_requirement="latest_required",
        output_goals=["snapshot", "risk_context"],
        analysis_requirement="interpretation_required",
        source_query=query,
    )
    baseline = _covered_baseline()
    agent = InvestmentAgent(
        portfolio_agent=FailingPortfolioAnalysisAgent(),
        sentiment_agent=FakeSentimentAgent(),
        ips=mock_investment_policy(),
        planner=FixtureTurnPlanner(
            InvestmentTurnDecision(
                route="delegate_portfolio",
                route_reasons=["deeper_risk_required"],
                portfolio_request=request,
            )
        ),
        portfolio_baseline_service=StaticBaselineService(baseline),
    )

    state = agent.run(query)

    assert state.portfolio_baseline == baseline
    assert state.portfolio_packet is None
    assert state.total_llm_calls == 2
    failure = next(
        event for event in state.status_events if event.status == "portfolio_analysis_failed"
    )
    assert failure.metadata["route"] == "delegate_portfolio"
    assert failure.metadata["actual_call_count"] == 2
    assert state.final_report is not None


@pytest.mark.parametrize(
    ("error", "expected_status", "expected_phase"),
    [
        (
            PortfolioEvidencePlanValidationError("compiled plan is invalid"),
            "portfolio_evidence_compilation_failed",
            "portfolio_evidence_planner",
        ),
        (
            RuntimeError("MCP evidence execution failed"),
            "portfolio_execution_failed",
            "deterministic_tool_execution",
        ),
    ],
)
def test_portfolio_compiler_and_execution_failures_have_route_context(
    error,
    expected_status,
    expected_phase,
):
    query = "Retrieve detailed portfolio evidence."
    request = PortfolioRequest(
        task_intent="what_changed",
        output_goals=["position_changes"],
        analysis_requirement="deterministic_only",
        source_query=query,
    )
    baseline = _covered_baseline()
    agent = InvestmentAgent(
        portfolio_agent=RaisingPortfolioAgent(error),
        sentiment_agent=FakeSentimentAgent(),
        ips=mock_investment_policy(),
        planner=FixtureTurnPlanner(
            InvestmentTurnDecision(
                route="delegate_portfolio",
                route_reasons=["asset_detail_required"],
                portfolio_request=request,
            )
        ),
        portfolio_baseline_service=StaticBaselineService(baseline),
    )

    state = agent.run(query)

    event = next(item for item in state.status_events if item.status == expected_status)
    assert event.phase == expected_phase
    assert event.metadata["route"] == "delegate_portfolio"
    assert state.portfolio_baseline == baseline
    assert state.portfolio_packet is None
    assert state.total_llm_calls == 1


def test_missing_baseline_evidence_routes_bounded_portfolio_request():
    query = "How has my portfolio changed since last week?"
    fallback = PortfolioRequest(
        task_intent="what_changed",
        time_range="7d",
        freshness_requirement="cached_ok",
        output_goals=["position_changes"],
        source_query=query,
    )
    decision = InvestmentTurnDecision(
        route="direct_context",
        route_reasons=["baseline_sufficient"],
        required_evidence=["top_position_changes_7d"],
        cited_evidence_refs=["missing.position.changes"],
        direct_answer="The portfolio changed during the week.",
        fallback_portfolio_request=fallback,
    )
    portfolio_agent = FakePortfolioAgent()
    agent = InvestmentAgent(
        portfolio_agent=portfolio_agent,
        sentiment_agent=FakeSentimentAgent(),
        ips=mock_investment_policy(),
        planner=FixtureTurnPlanner(decision),
        portfolio_baseline_service=StaticBaselineService(
            PortfolioBaselinePacket(portfolio_id="portfolio_default")
        ),
    )

    state = agent.run(query)

    assert portfolio_agent.calls == 1
    assert portfolio_agent.last_request == fallback
    assert state.validated_turn_decision is not None
    assert state.validated_turn_decision.route == "delegate_portfolio"
    assert state.validated_turn_decision.route_reasons == [
        "missing_baseline_capability"
    ]
    assert state.evidence_coverage["is_valid"] is False


@pytest.mark.parametrize(
    ("case", "expected_reason"),
    [("stale", "stale_baseline"), ("short_window", "unsupported_time_window")],
)
def test_stale_or_short_window_evidence_routes_bounded_portfolio_request(
    case,
    expected_reason,
):
    query = "Explain the requested portfolio trend."
    baseline = _covered_baseline()
    if case == "stale":
        baseline = baseline.model_copy(
            update={
                "evidence_refs": [
                    ref.model_copy(update={"quality": "stale"})
                    if ref.ref_id == "baseline.latest"
                    else ref
                    for ref in baseline.evidence_refs
                ]
            }
        )
        required = ["latest_snapshot"]
        refs = ["baseline.latest"]
        time_range = None
        freshness = "cached_ok"
    else:
        required = ["portfolio_value_trend_7d"]
        refs = ["baseline.trend.7d"]
        time_range = "30d"
        freshness = "cached_ok"
    fallback = PortfolioRequest(
        task_intent="what_changed",
        time_range=time_range,
        freshness_requirement=freshness,
        output_goals=["position_changes"],
        source_query=query,
    )
    decision = InvestmentTurnDecision(
        route="direct_context",
        route_reasons=["baseline_sufficient"],
        required_evidence=required,
        cited_evidence_refs=refs,
        direct_answer="The stored trend is available.",
        fallback_portfolio_request=fallback,
    )
    portfolio_agent = FakePortfolioAgent()
    agent = InvestmentAgent(
        portfolio_agent=portfolio_agent,
        sentiment_agent=FakeSentimentAgent(),
        ips=mock_investment_policy(),
        planner=FixtureTurnPlanner(decision),
        portfolio_baseline_service=StaticBaselineService(baseline),
    )

    state = agent.run(query)

    assert portfolio_agent.calls == 1
    assert state.validated_turn_decision is not None
    assert state.validated_turn_decision.route_reasons == [expected_reason]


def test_missing_fallback_request_fails_closed():
    query = "Explain a detailed unsupported portfolio change."
    decision = InvestmentTurnDecision(
        route="direct_context",
        route_reasons=["baseline_sufficient"],
        required_evidence=["top_position_changes_7d"],
        cited_evidence_refs=["missing.position.changes"],
        direct_answer="Unsupported detail.",
    )
    portfolio_agent = FakePortfolioAgent()
    agent = InvestmentAgent(
        portfolio_agent=portfolio_agent,
        sentiment_agent=FakeSentimentAgent(),
        ips=mock_investment_policy(),
        planner=FixtureTurnPlanner(decision),
        portfolio_baseline_service=StaticBaselineService(
            PortfolioBaselinePacket(portfolio_id="portfolio_default")
        ),
    )

    state = agent.run(query)

    assert portfolio_agent.calls == 0
    assert state.validated_turn_decision is not None
    assert state.validated_turn_decision.route == "unsupported"
    assert state.final_report is not None
    assert "missing capabilities" in state.final_report.summary


@pytest.mark.parametrize(
    ("query", "reason", "task_intent", "time_range"),
    [
        (
            "What price did I buy my AMZN shares at?",
            "cost_basis_required",
            "what_changed",
            "90d",
        ),
        (
            "Show my exact portfolio change over 45 days.",
            "unsupported_time_window",
            "what_changed",
            "45d",
        ),
        (
            "Give me a detailed portfolio risk decomposition.",
            "deeper_risk_required",
            "risk_check",
            "30d",
        ),
        (
            "Refresh OpenD and tell me the latest portfolio value.",
            "latest_opend_required",
            "portfolio_fact",
            None,
        ),
        (
            "Investigate the root cause of this portfolio anomaly.",
            "anomaly_investigation_required",
            "deep_dive",
            "30d",
        ),
    ],
)
def test_golden_detailed_prompts_delegate_portfolio(
    query,
    reason,
    task_intent,
    time_range,
):
    request = PortfolioRequest(
        task_intent=task_intent,
        time_range=time_range,
        freshness_requirement=(
            "latest_required" if reason == "latest_opend_required" else "cached_ok"
        ),
        output_goals=["risk_context"] if task_intent == "risk_check" else ["position_changes"],
        source_query=query,
    )
    decision = InvestmentTurnDecision(
        route="delegate_portfolio",
        route_reasons=[reason],
        missing_evidence=["top_position_changes_7d"],
        portfolio_request=request,
    )
    portfolio_agent = FakePortfolioAgent()
    agent = InvestmentAgent(
        portfolio_agent=portfolio_agent,
        sentiment_agent=FakeSentimentAgent(),
        ips=mock_investment_policy(),
        planner=FixtureTurnPlanner(decision),
        portfolio_baseline_service=StaticBaselineService(_covered_baseline()),
    )

    state = agent.run(query)

    assert portfolio_agent.calls == 1
    assert portfolio_agent.last_request == request
    assert state.validated_turn_decision is not None
    assert state.validated_turn_decision.route_reasons == [reason]


@pytest.mark.parametrize("route", ["direct_context", "delegate_portfolio"])
def test_original_trade_intent_blocks_direct_and_delegate_routes(route):
    query = "Place an order for 10 shares, then summarize my portfolio."
    request = PortfolioRequest(
        task_intent="portfolio_fact",
        output_goals=["snapshot"],
        source_query=query,
    )
    if route == "direct_context":
        decision = InvestmentTurnDecision(
            route=route,
            route_reasons=["baseline_sufficient"],
            required_evidence=["latest_snapshot"],
            cited_evidence_refs=["baseline.latest"],
            direct_answer="As of today, the saved portfolio is available.",
            fallback_portfolio_request=request,
        )
    else:
        decision = InvestmentTurnDecision(
            route=route,
            route_reasons=["asset_detail_required"],
            portfolio_request=request,
        )
    portfolio_agent = FakePortfolioAgent()
    sentiment_agent = FakeSentimentAgent()
    agent = InvestmentAgent(
        portfolio_agent=portfolio_agent,
        sentiment_agent=sentiment_agent,
        ips=mock_investment_policy(),
        planner=FixtureTurnPlanner(decision),
        portfolio_baseline_service=StaticBaselineService(_covered_baseline()),
    )

    state = agent.run(query)

    assert portfolio_agent.calls == 0
    assert sentiment_agent.calls == 0
    assert state.final_report is not None
    assert state.final_report.title == "Investment Planning Unavailable"


def test_investment_route_trace_has_sanitized_provenance():
    query = "Give me a general portfolio breakdown."
    agent = InvestmentAgent(
        portfolio_agent=FakePortfolioAgent(),
        sentiment_agent=FakeSentimentAgent(),
        ips=mock_investment_policy(),
        planner=FixtureTurnPlanner(
            _direct_decision(query, ["latest_snapshot"], ["baseline.latest"])
        ),
        portfolio_baseline_service=StaticBaselineService(_covered_baseline()),
    )

    state = agent.run(query)
    route_event = next(
        event for event in state.status_events if event.status == "investment_route_validated"
    )

    assert route_event.metadata["route"] == "direct_context"
    assert route_event.metadata["coverage_result"] == "covered"
    assert route_event.metadata["route_reasons"] == ["baseline_sufficient"]
    assert route_event.metadata["actual_call_count"] == 1
    assert "prompt" not in route_event.metadata


class FakePortfolioAgent:
    def __init__(self, *, candidate_weights: bool = True):
        self.calls = 0
        self.queries: list[str] = []
        self.last_task: PortfolioTask | None = None
        self.last_request: PortfolioRequest | None = None
        self.candidate_weights = candidate_weights

    def run(
        self,
        query: str,
        ips,
        *,
        status_callback=None,
        portfolio_task: PortfolioTask | None = None,
        portfolio_request: PortfolioRequest | None = None,
    ) -> PortfolioAgentResult:
        del status_callback
        self.calls += 1
        self.queries.append(query)
        self.last_task = portfolio_task
        self.last_request = portfolio_request
        packet = mock_portfolio_packet()
        if not self.candidate_weights:
            holdings = [
                holding.model_copy(update={"portfolio_weight": 0.01})
                for holding in packet.snapshot.holdings
            ]
            snapshot = packet.snapshot.model_copy(update={"holdings": holdings})
            packet = packet.model_copy(update={"snapshot": snapshot})
        metrics = calculate_snapshot_metrics(packet.snapshot, ips)
        effective_cash: EffectiveCashSummary = build_effective_cash_summary(packet.snapshot)
        history_context = PortfolioHistoryContext(
            history_status={"snapshot_count": 1, "data_quality": {"warnings": []}},
            latest_portfolio_state=None,
            portfolio_growth=[],
            allocation_history=[],
        )
        return PortfolioAgentResult(
            run_id=f"fake_portfolio_{self.calls}",
            portfolio_id=packet.portfolio_id,
            context_plan=_fake_context_plan(query, portfolio_task, portfolio_request),
            evidence_packet=PortfolioEvidencePacket(
                portfolio_id=packet.portfolio_id,
                task_intent=_fake_task_intent(portfolio_task, portfolio_request),
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
                tool_refs=["fake_portfolio_agent"],
            ),
            snapshot=packet.snapshot,
            portfolio_packet=packet,
            metrics=metrics,
            storage_result={"status": "inserted"},
            metrics_storage_result={"metrics_stored": 0, "weight_rows_stored": 0},
            effective_cash=effective_cash,
            history_status=history_context.history_status,
            history_context=history_context,
            evaluation=PortfolioEvaluation(summary="Fake portfolio evaluation complete."),
            tool_calls=["planned:fake_portfolio_agent", "fake_portfolio_agent"],
            status_events=[],
            warnings=[],
        )


class LLMReportingPortfolioAgent(FakePortfolioAgent):
    def __init__(self, *, call_count: int):
        super().__init__()
        self.call_count = call_count

    def run(self, *args, **kwargs) -> PortfolioAgentResult:
        result = super().run(*args, **kwargs)
        started_at = datetime(2026, 8, 5, 1, 0, tzinfo=UTC)
        calls = [
            LLMCallTrace(
                run_id=result.run_id,
                purpose="portfolio_analysis",
                provider="fake-provider",
                model="fake-portfolio-model",
                subagent="portfolio_agent",
                status="completed",
                started_at=started_at,
                ended_at=started_at,
                duration_ms=0.0,
                attempt=index,
                retry_reason=("explicit_test_retry" if index > 1 else None),
                metadata={
                    "budget_limit": self.call_count,
                    "expected_call_count": 1,
                    "actual_call_count": index,
                },
            )
            for index in range(1, self.call_count + 1)
        ]
        return result.model_copy(
            update={
                "llm_calls": calls,
                "expected_llm_calls": {"portfolio_analysis": 1},
                "actual_llm_calls": {"portfolio_analysis": self.call_count},
                "total_llm_calls": self.call_count,
            }
        )


class FailingPortfolioAnalysisAgent:
    def run(self, query, ips, **kwargs):
        del query, ips, kwargs
        started_at = datetime(2026, 8, 5, 1, 0, tzinfo=UTC)
        call = LLMCallTrace(
            run_id="failed_portfolio_run",
            purpose="portfolio_analysis",
            provider="fake-provider",
            model="fake-portfolio-model",
            subagent="portfolio_agent",
            status="failed",
            started_at=started_at,
            ended_at=started_at,
            duration_ms=0.0,
            attempt=1,
            error_category="ProviderError",
            metadata={
                "budget_limit": 1,
                "expected_call_count": 1,
                "actual_call_count": 1,
            },
        )
        raise PortfolioAnalysisUnavailableError(
            "Portfolio provider failed.",
            run_id="failed_portfolio_run",
            llm_calls=[call],
        )


class RaisingPortfolioAgent:
    def __init__(self, error: Exception):
        self.error = error

    def run(self, query, ips, **kwargs):
        del query, ips, kwargs
        raise self.error


class FixtureInvestmentPlanner:
    def plan(self, query: str, ips) -> InvestmentPlan:
        del ips
        if query == "How much effective cash do I have?":
            return InvestmentPlan(
                mode="portfolio_fact",
                needs_portfolio_agent=True,
                needs_sentiment_agent=False,
                portfolio_request=PortfolioRequest(
                    task_intent="portfolio_fact",
                    output_goals=["snapshot", "effective_cash"],
                    source_query=query,
                ),
                logical_asset_hints=[],
                themes=["portfolio_fact"],
                freshness_requirement="latest_required",
                answer_constraints=[
                    "no_trade_execution",
                    "no_order_preparation",
                    "no_exact_share_count",
                    "source_backed",
                    "portfolio_only",
                ],
            )
        if query == "What price did I buy my recent AMZN shares at?":
            return InvestmentPlan(
                mode="what_changed",
                needs_portfolio_agent=True,
                needs_sentiment_agent=False,
                portfolio_request=PortfolioRequest(
                    task_intent="what_changed",
                    asset_hints=[AssetHint(raw_input="AMZN")],
                    time_range="90d",
                    freshness_requirement="history_only",
                    output_goals=["snapshot", "position_changes", "portfolio_patterns"],
                    source_query=query,
                ),
                logical_asset_hints=[AssetHint(raw_input="AMZN")],
                themes=["position_changes"],
                time_horizon="90d",
                freshness_requirement="history_only",
            )
        if query == "What does recent research say about GOOG?":
            return InvestmentPlan(
                mode="deep_dive",
                needs_portfolio_agent=False,
                needs_sentiment_agent=True,
                sentiment_task=SentimentTask(
                    tickers=["GOOG"],
                    key_questions=[query],
                ),
                logical_asset_hints=[AssetHint(raw_input="GOOG")],
                themes=["research"],
            )
        task_intent = "deep_dive" if "market sentiment" in query else "full_review"
        return InvestmentPlan(
            mode="review" if task_intent == "full_review" else "deep_dive",
            needs_portfolio_agent=True,
            needs_sentiment_agent=True,
            portfolio_request=PortfolioRequest(
                task_intent=task_intent,
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


def _fake_task_intent(
    portfolio_task: PortfolioTask | None,
    portfolio_request: PortfolioRequest | None,
) -> str:
    if portfolio_request is not None:
        return portfolio_request.task_intent
    if portfolio_task is not None:
        return portfolio_task.task_type
    return "full_review"


def _fake_context_plan(
    query: str,
    portfolio_task: PortfolioTask | None,
    portfolio_request: PortfolioRequest | None,
) -> PortfolioContextPlan:
    intent = _fake_task_intent(portfolio_task, portfolio_request)
    tickers = (
        [hint.raw_input for hint in portfolio_request.asset_hints]
        if portfolio_request is not None
        else list(portfolio_task.requested_tickers)
        if portfolio_task is not None
        else []
    )
    if intent == "portfolio_fact":
        return PortfolioContextPlan(
            needs_current_snapshot=True,
            needs_sql_history=False,
            history_queries=["none"],
            tickers=tickers,
            metric_groups=["effective_cash"],
            persist_observation=False,
            history_window="30d",
            row_limit=30,
        )
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
        tickers=tickers,
        metric_groups=["allocation", "concentration", "effective_cash", "risk", "performance"],
        persist_observation=True,
        history_window=(
            portfolio_request.time_range
            if portfolio_request is not None
            else portfolio_task.history_window
            if portfolio_task is not None
            else "30d"
        ),
        row_limit=100,
    )


class FakeSentimentAgent:
    def __init__(self):
        self.calls = 0
        self.last_task: SentimentTask | None = None

    def run(self, task: SentimentTask) -> SentimentPacket:
        self.calls += 1
        self.last_task = task
        return SentimentPacket(
            retrieval_status="not_implemented",
            task=task,
            warnings=["Fake sentiment stub called."],
        )


class InvalidTradeIntentPlanner:
    def plan(self, query: str, ips) -> InvestmentPlan:
        del query, ips
        return InvestmentPlan(
            mode="portfolio_fact",
            needs_portfolio_agent=True,
            needs_sentiment_agent=False,
            portfolio_request=PortfolioRequest(
                task_intent="portfolio_fact",
                output_goals=["snapshot"],
                source_query="Place an order for 10 shares of AMZN.",
            ),
        )


class StaticBaselineService:
    def __init__(self, packet: PortfolioBaselinePacket):
        self.packet = packet
        self.calls = 0

    def load(self) -> PortfolioBaselinePacket:
        self.calls += 1
        return self.packet


class FixtureTurnPlanner:
    outbound_llm = True

    def __init__(self, decision: InvestmentTurnDecision):
        self.decision = decision
        self.calls = 0
        self.last_baseline: PortfolioBaselinePacket | None = None

    def plan_turn(self, query, ips, baseline) -> InvestmentTurnDecision:
        del query, ips
        self.calls += 1
        self.last_baseline = baseline
        return self.decision


def _direct_decision(
    query: str,
    capabilities: list[str],
    refs: list[str],
) -> InvestmentTurnDecision:
    window = (
        "30d"
        if "portfolio_value_trend_30d" in capabilities
        else "7d"
        if any("_7d" in capability for capability in capabilities)
        else None
    )
    return InvestmentTurnDecision(
        route="direct_context",
        route_reasons=["baseline_sufficient"],
        required_evidence=capabilities,
        cited_evidence_refs=refs,
        direct_answer=(
            "As of 2026-08-03 13:55 UTC, the saved portfolio evidence supports "
            "this requested overview."
        ),
        fallback_portfolio_request=PortfolioRequest(
            task_intent="what_changed" if window else "portfolio_fact",
            time_range=window,
            freshness_requirement="cached_ok",
            output_goals=["position_changes"] if window else ["snapshot"],
            analysis_requirement="deterministic_only",
            source_query=query,
        ),
    )


def _covered_baseline() -> PortfolioBaselinePacket:
    as_of = datetime(2026, 8, 3, 13, 55, tzinfo=UTC)
    generated_at = datetime(2026, 8, 3, 14, 0, tzinfo=UTC)
    rows = [
        ("latest", "latest_snapshot", "Latest stored total", None),
        ("allocation", "allocation_breakdown", "Current allocation", None),
        ("cash", "effective_cash", "Effective cash", None),
        ("trend.7d", "portfolio_value_trend_7d", "Seven-day trend", "7d"),
        ("trend.30d", "portfolio_value_trend_30d", "Thirty-day trend", "30d"),
        (
            "allocation_changes",
            "top_allocation_changes_7d",
            "Seven-day allocation changes",
            "7d",
        ),
        (
            "position_changes",
            "top_position_changes_7d",
            "Seven-day position changes",
            "7d",
        ),
        ("history", "history_freshness", "History freshness", "30d"),
    ]
    return PortfolioBaselinePacket(
        portfolio_id="portfolio_default",
        generated_at=generated_at,
        as_of=as_of,
        capabilities=[row[1] for row in rows],
        summaries=[
            BaselineSummary(
                summary_id=f"baseline.{key}",
                capability=capability,
                label=label,
                facts={"status": "covered", "value": 1.0},
                evidence_refs=[f"baseline.{key}"],
            )
            for key, capability, label, _window in rows
        ],
        evidence_refs=[
            EvidenceRef(
                ref_id=f"baseline.{key}",
                source="portfolio_sql",
                field_path=f"baseline.{key}",
                as_of=as_of,
                window=window,
            )
            for key, _capability, _label, window in rows
        ],
        limitations=["Stored data only; no live OpenD refresh was performed."],
    )
