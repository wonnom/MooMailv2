from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from moomail_finance_ai.mcp.finance_metrics_mcp import build_finance_metrics_mcp_module
from moomail_finance_ai.mcp.gateway import DirectToolGateway
from moomail_finance_ai.mcp.portfolio_sql_mcp import build_portfolio_sql_mcp_module
from moomail_finance_ai.metrics import OPEND_FUND_ASSETS_CASH_SWEEP_ID
from moomail_finance_ai.portfolio_baseline import (
    BASELINE_ALLOCATION_HISTORY_ROW_LIMIT,
    BASELINE_CONSUMER,
    BASELINE_GROWTH_ROW_LIMIT,
    BASELINE_POSITION_CHANGE_ROW_LIMIT,
    PortfolioBaselineService,
)
from moomail_finance_ai.portfolio_data_service import snapshot_from_latest_state
from moomail_finance_ai.schemas import (
    CashBalance,
    DataQuality,
    Holding,
    Money,
    PortfolioSnapshot,
)
from moomail_finance_ai.sql_store import PortfolioSqlStore


NOW = datetime(2026, 8, 3, 12, tzinfo=UTC)


def test_baseline_context_reuses_deterministic_snapshot_lane(tmp_path):
    store, service, _gateway = _seeded_service(tmp_path)
    expected = snapshot_from_latest_state(
        store.latest_portfolio_state("portfolio_default"),
        base_currency="USD",
    )

    packet = service.load(now=NOW)

    assert expected is not None
    latest = _summary(packet, "latest_snapshot")
    assert latest.facts["total_value"] == expected.total_value.amount
    assert packet.as_of == expected.as_of
    assert "latest_snapshot" in packet.capabilities


def test_baseline_context_does_not_call_opend_refresh(tmp_path):
    _store, service, gateway = _seeded_service(tmp_path)

    service.load(now=NOW)

    assert gateway.calls
    assert {call[3] for call in gateway.calls} == {BASELINE_CONSUMER}
    assert all("opend" not in server_name for server_name, *_rest in gateway.calls)
    assert all("refresh" not in tool_name for _server, tool_name, *_rest in gateway.calls)


def test_baseline_context_does_not_call_agents_or_llm():
    source = Path("src/moomail_finance_ai/portfolio_baseline.py").read_text(encoding="utf-8")

    for forbidden in (
        "InvestmentAgent",
        "PortfolioAgent",
        "PortfolioEvaluator",
        "SentimentAgent",
        "build_llm_client",
        "generate_text",
    ):
        assert forbidden not in source


def test_baseline_context_reads_bounded_history_windows(tmp_path):
    _store, service, gateway = _seeded_service(tmp_path)

    service.load(now=NOW)

    calls = {tool_name: arguments for _server, tool_name, arguments, _consumer in gateway.calls}
    assert calls["portfolio_sql_get_portfolio_growth"]["limit"] == BASELINE_GROWTH_ROW_LIMIT
    assert (
        calls["portfolio_sql_get_allocation_history"]["limit"]
        == BASELINE_ALLOCATION_HISTORY_ROW_LIMIT
    )
    position_call = calls["portfolio_sql_get_position_state_changes"]
    assert position_call["lookback_days"] == 7
    assert position_call["limit"] == BASELINE_POSITION_CHANGE_ROW_LIMIT
    assert position_call["until"] == NOW.isoformat()


def test_baseline_context_calculates_7d_and_30d_value_trends(tmp_path):
    _store, service, _gateway = _seeded_service(tmp_path)

    packet = service.load(now=NOW)

    seven = _summary(packet, "portfolio_value_trend_7d")
    thirty = _summary(packet, "portfolio_value_trend_30d")
    assert seven.facts["start_value"] == 1100.0
    assert seven.facts["end_value"] == 1200.0
    assert seven.facts["absolute_change"] == 100.0
    assert seven.facts["percent_change"] == round(100 / 1100, 10)
    assert thirty.facts["start_value"] == 1000.0
    assert thirty.facts["absolute_change"] == 200.0
    assert thirty.facts["actual_window_days"] == 30.0


def test_baseline_context_summarizes_top_allocation_changes(tmp_path):
    _store, service, _gateway = _seeded_service(tmp_path)

    packet = service.load(now=NOW)
    changes = [
        summary
        for summary in packet.summaries
        if summary.capability == "top_allocation_changes_7d"
    ]

    assert changes
    assert changes[0].facts["ticker"] == "AAPL"
    assert changes[0].facts["weight_change"] > 0
    assert "top_allocation_changes_7d" in packet.capabilities


def test_baseline_context_summarizes_recent_position_changes(tmp_path):
    _store, service, _gateway = _seeded_service(tmp_path)

    packet = service.load(now=NOW)
    changes = [
        summary
        for summary in packet.summaries
        if summary.capability == "top_position_changes_7d"
    ]

    aapl = next(summary for summary in changes if summary.facts.get("ticker") == "AAPL")
    assert aapl.facts["quantity_delta"] == 3.0
    assert aapl.facts["previous_quantity"] == 10.0
    assert aapl.facts["current_quantity"] == 13.0
    assert not {
        "average_cost_delta",
        "cost_basis_delta",
        "implied_added_average_cost",
        "previous_state",
        "current_state",
    } & set(aapl.facts)


