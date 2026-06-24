from __future__ import annotations

from typing import Any, Iterable

from pydantic import Field

from moomail_finance_ai.schemas import Holding, InvestmentPolicy, PortfolioSnapshot, StrictModel


METRIC_VERSION = "finance-metrics-v0.1.0"
US_EQUITY_ANALYSIS_SCOPE = "us_equities"
OPEND_FUND_ASSETS_CASH_SWEEP_ID = "opend_fund_assets_cash_sweep"


class MetricResult(StrictModel):
    metric_name: str
    value: Any
    metric_version: str = METRIC_VERSION
    input_scope: dict[str, Any] = Field(default_factory=dict)
    source_inputs: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


def us_equity_analysis_holdings(snapshot: PortfolioSnapshot) -> list[Holding]:
    return [
        holding
        for holding in snapshot.holdings
        if holding.asset_type == "equity" and (holding.exchange or "").upper() == "US"
    ]


def calculate_cash_weight(snapshot: PortfolioSnapshot) -> MetricResult:
    cash_value = _literal_cash_value(snapshot)
    auto_invested_fund_assets_value = _auto_invested_fund_assets_value(snapshot)
    cash_equivalent_value = _cash_equivalent_value(snapshot)
    effective_cash_value = (
        cash_value + auto_invested_fund_assets_value + cash_equivalent_value
    )
    total_value = snapshot.total_value.amount
    value = _weight(effective_cash_value, total_value)
    return MetricResult(
        metric_name="cash_weight",
        value=value,
        input_scope={"scope": "full_portfolio"},
        source_inputs={
            "portfolio_id": snapshot.portfolio_id,
            "snapshot_as_of": snapshot.as_of.isoformat(),
            "total_value": total_value,
            "cash_value": cash_value,
            "auto_invested_fund_assets_value": auto_invested_fund_assets_value,
            "cash_equivalent_value": cash_equivalent_value,
            "effective_cash_value": effective_cash_value,
        },
    )


def calculate_position_weights(
    snapshot: PortfolioSnapshot,
    *,
    scope: str = US_EQUITY_ANALYSIS_SCOPE,
) -> MetricResult:
    holdings = _holdings_for_scope(snapshot, scope)
    total_value = _scope_total_market_value(holdings)
    return MetricResult(
        metric_name="position_weights",
        value=[
            {
                "ticker": holding.ticker,
                "asset_id": holding.asset_id,
                "asset_type": holding.asset_type,
                "market_value": holding.market_value,
                "weight_in_scope": _weight(holding.market_value, total_value),
                "weight_in_portfolio": holding.portfolio_weight,
            }
            for holding in holdings
        ],
        input_scope={"scope": scope},
        source_inputs={
            "portfolio_id": snapshot.portfolio_id,
            "snapshot_as_of": snapshot.as_of.isoformat(),
            "holdings_count": len(holdings),
        },
        warnings=_scope_warnings(snapshot, holdings, scope),
    )


def calculate_single_position_concentration(
    snapshot: PortfolioSnapshot,
    ips: InvestmentPolicy,
    *,
    scope: str = US_EQUITY_ANALYSIS_SCOPE,
) -> MetricResult:
    holdings = _holdings_for_scope(snapshot, scope)
    total_value = _scope_total_market_value(holdings)
    rows = []
    for holding in holdings:
        weight_in_scope = _weight(holding.market_value, total_value)
        if abs(weight_in_scope) > ips.max_single_stock_concentration:
            rows.append(
                {
                    "ticker": holding.ticker,
                    "asset_id": holding.asset_id,
                    "asset_type": holding.asset_type,
                    "weight_in_scope": weight_in_scope,
                    "weight_in_portfolio": holding.portfolio_weight,
                    "limit": ips.max_single_stock_concentration,
                }
            )
    return MetricResult(
        metric_name="single_position_concentration",
        value=rows,
        input_scope={"scope": scope},
        source_inputs={
            "portfolio_id": snapshot.portfolio_id,
            "snapshot_as_of": snapshot.as_of.isoformat(),
            "limit": ips.max_single_stock_concentration,
            "holdings_count": len(holdings),
        },
        warnings=_scope_warnings(snapshot, holdings, scope),
    )


