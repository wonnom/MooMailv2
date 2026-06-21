from __future__ import annotations

import pytest

from moomail_finance_ai.mcp.finance_metrics_mcp import SERVER_NAME as FINANCE_METRICS_SERVER
from moomail_finance_ai.mcp.finance_metrics_mcp import build_finance_metrics_mcp_module
from moomail_finance_ai.mcp.gateway import DirectToolGateway, MCPPermissionError
from moomail_finance_ai.mcp.opend_mcp import SERVER_NAME as OPEND_SERVER
from moomail_finance_ai.mcp.opend_mcp import build_opend_mcp_module
from moomail_finance_ai.mcp.portfolio_sql_mcp import SERVER_NAME as PORTFOLIO_SQL_SERVER
from moomail_finance_ai.mcp.portfolio_sql_mcp import build_portfolio_sql_mcp_module
from moomail_finance_ai.mcp.registry import MCPToolSpec, RegisteredMCPModule, object_schema


def test_direct_gateway_allows_dashboard_refresh_and_returns_structured_result(
    tmp_path,
    recorded_opend_client,
):
    gateway = DirectToolGateway(
        [
            build_opend_mcp_module(client=recorded_opend_client),
            build_finance_metrics_mcp_module(),
            build_portfolio_sql_mcp_module(db_path=tmp_path / "portfolio.sqlite"),
        ]
    )

    connection = gateway.call_tool(
        OPEND_SERVER,
        "opend_check_connection",
        {},
        consumer="dashboard_refresh",
    )
    cash = gateway.call_tool(
        FINANCE_METRICS_SERVER,
        "calculate_cash_weight",
        {"total_value": 1000.0, "cash_value": 125.0},
        consumer="dashboard_refresh",
    )
    initialized = gateway.call_tool(
        PORTFOLIO_SQL_SERVER,
        "portfolio_sql_initialize",
        {},
        consumer="dashboard_refresh",
    )

    assert connection.structured_content["ok"] is True
    assert cash.structured_content["value"] == 0.125
    assert initialized.structured_content["initialized"] is True
    assert cash.duration_ms is not None


def test_gateway_denies_investment_agent_direct_opend(recorded_opend_client):
    gateway = DirectToolGateway([build_opend_mcp_module(client=recorded_opend_client)])

    with pytest.raises(MCPPermissionError):
        gateway.call_tool(
            OPEND_SERVER,
            "opend_get_portfolio_context",
            {},
            consumer="investment_agent",
        )


def test_gateway_globally_denies_trade_order_tool_names():
    module = RegisteredMCPModule(server_name="fake-trading-mcp", version="0.0")
    module.add_tool(
        MCPToolSpec(
            name="place_order",
            description="Should never be callable.",
            input_schema=object_schema(),
        ),
        lambda _arguments: {"placed": True},
    )
    gateway = DirectToolGateway([module])

    with pytest.raises(MCPPermissionError):
        gateway.call_tool(
            "fake-trading-mcp",
            "place_order",
            {},
            consumer="portfolio_agent",
        )


def test_gateway_resource_permissions(recorded_opend_client):
    gateway = DirectToolGateway([build_opend_mcp_module(client=recorded_opend_client)])

    capabilities = gateway.read_resource(
        OPEND_SERVER,
        "opend://capabilities/read-only",
        consumer="dashboard_refresh",
    )

    assert "place order" in capabilities["contents"][0]["text"]
    with pytest.raises(MCPPermissionError):
        gateway.read_resource(
            OPEND_SERVER,
            "opend://capabilities/read-only",
            consumer="investment_agent",
        )
