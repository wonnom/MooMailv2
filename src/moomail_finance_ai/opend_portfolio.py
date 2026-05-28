from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any

from moomail_finance_ai.config import OpenDConfig
from moomail_finance_ai.metrics import v1_us_equity_holdings
from moomail_finance_ai.opend import OpenDFieldReport, OpenDTableResult, ReadOnlyOpenDClient
from moomail_finance_ai.schemas import (
    AllocationSlice,
    CandidateIssue,
    CashBalance,
    DataQuality,
    Holding,
    InvestmentPolicy,
    Money,
    PerformanceSummary,
    PortfolioAgentPacket,
    PortfolioSnapshot,
    RiskSummary,
)


class OpenDPortfolioDataError(RuntimeError):
    """Raised when OpenD data cannot be normalized into a portfolio snapshot."""


class OpenDPortfolioAgent:
    def __init__(self, client: ReadOnlyOpenDClient, config: OpenDConfig):
        self.client = client
        self.config = config
        self.calls = 0

    def run(self, query: str, ips: InvestmentPolicy) -> PortfolioAgentPacket:
        self.calls += 1
        report = self.client.explore_fields()
        snapshot = build_portfolio_snapshot_from_report(
            report,
            portfolio_id=ips.portfolio_id,
            base_currency=self.config.base_currency,
        )
        return build_portfolio_agent_packet(snapshot, ips, report)


def build_portfolio_snapshot_from_report(
    report: OpenDFieldReport,
    *,
    portfolio_id: str,
    base_currency: str,
) -> PortfolioSnapshot:
    funds = _required_table(report, "funds")
    positions = _required_table(report, "positions")
    quotes = _optional_table(report, "quotes")

    if not funds.rows:
        raise OpenDPortfolioDataError("OpenD funds table is empty.")

    fund_row = funds.rows[0]
    as_of = _latest_as_of([funds, positions, quotes])
    total_value = _number(fund_row.get("total_assets"))
    cash_value = _number(fund_row.get("cash"))
    currency = str(fund_row.get("currency") or base_currency)

    quote_by_code = {row.get("code"): row for row in quotes.rows} if quotes else {}
    holdings = [
        _holding_from_position(row, quote_by_code.get(row.get("code")), total_value, as_of)
        for row in positions.rows
    ]

    warnings = list(report.warnings)
    for table in report.tables:
        warnings.extend(table.warnings)

    missing_fields = []
    if not quotes or len(quotes.rows) < len(positions.rows):
        missing_fields.append("quotes_for_all_positions")

    return PortfolioSnapshot(
        portfolio_id=portfolio_id,
        as_of=as_of,
        base_currency=base_currency,
        total_value=Money(amount=total_value, currency=currency, source="opend", as_of=as_of),
        cash=[
            CashBalance(
                account_id="opend_selected_account",
                amount=cash_value,
                currency=currency,
                weight=_weight(cash_value, total_value),
            )
        ],
        holdings=holdings,
        data_quality=DataQuality(
            freshness_status="fresh" if report.connection.ok else "unknown",
            missing_fields=missing_fields,
            warnings=warnings,
        ),
    )


