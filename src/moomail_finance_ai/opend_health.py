from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import Field

from moomail_finance_ai.config import OpenDConfig
from moomail_finance_ai.opend import OpenDFieldReport, OpenDTableResult, ReadOnlyOpenDClient
from moomail_finance_ai.opend_portfolio import (
    OPEND_FUND_ASSETS_CASH_SWEEP_ID,
    build_portfolio_snapshot_from_report,
)
from moomail_finance_ai.schemas import PortfolioSnapshot, StrictModel


HealthStatus = Literal["pass", "warn", "fail"]


class OpenDHealthTableCheck(StrictModel):
    name: str
    ok: bool
    row_count: int = 0
    field_count: int = 0
    fields: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    error: str | None = None


class OpenDHealthReport(StrictModel):
    generated_at: datetime
    source: Literal["live", "recorded"]
    status: HealthStatus
    config: dict[str, Any]
    connection: dict[str, Any]
    table_checks: list[OpenDHealthTableCheck]
    quote_coverage: dict[str, Any]
    portfolio_summary: dict[str, Any] | None = None
    cash_summary: dict[str, Any] | None = None
    expected_holdings_count: int | None = None
    crypto_scope: dict[str, Any]
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


def build_opend_health_report(
    client: ReadOnlyOpenDClient,
    config: OpenDConfig,
    *,
    portfolio_id: str = "portfolio_default",
    expected_holdings_count: int | None = None,
    source: Literal["live", "recorded"] = "live",
) -> OpenDHealthReport:
    generated_at = datetime.now(UTC)
    connection = client.check_connection()
    warnings: list[str] = []
    errors: list[str] = []
    table_checks: list[OpenDHealthTableCheck] = []
    tables: list[OpenDTableResult] = []

    if connection.ok:
        for name, fetch in (
            ("accounts", client.get_account_list),
            ("funds", client.get_account_funds),
            ("positions", client.get_positions),
        ):
            table = _fetch_table(name, fetch)
            table_checks.append(table.check)
            if table.table is not None:
                tables.append(table.table)
            else:
                errors.append(f"{name} read failed: {table.check.error}")

        positions = _table_by_name(tables, "positions")
        position_codes = _position_codes(positions)
        if position_codes:
            quote_result = _fetch_table(
                "quotes",
                lambda: client.get_market_snapshots(position_codes),
            )
            table_checks.append(quote_result.check)
            if quote_result.table is not None:
                tables.append(quote_result.table)
            else:
                warnings.append(f"quotes read failed: {quote_result.check.error}")
        else:
            warnings.append("No position codes found; quote health check was skipped.")
    else:
        errors.append("OpenD connection check failed.")

    field_report = OpenDFieldReport(
        generated_at=generated_at,
        connection=connection,
        tables=tables,
        warnings=warnings,
    )
    snapshot: PortfolioSnapshot | None = None
    try:
        if _table_by_name(tables, "positions") is not None:
            snapshot = build_portfolio_snapshot_from_report(
                field_report,
                portfolio_id=portfolio_id,
                base_currency=config.base_currency,
                treat_fund_assets_as_cash_sweep=config.treat_fund_assets_as_cash_sweep,
            )
            warnings.extend(snapshot.data_quality.warnings)
        elif connection.ok:
            errors.append("OpenD positions table is unavailable; normalized snapshot was not built.")
    except Exception as exc:
        errors.append(f"Normalized portfolio snapshot failed: {exc}")

    quote_coverage = _quote_coverage(tables)
    if quote_coverage["missing_quote_codes"]:
        warnings.append(
            "Some position quote rows are unavailable, but position rows remain available."
        )

    if snapshot is not None and expected_holdings_count is not None:
        holdings_count = len(snapshot.holdings)
        if holdings_count != expected_holdings_count:
            errors.append(
                "Expected holdings count mismatch: "
                f"expected {expected_holdings_count}, got {holdings_count}."
            )

    if snapshot is not None and len(snapshot.holdings) == 0:
        warnings.append("OpenD positions returned zero holdings.")

    status = _status(errors, warnings)
    return OpenDHealthReport(
        generated_at=generated_at,
        source=source,
        status=status,
        config=_config_summary(config),
        connection=connection.model_dump(mode="json"),
        table_checks=table_checks,
        quote_coverage=quote_coverage,
        portfolio_summary=_portfolio_summary(snapshot, quote_coverage) if snapshot else None,
        cash_summary=_cash_summary(snapshot) if snapshot else None,
        expected_holdings_count=expected_holdings_count,
        crypto_scope={
            "status": "deferred",
            "message": (
                "Crypto account discovery is intentionally outside the securities-account "
                "OpenD health path; explore it separately with OpenCryptoTradeContext later."
            ),
        },
        warnings=_dedupe(warnings),
        errors=_dedupe(errors),
    )