def calculate_asset_type_allocation(snapshot: PortfolioSnapshot) -> MetricResult:
    totals: dict[str, float] = {}
    for holding in snapshot.holdings:
        asset_type = _allocation_asset_type(holding)
        totals[asset_type] = totals.get(asset_type, 0.0) + holding.market_value
    for cash in snapshot.cash:
        totals["cash"] = totals.get("cash", 0.0) + cash.amount

    total_value = snapshot.total_value.amount
    return MetricResult(
        metric_name="asset_type_allocation",
        value=[
            {
                "asset_type": asset_type,
                "market_value": market_value,
                "weight": _weight(market_value, total_value),
            }
            for asset_type, market_value in sorted(totals.items())
        ],
        input_scope={"scope": "full_portfolio"},
        source_inputs={
            "portfolio_id": snapshot.portfolio_id,
            "snapshot_as_of": snapshot.as_of.isoformat(),
        },
    )


def calculate_benchmark_reference(ips: InvestmentPolicy) -> MetricResult:
    return MetricResult(
        metric_name="benchmark_reference",
        value={"benchmark": ips.benchmark},
        input_scope={"scope": US_EQUITY_ANALYSIS_SCOPE},
        source_inputs={"policy_id": ips.policy_id},
        warnings=[
            "Benchmark return comparison requires historical portfolio snapshots and benchmark prices."
        ],
    )


def calculate_snapshot_metrics(
    snapshot: PortfolioSnapshot,
    ips: InvestmentPolicy,
    *,
    scope: str = US_EQUITY_ANALYSIS_SCOPE,
) -> list[MetricResult]:
    return [
        calculate_cash_weight(snapshot),
        calculate_position_weights(snapshot, scope=scope),
        calculate_single_position_concentration(snapshot, ips, scope=scope),
        calculate_asset_type_allocation(snapshot),
        calculate_benchmark_reference(ips),
    ]


def _holdings_for_scope(snapshot: PortfolioSnapshot, scope: str) -> list[Holding]:
    if scope == US_EQUITY_ANALYSIS_SCOPE:
        return us_equity_analysis_holdings(snapshot)
    if scope == "full_portfolio":
        return list(snapshot.holdings)
    raise ValueError(f"Unknown metric scope: {scope}")


def _scope_total_market_value(holdings: Iterable[Holding]) -> float:
    return sum(holding.market_value for holding in holdings)


def _scope_warnings(
    snapshot: PortfolioSnapshot,
    scoped_holdings: list[Holding],
    scope: str,
) -> list[str]:
    if scope != US_EQUITY_ANALYSIS_SCOPE:
        return []
    excluded = len(snapshot.holdings) - len(scoped_holdings)
    if excluded <= 0:
        return []
    return [f"{excluded} holding(s) excluded from US-equity analysis metrics."]


def _cash_equivalent_value(snapshot: PortfolioSnapshot) -> float:
    return sum(
        holding.market_value
        for holding in snapshot.holdings
        if holding.asset_type == "cash_equivalent"
    )


def _literal_cash_value(snapshot: PortfolioSnapshot) -> float:
    return sum(
        cash.amount
        for cash in snapshot.cash
        if cash.account_id != OPEND_FUND_ASSETS_CASH_SWEEP_ID
    )


def _auto_invested_fund_assets_value(snapshot: PortfolioSnapshot) -> float:
    return sum(
        cash.amount
        for cash in snapshot.cash
        if cash.account_id == OPEND_FUND_ASSETS_CASH_SWEEP_ID
    )


def _allocation_asset_type(holding: Holding) -> str:
    if holding.asset_type == "cash_equivalent":
        return "cash"
    return holding.asset_type


def _weight(value: float, total: float) -> float:
    if total == 0:
        return 0.0
    return value / total
