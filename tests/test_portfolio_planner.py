from __future__ import annotations

import json
from datetime import UTC, datetime
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
from moomail_finance_ai.mocks import mock_investment_policy, mock_portfolio_packet
from moomail_finance_ai.portfolio_agent import (
    PortfolioAgent,
    PortfolioEvaluation,
    interpret_portfolio_task,
    plan_portfolio_context,
)
from moomail_finance_ai.portfolio_evidence_planner import (
    LLMPortfolioEvidencePlanner,
    PortfolioEvidencePlanningUnavailableError,
    PortfolioEvidencePlanValidationError,
    PortfolioEvidencePlanner,
    portfolio_evidence_plan_to_context_plan,
)
from moomail_finance_ai.sql_store import PortfolioSqlStore
from moomail_finance_ai.agent_schemas import PortfolioTask


def test_portfolio_task_interpreter_requires_llm_request():
    with pytest.raises(PortfolioEvidencePlanningUnavailableError) as exc_info:
        interpret_portfolio_task("How much effective cash do I have?")

    assert "Deterministic direct-query interpretation has been removed" in str(exc_info.value)


def test_portfolio_task_context_planner_requires_evidence_plan():
    task = PortfolioTask(
        task_type="portfolio_fact",
        source_query="How much effective cash do I have?",
        required_outputs=["snapshot", "effective_cash"],
    )

    with pytest.raises(PortfolioEvidencePlanningUnavailableError) as exc_info:
        plan_portfolio_context(task)

    assert "Deterministic PortfolioTask-to-context planning has been removed" in str(
        exc_info.value
    )


def test_direct_portfolio_agent_query_requires_bounded_request(tmp_path, recorded_opend_client):
    store = PortfolioSqlStore(tmp_path / "portfolio.sqlite")
    agent = _agent(store, recorded_opend_client, CapturingEvaluator())

    with pytest.raises(PortfolioEvidencePlanningUnavailableError) as exc_info:
        agent.run("What price were my recently purchased AMZN shares?", mock_investment_policy())

    assert "bounded PortfolioRequest" in str(exc_info.value)


def test_portfolio_evidence_planner_protocol_returns_plan():
    planner: PortfolioEvidencePlanner = _fixture_evidence_planner()
    request = PortfolioRequest(
        task_intent="portfolio_fact",
        output_goals=["snapshot", "effective_cash"],
        source_query="How much effective cash do I have?",
    )

    plan = planner.plan(request, mock_investment_policy(), [])

    assert isinstance(plan, PortfolioEvidencePlan)
    assert plan.task_intent == "portfolio_fact"
    assert plan.metric_groups == ["effective_cash"]


def test_portfolio_planner_rejects_position_changes_without_history_query():
    request = PortfolioRequest(
        task_intent="what_changed",
        freshness_requirement="history_only",
        output_goals=["position_changes"],
        source_query="What changed in my portfolio positions?",
    )
    planner = LLMPortfolioEvidencePlanner(
        StaticPortfolioPlannerLLM(
            _static_evidence_payload(
                history_queries=["none"],
                metric_groups=["performance"],
                needs_current_values=False,
                freshness_requirement="history_only",
                position_change_scope="portfolio_wide",
                persistence_mode="skip",
            )
        )
    )

    with pytest.raises(PortfolioEvidencePlanValidationError) as exc_info:
        planner.plan(request, mock_investment_policy(), [])

    assert "position_changes requires position_state_changes" in str(exc_info.value)


def test_portfolio_planner_rejects_latest_required_without_current_values():
    request = PortfolioRequest(
        task_intent="portfolio_fact",
        freshness_requirement="latest_required",
        output_goals=["snapshot"],
        source_query="Show my latest portfolio snapshot.",
    )
    planner = LLMPortfolioEvidencePlanner(
        StaticPortfolioPlannerLLM(
            _static_evidence_payload(
                history_queries=["none"],
                metric_groups=["allocation"],
                needs_current_values=False,
                freshness_requirement="latest_required",
                position_change_scope="none",
                persistence_mode="skip",
            )
        )
    )

    with pytest.raises(PortfolioEvidencePlanValidationError) as exc_info:
        planner.plan(request, mock_investment_policy(), [])

    assert "latest_required requests require needs_current_values=true" in str(exc_info.value)