def test_baseline_context_preserves_effective_cash_semantics(tmp_path):
    _store, service, _gateway = _seeded_service(tmp_path)

    cash = _summary(service.load(now=NOW), "effective_cash")

    assert cash.facts["literal_cash"] == 100.0
    assert cash.facts["configured_cash_sweep"] == 50.0
    assert cash.facts["cash_equivalent_holdings"] == 50.0
    assert cash.facts["effective_cash"] == 200.0
    assert cash.facts["effective_cash_weight"] == round(200 / 1200, 10)


def test_baseline_context_reports_partial_history(tmp_path):
    store, service, _gateway = _empty_service(tmp_path)
    store.store_portfolio_observation(_snapshot(NOW - timedelta(days=2), total=1000))

    packet = service.load(now=NOW)

    assert any("stale or incomplete" in limitation for limitation in packet.limitations)
    freshness = _summary(packet, "history_freshness")
    assert freshness.facts["freshness_status"] == "stale"
    history_ref = next(
        ref for ref in packet.evidence_refs if ref.ref_id == "sql.history.freshness"
    )
    assert history_ref.quality == "stale"


def test_baseline_context_reports_unsupported_quotes(tmp_path):
    store, service, _gateway = _empty_service(tmp_path)
    warning_snapshot = _snapshot(NOW, total=1000).model_copy(
        update={
            "data_quality": DataQuality(
                freshness_status="fresh",
                warnings=["OTC quote missing for one stored holding."],
            )
        }
    )
    store.store_portfolio_observation(warning_snapshot, observed_at=NOW)

    packet = service.load(now=NOW)

    assert any("OTC quote missing" in warning for warning in packet.warnings)
    assert any("unsupported quote" in limitation for limitation in packet.limitations)


def test_baseline_context_omits_uncovered_trend_capability(tmp_path):
    store, service, _gateway = _empty_service(tmp_path)
    store.store_portfolio_observation(_snapshot(NOW, total=1000))

    packet = service.load(now=NOW)

    assert "portfolio_value_trend_7d" not in packet.capabilities
    assert "portfolio_value_trend_30d" not in packet.capabilities
    assert any("7-day" in limitation for limitation in packet.limitations)
    assert any("30-day" in limitation for limitation in packet.limitations)


def test_baseline_context_keeps_fresh_current_evidence_when_history_is_shallow(tmp_path):
    store, service, _gateway = _empty_service(tmp_path)
    store.store_portfolio_observation(_snapshot(NOW, total=1000), observed_at=NOW)

    packet = service.load(now=NOW)

    latest_ref = next(
        ref for ref in packet.evidence_refs if ref.ref_id == "dashboard.snapshot.total_value"
    )
    history_ref = next(
        ref for ref in packet.evidence_refs if ref.ref_id == "sql.history.freshness"
    )
    assert latest_ref.quality == "complete"
    assert history_ref.quality == "partial"
    assert "latest_snapshot" in packet.capabilities
    assert "portfolio_value_trend_7d" not in packet.capabilities


def test_baseline_context_preserves_actual_as_of(tmp_path):
    observed_at = NOW - timedelta(hours=8)
    store, service, _gateway = _empty_service(tmp_path)
    store.store_portfolio_observation(_snapshot(observed_at, total=1000))

    packet = service.load(now=NOW)

    assert packet.as_of == observed_at
    latest_ref = next(
        ref for ref in packet.evidence_refs if ref.ref_id == "dashboard.snapshot.total_value"
    )
    assert latest_ref.as_of == observed_at


def test_baseline_context_degrades_to_explicit_limitations():
    packet = PortfolioBaselineService(DirectToolGateway([])).load(now=NOW)

    assert packet.capabilities == []
    assert packet.summaries == []
    assert packet.evidence_refs == []
    assert any("unavailable" in limitation for limitation in packet.limitations)


def test_baseline_context_assigns_stable_evidence_refs(tmp_path):
    _store, service, _gateway = _seeded_service(tmp_path)

    first = service.load(now=NOW)
    second = service.load(now=NOW)

    assert [ref.ref_id for ref in first.evidence_refs] == [
        ref.ref_id for ref in second.evidence_refs
    ]
    known_refs = {ref.ref_id for ref in first.evidence_refs}
    assert all(set(summary.evidence_refs) <= known_refs for summary in first.summaries)


def test_baseline_change_sort_is_deterministic(tmp_path):
    _store, service, _gateway = _seeded_service(tmp_path)

    packet = service.load(now=NOW)
    changes = [
        summary
        for summary in packet.summaries
        if summary.capability == "top_allocation_changes_7d"
    ]
    materiality = [abs(float(summary.facts["weight_change"])) for summary in changes]

    assert materiality == sorted(materiality, reverse=True)


