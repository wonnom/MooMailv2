from datetime import UTC, datetime

from moomail_finance_ai.metrics import (
    METRIC_VERSION,
    calculate_asset_type_allocation,
    calculate_cash_weight,
    calculate_position_weights,
    calculate_single_position_concentration,
    calculate_snapshot_metrics,
)
from moomail_finance_ai.mocks import mock_investment_policy
from moomail_finance_ai.schemas import CashBalance, DataQuality, Holding, Money, PortfolioSnapshot


def test_cash_weight_is_deterministic_and_versioned():
    snapshot = _snapshot()

    result = calculate_cash_weight(snapshot)

    assert result.metric_name == "cash_weight"
    assert result.metric_version == METRIC_VERSION
    assert result.value == 0.1
    assert result.source_inputs["total_value"] == 1000.0


def test_cash_weight_counts_cash_equivalent_holdings():
    snapshot = _snapshot()
    snapshot = snapshot.model_copy(
        update={
            "holdings": [
                holding.model_copy(update={"asset_type": "cash_equivalent"})
                if holding.ticker == "MONEYFUND"
                else holding
                for holding in snapshot.holdings
            ]
        }
    )

    cash = calculate_cash_weight(snapshot)
    allocation = calculate_asset_type_allocation(snapshot)

    assert cash.value == 0.65
    assert cash.source_inputs["cash_value"] == 100.0
    assert cash.source_inputs["cash_equivalent_value"] == 550.0
    assert cash.source_inputs["effective_cash_value"] == 650.0
    cash_allocation = next(row for row in allocation.value if row["asset_type"] == "cash")
    assert cash_allocation["market_value"] == 650.0


def test_position_weights_default_to_v1_us_equities_scope():
    snapshot = _snapshot()

    result = calculate_position_weights(snapshot)

    tickers = [row["ticker"] for row in result.value]
    assert tickers == ["AAPL", "MSFT"]
    assert result.value[0]["weight_in_scope"] == 0.25
    assert result.value[1]["weight_in_scope"] == 0.75
    assert result.warnings == ["2 holding(s) excluded from v1 US-equity metrics."]


def test_concentration_uses_v1_scope_not_full_account_noise():
    snapshot = _snapshot()
    ips = mock_investment_policy().model_copy(update={"max_single_stock_concentration": 0.7})

    result = calculate_single_position_concentration(snapshot, ips)

    assert result.metric_name == "single_position_concentration"
    assert [row["ticker"] for row in result.value] == ["MSFT"]
    assert result.value[0]["weight_in_scope"] == 0.75


def test_snapshot_metrics_are_versioned_as_a_set():
    metrics = calculate_snapshot_metrics(_snapshot(), mock_investment_policy())

    assert {metric.metric_version for metric in metrics} == {METRIC_VERSION}
    assert {metric.metric_name for metric in metrics} == {
        "asset_type_allocation",
        "benchmark_reference",
        "cash_weight",
        "position_weights",
        "single_position_concentration",
    }


def _snapshot() -> PortfolioSnapshot:
    now = datetime(2026, 5, 23, tzinfo=UTC)
    return PortfolioSnapshot(
        portfolio_id="portfolio_default",
        as_of=now,
        base_currency="USD",
        total_value=Money(amount=1000.0, currency="USD", source="test", as_of=now),
        cash=[CashBalance(account_id="acct", amount=100.0, currency="USD", weight=0.1)],
        holdings=[
            Holding(
                asset_id="asset_aapl",
                ticker="AAPL",
                name="Apple",
                asset_type="equity",
                exchange="US",
                currency="USD",
                quantity=1,
                market_price=100,
                market_value=100,
                portfolio_weight=0.1,
                source="test",
                as_of=now,
            ),
            Holding(
                asset_id="asset_msft",
                ticker="MSFT",
                name="Microsoft",
                asset_type="equity",
                exchange="US",
                currency="USD",
                quantity=3,
                market_price=100,
                market_value=300,
                portfolio_weight=0.3,
                source="test",
                as_of=now,
            ),
            Holding(
                asset_id="asset_option",
                ticker="TSLA260618P400000",
                name="TSLA Put",
                asset_type="option",
                exchange="US",
                currency="USD",
                quantity=-1,
                market_price=5,
                market_value=-50,
                portfolio_weight=-0.05,
                source="test",
                as_of=now,
            ),
            Holding(
                asset_id="asset_fund",
                ticker="MONEYFUND",
                name="Money Fund",
                asset_type="fund",
                exchange="US",
                currency="USD",
                quantity=1,
                market_price=550,
                market_value=550,
                portfolio_weight=0.55,
                source="test",
                as_of=now,
            ),
        ],
        data_quality=DataQuality(freshness_status="fresh"),
    )
