from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from moomail_finance_ai.config import OpenDConfig
from moomail_finance_ai.agent_schemas import (
    AssetHint,
    AssetResolution,
    PortfolioEvidencePlan,
    PortfolioRequest,
)
from moomail_finance_ai.asset_resolver import PortfolioAssetCandidate
from moomail_finance_ai.asset_resolver import validate_portfolio_request
from moomail_finance_ai.mcp.finance_metrics_mcp import build_finance_metrics_mcp_module
from moomail_finance_ai.mcp.gateway import DirectToolGateway
from moomail_finance_ai.mcp.opend_mcp import SERVER_NAME as OPEND_SERVER
from moomail_finance_ai.mcp.opend_mcp import build_opend_mcp_module
from moomail_finance_ai.mcp.portfolio_sql_mcp import SERVER_NAME as PORTFOLIO_SQL_SERVER
from moomail_finance_ai.mcp.portfolio_sql_mcp import build_portfolio_sql_mcp_module
from moomail_finance_ai.mocks import mock_investment_policy
from moomail_finance_ai.portfolio_agent import (
    PortfolioAgent,
    PortfolioEvaluation,
    interpret_portfolio_task,
    plan_portfolio_context,
)
from moomail_finance_ai.portfolio_evidence_planner import (
    DeterministicPortfolioEvidencePlanner,
    FallbackPortfolioEvidencePlanner,
    PortfolioEvidencePlanValidationError,
    PortfolioEvidencePlanner,
    portfolio_evidence_plan_to_context_plan,
    portfolio_task_to_request,
)
from moomail_finance_ai.sql_store import PortfolioSqlStore
from moomail_finance_ai.agent_schemas import PortfolioTask


def test_portfolio_task_interpreter_cash_weight():
    task = interpret_portfolio_task("How much effective cash do I have?")

    assert task.task_type == "portfolio_fact"
    assert task.required_outputs == ["snapshot", "effective_cash"]
    assert task.persistence_mode == "auto"
    assert "cash" in task.focus_areas


def test_cash_weight_plan_minimal_context():
    task = PortfolioTask(
        task_type="portfolio_fact",
        source_query="How much effective cash do I have?",
        required_outputs=["snapshot", "effective_cash"],
    )
    plan = plan_portfolio_context(task)

    assert plan.needs_current_snapshot is True
    assert plan.needs_sql_history is False
    assert plan.history_queries == ["none"]
    assert plan.metric_groups == ["effective_cash"]
    assert plan.persist_observation is False


def test_what_changed_plan_requests_history():
    task = interpret_portfolio_task("What changed in my portfolio allocation?")
    plan = plan_portfolio_context(task)

    assert task.task_type == "what_changed"
    assert plan.needs_sql_history is True
    assert plan.history_queries == [
        "history_status",
        "latest_state",
        "portfolio_growth",
        "allocation_history",
        "position_state_changes",
    ]
    assert plan.persist_observation is True
    assert plan.row_limit == 100


def test_purchase_cost_query_routes_to_position_change_history():
    task = interpret_portfolio_task("What price were my recently purchased AMZN shares?")
    plan = plan_portfolio_context(task)

    assert task.task_type == "what_changed"
    assert task.requested_tickers == ["AMZN"]
    assert "position_state_changes" in plan.history_queries


def test_portfolio_evidence_planner_protocol_returns_plan():
    planner: PortfolioEvidencePlanner = DeterministicPortfolioEvidencePlanner()
    request = PortfolioRequest(
        task_intent="portfolio_fact",
        output_goals=["snapshot", "effective_cash"],
        source_query="How much effective cash do I have?",
    )

    plan = planner.plan(request, mock_investment_policy(), [])

    assert isinstance(plan, PortfolioEvidencePlan)
    assert plan.task_intent == "portfolio_fact"
    assert plan.metric_groups == ["effective_cash"]


def test_existing_portfolio_task_can_be_adapted_to_request():
    task = interpret_portfolio_task("What price were my recently purchased AMZN shares?")

    request = portfolio_task_to_request(task)

    assert request.task_intent == "what_changed"
    assert request.asset_hints[0].raw_input == "AMZN"
    assert request.output_goals == [
        "snapshot",
        "performance_context",
        "position_changes",
        "sentiment_context_needs",
    ]


