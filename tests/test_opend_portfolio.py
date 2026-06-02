from datetime import UTC, datetime

from moomail_finance_ai.mocks import mock_investment_policy
from moomail_finance_ai.opend import OpenDConnectionStatus, OpenDFieldReport, OpenDTableResult
from moomail_finance_ai.opend_portfolio import (
    OpenDPortfolioDataError,
    build_portfolio_agent_packet,
    build_portfolio_snapshot_from_report,
)


def test_build_portfolio_snapshot_from_opend_report():
    report = _sample_report()

    snapshot = build_portfolio_snapshot_from_report(
        report,
        portfolio_id="portfolio_default",
        base_currency="USD",
    )

    assert snapshot.total_value.amount == 1000.0
    assert snapshot.cash[0].amount == 100.0
    assert len(snapshot.holdings) == 2
    assert snapshot.holdings[0].ticker == "AAPL"
    assert snapshot.holdings[0].asset_type == "equity"
    assert snapshot.holdings[0].portfolio_weight == 0.3
    assert snapshot.holdings[1].asset_type == "option"
    assert snapshot.data_quality.missing_fields == []


def test_build_portfolio_snapshot_infers_value_when_funds_table_is_missing():
    report = _sample_report(include_funds=False)

    snapshot = build_portfolio_snapshot_from_report(
        report,
        portfolio_id="portfolio_default",
        base_currency="USD",
    )

    assert snapshot.total_value.amount == 250.0
    assert snapshot.cash[0].amount == 0.0
    assert "funds_table" in snapshot.data_quality.missing_fields
    assert any("funds were unavailable" in warning for warning in snapshot.data_quality.warnings)


def test_build_portfolio_snapshot_uses_base_currency_fund_fields():
    report = _sample_report(
        fund_row={"usd_assets": 1200.0, "us_cash": 150.0, "currency": "USD"}
    )

    snapshot = build_portfolio_snapshot_from_report(
        report,
        portfolio_id="portfolio_default",
        base_currency="USD",
    )

    assert snapshot.total_value.amount == 1200.0
    assert snapshot.cash[0].amount == 150.0
    assert "total_assets" not in snapshot.data_quality.missing_fields
    assert "cash" not in snapshot.data_quality.missing_fields


def test_build_portfolio_snapshot_classifies_money_market_fund_as_cash_equivalent():
    report = _sample_report(include_cash_fund=True)

    snapshot = build_portfolio_snapshot_from_report(
        report,
        portfolio_id="portfolio_default",
        base_currency="USD",
    )

    cash_fund = next(holding for holding in snapshot.holdings if holding.ticker == "USDMMF")
    packet = build_portfolio_agent_packet(snapshot, mock_investment_policy(), report)
    cash_allocation = next(row for row in packet.allocation["by_sector"] if row.name == "cash")

    assert cash_fund.asset_type == "cash_equivalent"
    assert any(
        row.name == "Moomoo USD Cash Plus Fund" for row in packet.allocation["by_asset"]
    )
    assert cash_allocation.value == 200.0 + snapshot.cash[0].amount
    assert any(
        "Cash-equivalent fund holdings" in warning for warning in packet.data_quality.warnings
    )


def test_build_portfolio_snapshot_treats_account_fund_assets_as_cash_sweep():
    report = _sample_report(
        fund_row={
            "total_assets": 1000.0,
            "cash": 3.0,
            "fund_assets": 250.0,
            "currency": "USD",
        }
    )

    snapshot = build_portfolio_snapshot_from_report(
        report,
        portfolio_id="portfolio_default",
        base_currency="USD",
        treat_fund_assets_as_cash_sweep=True,
    )
    packet = build_portfolio_agent_packet(snapshot, mock_investment_policy(), report)

    assert [cash.account_id for cash in snapshot.cash] == [
        "opend_selected_account",
        "opend_fund_assets_cash_sweep",
    ]
    assert sum(cash.amount for cash in snapshot.cash) == 253.0
    assert any(
        row.name == "Fund Assets" for row in packet.allocation["by_asset"]
    )
    assert any("auto-invested" in warning for warning in packet.data_quality.warnings)


