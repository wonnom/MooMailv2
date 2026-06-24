from __future__ import annotations

from moomail_finance_ai.config import OpenDConfig
from moomail_finance_ai.mcp.agent_access import build_agent_manifest
from moomail_finance_ai.mcp.finance_metrics_mcp import build_finance_metrics_mcp_module
from moomail_finance_ai.mcp.opend_mcp import build_opend_mcp_module
from moomail_finance_ai.mcp.portfolio_sql_mcp import build_portfolio_sql_mcp_module
from moomail_finance_ai.mocks import mock_investment_policy, mock_portfolio_packet
from moomail_finance_ai.sql_store import PortfolioSqlStore


def test_finance_metrics_mcp_lists_tools_resources_and_calls_metric():
    module = build_finance_metrics_mcp_module()
    tool_names = [tool.name for tool in module.list_tools()]

    result = module.call_tool(
        "calculate_cash_weight",
        {"total_value": 1000.0, "cash_value": 125.0},
    )
    resource = module.read_resource("finance-metrics://version")

    assert "calculate_snapshot_metrics" in tool_names
    assert result.structured_content["metric_name"] == "cash_weight"
    assert result.structured_content["value"] == 0.125
    assert "finance-metrics://version" in resource["contents"][0]["uri"]


def test_opend_mcp_is_read_only_and_can_normalize_recorded_snapshot(recorded_opend_client):
    module = build_opend_mcp_module(
        client=recorded_opend_client,
        config=OpenDConfig(base_currency="USD"),
    )
    tool_names = [tool.name for tool in module.list_tools()]

    snapshot_result = module.call_tool(
        "opend_get_normalized_portfolio_snapshot",
        {"portfolio_id": "portfolio_default"},
    )
    capabilities = module.read_resource("opend://capabilities/read-only")

    assert "opend_get_positions" in tool_names
    assert not any("order" in name or "place" in name or "cancel" in name for name in tool_names)
    assert snapshot_result.structured_content["holdings"][0]["ticker"] == "AAPL"
    assert snapshot_result.structured_content["data_quality"]["freshness_status"] == "fresh"
    assert "place order" in capabilities["contents"][0]["text"]


def test_portfolio_sql_mcp_stores_lean_history_and_reads_history(tmp_path):
    store = PortfolioSqlStore(tmp_path / "portfolio.sqlite")
    module = build_portfolio_sql_mcp_module(store=store)
    packet = mock_portfolio_packet()

    account = module.call_tool(
        "portfolio_sql_upsert_broker_account",
        {
            "portfolio_id": packet.portfolio_id,
            "base_currency": packet.snapshot.base_currency,
        },
    )
    value = module.call_tool(
        "portfolio_sql_store_daily_value_snapshot",
        {"snapshot": packet.snapshot.model_dump(mode="json")},
    )
    weights = module.call_tool(
        "portfolio_sql_store_weight_snapshots",
        {
            "snapshot": packet.snapshot.model_dump(mode="json"),
            "account_id": account.structured_content["account_id"],
            "value_snapshot_id": value.structured_content["value_snapshot_id"],
        },
    )
    status = module.call_tool(
        "portfolio_sql_get_history_status",
        {
            "portfolio_id": packet.portfolio_id,
            "now": packet.snapshot.as_of.isoformat(),
            "min_snapshots_for_history": 1,
        },
    )
    latest = module.call_tool(
        "portfolio_sql_get_latest_portfolio_state",
        {"portfolio_id": packet.portfolio_id},
    )
    schema_resource = module.read_resource("portfolio-sql://schema")

    assert value.structured_content["status"] == "inserted"
    assert weights.structured_content["rows_stored"] == (
        len(packet.snapshot.holdings) + len(packet.snapshot.cash)
    )
    assert status.structured_content["snapshot_count"] == 1
    assert latest.structured_content["value_snapshot"]["portfolio_id"] == packet.portfolio_id
    assert "portfolio_value_snapshots" in schema_resource["contents"][0]["text"]


def test_agent_mcp_manifest_scopes_allowed_servers_and_tools(tmp_path, recorded_opend_client):
    modules = [
        build_opend_mcp_module(client=recorded_opend_client, config=OpenDConfig()),
        build_portfolio_sql_mcp_module(db_path=tmp_path / "portfolio.sqlite"),
        build_finance_metrics_mcp_module(),
    ]

    portfolio_manifest = build_agent_manifest("portfolio_agent", modules)
    sentiment_manifest = build_agent_manifest("sentiment_agent", modules)
    investment_manifest = build_agent_manifest("investment_agent", modules)

    assert "moomail-opend-mcp" in portfolio_manifest.allowed_servers
    assert any(tool.endswith(":opend_get_positions") for tool in portfolio_manifest.allowed_tools)
    assert "moomail-opend-mcp" not in sentiment_manifest.allowed_servers
    assert all(":opend_" not in tool for tool in investment_manifest.allowed_tools)