def test_portfolio_planner_maps_request_to_evidence_subtasks():
    request = PortfolioRequest(
        task_intent="what_changed",
        asset_hints=[AssetHint(raw_input="AMZN")],
        time_range="90d",
        freshness_requirement="history_only",
        output_goals=["snapshot", "position_changes", "portfolio_patterns"],
        source_query="What changed in my AMZN position?",
    )

    plan = DeterministicPortfolioEvidencePlanner().plan(
        request,
        mock_investment_policy(),
        _asset_candidates(),
    )

    assert plan.history_queries == [
        "history_status",
        "latest_state",
        "portfolio_growth",
        "allocation_history",
        "position_state_changes",
    ]
    assert plan.metric_groups == ["performance"]
    assert plan.pattern_detectors == [
        "stale_data",
        "unsupported_quote_warnings",
        "large_position_changes",
        "average_cost_shifts",
        "portfolio_outliers",
    ]


def test_portfolio_planner_warns_on_incoherent_output_goal():
    request = PortfolioRequest(
        task_intent="portfolio_fact",
        output_goals=["snapshot", "position_changes"],
        source_query="Show a position-change history as a portfolio fact.",
    )

    plan = DeterministicPortfolioEvidencePlanner().plan(
        request,
        mock_investment_policy(),
        [],
    )

    assert "position_state_changes" in plan.history_queries
    assert any("position_changes was requested" in warning for warning in plan.warnings)


def test_portfolio_planner_resolves_assets_before_tool_scope():
    request = PortfolioRequest(
        task_intent="what_changed",
        asset_hints=[AssetHint(raw_input="AMZN")],
        output_goals=["position_changes"],
        source_query="What changed in my AMZN position?",
    )

    plan = DeterministicPortfolioEvidencePlanner().plan(
        request,
        mock_investment_policy(),
        _asset_candidates(),
    )

    assert plan.resolved_assets[0].resolution_status == "resolved"
    assert plan.resolved_assets[0].canonical_symbol == "US.AMZN"
    assert plan.position_change_scope == "asset_scoped"


def test_portfolio_planner_uses_resolved_asset_id_for_history_scope():
    request = PortfolioRequest(
        task_intent="what_changed",
        asset_hints=[AssetHint(raw_input="AMZN")],
        output_goals=["position_changes"],
        source_query="What changed in my AMZN position?",
    )
    evidence_plan = DeterministicPortfolioEvidencePlanner().plan(
        request,
        mock_investment_policy(),
        _asset_candidates(),
    )

    context_plan = portfolio_evidence_plan_to_context_plan(evidence_plan)

    assert context_plan.asset_ids == ["asset_amzn"]
    assert context_plan.canonical_symbols == ["US.AMZN"]
    assert context_plan.tickers == ["AMZN"]


def test_portfolio_planner_surfaces_unresolved_asset_warnings():
    request = PortfolioRequest(
        task_intent="full_review",
        asset_hints=[AssetHint(raw_input="mystery holding")],
        output_goals=["snapshot", "portfolio_patterns"],
        source_query="Review my mystery holding in context.",
    )

    plan = DeterministicPortfolioEvidencePlanner().plan(
        request,
        mock_investment_policy(),
        [],
    )

    assert plan.resolved_assets[0].resolution_status == "unknown"
    assert any("could not be resolved" in warning for warning in plan.warnings)


def test_no_hidden_ticker_extraction_when_request_has_asset_hints():
    request = PortfolioRequest(
        task_intent="what_changed",
        asset_hints=[AssetHint(raw_input="AMZN")],
        output_goals=["position_changes"],
        source_query="What changed in AMZN? Ignore the MSFT text here.",
    )

    plan = DeterministicPortfolioEvidencePlanner().plan(
        request,
        mock_investment_policy(),
        _asset_candidates(
            PortfolioAssetCandidate(
                canonical_symbol="US.MSFT",
                ticker="MSFT",
                display_name="Microsoft",
                sql_asset_id="asset_msft",
            )
        ),
    )

    assert [asset.canonical_symbol for asset in plan.resolved_assets] == ["US.AMZN"]


