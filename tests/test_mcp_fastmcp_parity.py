from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path
import sys
import tempfile

import anyio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from moomail_finance_ai.config import OpenDConfig
from moomail_finance_ai.mcp.finance_metrics_mcp import build_finance_metrics_mcp_module
from moomail_finance_ai.mcp.opend_mcp import build_opend_mcp_module
from moomail_finance_ai.mcp.portfolio_sql_mcp import build_portfolio_sql_mcp_module
from moomail_finance_ai.mocks import mock_portfolio_packet
from moomail_finance_ai.sql_store import PortfolioSqlStore


ROOT = Path(__file__).resolve().parents[1]


def test_fastmcp_metrics_matches_direct_module_shape():
    direct = build_finance_metrics_mcp_module().call_tool(
        "calculate_cash_weight",
        {"total_value": 1000.0, "cash_value": 125.0},
    )

    async def scenario(session: ClientSession) -> None:
        await session.initialize()
        result = await session.call_tool(
            "calculate_cash_weight",
            {"total_value": 1000.0, "cash_value": 125.0},
        )
        assert result.structuredContent == direct.structured_content

    _run_with_stdio_server(
        [sys.executable, str(ROOT / "scripts/mcp_finance_metrics_server.py")],
        scenario,
    )


def test_fastmcp_opend_recorded_context_matches_direct_module_shape(
    recorded_opend_client,
    sample_opend_report_path,
):
    direct_module = build_opend_mcp_module(
        client=recorded_opend_client,
        config=OpenDConfig(base_currency="USD"),
    )
    direct = direct_module.call_tool(
        "opend_get_normalized_portfolio_snapshot",
        {"portfolio_id": "portfolio_default"},
    )

    async def scenario(session: ClientSession) -> None:
        await session.initialize()
        result = await session.call_tool(
            "opend_get_normalized_portfolio_snapshot",
            {"portfolio_id": "portfolio_default"},
        )
        assert result.structuredContent == direct.structured_content

    _run_with_stdio_server(
        [
            sys.executable,
            str(ROOT / "scripts/mcp_opend_server.py"),
            "--from-report",
            str(sample_opend_report_path),
        ],
        scenario,
    )


def test_fastmcp_portfolio_sql_matches_direct_module_shape(tmp_path):
    snapshot = mock_portfolio_packet().snapshot
    direct_store = PortfolioSqlStore(tmp_path / "direct.sqlite")
    direct_module = build_portfolio_sql_mcp_module(store=direct_store)
    direct_init = direct_module.call_tool("portfolio_sql_initialize", {})
    direct_value = direct_module.call_tool(
        "portfolio_sql_store_daily_value_snapshot",
        {"snapshot": snapshot.model_dump(mode="json")},
    )
    direct_count = direct_module.call_tool(
        "portfolio_sql_table_count",
        {"table_name": "portfolio_value_snapshots"},
    )

    async def scenario(session: ClientSession) -> None:
        await session.initialize()
        init_result = await session.call_tool("portfolio_sql_initialize")
        value = await session.call_tool(
            "portfolio_sql_store_daily_value_snapshot",
            {"snapshot": snapshot.model_dump(mode="json")},
        )
        count = await session.call_tool(
            "portfolio_sql_table_count",
            {"table_name": "portfolio_value_snapshots"},
        )

        assert init_result.structuredContent["initialized"] == (
            direct_init.structured_content["initialized"]
        )
        assert init_result.structuredContent["schema_version"] == (
            direct_init.structured_content["schema_version"]
        )
        assert value.structuredContent["portfolio_id"] == (
            direct_value.structured_content["portfolio_id"]
        )
        assert value.structuredContent["status"] == direct_value.structured_content["status"]
        assert count.structuredContent == direct_count.structured_content

    _run_with_stdio_server(
        [
            sys.executable,
            str(ROOT / "scripts/mcp_portfolio_sql_server.py"),
            "--db-path",
            str(tmp_path / "fastmcp.sqlite"),
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