def test_baseline_context_enforces_compact_limits(tmp_path):
    _store, _service, gateway = _seeded_service(tmp_path)
    service = PortfolioBaselineService(
        gateway,
        allocation_summary_limit=2,
        change_summary_limit=1,
    )

    packet = service.load(now=NOW)

    assert len([row for row in packet.summaries if row.capability == "allocation_breakdown"]) == 2
    assert len(
        [row for row in packet.summaries if row.capability == "top_allocation_changes_7d"]
    ) == 1
    assert len(
        [row for row in packet.summaries if row.capability == "top_position_changes_7d"]
    ) == 1
    assert len(packet.model_dump_json().encode("utf-8")) < 65_536


def test_baseline_context_excludes_sensitive_raw_fields(tmp_path):
    _store, service, _gateway = _seeded_service(tmp_path)

    serialized = json.dumps(
        service.load(now=NOW).model_dump(mode="json"),
        sort_keys=True,
    ).casefold()

    assert "account_id" not in serialized
    assert "broker_account" not in serialized
    assert "raw_broker_payload" not in serialized
    assert OPEND_FUND_ASSETS_CASH_SWEEP_ID not in serialized


def _seeded_service(tmp_path):
    store, service, gateway = _empty_service(tmp_path)
    for snapshot in (
        _snapshot(NOW - timedelta(days=30), total=1000, aapl_quantity=8, aapl_value=400),
        _snapshot(NOW - timedelta(days=7), total=1100, aapl_quantity=10, aapl_value=500),
        _snapshot(NOW, total=1200, aapl_quantity=13, aapl_value=650),
    ):
        store.store_portfolio_observation(snapshot, observed_at=snapshot.as_of)
    return store, service, gateway


def _empty_service(tmp_path):
    store = PortfolioSqlStore(tmp_path / "portfolio.sqlite")
    gateway = RecordingGateway(
        DirectToolGateway(
            [
                build_portfolio_sql_mcp_module(store=store),
                build_finance_metrics_mcp_module(),
            ]
        )
    )
    return store, PortfolioBaselineService(gateway), gateway


def _snapshot(
    as_of: datetime,
    *,
    total: float,
    aapl_quantity: float = 10,
    aapl_value: float = 500,
) -> PortfolioSnapshot:
    cash = 100.0
    sweep = 50.0
    cash_equivalent = 50.0
    msft_value = total - aapl_value - cash - sweep - cash_equivalent
    return PortfolioSnapshot(
        portfolio_id="portfolio_default",
        as_of=as_of,
        base_currency="USD",
        total_value=Money(amount=total, currency="USD", source="test", as_of=as_of),
        cash=[
            CashBalance(
                account_id="internal_cash_account",
                amount=cash,
                currency="USD",
                weight=cash / total,
            ),
            CashBalance(
                account_id=OPEND_FUND_ASSETS_CASH_SWEEP_ID,
                amount=sweep,
                currency="USD",
                weight=sweep / total,
            ),
        ],
        holdings=[
            Holding(
                asset_id="asset_aapl",
                ticker="AAPL",
                name="Apple",
                asset_type="equity",
                exchange="US",
                currency="USD",
                quantity=aapl_quantity,
                market_price=aapl_value / aapl_quantity,
                market_value=aapl_value,
                portfolio_weight=aapl_value / total,
                source="test",
                as_of=as_of,
            ),
            Holding(
                asset_id="asset_msft",
                ticker="MSFT",
                name="Microsoft",
                asset_type="equity",
                exchange="US",
                currency="USD",
                quantity=5,
                market_price=msft_value / 5,
                market_value=msft_value,
                portfolio_weight=msft_value / total,
                source="test",
                as_of=as_of,
            ),
            Holding(
                asset_id="asset_money_fund",
                ticker="MONEYFUND",
                name="Money Market Fund",
                asset_type="cash_equivalent",
                exchange="US",
                currency="USD",
                quantity=1,
                market_price=cash_equivalent,
                market_value=cash_equivalent,
                portfolio_weight=cash_equivalent / total,
                source="test",
                as_of=as_of,
            ),
        ],
        data_quality=DataQuality(freshness_status="fresh"),
    )


def _summary(packet, capability):
    return next(summary for summary in packet.summaries if summary.capability == capability)


class RecordingGateway:
    def __init__(self, gateway):
        self.gateway = gateway
        self.calls: list[tuple[str, str, dict[str, Any], str]] = []

    def call_tool(self, server_name, tool_name, arguments=None, *, consumer):
        self.calls.append((server_name, tool_name, dict(arguments or {}), consumer))
        return self.gateway.call_tool(server_name, tool_name, arguments, consumer=consumer)

    def list_tools(self, server_name, *, consumer):
        return self.gateway.list_tools(server_name, consumer=consumer)

    def read_resource(self, server_name, uri, *, consumer):
        return self.gateway.read_resource(server_name, uri, consumer=consumer)

    def list_resources(self, server_name, *, consumer):
        return self.gateway.list_resources(server_name, consumer=consumer)
