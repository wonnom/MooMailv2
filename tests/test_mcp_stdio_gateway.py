from __future__ import annotations

from moomail_finance_ai.mcp.finance_metrics_mcp import SERVER_NAME as FINANCE_METRICS_SERVER
from moomail_finance_ai.mcp.gateway import StdioMCPToolGateway, local_stdio_server_configs
from moomail_finance_ai.mcp.opend_mcp import SERVER_NAME as OPEND_SERVER
from moomail_finance_ai.mcp.portfolio_sql_mcp import SERVER_NAME as PORTFOLIO_SQL_SERVER


def test_stdio_gateway_calls_fastmcp_servers_and_reuses_sessions(
    tmp_path,
    sample_opend_report_path,
):
    gateway = StdioMCPToolGateway(
        local_stdio_server_configs(
            from_report=sample_opend_report_path,
            db_path=tmp_path / "portfolio.sqlite",
            timeout_seconds=10.0,
        )
    )
    try:
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
        first_init = gateway.call_tool(
            PORTFOLIO_SQL_SERVER,
            "portfolio_sql_initialize",
            {},
            consumer="dashboard_refresh",
        )
        second_init = gateway.call_tool(
            PORTFOLIO_SQL_SERVER,
            "portfolio_sql_initialize",
            {},
            consumer="dashboard_refresh",
        )

        assert connection.structured_content["ok"] is True
        assert cash.structured_content["value"] == 0.125
        assert first_init.structured_content["initialized"] is True
        assert second_init.structured_content["initialized"] is True
        assert gateway.started_servers == {
            OPEND_SERVER,
            FINANCE_METRICS_SERVER,
            PORTFOLIO_SQL_SERVER,
        }
    finally:
        gateway.close()

    assert gateway.closed is True