def build_portfolio_agent_packet(
    snapshot: PortfolioSnapshot,
    ips: InvestmentPolicy,
    report: OpenDFieldReport | None = None,
) -> PortfolioAgentPacket:
    by_asset = [
        AllocationSlice(
            name=holding.ticker,
            value=holding.market_value,
            weight=holding.portfolio_weight,
            currency=holding.currency,
        )
        for holding in snapshot.holdings
    ]
    by_asset.extend(
        AllocationSlice(
            name="Cash",
            value=cash.amount,
            weight=cash.weight,
            currency=cash.currency,
        )
        for cash in snapshot.cash
    )
    by_currency_values: dict[str, float] = defaultdict(float)
    for holding in snapshot.holdings:
        by_currency_values[holding.currency] += holding.market_value
    for cash in snapshot.cash:
        by_currency_values[cash.currency] += cash.amount

    by_type_values: dict[str, float] = defaultdict(float)
    for holding in snapshot.holdings:
        by_type_values[holding.asset_type] += holding.market_value
    for cash in snapshot.cash:
        by_type_values["cash"] += cash.amount

    analysis_holdings = v1_us_equity_holdings(snapshot)
    concentration = [
        {
            "ticker": holding.ticker,
            "weight": holding.portfolio_weight,
            "limit": ips.max_single_stock_concentration,
        }
        for holding in analysis_holdings
        if abs(holding.portfolio_weight) > ips.max_single_stock_concentration
    ]
    candidate_issues = [
        CandidateIssue(
            issue_type="single_position_concentration",
            description=(
                f"{item['ticker']} exceeds the IPS single-position concentration limit."
            ),
            evidence=[
                f"{item['ticker']} weight {item['weight']:.2%}",
                f"IPS limit {item['limit']:.2%}",
            ],
            severity="high",
        )
        for item in concentration
    ]
    warnings = list(snapshot.data_quality.warnings)
    if report is not None and _optional_table(report, "quotes") is None:
        warnings.append("Quote table is unavailable.")
    excluded_holdings = len(snapshot.holdings) - len(analysis_holdings)
    if excluded_holdings:
        warnings.append(
            f"{excluded_holdings} holding(s) are stored but excluded from v1 US-equity analysis."
        )
    if snapshot.cash and snapshot.cash[0].amount < 0:
        warnings.append("Negative cash or margin balance is stored but not treated as a v1 equity issue.")

    return PortfolioAgentPacket(
        portfolio_id=snapshot.portfolio_id,
        snapshot=snapshot,
        allocation={
            "by_asset": by_asset,
            "by_sector": [
                AllocationSlice(
                    name=asset_type,
                    value=value,
                    weight=_weight(value, snapshot.total_value.amount),
                    currency=snapshot.base_currency,
                )
                for asset_type, value in sorted(by_type_values.items())
            ],
            "by_currency": [
                AllocationSlice(
                    name=currency,
                    value=value,
                    weight=_weight(value, snapshot.total_value.amount),
                    currency=currency,
                )
                for currency, value in sorted(by_currency_values.items())
            ],
        },
        performance=PerformanceSummary(
            summary=(
                "OpenD current snapshot is available. Historical performance attribution still "
                "requires SQL snapshots or transaction history."
            ),
            periods=[],
            benchmark=ips.benchmark,
            warnings=["SQL history is not connected in Milestone 2."],
        ),
        risk=RiskSummary(
            concentration=concentration,
            warnings=["Volatility, drawdown, and beta require historical data."],
        ),
        candidate_issues=candidate_issues,
        data_quality=snapshot.data_quality.model_copy(update={"warnings": warnings}),
    )


def _holding_from_position(
    row: dict[str, Any],
    quote: dict[str, Any] | None,
    total_value: float,
    as_of: datetime,
) -> Holding:
    code = str(row.get("code") or "")
    ticker = code.split(".", 1)[1] if "." in code else code
    market_value = _number(row.get("market_val"))
    nominal_price = _number(row.get("nominal_price"))
    last_price = _number(quote.get("last_price")) if quote else nominal_price

    return Holding(
        asset_id=f"opend:{code}",
        ticker=ticker,
        name=str(row.get("stock_name") or quote.get("name") if quote else row.get("stock_name") or ticker),
        asset_type=_asset_type(code, row, quote),
        exchange=str(row.get("position_market") or "").upper() or None,
        currency=str(row.get("currency") or "USD"),
        quantity=_number(row.get("qty")),
        market_price=last_price,
        market_value=market_value,
        portfolio_weight=_weight(market_value, total_value),
        unrealized_pnl=_optional_number(row.get("unrealized_pl")),
        sector=None,
        source="opend",
        as_of=as_of,
    )


def _asset_type(code: str, row: dict[str, Any], quote: dict[str, Any] | None) -> str:
    if quote and quote.get("option_valid") is True:
        return "option"
    if quote and quote.get("trust_valid") is True:
        return "fund"
    if quote and quote.get("equity_valid") is False:
        return "other"
    name = str(row.get("stock_name") or quote.get("name") if quote else row.get("stock_name") or "")
    normalized = f"{code} {name}".upper()
    if "BITCOIN" in normalized or "BTC" in normalized:
        return "crypto"
    if "MONEY" in normalized and "FUND" in normalized:
        return "fund"
    if row.get("position_side") in {"LONG", "SHORT"} and _looks_like_option_code(code):
        return "option"
    return "equity"


def _looks_like_option_code(code: str) -> bool:
    symbol = code.split(".", 1)[1] if "." in code else code
    return len(symbol) > 9 and any(marker in symbol for marker in ("C", "P"))


def _required_table(report: OpenDFieldReport, name: str) -> OpenDTableResult:
    table = _optional_table(report, name)
    if table is None:
        raise OpenDPortfolioDataError(f"OpenD field report is missing {name} table.")
    return table


def _optional_table(report: OpenDFieldReport, name: str) -> OpenDTableResult | None:
    return next((table for table in report.tables if table.name == name), None)


def _latest_as_of(tables: list[OpenDTableResult | None]) -> datetime:
    return max(table.as_of for table in tables if table is not None)


def _number(value: Any) -> float:
    if value in (None, "", "N/A"):
        return 0.0
    return float(value)


def _optional_number(value: Any) -> float | None:
    if value in (None, "", "N/A"):
        return None
    return float(value)


def _weight(value: float, total: float) -> float:
    if total == 0:
        return 0.0
    return value / total
