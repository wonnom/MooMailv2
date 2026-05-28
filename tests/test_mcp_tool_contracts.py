from __future__ import annotations

from datetime import UTC, datetime

import pytest

from moomail_finance_ai.config import OpenDConfig
from moomail_finance_ai.mcp.finance_metrics_mcp import build_finance_metrics_mcp_module
from moomail_finance_ai.mcp.opend_mcp import build_opend_mcp_module
from moomail_finance_ai.mcp.portfolio_sql_mcp import build_portfolio_sql_mcp_module
from moomail_finance_ai.mocks import mock_investment_policy, mock_portfolio_packet
from moomail_finance_ai.schemas import AuditRecord, GuardrailCheck, GuardrailResult


def test_finance_metrics_mcp_tool_contracts_cover_each_tool():
    module = build_finance_metrics_mcp_module()
    snapshot = _metrics_snapshot()
    ips = mock_investment_policy().model_copy(update={"max_single_stock_concentration": 0.5})
    snapshot_json = snapshot.model_dump(mode="json")
    ips_json = ips.model_dump(mode="json")

    cash = module.call_tool("calculate_cash_weight", {"snapshot": snapshot_json})
    weights = module.call_tool("calculate_position_weights", {"snapshot": snapshot_json})
    concentration = module.call_tool(
        "calculate_single_position_concentration",
        {"snapshot": snapshot_json, "ips": ips_json},
    )
    allocation = module.call_tool("calculate_asset_type_allocation", {"snapshot": snapshot_json})
    benchmark = module.call_tool("calculate_benchmark_reference", {"ips": ips_json})
    metric_set = module.call_tool(
        "calculate_snapshot_metrics",
        {"snapshot": snapshot_json, "ips": ips_json},
    )
    definitions = module.call_tool("list_metric_definitions", {})

    assert cash.structured_content["metric_name"] == "cash_weight"
    assert cash.structured_content["value"] == 0.05
    assert [row["ticker"] for row in weights.structured_content["value"]] == ["MSFT", "AAPL"]
    assert [row["ticker"] for row in concentration.structured_content["value"]] == ["MSFT"]
    assert {row["asset_type"] for row in allocation.structured_content["value"]} == {
        "cash",
        "equity",
        "etf",
    }
    assert benchmark.structured_content["value"]["benchmark"] == "SPY"
    assert {metric["metric_name"] for metric in metric_set.structured_content} == {
        "asset_type_allocation",
        "benchmark_reference",
        "cash_weight",
        "position_weights",
        "single_position_concentration",
    }
    assert definitions.structured_content["metric_version"] == "finance-metrics-v0.1.0"


def test_opend_mcp_tool_contracts_cover_each_read_only_tool(recorded_opend_client):
    module = build_opend_mcp_module(
        client=recorded_opend_client,
        config=OpenDConfig(base_currency="USD"),
    )
    tool_names = {tool.name for tool in module.list_tools()}

    connection = module.call_tool("opend_check_connection", {})
    accounts = module.call_tool("opend_get_account_list", {})
    funds = module.call_tool("opend_get_account_funds", {})
    positions = module.call_tool("opend_get_positions", {})
    quotes = module.call_tool(
        "opend_get_market_snapshots",
        {"codes": ["US.AAPL", "US.MSFT"]},
    )
    report = module.call_tool("opend_explore_fields", {})
    snapshot = module.call_tool(
        "opend_get_normalized_portfolio_snapshot",
        {"portfolio_id": "portfolio_default"},
    )
    context = module.call_tool(
        "opend_get_portfolio_context",
        {"portfolio_id": "portfolio_default"},
    )
    capabilities = module.read_resource("opend://capabilities/read-only")
    config_summary = module.read_resource("opend://config/summary")

    assert tool_names == {
        "opend_check_connection",
        "opend_explore_fields",
        "opend_get_account_funds",
        "opend_get_account_list",
        "opend_get_market_snapshots",
        "opend_get_normalized_portfolio_snapshot",
        "opend_get_portfolio_context",
        "opend_get_positions",
    }
    assert all(tool.read_only for tool in module.list_tools())
    assert connection.structured_content["ok"] is True
    assert accounts.structured_content["rows"] == [{"acc_id": "redacted"}]
    assert funds.structured_content["rows"][0]["total_assets"] == 1000.0
    assert positions.structured_content["rows"][0]["code"] == "US.AAPL"
    assert quotes.structured_content["rows"][0]["last_price"] == 300.0
    assert "US.MSFT" in quotes.structured_content["warnings"][-1]
    assert {table["name"] for table in report.structured_content["tables"]} == {
        "accounts",
        "funds",
        "positions",
        "quotes",
    }
    assert snapshot.structured_content["holdings"][0]["ticker"] == "AAPL"
    assert context.structured_content["snapshot"]["holdings"][0]["ticker"] == "AAPL"
    assert context.structured_content["source_report"]["connection"]["ok"] is True
    assert "place order" in capabilities["contents"][0]["text"]
    assert '"account_id_configured": false' in config_summary["contents"][0]["text"]