def test_portfolio_planner_selects_allowlisted_history_queries():
    request = PortfolioRequest(
        task_intent="compare",
        output_goals=["snapshot", "performance_context", "portfolio_patterns"],
        source_query="Compare my portfolio exposures.",
    )

    plan = DeterministicPortfolioEvidencePlanner().plan(request, mock_investment_policy(), [])

    assert set(plan.history_queries) <= {
        "none",
        "history_status",
        "latest_state",
        "portfolio_growth",
        "allocation_history",
        "position_state_changes",
    }
    assert plan.history_queries != ["none"]


def test_portfolio_planner_selects_metric_groups():
    request = PortfolioRequest(
        task_intent="risk_check",
        output_goals=["snapshot", "risk_context", "portfolio_patterns"],
        source_query="Check concentration risk.",
    )

    plan = DeterministicPortfolioEvidencePlanner().plan(request, mock_investment_policy(), [])

    assert plan.metric_groups == ["allocation", "concentration", "effective_cash", "risk"]


def test_position_change_scope_is_asset_scoped_for_resolved_asset():
    request = PortfolioRequest(
        task_intent="what_changed",
        asset_hints=[AssetHint(raw_input="AMZN")],
        output_goals=["position_changes"],
        source_query="What changed in my AMZN position?",
    )

    plan = DeterministicPortfolioEvidencePlanner().plan(
        request,
        mock_investment_policy(),
        _asset_candidates(),
    )

    assert plan.position_change_scope == "asset_scoped"


def test_position_change_plan_has_sql_tool_arguments(tmp_path, recorded_opend_client):
    store = PortfolioSqlStore(tmp_path / "portfolio.sqlite")
    gateway = RecordingGateway(
        DirectToolGateway(
            [
                build_opend_mcp_module(client=recorded_opend_client, config=OpenDConfig()),
                build_finance_metrics_mcp_module(),
                build_portfolio_sql_mcp_module(store=store),
            ]
        )
    )
    agent = PortfolioAgent(gateway=gateway, evaluator=CapturingEvaluator())
    request = PortfolioRequest(
        task_intent="what_changed",
        asset_hints=[AssetHint(raw_input="AMZN")],
        time_range="90d",
        output_goals=["position_changes"],
        source_query="What changed in my AMZN position?",
    )

    result = agent.run(
        request.source_query,
        mock_investment_policy(),
        portfolio_request=request,
        asset_candidates=_asset_candidates(),
    )

    position_change_calls = [
        arguments
        for server_name, tool_name, arguments, consumer in gateway.calls
        if server_name == PORTFOLIO_SQL_SERVER
        and tool_name == "portfolio_sql_get_position_state_changes"
        and consumer == "portfolio_agent"
    ]
    assert result.evidence_plan is not None
    assert result.evidence_plan.position_change_scope == "asset_scoped"
    assert result.context_plan is not None
    assert result.context_plan.asset_ids == ["asset_amzn"]
    assert position_change_calls[0]["asset_id"] == "asset_amzn"
    assert position_change_calls[0]["lookback_days"] == 90.0


def test_portfolio_planner_sets_current_value_dependency_and_persistence():
    history_request = PortfolioRequest(
        task_intent="what_changed",
        freshness_requirement="history_only",
        output_goals=["position_changes"],
        source_query="What changed in my portfolio?",
    )
    review_request = PortfolioRequest(
        task_intent="full_review",
        freshness_requirement="latest_required",
        output_goals=["snapshot", "portfolio_patterns"],
        source_query="Review my portfolio.",
    )

    history_plan = DeterministicPortfolioEvidencePlanner().plan(
        history_request,
        mock_investment_policy(),
        [],
    )
    review_plan = DeterministicPortfolioEvidencePlanner().plan(
        review_request,
        mock_investment_policy(),
        [],
    )

    assert history_plan.needs_current_values is False
    assert history_plan.persistence_mode == "skip"
    assert review_plan.needs_current_values is True
    assert review_plan.persistence_mode == "persist"


def test_fallback_portfolio_planner_matches_current_cash_query_behavior():
    evidence_plan = FallbackPortfolioEvidencePlanner().plan_from_query(
        "How much effective cash do I have?",
        mock_investment_policy(),
        [],
    )
    context_plan = portfolio_evidence_plan_to_context_plan(evidence_plan)

    assert evidence_plan.task_intent == "portfolio_fact"
    assert evidence_plan.history_queries == ["none"]
    assert evidence_plan.metric_groups == ["effective_cash"]
    assert evidence_plan.persistence_mode == "skip"
    assert context_plan.needs_sql_history is False
    assert context_plan.persist_observation is False