def test_build_portfolio_snapshot_does_not_treat_fund_assets_as_cash_by_default():
    report = _sample_report(
        fund_row={
            "total_assets": 1000.0,
            "cash": 3.0,
            "fund_assets": 250.0,
            "currency": "USD",
        }
    )

    snapshot = build_portfolio_snapshot_from_report(
        report,
        portfolio_id="portfolio_default",
        base_currency="USD",
    )

    assert [cash.account_id for cash in snapshot.cash] == ["opend_selected_account"]
    assert snapshot.cash[0].amount == 3.0
    assert any("fund_assets is present" in warning for warning in snapshot.data_quality.warnings)


def test_build_portfolio_snapshot_reports_upstream_warning_when_positions_missing():
    report = _sample_report(include_positions=False)
    report = report.model_copy(update={"warnings": ["get_positions failed: Network interruption"]})

    try:
        build_portfolio_snapshot_from_report(
            report,
            portfolio_id="portfolio_default",
            base_currency="USD",
        )
    except OpenDPortfolioDataError as exc:
        message = str(exc)
    else:
        raise AssertionError("Expected missing positions to raise")

    assert "missing positions table" in message
    assert "get_positions failed: Network interruption" in message


def test_build_portfolio_agent_packet_scopes_candidate_issues_to_v1_equities():
    report = _sample_report(cash=-100.0)
    ips = mock_investment_policy().model_copy(update={"max_single_stock_concentration": 0.2})
    snapshot = build_portfolio_snapshot_from_report(
        report,
        portfolio_id="portfolio_default",
        base_currency="USD",
    )

    packet = build_portfolio_agent_packet(snapshot, ips, report)

    assert packet.allocation["by_asset"]
    assert any(
        issue.issue_type == "single_position_concentration"
        for issue in packet.candidate_issues
    )
    assert not any(issue.issue_type == "negative_cash" for issue in packet.candidate_issues)
    assert any("Negative cash" in warning for warning in packet.data_quality.warnings)


def _sample_report(
    cash: float = 100.0,
    *,
    include_funds: bool = True,
    include_positions: bool = True,
    include_cash_fund: bool = False,
    fund_row: dict | None = None,
) -> OpenDFieldReport:
    now = datetime(2026, 5, 23, tzinfo=UTC)
    tables = []
    if include_funds:
        row = fund_row or {"total_assets": 1000.0, "cash": cash, "currency": "USD"}
        tables.append(
            OpenDTableResult(
                name="funds",
                rows=[row],
                fields=sorted(row),
                as_of=now,
            )
        )
    if include_positions:
        position_rows = [
            {
                "code": "US.AAPL",
                "stock_name": "Apple",
                "position_market": "US",
                "qty": 1,
                "nominal_price": 300,
                "market_val": 300,
                "unrealized_pl": 10,
                "currency": "USD",
                "position_side": "LONG",
            },
            {
                "code": "US.TSLA260618P400000",
                "stock_name": "TSLA Put",
                "position_market": "US",
                "qty": -1,
                "nominal_price": 5,
                "market_val": -50,
                "unrealized_pl": 2,
                "currency": "USD",
                "position_side": "SHORT",
            },
        ]
        if include_cash_fund:
            position_rows.append(
                {
                    "code": "US.USDMMF",
                    "stock_name": "Moomoo USD Cash Plus Fund",
                    "position_market": "US",
                    "qty": 200,
                    "nominal_price": 1,
                    "market_val": 200,
                    "unrealized_pl": 0,
                    "currency": "USD",
                    "position_side": "LONG",
                }
            )
        tables.append(
            OpenDTableResult(
                name="positions",
                rows=position_rows,
                fields=["code", "stock_name", "qty", "nominal_price", "market_val"],
                as_of=now,
            )
        )
    quote_rows = [
        {
            "code": "US.AAPL",
            "name": "Apple",
            "last_price": 300,
            "option_valid": False,
        },
        {
            "code": "US.TSLA260618P400000",
            "name": "TSLA Put",
            "last_price": 5,
            "option_valid": True,
        },
    ]
    if include_cash_fund:
        quote_rows.append(
            {
                "code": "US.USDMMF",
                "name": "Moomoo USD Cash Plus Fund",
                "last_price": 1,
                "trust_valid": True,
            }
        )
    tables.append(
        OpenDTableResult(
            name="quotes",
            rows=quote_rows,
            fields=["code", "name", "last_price", "option_valid"],
            as_of=now,
        )
    )
    return OpenDFieldReport(
        generated_at=now,
        connection=OpenDConnectionStatus(
            ok=True,
            host="127.0.0.1",
            port=11111,
            checked_at=now,
            message="ok",
        ),
        tables=tables,
    )
