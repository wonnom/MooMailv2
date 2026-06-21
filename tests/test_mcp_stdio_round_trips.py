from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path
import sys
import tempfile
from typing import Any

import anyio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from moomail_finance_ai.mocks import mock_portfolio_packet


ROOT = Path(__file__).resolve().parents[1]


def test_finance_metrics_fastmcp_stdio_server_round_trip():
    async def scenario(session: ClientSession) -> None:
        initialized = await session.initialize()
        tools = await session.list_tools()
        resources = await session.list_resources()
        result = await session.call_tool(
            "calculate_cash_weight",
            {"total_value": 1000.0, "cash_value": 125.0},
        )
        version = await session.read_resource("finance-metrics://version")

        assert initialized.serverInfo.name == "moomail-finance-metrics-mcp"
        assert "calculate_cash_weight" in {tool.name for tool in tools.tools}
        resource_uris = {str(resource.uri) for resource in resources.resources}
        assert "finance-metrics://version" in resource_uris
        assert result.structuredContent["value"] == 0.125
        assert "finance-metrics://version" in str(version.contents[0].uri)

    _run_with_stdio_server(
        [sys.executable, str(ROOT / "scripts/mcp_finance_metrics_server.py")],
        scenario,
    )


def test_portfolio_sql_fastmcp_stdio_server_round_trip(tmp_path):
    db_path = tmp_path / "portfolio.sqlite"
    snapshot = mock_portfolio_packet().snapshot

    async def scenario(session: ClientSession) -> None:
        initialized = await session.initialize()
        init_result = await session.call_tool("portfolio_sql_initialize")
        value = await session.call_tool(
            "portfolio_sql_store_daily_value_snapshot",
            {"snapshot": snapshot.model_dump(mode="json")},
        )
        count = await session.call_tool(
            "portfolio_sql_table_count",
            {"table_name": "portfolio_value_snapshots"},
        )
        status = await session.read_resource("portfolio-sql://status")

        assert initialized.serverInfo.name == "moomail-portfolio-sql-mcp"
        assert init_result.structuredContent["initialized"] is True
        assert value.structuredContent["portfolio_id"] == snapshot.portfolio_id
        assert count.structuredContent["count"] == 1
        assert "portfolio-sql://status" in str(status.contents[0].uri)

    _run_with_stdio_server(
        [
            sys.executable,
            str(ROOT / "scripts/mcp_portfolio_sql_server.py"),
            "--db-path",
            str(db_path),
        ],
        scenario,
    )


def test_opend_fastmcp_stdio_server_round_trip_with_recorded_report(sample_opend_report_path):
    async def scenario(session: ClientSession) -> None:
        initialized = await session.initialize()
        tools = await session.list_tools()
        connection = await session.call_tool("opend_check_connection")
        snapshot = await session.call_tool(
            "opend_get_normalized_portfolio_snapshot",
            {"portfolio_id": "portfolio_default"},
        )
        capabilities = await session.read_resource("opend://capabilities/read-only")

        assert initialized.serverInfo.name == "moomail-opend-mcp"
        assert "opend_get_positions" in {tool.name for tool in tools.tools}
        assert connection.structuredContent["ok"] is True
        assert snapshot.structuredContent["holdings"][0]["ticker"] == "AAPL"
        assert "place order" in capabilities.contents[0].text

    _run_with_stdio_server(
        [
            sys.executable,
            str(ROOT / "scripts/mcp_opend_server.py"),
            "--from-report",
            str(sample_opend_report_path),
        ],
        scenario,
    )


def _run_with_stdio_server(
    command: list[str],
    scenario: Callable[[ClientSession], Awaitable[None]],
) -> None:
    async def runner() -> None:
        with tempfile.TemporaryFile(mode="w+") as errlog:
            params = StdioServerParameters(
                command=command[0],
                args=command[1:],
                cwd=ROOT,
            )
            async with stdio_client(params, errlog=errlog) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    await scenario(session)

    anyio.run(runner)