def test_portfolio_evidence_plan_has_no_sentiment_routing_or_final_thesis():
    plan = DeterministicPortfolioEvidencePlanner().plan(
        PortfolioRequest(
            task_intent="full_review",
            output_goals=["snapshot", "sentiment_context_needs"],
            source_query="Review my portfolio and tell me what needs sentiment.",
        ),
        mock_investment_policy(),
        [],
    )

    assert not hasattr(plan, "needs_sentiment_agent")
    assert not hasattr(plan, "final_thesis")
    assert "sentiment_context_needed" in plan.pattern_detectors
    assert any("does not route" in warning for warning in plan.warnings)


def test_portfolio_planner_selects_pattern_detectors():
    request = PortfolioRequest(
        task_intent="full_review",
        output_goals=[
            "snapshot",
            "allocation_context",
            "effective_cash",
            "position_changes",
            "portfolio_patterns",
        ],
        source_query="Review cash, drift, and position changes.",
    )

    plan = DeterministicPortfolioEvidencePlanner().plan(request, mock_investment_policy(), [])

    assert {
        "concentration",
        "allocation_drift",
        "cash_effective_cash",
        "large_position_changes",
        "average_cost_shifts",
        "stale_data",
        "unsupported_quote_warnings",
    } <= set(plan.pattern_detectors)


def test_portfolio_planner_trace_includes_request_resolution_and_evidence_scope(
    tmp_path,
    recorded_opend_client,
):
    store = PortfolioSqlStore(tmp_path / "portfolio.sqlite")
    agent = _agent(store, recorded_opend_client, CapturingEvaluator())
    emitted = []
    request = PortfolioRequest(
        task_intent="portfolio_fact",
        output_goals=["snapshot", "effective_cash"],
        source_query="How much effective cash do I have?",
    )

    result = agent.run(
        request.source_query,
        mock_investment_policy(),
        status_callback=emitted.append,
        portfolio_request=request,
        asset_candidates=[],
    )

    statuses = [event.status for event in emitted]
    assert "planning_portfolio_evidence" in statuses
    assert "portfolio_evidence_plan_validated" in statuses
    assert any(call.startswith("planned:") for call in result.tool_calls)
    assert any(call.startswith("skipped:") for call in result.tool_calls)


def test_portfolio_planner_rejects_required_unresolved_asset_before_tools():
    request = PortfolioRequest(
        task_intent="what_changed",
        asset_hints=[AssetHint(raw_input="TSLA")],
        output_goals=["position_changes"],
        source_query="What changed in my TSLA position?",
    )

    with pytest.raises(PortfolioEvidencePlanValidationError):
        DeterministicPortfolioEvidencePlanner().plan(request, mock_investment_policy(), [])


def test_full_review_plan_matches_broad_portfolio_context():
    task = interpret_portfolio_task("Review my portfolio risk")
    plan = plan_portfolio_context(task)

    assert task.task_type == "full_review"
    assert plan.needs_current_snapshot is True
    assert plan.needs_sql_history is True
    assert plan.history_queries == [
        "history_status",
        "latest_state",
        "portfolio_growth",
        "allocation_history",
        "position_state_changes",
    ]
    assert plan.metric_groups == [
        "allocation",
        "concentration",
        "effective_cash",
        "risk",
        "performance",
    ]
    assert plan.persist_observation is True


def test_cash_query_execution_skips_history_and_persistence(tmp_path, recorded_opend_client):
    store = PortfolioSqlStore(tmp_path / "portfolio.sqlite")
    evaluator = CapturingEvaluator()
    agent = _agent(store, recorded_opend_client, evaluator)

    result = agent.run("How much effective cash do I have?", mock_investment_policy())

    assert result.context_plan is not None
    assert result.context_plan.needs_sql_history is False
    assert result.context_plan.persist_observation is False
    assert result.history_context.history_status["skipped"] is True
    assert result.storage_result["status"] == "skipped"
    assert store.table_count("portfolio_value_snapshots") == 0
    assert _actual("portfolio_sql_get_portfolio_growth") not in result.tool_calls
    assert _actual("portfolio_sql_get_allocation_history") not in result.tool_calls
    assert _actual("portfolio_sql_store_daily_value_snapshot") not in result.tool_calls
    assert any(
        call.startswith(f"skipped:{PORTFOLIO_SQL_SERVER}:portfolio_sql_get_portfolio_growth")
        and "not_needed_for_cash_query" in call
        for call in result.tool_calls
    )
    assert any(
        call.startswith(f"planned:{OPEND_SERVER}:opend_get_portfolio_context")
        for call in result.tool_calls
    )
    assert evaluator.context["history_context"].history_status["skipped"] is True


