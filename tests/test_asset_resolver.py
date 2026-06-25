from __future__ import annotations

import json
from datetime import UTC, datetime

from moomail_finance_ai.agent_schemas import AssetHint
from moomail_finance_ai.asset_resolver import (
    PortfolioAssetCandidate,
    asset_resolution_trace_events,
    build_portfolio_asset_candidates,
    normalize_asset_hint_key,
    resolve_asset_hint,
)
from moomail_finance_ai.schemas import DataQuality, Holding, Money, PortfolioSnapshot


def test_asset_resolver_import_smoke():
    candidate = PortfolioAssetCandidate(
        canonical_symbol="US.AMZN",
        ticker="AMZN",
        display_name="Amazon.com Inc.",
        sql_asset_id="asset_amzn",
    )

    assert candidate.canonical_symbol == "US.AMZN"


def test_resolver_prefers_current_portfolio_candidates():
    snapshot = _snapshot(
        [
            _holding("US.AMZN", "AMZN", "Amazon Current"),
            _holding("US.GOOG", "GOOG", "Alphabet Current"),
        ]
    )

    candidates = build_portfolio_asset_candidates(
        sql_assets=[
            {
                "asset_id": "asset_amzn_sql",
                "provider_code": "US.AMZN",
                "ticker": "AMZN",
                "name": "Amazon SQL",
                "asset_type": "equity",
                "exchange": "NASDAQ",
            }
        ],
        current_snapshot=snapshot,
        fixture_candidates=[
            {
                "canonical_symbol": "US.AMZN",
                "ticker": "AMZN",
                "display_name": "Amazon Fixture",
                "sql_asset_id": "asset_amzn_fixture",
            },
            {
                "canonical_symbol": "US.GOOG",
                "ticker": "GOOG",
                "display_name": "Alphabet Fixture",
                "sql_asset_id": "asset_goog_fixture",
            },
        ],
    )

    amzn = resolve_asset_hint("AMZN", candidates)
    goog = resolve_asset_hint("GOOG", candidates)

    assert amzn.display_name == "Amazon SQL"
    assert amzn.sql_asset_id == "asset_amzn_sql"
    assert amzn.source == "sql_latest"
    assert goog.display_name == "Alphabet Current"
    assert goog.sql_asset_id == "opend:US.GOOG"
    assert goog.source == "current_snapshot"


def test_resolver_preserves_raw_hint_and_normalizes_match_key():
    hint = AssetHint(raw_input="  amzn  ")
    resolution = resolve_asset_hint(hint, _base_candidates())

    assert resolution.input == "  amzn  "
    assert resolution.resolution_status == "resolved"
    assert resolution.canonical_symbol == "US.AMZN"
    assert normalize_asset_hint_key(hint.raw_input) == "amzn"


def test_resolver_maps_us_symbol_hint_to_canonical_symbol():
    resolution = resolve_asset_hint("AMZN", _base_candidates())

    assert resolution.resolution_status == "resolved"
    assert resolution.canonical_symbol == "US.AMZN"
    assert resolution.sql_asset_id == "opend:US.AMZN"


def test_resolver_maps_display_name_hint_to_asset():
    resolution = resolve_asset_hint("Amazon", _base_candidates())

    assert resolution.resolution_status == "resolved"
    assert resolution.canonical_symbol == "US.AMZN"
    assert resolution.display_name == "Amazon.com Inc."


def test_resolver_accepts_prefixed_symbol():
    resolution = resolve_asset_hint("US.AMZN", _base_candidates())

    assert resolution.resolution_status == "resolved"
    assert resolution.canonical_symbol == "US.AMZN"


def test_resolver_returns_not_in_portfolio_for_unheld_symbol():
    resolution = resolve_asset_hint("TSLA", _base_candidates())

    assert resolution.resolution_status == "not_in_portfolio"
    assert resolution.canonical_symbol is None
    assert "does not match" in resolution.warnings[0]


def test_resolver_returns_ambiguous_for_multiple_matches():
    resolution = resolve_asset_hint(
        "Alphabet",
        [
            PortfolioAssetCandidate(
                canonical_symbol="US.GOOG",
                ticker="GOOG",
                display_name="Alphabet Inc.",
                sql_asset_id="opend:US.GOOG",
            ),
            PortfolioAssetCandidate(
                canonical_symbol="US.GOOGL",
                ticker="GOOGL",
                display_name="Alphabet Class A",
                sql_asset_id="opend:US.GOOGL",
            ),
        ],
    )

    assert resolution.resolution_status == "ambiguous"
    assert resolution.canonical_symbol is None
    assert "US.GOOG" in resolution.warnings[0]


def test_resolver_flags_unsupported_market_hint():
    resolution = resolve_asset_hint("HK.0700", _base_candidates())

    assert resolution.resolution_status == "unsupported_market"
    assert resolution.canonical_symbol is None
    assert "outside the V1.4 US-equity resolver scope" in resolution.warnings[0]


def test_resolver_returns_unknown_for_vague_hint():
    resolution = resolve_asset_hint("the e-commerce one", _base_candidates())

    assert resolution.resolution_status == "unknown"
    assert resolution.canonical_symbol is None


def test_resolver_preserves_non_blocking_asset_warnings():
    resolution = resolve_asset_hint(
        "TCEHY",
        [
            PortfolioAssetCandidate(
                canonical_symbol="US.TCEHY",
                ticker="TCEHY",
                display_name="Tencent Holdings ADR",
                sql_asset_id="opend:US.TCEHY",
                exchange="OTC",
            )
        ],
    )

    assert resolution.resolution_status == "resolved"
    assert any("OTC market data" in warning for warning in resolution.warnings)


def test_asset_resolution_trace_is_sanitized():
    resolution = resolve_asset_hint("AMZN", _base_candidates())
    events = asset_resolution_trace_events("run_asset_trace", [resolution])
    payload = events[0].model_dump(mode="json")
    serialized = json.dumps(payload)

    assert payload["phase"] == "asset_resolver"
    assert payload["metadata"]["resolution_status"] == "resolved"
    assert payload["metadata"]["sql_asset_id_present"] is True
    assert "sql_asset_id" not in payload["metadata"]
    assert "account_id" not in serialized
    assert "raw_positions" not in serialized


def _base_candidates() -> list[PortfolioAssetCandidate]:
    return [
        PortfolioAssetCandidate(
            canonical_symbol="US.AMZN",
            ticker="AMZN",
            display_name="Amazon.com Inc.",
            sql_asset_id="opend:US.AMZN",
        )
    ]


def _snapshot(holdings: list[Holding]) -> PortfolioSnapshot:
    return PortfolioSnapshot(
        portfolio_id="portfolio_default",
        as_of=datetime(2026, 6, 24, tzinfo=UTC),
        base_currency="USD",
        total_value=Money(amount=1000.0, currency="USD"),
        cash=[],
        holdings=holdings,
        data_quality=DataQuality(),
    )


def _holding(canonical_symbol: str, ticker: str, name: str) -> Holding:
    return Holding(
        asset_id=f"opend:{canonical_symbol}",
        ticker=ticker,
        name=name,
        asset_type="equity",
        exchange="NASDAQ",
        currency="USD",
        quantity=1.0,
        market_price=100.0,
        market_value=100.0,
        portfolio_weight=0.1,
        source="recorded",
        as_of=datetime(2026, 6, 24, tzinfo=UTC),
    )
