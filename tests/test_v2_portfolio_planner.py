from __future__ import annotations

from typing import Any

from moomail_finance_ai.config import OpenDConfig
from moomail_finance_ai.mcp.finance_metrics_mcp import build_finance_metrics_mcp_module
from moomail_finance_ai.mcp.gateway import DirectToolGateway
from moomail_finance_ai.mcp.opend_mcp import SERVER_NAME as OPEND_SERVER
from moomail_finance_ai.mcp.opend_mcp import build_opend_mcp_module
from moomail_finance_ai.mcp.portfolio_sql_mcp import SERVER_NAME as PORTFOLIO_SQL_SERVER
from moomail_finance_ai.mcp.portfolio_sql_mcp import build_portfolio_sql_mcp_module
from moomail_finance_ai.mocks import mock_investment_policy
from moomail_finance_ai.portfolio_agent import (
    MCPPortfolioAgent,
    PortfolioEvaluation,
    interpret_portfolio_task,
    plan_portfolio_context,
)
from moomail_finance_ai.sql_store import PortfolioSqlStore
from moomail_finance_ai.v2_schemas import PortfolioTask


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


def test_full_review_plan_matches_v1_broad_context():
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
    agent = MCPPortfolioAgent(
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
            f"actual_detail:{PORTFOLIO_SQL_SERVER}:"
            "portfolio_sql_get_position_state_changes"
        )
        and "ticker=AMZN" in call
        for call in result.tool_calls
    )


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
    return MCPPortfolioAgent(
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
