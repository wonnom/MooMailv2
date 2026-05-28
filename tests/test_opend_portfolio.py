from datetime import UTC, datetime

from moomail_finance_ai.mocks import mock_investment_policy
from moomail_finance_ai.opend import OpenDConnectionStatus, OpenDFieldReport, OpenDTableResult
from moomail_finance_ai.opend_portfolio import (
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
    assert any(issue.issue_type == "single_position_concentration" for issue in packet.candidate_issues)
    assert not any(issue.issue_type == "negative_cash" for issue in packet.candidate_issues)
    assert any("Negative cash" in warning for warning in packet.data_quality.warnings)


def _sample_report(cash: float = 100.0) -> OpenDFieldReport:
    now = datetime(2026, 5, 23, tzinfo=UTC)
    return OpenDFieldReport(
        generated_at=now,
        connection=OpenDConnectionStatus(
            ok=True,
            host="127.0.0.1",
            port=11111,
            checked_at=now,
            message="ok",
        ),
        tables=[
            OpenDTableResult(
                name="funds",
                rows=[{"total_assets": 1000.0, "cash": cash, "currency": "USD"}],
                fields=["total_assets", "cash", "currency"],
                as_of=now,
            ),
            OpenDTableResult(
                name="positions",
                rows=[
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
                ],
                fields=["code", "stock_name", "qty", "nominal_price", "market_val"],
                as_of=now,
            ),
            OpenDTableResult(
                name="quotes",
                rows=[
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
                ],
                fields=["code", "name", "last_price", "option_valid"],
                as_of=now,
            ),
        ],
    )