def test_what_changed_execution_reads_growth_and_allocation_history(
    tmp_path,
    recorded_opend_client,
):
    store = PortfolioSqlStore(tmp_path / "portfolio.sqlite")
    agent = _agent(store, recorded_opend_client, CapturingEvaluator())

    result = agent.run("What changed in my portfolio allocation?", mock_investment_policy())

    assert result.context_plan is not None
    assert result.context_plan.needs_sql_history is True
    assert _actual("portfolio_sql_get_portfolio_growth") in result.tool_calls
    assert _actual("portfolio_sql_get_allocation_history") in result.tool_calls
    assert _actual("portfolio_sql_get_position_state_changes") in result.tool_calls
    assert result.history_context.portfolio_growth == []
    assert result.history_context.allocation_history == []
    assert result.history_context.position_state_changes == []
    assert result.storage_result["status"] == "inserted"


def test_named_ticker_change_query_scopes_position_history_tool(
    tmp_path,
    recorded_opend_client,
):
    store = PortfolioSqlStore(tmp_path / "portfolio.sqlite")
    gateway = RecordingGateway(
        DirectToolGateway(
            [
                build_opend_mcp_module(
                    client=recorded_opend_client,
                    config=OpenDConfig(),
                ),
                build_finance_metrics_mcp_module(),
                build_portfolio_sql_mcp_module(store=store),
            ]
        )
    )
    agent = PortfolioAgent(
        gateway=gateway,
        evaluator=CapturingEvaluator(),
    )

    result = agent.run(
        "What price were my recently purchased AMZN shares?",
        mock_investment_policy(),
    )

    position_change_calls = [
        arguments
        for server_name, tool_name, arguments, consumer in gateway.calls
        if server_name == PORTFOLIO_SQL_SERVER
        and tool_name == "portfolio_sql_get_position_state_changes"
        and consumer == "portfolio_agent"
    ]
    assert result.context_plan is not None
    assert result.context_plan.tickers == ["AMZN"]
    assert len(position_change_calls) == 1
    assert position_change_calls[0]["ticker"] == "AMZN"
    assert position_change_calls[0]["lookback_days"] == 90.0
    assert position_change_calls[0]["until"] == result.snapshot.as_of.isoformat()
    assert any(
        call.startswith(
            f"actual_detail:{PORTFOLIO_SQL_SERVER}:portfolio_sql_get_position_state_changes"
        )
        and "ticker=AMZN" in call
        for call in result.tool_calls
    )


def test_portfolio_request_rejects_unknown_task_intent():
    with pytest.raises(ValidationError):
        PortfolioRequest(
            task_intent="trade_execution",
            output_goals=["snapshot"],
            source_query="Prepare an AMZN trade.",
        )


def test_plan_validator_rejects_trade_execution_request():
    request = PortfolioRequest(
        task_intent="portfolio_fact",
        output_goals=["snapshot"],
        source_query="Place an order for 10 shares of AMZN.",
    )

    result = validate_portfolio_request(request, [])

    assert result.is_valid is False
    assert result.blocking_issues[0].code == "trade_execution_intent_blocked"


def test_plan_validator_rejects_invalid_freshness_or_time_range():
    with pytest.raises(ValidationError):
        PortfolioRequest(
            task_intent="portfolio_fact",
            freshness_requirement="stale_enough",
            output_goals=["snapshot"],
            source_query="Show my AMZN position.",
        )

    with pytest.raises(ValidationError):
        PortfolioRequest(
            task_intent="portfolio_fact",
            time_range="eventually",
            output_goals=["snapshot"],
            source_query="Show my AMZN position.",
        )