def test_opend_mcp_rejects_invalid_quote_code_arguments(recorded_opend_client):
    module = build_opend_mcp_module(client=recorded_opend_client, config=OpenDConfig())

    with pytest.raises(ValueError, match="codes must be a list of strings"):
        module.call_tool("opend_get_market_snapshots", {"codes": "US.AAPL"})


def test_portfolio_sql_mcp_tool_contracts_cover_each_tool(tmp_path, sample_opend_report):
    module = build_portfolio_sql_mcp_module(db_path=tmp_path / "portfolio.sqlite")
    snapshot = mock_portfolio_packet().snapshot
    metrics = build_finance_metrics_mcp_module().call_tool(
        "calculate_snapshot_metrics",
        {
            "snapshot": _metrics_snapshot().model_dump(mode="json"),
            "ips": mock_investment_policy().model_dump(mode="json"),
        },
    )

    initialized = module.call_tool("portfolio_sql_initialize", {})
    empty_count = module.call_tool(
        "portfolio_sql_table_count",
        {"table_name": "portfolio_snapshots"},
    )
    stored_snapshot = module.call_tool(
        "portfolio_sql_store_snapshot",
        {
            "snapshot": snapshot.model_dump(mode="json"),
            "source_report": sample_opend_report.model_dump(mode="json"),
        },
    )
    skipped_daily_snapshot = module.call_tool(
        "portfolio_sql_store_daily_snapshot_if_needed",
        {
            "snapshot": snapshot.model_dump(mode="json"),
            "source_report": sample_opend_report.model_dump(mode="json"),
        },
    )
    stored_metrics = module.call_tool(
        "portfolio_sql_store_metrics",
        {
            "snapshot_id": stored_snapshot.structured_content["snapshot_id"],
            "metrics": metrics.structured_content,
        },
    )
    history = module.call_tool(
        "portfolio_sql_history_status",
        {
            "portfolio_id": snapshot.portfolio_id,
            "now": snapshot.as_of.isoformat(),
            "min_snapshots_for_history": 1,
        },
    )
    latest = module.call_tool(
        "portfolio_sql_latest_snapshot",
        {"portfolio_id": snapshot.portfolio_id},
    )
    stored_audit = module.call_tool(
        "portfolio_sql_store_audit_record",
        {"audit_record": _audit_record().model_dump(mode="json")},
    )
    status_resource = module.read_resource("portfolio-sql://status")
    schema_resource = module.read_resource("portfolio-sql://schema")

    assert initialized.structured_content["initialized"] is True
    assert empty_count.structured_content["count"] == 0
    assert stored_snapshot.structured_content["holdings_count"] == len(snapshot.holdings)
    assert skipped_daily_snapshot.structured_content["status"] == "skipped"
    assert skipped_daily_snapshot.structured_content["existing_snapshot_id"] == (
        stored_snapshot.structured_content["snapshot_id"]
    )
    assert stored_snapshot.structured_content["quotes_count"] == 1
    assert stored_metrics.structured_content["metrics_stored"] == 5
    assert history.structured_content["snapshot_count"] == 1
    assert latest.structured_content["snapshot"]["portfolio_id"] == snapshot.portfolio_id
    assert stored_audit.structured_content == {"stored": True, "run_id": "run_mcp_contract"}
    assert '"portfolio_snapshots": 1' in status_resource["contents"][0]["text"]
    assert "CREATE TABLE IF NOT EXISTS portfolio_snapshots" in schema_resource["contents"][0]["text"]


def test_portfolio_sql_mcp_rejects_table_count_outside_allowlist(tmp_path):
    module = build_portfolio_sql_mcp_module(db_path=tmp_path / "portfolio.sqlite")

    with pytest.raises(ValueError, match="Unsupported table count"):
        module.call_tool("portfolio_sql_table_count", {"table_name": "sqlite_master"})


def _metrics_snapshot():
    snapshot = mock_portfolio_packet().snapshot
    holdings = []
    for holding in snapshot.holdings:
        holdings.append(
            holding.model_copy(
                update={
                    "exchange": "US",
                    "asset_type": "equity" if holding.ticker in {"MSFT", "AAPL"} else "etf",
                }
            )
        )
    return snapshot.model_copy(update={"holdings": holdings})


def _audit_record() -> AuditRecord:
    return AuditRecord(
        run_id="run_mcp_contract",
        timestamp=datetime(2026, 5, 23, tzinfo=UTC),
        user_query="Review my portfolio",
        mode="review",
        tools_called=["portfolio_sql_store_audit_record"],
        data_timestamps=["2026-05-23T00:00:00+00:00"],
        source_ids=[],
        assumptions=[],
        guardrail_result=GuardrailResult(
            passed=True,
            checks=[
                GuardrailCheck(
                    check="no_trade_placement",
                    passed=True,
                    message="No trade placement requested.",
                )
            ],
        ),
        output_summary="MCP audit summary only.",
        memory_updates=[],
    )