def test_existing_portfolio_task_adapter_is_removed():
    with pytest.raises(PortfolioEvidencePlanningUnavailableError):
        interpret_portfolio_task("What price were my recently purchased AMZN shares?")


def test_portfolio_planner_maps_request_to_evidence_subtasks():
    request = PortfolioRequest(
        task_intent="what_changed",
        asset_hints=[AssetHint(raw_input="AMZN")],
        time_range="90d",
        freshness_requirement="history_only",
        output_goals=["snapshot", "position_changes", "portfolio_patterns"],
        source_query="What changed in my AMZN position?",
    )

    plan = _fixture_evidence_planner().plan(
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

    plan = _fixture_evidence_planner().plan(
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

    plan = _fixture_evidence_planner().plan(
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
    evidence_plan = _fixture_evidence_planner().plan(
        request,
        mock_investment_policy(),
        _asset_candidates(),
    )

    context_plan = portfolio_evidence_plan_to_context_plan(evidence_plan)

    assert context_plan.asset_ids == ["asset_amzn"]
    assert context_plan.canonical_symbols == ["US.AMZN"]
    assert context_plan.tickers == ["AMZN"]


def test_portfolio_planner_preserves_mixed_asset_and_ticker_history_scopes():
    request = PortfolioRequest(
        task_intent="what_changed",
        asset_hints=[AssetHint(raw_input="AMZN"), AssetHint(raw_input="BRK.B")],
        output_goals=["position_changes"],
        source_query="What changed in AMZN and BRK.B?",
    )
    evidence_plan = _fixture_evidence_planner().plan(
        request,
        mock_investment_policy(),
        _asset_candidates(
            PortfolioAssetCandidate(
                canonical_symbol="US.BRK.B",
                ticker="BRK.B",
                display_name="Berkshire Hathaway Inc. Class B",
                sql_asset_id=None,
            )
        ),
    )

    context_plan = portfolio_evidence_plan_to_context_plan(evidence_plan)

    assert context_plan.asset_ids == ["asset_amzn"]
    assert context_plan.tickers == ["AMZN", "BRK.B"]
    assert [scope.model_dump(mode="json") for scope in context_plan.position_change_scopes] == [
        {"asset_id": "asset_amzn", "ticker": "AMZN"},
        {"asset_id": None, "ticker": "BRK.B"},
    ]


def test_portfolio_planner_surfaces_unresolved_asset_warnings():
    request = PortfolioRequest(
        task_intent="full_review",
        asset_hints=[AssetHint(raw_input="mystery holding")],
        output_goals=["snapshot", "portfolio_patterns"],
        source_query="Review my mystery holding in context.",
    )

    plan = _fixture_evidence_planner().plan(
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

    plan = _fixture_evidence_planner().plan(
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

    plan = _fixture_evidence_planner().plan(request, mock_investment_policy(), [])

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

    plan = _fixture_evidence_planner().plan(request, mock_investment_policy(), [])

    assert plan.metric_groups == ["allocation", "concentration", "effective_cash", "risk"]


def test_position_change_scope_is_asset_scoped_for_resolved_asset():
    request = PortfolioRequest(
        task_intent="what_changed",
        asset_hints=[AssetHint(raw_input="AMZN")],
        output_goals=["position_changes"],
        source_query="What changed in my AMZN position?",
    )

    plan = _fixture_evidence_planner().plan(
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
    agent = PortfolioAgent(
        gateway=gateway,
        evaluator=CapturingEvaluator(),
        evidence_planner=_fixture_evidence_planner(),
    )
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


@pytest.mark.parametrize(
    ("time_range", "expected_days"),
    [("12w", 84.0), ("6m", 180.0), ("1y", 365.0)],
)
def test_position_change_plan_converts_non_day_history_windows(
    tmp_path,
    recorded_opend_client,
    time_range,
    expected_days,
):
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
    agent = PortfolioAgent(
        gateway=gateway,
        evaluator=CapturingEvaluator(),
        evidence_planner=_fixture_evidence_planner(),
    )
    request = PortfolioRequest(
        task_intent="what_changed",
        asset_hints=[AssetHint(raw_input="AMZN")],
        time_range=time_range,
        output_goals=["position_changes"],
        source_query="What changed in my AMZN position?",
    )

    agent.run(
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
    assert position_change_calls[0]["lookback_days"] == expected_days


def test_position_change_plan_executes_mixed_asset_and_ticker_scopes(
    tmp_path,
    recorded_opend_client,
):
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
    agent = PortfolioAgent(
        gateway=gateway,
        evaluator=CapturingEvaluator(),
        evidence_planner=_fixture_evidence_planner(),
    )
    request = PortfolioRequest(
        task_intent="what_changed",
        asset_hints=[AssetHint(raw_input="AMZN"), AssetHint(raw_input="BRK.B")],
        time_range="90d",
        output_goals=["position_changes"],
        source_query="What changed in AMZN and BRK.B?",
    )

    result = agent.run(
        request.source_query,
        mock_investment_policy(),
        portfolio_request=request,
        asset_candidates=_asset_candidates(
            PortfolioAssetCandidate(
                canonical_symbol="US.BRK.B",
                ticker="BRK.B",
                display_name="Berkshire Hathaway Inc. Class B",
                sql_asset_id=None,
            )
        ),
    )

    position_change_calls = [
        arguments
        for server_name, tool_name, arguments, consumer in gateway.calls
        if server_name == PORTFOLIO_SQL_SERVER
        and tool_name == "portfolio_sql_get_position_state_changes"
        and consumer == "portfolio_agent"
    ]
    assert result.context_plan is not None
    assert result.context_plan.tickers == ["AMZN", "BRK.B"]
    assert len(position_change_calls) == 2
    assert position_change_calls[0]["asset_id"] == "asset_amzn"
    assert "ticker" not in position_change_calls[0]
    assert position_change_calls[1]["ticker"] == "BRK.B"
    assert "asset_id" not in position_change_calls[1]


def test_portfolio_request_planner_warnings_are_result_warnings(
    tmp_path,
    recorded_opend_client,
):
    store = PortfolioSqlStore(tmp_path / "portfolio.sqlite")
    agent = _agent(store, recorded_opend_client, CapturingEvaluator())
    request = PortfolioRequest(
        task_intent="portfolio_fact",
        output_goals=["snapshot", "sentiment_context_needs"],
        source_query="Show portfolio facts and note sentiment context needs.",
    )

    result = agent.run(
        request.source_query,
        mock_investment_policy(),
        portfolio_request=request,
        asset_candidates=[],
    )

    assert result.evidence_plan is not None
    assert any("does not route" in warning for warning in result.evidence_plan.warnings)
    assert any("does not route" in warning for warning in result.warnings)


def test_cached_ok_uses_fresh_sql_without_opend(tmp_path):
    store = PortfolioSqlStore(tmp_path / "portfolio.sqlite")
    store.store_portfolio_observation(
        mock_portfolio_packet().snapshot.model_copy(update={"as_of": datetime.now(UTC)})
    )
    gateway = RecordingGateway(
        DirectToolGateway(
            [
                build_finance_metrics_mcp_module(),
                build_portfolio_sql_mcp_module(store=store),
            ]
        )
    )
    agent = PortfolioAgent(
        gateway=gateway,
        evaluator=CapturingEvaluator(),
        evidence_planner=_fixture_evidence_planner(),
    )
    request = PortfolioRequest(
        task_intent="portfolio_fact",
        freshness_requirement="cached_ok",
        output_goals=["snapshot", "effective_cash"],
        source_query="How much effective cash do I have?",
    )

    result = agent.run(
        request.source_query,
        mock_investment_policy(),
        portfolio_request=request,
    )

    assert result.evidence_plan is not None
    assert result.evidence_plan.freshness_requirement == "cached_ok"
    assert all(server_name != OPEND_SERVER for server_name, *_ in gateway.calls)
    assert result.snapshot.holdings[0].ticker == "MSFT"
    assert result.storage_result["status"] == "skipped"
    assert result.storage_result["reason"] == (
        "cached_sql_latest_state_has_no_current_opend_observation"
    )
    assert (
        result.evidence_packet.derived_metrics["effective_cash"]["effective_cash_value"]
        == 5000.0
    )


def test_history_only_query_skips_opend_and_scopes_position_changes_to_resolved_asset(
    tmp_path,
):
    store = PortfolioSqlStore(tmp_path / "portfolio.sqlite")
    store.store_portfolio_observation(mock_portfolio_packet().snapshot)
    gateway = RecordingGateway(
        DirectToolGateway(
            [
                build_finance_metrics_mcp_module(),
                build_portfolio_sql_mcp_module(store=store),
            ]
        )
    )
    agent = PortfolioAgent(
        gateway=gateway,
        evaluator=CapturingEvaluator(),
        evidence_planner=_fixture_evidence_planner(),
    )
    request = PortfolioRequest(
        task_intent="what_changed",
        asset_hints=[AssetHint(raw_input="AAPL")],
        freshness_requirement="history_only",
        output_goals=["position_changes"],
        source_query="What price did I buy recent AAPL shares at?",
    )

    result = agent.run(
        request.source_query,
        mock_investment_policy(),
        portfolio_request=request,
    )

    position_change_calls = [
        arguments
        for server_name, tool_name, arguments, consumer in gateway.calls
        if server_name == PORTFOLIO_SQL_SERVER
        and tool_name == "portfolio_sql_get_position_state_changes"
        and consumer == "portfolio_agent"
    ]
    assert all(server_name != OPEND_SERVER for server_name, *_ in gateway.calls)
    assert result.evidence_plan is not None
    assert result.evidence_plan.position_change_scope == "asset_scoped"
    assert result.evidence_plan.resolved_assets[0].sql_asset_id == "asset_aapl_us"
    assert position_change_calls[0]["asset_id"] == "asset_aapl_us"
    assert result.storage_result["reason"] == "history_only_sql_has_no_current_opend_observation"
    assert "No position-state changes matched the resolved scope and time range." in (
        result.evidence_packet.limitations
    )


def test_stale_cache_returns_warning_in_evidence_packet(tmp_path):
    store = PortfolioSqlStore(tmp_path / "portfolio.sqlite")
    gateway = RecordingGateway(
        DirectToolGateway(
            [
                build_finance_metrics_mcp_module(),
                build_portfolio_sql_mcp_module(store=store),
            ]
        )
    )
    agent = PortfolioAgent(
        gateway=gateway,
        evaluator=CapturingEvaluator(),
        evidence_planner=_fixture_evidence_planner(),
    )
    request = PortfolioRequest(
        task_intent="portfolio_fact",
        freshness_requirement="cached_ok",
        output_goals=["snapshot"],
        source_query="Show my portfolio snapshot.",
    )

    result = agent.run(
        request.source_query,
        mock_investment_policy(),
        portfolio_request=request,
    )

    assert result.snapshot.total_value.amount == 0.0
    assert any("OpenD current context is unavailable" in warning for warning in result.warnings)
    assert any(
        "OpenD current context is unavailable" in limitation
        for limitation in result.evidence_packet.limitations
    )


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

    history_plan = _fixture_evidence_planner().plan(
        history_request,
        mock_investment_policy(),
        [],
    )
    review_plan = _fixture_evidence_planner().plan(
        review_request,
        mock_investment_policy(),
        [],
    )

    assert history_plan.needs_current_values is False
    assert history_plan.persistence_mode == "skip"
    assert review_plan.needs_current_values is True
    assert review_plan.persistence_mode == "persist"


def test_fallback_portfolio_planner_has_been_removed():
    with pytest.raises(PortfolioEvidencePlanningUnavailableError):
        interpret_portfolio_task("How much effective cash do I have?")


def test_portfolio_evidence_plan_has_no_sentiment_routing_or_final_thesis():
    plan = _fixture_evidence_planner().plan(
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

    plan = _fixture_evidence_planner().plan(request, mock_investment_policy(), [])

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
        _fixture_evidence_planner().plan(request, mock_investment_policy(), [])


def test_full_review_evidence_plan_matches_broad_portfolio_context():
    evidence_plan = _fixture_evidence_planner().plan(
        PortfolioRequest(
            task_intent="full_review",
            output_goals=["snapshot", "allocation_context", "risk_context"],
            source_query="Review my portfolio risk",
        ),
        mock_investment_policy(),
        [],
    )
    plan = portfolio_evidence_plan_to_context_plan(evidence_plan)

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
    request = PortfolioRequest(
        task_intent="portfolio_fact",
        output_goals=["snapshot", "effective_cash"],
        source_query="How much effective cash do I have?",
    )

    result = agent.run(
        request.source_query,
        mock_investment_policy(),
        portfolio_request=request,
    )

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
    assert _actual("opend_get_portfolio_context", server=OPEND_SERVER) in result.tool_calls
    assert evaluator.context["history_context"].history_status["skipped"] is True


def test_what_changed_execution_reads_growth_and_allocation_history(
    tmp_path,
    recorded_opend_client,
):
    store = PortfolioSqlStore(tmp_path / "portfolio.sqlite")
    agent = _agent(store, recorded_opend_client, CapturingEvaluator())
    request = PortfolioRequest(
        task_intent="what_changed",
        output_goals=["snapshot", "position_changes"],
        source_query="What changed in my portfolio allocation?",
    )

    result = agent.run(
        request.source_query,
        mock_investment_policy(),
        portfolio_request=request,
    )

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
        evidence_planner=_fixture_evidence_planner(),
    )

    result = agent.run(
        "What price were my recently purchased AMZN shares?",
        mock_investment_policy(),
        portfolio_request=PortfolioRequest(
            task_intent="what_changed",
            asset_hints=[AssetHint(raw_input="AMZN")],
            time_range="90d",
            output_goals=["position_changes"],
            source_query="What price were my recently purchased AMZN shares?",
        ),
        asset_candidates=_asset_candidates(),
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
    assert position_change_calls[0]["asset_id"] == "asset_amzn"
    assert position_change_calls[0]["lookback_days"] == 90.0
    assert position_change_calls[0]["until"] == result.snapshot.as_of.isoformat()
    assert any(
        call.startswith(
            f"actual_detail:{PORTFOLIO_SQL_SERVER}:portfolio_sql_get_position_state_changes"
        )
        and "asset_id=asset_amzn" in call
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
    request = PortfolioRequest(
        task_intent="full_review",
        output_goals=["snapshot", "portfolio_patterns"],
        source_query="Review my portfolio without storing this observation.",
        warnings=["skip_persistence"],
    )

    result = agent.run(
        request.source_query,
        mock_investment_policy(),
        portfolio_request=request,
    )

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
    request = PortfolioRequest(
        task_intent="portfolio_fact",
        output_goals=["snapshot", "effective_cash"],
        source_query="How much effective cash do I have?",
    )

    result = agent.run(
        request.source_query,
        mock_investment_policy(),
        portfolio_request=request,
    )

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
        evidence_planner=_fixture_evidence_planner(),
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


def _fixture_evidence_planner() -> LLMPortfolioEvidencePlanner:
    return LLMPortfolioEvidencePlanner(FakePortfolioPlannerLLM())


class FakePortfolioPlannerLLM:
    config = None

    def generate_text(self, prompt: str, *args, **kwargs) -> str:
        context = json.loads(prompt)
        return json.dumps(_evidence_payload_for_request(context["portfolio_request"]))


class StaticPortfolioPlannerLLM:
    config = None

    def __init__(self, payload: dict[str, Any]):
        self.payload = payload

    def generate_text(self, prompt: str, *args, **kwargs) -> str:
        del prompt, args, kwargs
        return json.dumps(self.payload)


def _static_evidence_payload(**overrides) -> dict[str, Any]:
    payload = {
        "task_intent": "portfolio_fact",
        "resolved_assets": [],
        "history_queries": ["none"],
        "metric_groups": ["allocation"],
        "needs_current_values": True,
        "history_window": "30d",
        "freshness_requirement": "cached_ok",
        "position_change_scope": "none",
        "persistence_mode": "skip",
        "pattern_detectors": ["stale_data"],
        "warnings": [],
    }
    payload.update(overrides)
    return payload


def _evidence_payload_for_request(request: dict[str, Any]) -> dict[str, Any]:
    goals = set(request.get("output_goals") or [])
    task_intent = request["task_intent"]
    freshness = request.get("freshness_requirement") or "cached_ok"
    needs_history = (
        task_intent in {"full_review", "deep_dive", "compare", "what_changed"}
        or "position_changes" in goals
        or "performance_context" in goals
    )
    history_queries = (
        [
            "history_status",
            "latest_state",
            "portfolio_growth",
            "allocation_history",
            "position_state_changes",
        ]
        if needs_history
        else ["none"]
    )
    warnings = []
    if "sentiment_context_needs" in goals:
        warnings.append(
            "Portfolio evidence planner does not route Sentiment Agent; "
            "Investment Agent owns sentiment routing."
        )
    if task_intent == "portfolio_fact" and "position_changes" in goals:
        warnings.append(
            "position_changes was requested for a portfolio_fact; evidence is scoped to "
            "portfolio-only history."
        )
    metric_groups = _metric_groups_for_request(task_intent, goals)
    return {
        "task_intent": task_intent,
        "resolved_assets": [],
        "history_queries": history_queries,
        "metric_groups": metric_groups,
        "needs_current_values": freshness != "history_only",
        "history_window": request.get("time_range") or "30d",
        "freshness_requirement": freshness,
        "position_change_scope": (
            "asset_scoped"
            if request.get("asset_hints") and "position_changes" in goals
            else "portfolio_wide"
            if "position_changes" in goals
            else "none"
        ),
        "persistence_mode": _persistence_for_request(request, task_intent, freshness),
        "pattern_detectors": _pattern_detectors_for_request(goals),
        "warnings": warnings,
    }


def _metric_groups_for_request(task_intent: str, goals: set[str]) -> list[str]:
    if task_intent in {"full_review", "deep_dive", "compare"}:
        return ["allocation", "concentration", "effective_cash", "risk", "performance"]
    if task_intent == "what_changed" or "position_changes" in goals:
        return ["performance"]
    if task_intent == "risk_check" or "risk_context" in goals:
        return ["allocation", "concentration", "effective_cash", "risk"]
    if "effective_cash" in goals:
        return ["effective_cash"]
    if "allocation_context" in goals:
        return ["allocation"]
    return ["allocation"]


def _persistence_for_request(request: dict[str, Any], task_intent: str, freshness: str) -> str:
    if "skip_persistence" in (request.get("warnings") or []):
        return "skip"
    if freshness == "history_only" or task_intent == "portfolio_fact":
        return "skip"
    if task_intent in {"full_review", "what_changed", "deep_dive", "compare"}:
        return "persist"
    return "auto"


def _pattern_detectors_for_request(goals: set[str]) -> list[str]:
    detectors = ["stale_data", "unsupported_quote_warnings"]
    if {"allocation_context", "risk_context"} & goals:
        detectors.extend(["concentration", "allocation_drift"])
    if "effective_cash" in goals:
        detectors.append("cash_effective_cash")
    if "position_changes" in goals:
        detectors.extend(
            [
                "large_position_changes",
                "average_cost_shifts",
                "portfolio_outliers",
            ]
        )
    if "sentiment_context_needs" in goals:
        detectors.append("sentiment_context_needed")
    return list(dict.fromkeys(detectors))


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