def test_plan_validator_blocks_required_unresolved_asset():
    request = PortfolioRequest(
        task_intent="what_changed",
        asset_hints=[AssetHint(raw_input="TSLA")],
        time_range="90d",
        freshness_requirement="history_only",
        output_goals=["position_changes"],
        source_query="What changed in my TSLA position?",
    )
    resolution = AssetResolution(
        input="TSLA",
        resolution_status="not_in_portfolio",
        warnings=["The symbol looks valid but does not match a held portfolio asset."],
    )

    result = validate_portfolio_request(request, [resolution])

    assert result.is_valid is False
    assert result.blocking_issues[0].code == "asset_resolution_failed"
    assert result.blocking_issues[0].resolution_status == "not_in_portfolio"
    assert result.trace_events[0].phase == "asset_resolver"


def test_explicit_persist_skip_does_not_write_daily_value_snapshot(
    tmp_path,
    recorded_opend_client,
):
    store = PortfolioSqlStore(tmp_path / "portfolio.sqlite")
    agent = _agent(store, recorded_opend_client, CapturingEvaluator())
    task = PortfolioTask(
        task_type="full_review",
        source_query="Review my portfolio without storing this observation.",
        persistence_mode="skip",
    )

    result = agent.run(task.source_query, mock_investment_policy(), portfolio_task=task)

    assert result.context_plan is not None
    assert result.context_plan.needs_sql_history is True
    assert result.context_plan.persist_observation is False
    assert result.storage_result["status"] == "skipped"
    assert _actual("portfolio_sql_get_history_status") in result.tool_calls
    assert _actual("portfolio_sql_store_daily_value_snapshot") not in result.tool_calls
    assert any(
        call.startswith(f"skipped:{PORTFOLIO_SQL_SERVER}:portfolio_sql_store_daily_value_snapshot")
        and "persist_observation_false" in call
        for call in result.tool_calls
    )
    assert store.table_count("portfolio_value_snapshots") == 0


def test_portfolio_trace_includes_planned_actual_and_skipped_tools(
    tmp_path,
    recorded_opend_client,
):
    store = PortfolioSqlStore(tmp_path / "portfolio.sqlite")
    agent = _agent(store, recorded_opend_client, CapturingEvaluator())

    result = agent.run("How much effective cash do I have?", mock_investment_policy())

    assert any(call.startswith("planned:") for call in result.tool_calls)
    assert any(call.startswith("skipped:") for call in result.tool_calls)
    assert any(call.startswith("actual_detail:") for call in result.tool_calls)
    assert _actual("calculate_snapshot_metrics", server="moomail-finance-metrics-mcp") in (
        result.tool_calls
    )


def _agent(store, recorded_opend_client, evaluator):
    return PortfolioAgent(
        gateway=DirectToolGateway(
            [
                build_opend_mcp_module(
                    client=recorded_opend_client,
                    config=OpenDConfig(),
                ),
                build_finance_metrics_mcp_module(),
                build_portfolio_sql_mcp_module(store=store),
            ]
        ),
        evaluator=evaluator,
    )


def _asset_candidates(*extra_candidates: PortfolioAssetCandidate) -> list[PortfolioAssetCandidate]:
    return [
        PortfolioAssetCandidate(
            canonical_symbol="US.AMZN",
            ticker="AMZN",
            display_name="Amazon.com Inc.",
            sql_asset_id="asset_amzn",
        ),
        *extra_candidates,
    ]


def _actual(tool_name: str, *, server: str = PORTFOLIO_SQL_SERVER) -> str:
    return f"{server}:{tool_name}"


class CapturingEvaluator:
    def __init__(self):
        self.calls = 0
        self.context: dict[str, Any] = {}

    def evaluate(self, **kwargs) -> PortfolioEvaluation:
        self.calls += 1
        self.context = kwargs
        return PortfolioEvaluation(summary="Portfolio-only evaluation complete.")


class RecordingGateway:
    def __init__(self, gateway):
        self.gateway = gateway
        self.calls: list[tuple[str, str, dict[str, Any], str]] = []

    def call_tool(self, server_name, tool_name, arguments=None, *, consumer):
        self.calls.append((server_name, tool_name, dict(arguments or {}), consumer))
        return self.gateway.call_tool(
            server_name,
            tool_name,
            arguments,
            consumer=consumer,
        )

    def list_tools(self, server_name, *, consumer):
        return self.gateway.list_tools(server_name, consumer=consumer)

    def read_resource(self, server_name, uri, *, consumer):
        return self.gateway.read_resource(server_name, uri, consumer=consumer)

    def list_resources(self, server_name, *, consumer):
        return self.gateway.list_resources(server_name, consumer=consumer)