class _FetchResult(StrictModel):
    check: OpenDHealthTableCheck
    table: OpenDTableResult | None = None


def _fetch_table(name: str, fetch) -> _FetchResult:
    try:
        table = fetch()
    except Exception as exc:
        return _FetchResult(
            check=OpenDHealthTableCheck(
                name=name,
                ok=False,
                error=str(exc),
            )
        )
    return _FetchResult(
        check=OpenDHealthTableCheck(
            name=name,
            ok=True,
            row_count=len(table.rows),
            field_count=len(table.fields),
            fields=table.fields,
            warnings=table.warnings,
        ),
        table=table,
    )


def _config_summary(config: OpenDConfig) -> dict[str, Any]:
    return {
        "host": config.host,
        "port": config.port,
        "security_firm": config.security_firm,
        "trade_market": config.trade_market,
        "trade_env": config.trade_env,
        "base_currency": config.base_currency,
        "account_id_configured": config.account_id is not None,
        "account_index": config.account_index,
        "treat_fund_assets_as_cash_sweep": config.treat_fund_assets_as_cash_sweep,
    }


def _portfolio_summary(
    snapshot: PortfolioSnapshot,
    quote_coverage: dict[str, Any],
) -> dict[str, Any]:
    returned_codes = set(quote_coverage["returned_quote_codes"])
    holdings = []
    for holding in snapshot.holdings:
        provider_code = _provider_code_from_asset_id(holding.asset_id)
        holdings.append(
            {
                "asset_id": holding.asset_id,
                "provider_code": provider_code,
                "ticker": holding.ticker,
                "name": holding.name,
                "asset_type": holding.asset_type,
                "currency": holding.currency,
                "quantity": holding.quantity,
                "market_value": holding.market_value,
                "portfolio_weight": holding.portfolio_weight,
                "quote_available": provider_code in returned_codes,
            }
        )
    return {
        "portfolio_id": snapshot.portfolio_id,
        "as_of": snapshot.as_of.isoformat(),
        "base_currency": snapshot.base_currency,
        "total_value": snapshot.total_value.model_dump(mode="json"),
        "holdings_count": len(snapshot.holdings),
        "cash_balances_count": len(snapshot.cash),
        "missing_fields": snapshot.data_quality.missing_fields,
        "holdings": holdings,
    }


def _cash_summary(snapshot: PortfolioSnapshot) -> dict[str, Any]:
    literal_cash = [
        cash for cash in snapshot.cash if cash.account_id != OPEND_FUND_ASSETS_CASH_SWEEP_ID
    ]
    auto_invested_fund_assets = [
        cash for cash in snapshot.cash if cash.account_id == OPEND_FUND_ASSETS_CASH_SWEEP_ID
    ]
    literal_cash_value = sum(cash.amount for cash in literal_cash)
    auto_invested_fund_assets_value = sum(cash.amount for cash in auto_invested_fund_assets)
    return {
        "literal_cash_value": literal_cash_value,
        "auto_invested_fund_assets_present": bool(auto_invested_fund_assets),
        "auto_invested_fund_assets_value": auto_invested_fund_assets_value,
        "effective_cash_value": literal_cash_value + auto_invested_fund_assets_value,
        "cash_balances": [cash.model_dump(mode="json") for cash in snapshot.cash],
    }


def _quote_coverage(tables: list[OpenDTableResult]) -> dict[str, Any]:
    positions = _table_by_name(tables, "positions")
    quotes = _table_by_name(tables, "quotes")
    position_codes = _position_codes(positions)
    returned_codes = (
        sorted(str(row.get("code")) for row in quotes.rows if row.get("code"))
        if quotes is not None
        else []
    )
    missing_quote_codes = sorted(set(position_codes) - set(returned_codes))
    return {
        "requested_position_codes": position_codes,
        "returned_quote_codes": returned_codes,
        "requested_count": len(position_codes),
        "returned_count": len(returned_codes),
        "missing_quote_codes": missing_quote_codes,
        "warnings": list(quotes.warnings) if quotes else [],
    }


def _table_by_name(tables: list[OpenDTableResult], name: str) -> OpenDTableResult | None:
    return next((table for table in tables if table.name == name), None)


def _position_codes(table: OpenDTableResult | None) -> list[str]:
    if table is None:
        return []
    return [
        str(row["code"])
        for row in table.rows
        if isinstance(row.get("code"), str) and row.get("code")
    ]


def _provider_code_from_asset_id(asset_id: str) -> str:
    if asset_id.startswith("opend:"):
        return asset_id.split(":", 1)[1]
    return asset_id


def _status(errors: list[str], warnings: list[str]) -> HealthStatus:
    if errors:
        return "fail"
    if warnings:
        return "warn"
    return "pass"


def _dedupe(values: list[str]) -> list[str]:
    seen = set()
    result = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result
