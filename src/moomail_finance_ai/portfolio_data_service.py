from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import Field

from moomail_finance_ai.mcp.finance_metrics_mcp import SERVER_NAME as FINANCE_METRICS_SERVER
from moomail_finance_ai.mcp.gateway import (
    DirectToolGateway,
    MCPGatewayError,
    MCPToolGateway,
    StdioMCPToolGateway,
    local_stdio_server_configs,
)
from moomail_finance_ai.mcp.opend_mcp import SERVER_NAME as OPEND_SERVER
from moomail_finance_ai.mcp.portfolio_sql_mcp import SERVER_NAME as PORTFOLIO_SQL_SERVER
from moomail_finance_ai.metrics import MetricResult
from moomail_finance_ai.mocks import mock_investment_policy
from moomail_finance_ai.mcp.finance_metrics_mcp import build_finance_metrics_mcp_module
from moomail_finance_ai.mcp.opend_mcp import build_opend_mcp_module
from moomail_finance_ai.mcp.portfolio_sql_mcp import build_portfolio_sql_mcp_module
from moomail_finance_ai.schemas import (
    CashBalance,
    DataQuality,
    Holding,
    Money,
    PortfolioSnapshot,
    StrictModel,
)


class PortfolioConnectionStatus(StrictModel):
    ok: bool
    status: Literal["connected", "disconnected", "degraded"]
    checked_at: datetime
    message: str
    source: str = OPEND_SERVER
    warnings: list[str] = Field(default_factory=list)
    error: str | None = None


class PortfolioDashboardSnapshot(StrictModel):
    portfolio_id: str
    as_of: datetime | None = None
    last_updated_at: datetime
    freshness_status: str = "unknown"
    connection: PortfolioConnectionStatus | None = None
    portfolio_snapshot: PortfolioSnapshot | None = None
    metrics: list[MetricResult] = Field(default_factory=list)
    history_status: dict[str, Any] = Field(default_factory=dict)
    latest_state: dict[str, Any] | None = None
    storage_result: dict[str, Any] | None = None
    source_summary: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class PortfolioRefreshResult(StrictModel):
    status: Literal["refreshed", "failed"]
    dashboard: PortfolioDashboardSnapshot
    connection: PortfolioConnectionStatus
    storage_result: dict[str, Any] | None = None
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class PortfolioDataService:
    def __init__(
        self,
        gateway: MCPToolGateway,
        *,
        portfolio_id: str = "portfolio_default",
        base_currency: str = "USD",
    ):
        self.gateway = gateway
        self.portfolio_id = portfolio_id
        self.base_currency = base_currency

    def connection_status(self) -> PortfolioConnectionStatus:
        try:
            result = self.gateway.call_tool(
                OPEND_SERVER,
                "opend_check_connection",
                {},
                consumer="dashboard_refresh",
            )
            payload = result.structured_content or {}
            ok = bool(payload.get("ok"))
            return PortfolioConnectionStatus(
                ok=ok,
                status="connected" if ok else "disconnected",
                checked_at=_parse_datetime(payload.get("checked_at")) or datetime.now(UTC),
                message=str(payload.get("message") or ("ok" if ok else "OpenD unavailable")),
                warnings=list(payload.get("warnings", [])),
            )
        except Exception as exc:
            return _connection_error(exc)

    def latest_snapshot(self) -> PortfolioDashboardSnapshot:
        self._initialize_sql()
        history_status = self._history_status()
        latest_state_result = self.gateway.call_tool(
            PORTFOLIO_SQL_SERVER,
            "portfolio_sql_get_latest_portfolio_state",
            {"portfolio_id": self.portfolio_id},
            consumer="dashboard_refresh",
        )
        latest_state = latest_state_result.structured_content
        snapshot = _snapshot_from_latest_state(latest_state, base_currency=self.base_currency)
        metrics = self._calculate_metrics(snapshot) if snapshot else []
        return PortfolioDashboardSnapshot(
            portfolio_id=self.portfolio_id,
            as_of=snapshot.as_of if snapshot else None,
            last_updated_at=datetime.now(UTC),
            freshness_status=_freshness_status(history_status),
            portfolio_snapshot=snapshot,
            metrics=metrics,
            history_status=history_status,
            latest_state=latest_state,
            source_summary={"source": "portfolio_sql_latest_state"},
            warnings=_dashboard_warnings(history_status, snapshot),
        )

    def refresh(self) -> PortfolioRefreshResult:
        connection = self.connection_status()
        try:
            context = self.gateway.call_tool(
                OPEND_SERVER,
                "opend_get_portfolio_context",
                {"portfolio_id": self.portfolio_id, "base_currency": self.base_currency},
                consumer="dashboard_refresh",
            ).structured_content
            snapshot = PortfolioSnapshot.model_validate(context["snapshot"])
            source_report = context["source_report"]
            metrics = self._calculate_metrics(snapshot)
            storage_result = self._store_refresh_observation(snapshot, source_report)
            history_status = self._history_status(now=snapshot.as_of)
            dashboard = PortfolioDashboardSnapshot(
                portfolio_id=snapshot.portfolio_id,
                as_of=snapshot.as_of,
                last_updated_at=datetime.now(UTC),
                freshness_status=_freshness_status(history_status),
                connection=connection,
                portfolio_snapshot=snapshot,
                metrics=metrics,
                history_status=history_status,
                storage_result=storage_result,
                source_summary={"source": "opend_refresh", "mcp_server": OPEND_SERVER},
                warnings=list(snapshot.data_quality.warnings),
            )
            return PortfolioRefreshResult(
                status="refreshed",
                dashboard=dashboard,
                connection=connection,
                storage_result=storage_result,
                warnings=list(snapshot.data_quality.warnings),
            )
        except Exception as exc:
            error = _sanitize_error(exc)
            fallback = self.latest_snapshot()
            fallback = fallback.model_copy(
                update={
                    "connection": connection,
                    "freshness_status": "stale" if fallback.portfolio_snapshot else "unknown",
                    "errors": [error],
                    "warnings": [*fallback.warnings, "Refresh failed; showing last-known data."],
                }
            )
            return PortfolioRefreshResult(
                status="failed",
                dashboard=fallback,
                connection=connection,
                warnings=fallback.warnings,
                errors=[error],
            )

    def _initialize_sql(self) -> None:
        self.gateway.call_tool(
            PORTFOLIO_SQL_SERVER,
            "portfolio_sql_initialize",
            {},
            consumer="dashboard_refresh",
        )

    def _history_status(self, *, now: datetime | None = None) -> dict[str, Any]:
        result = self.gateway.call_tool(
            PORTFOLIO_SQL_SERVER,
            "portfolio_sql_get_history_status",
            {
                "portfolio_id": self.portfolio_id,
                "now": (now or datetime.now(UTC)).isoformat(),
                "min_snapshots_for_history": 1,
            },
            consumer="dashboard_refresh",
        )
        return dict(result.structured_content or {})

    def _calculate_metrics(self, snapshot: PortfolioSnapshot) -> list[MetricResult]:
        result = self.gateway.call_tool(
            FINANCE_METRICS_SERVER,
            "calculate_snapshot_metrics",
            {
                "snapshot": snapshot.model_dump(mode="json"),
                "ips": mock_investment_policy().model_dump(mode="json"),
            },
            consumer="dashboard_refresh",
        )
        return [MetricResult.model_validate(row) for row in result.structured_content or []]

    def _store_refresh_observation(
        self,
        snapshot: PortfolioSnapshot,
        source_report: dict[str, Any],
    ) -> dict[str, Any]:
        self._initialize_sql()
        snapshot_json = snapshot.model_dump(mode="json")
        self.gateway.call_tool(
            PORTFOLIO_SQL_SERVER,
            "portfolio_sql_upsert_portfolio",
            {"portfolio_id": snapshot.portfolio_id, "base_currency": snapshot.base_currency},
            consumer="dashboard_refresh",
        )
        account = self.gateway.call_tool(
            PORTFOLIO_SQL_SERVER,
            "portfolio_sql_upsert_broker_account",
            {"portfolio_id": snapshot.portfolio_id, "base_currency": snapshot.base_currency},
            consumer="dashboard_refresh",
        ).structured_content
        account_id = account["account_id"]
        assets = self.gateway.call_tool(
            PORTFOLIO_SQL_SERVER,
            "portfolio_sql_upsert_assets",
            {"snapshot": snapshot_json, "include_cash_assets": True},
            consumer="dashboard_refresh",
        ).structured_content
        positions = self.gateway.call_tool(
            PORTFOLIO_SQL_SERVER,
            "portfolio_sql_upsert_position_states",
            {
                "snapshot": snapshot_json,
                "source_report": source_report,
                "account_id": account_id,
            },
            consumer="dashboard_refresh",
        ).structured_content
        value = self.gateway.call_tool(
            PORTFOLIO_SQL_SERVER,
            "portfolio_sql_store_daily_value_snapshot",
            {
                "snapshot": snapshot_json,
                "source_report": source_report,
                "account_id": account_id,
            },
            consumer="dashboard_refresh",
        ).structured_content
        weights = self.gateway.call_tool(
            PORTFOLIO_SQL_SERVER,
            "portfolio_sql_store_weight_snapshots",
            {
                "snapshot": snapshot_json,
                "source_report": source_report,
                "account_id": account_id,
                "value_snapshot_id": value["value_snapshot_id"],
            },
            consumer="dashboard_refresh",
        ).structured_content
        events = self.gateway.call_tool(
            PORTFOLIO_SQL_SERVER,
            "portfolio_sql_store_data_quality_events",
            {
                "snapshot": snapshot_json,
                "source_report": source_report,
                "account_id": account_id,
                "value_snapshot_id": value["value_snapshot_id"],
            },
            consumer="dashboard_refresh",
        ).structured_content
        return {
            "status": value["status"],
            "portfolio_id": snapshot.portfolio_id,
            "account_id": account_id,
            "value_snapshot_id": value["value_snapshot_id"],
            "snapshot_date": value["snapshot_date"],
            "assets_upserted": assets["assets_upserted"],
            "position_states_inserted": positions["inserted"],
            "position_states_updated": positions["updated"],
            "position_states_marked_inactive": positions["marked_inactive"],
            "weight_rows_stored": weights["rows_stored"],
            "data_quality_events_stored": events["events_stored"],
        }


def build_default_portfolio_data_service(
    *,
    from_report: str | Path | None = "reports/opend/field-report.json",
    db_path: str | Path = "data/portfolio-history.sqlite",
    env_file: str | Path | None = "config/local.env",
    gateway: MCPToolGateway | None = None,
    gateway_mode: Literal["stdio", "direct"] = "stdio",
) -> PortfolioDataService:
    if gateway is None and gateway_mode == "direct":
        gateway = DirectToolGateway(
            [
                build_opend_mcp_module(env_file=env_file, from_report=from_report),
                build_portfolio_sql_mcp_module(db_path=db_path),
                build_finance_metrics_mcp_module(),
            ]
        )
    if gateway is None:
        gateway = StdioMCPToolGateway(
            local_stdio_server_configs(
                env_file=env_file,
                from_report=from_report,
                db_path=db_path,
            )
        )
    return PortfolioDataService(gateway)


def _snapshot_from_latest_state(
    latest_state: dict[str, Any] | None,
    *,
    base_currency: str,
) -> PortfolioSnapshot | None:
    if not latest_state or not latest_state.get("value_snapshot"):
        return None
    value = latest_state["value_snapshot"]
    as_of = _parse_datetime(value.get("as_of")) or datetime.now(UTC)
    currency = str(value.get("currency") or base_currency)
    cash: list[CashBalance] = []
    holdings: list[Holding] = []
    for row in latest_state.get("weights") or []:
        asset_type = str(row.get("asset_type") or "")
        quantity = float(row.get("quantity") or 0.0)
        market_value = float(row.get("market_value") or 0.0)
        weight = float(row.get("weight") or 0.0)
        if asset_type in {"cash", "cash_sweep", "cash_equivalent"}:
            cash.append(
                CashBalance(
                    account_id=str(row.get("asset_id") or row.get("ticker") or "cash"),
                    amount=market_value,
                    currency=str(row.get("currency") or currency),
                    weight=weight,
                )
            )
            continue
        holdings.append(
            Holding(
                asset_id=str(row.get("asset_id")),
                ticker=str(row.get("ticker") or row.get("asset_id")),
                name=str(row.get("name") or row.get("ticker") or row.get("asset_id")),
                asset_type=asset_type or "unknown",
                exchange=row.get("exchange"),
                currency=str(row.get("currency") or currency),
                quantity=quantity,
                market_price=0.0 if quantity == 0 else market_value / quantity,
                market_value=market_value,
                portfolio_weight=weight,
                unrealized_pnl=row.get("unrealized_pl"),
                source="portfolio_sql",
                as_of=as_of,
            )
        )
    return PortfolioSnapshot(
        portfolio_id=str(value.get("portfolio_id") or "portfolio_default"),
        as_of=as_of,
        base_currency=currency,
        total_value=Money(
            amount=float(value.get("total_assets") or 0.0),
            currency=currency,
            source="portfolio_sql",
            as_of=as_of,
        ),
        cash=cash,
        holdings=holdings,
        data_quality=DataQuality(freshness_status=_freshness_status(latest_state)),
    )


def _connection_error(exc: Exception) -> PortfolioConnectionStatus:
    return PortfolioConnectionStatus(
        ok=False,
        status="disconnected",
        checked_at=datetime.now(UTC),
        message=_sanitize_error(exc),
        error=_sanitize_error(exc),
    )


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def _freshness_status(history_status: dict[str, Any]) -> str:
    data_quality = history_status.get("data_quality") or {}
    return str(data_quality.get("freshness_status") or "unknown")


def _dashboard_warnings(
    history_status: dict[str, Any],
    snapshot: PortfolioSnapshot | None,
) -> list[str]:
    warnings = list((history_status.get("data_quality") or {}).get("warnings") or [])
    if snapshot is None:
        warnings.append("No stored portfolio dashboard snapshot is available.")
    return warnings


def _sanitize_error(exc: BaseException) -> str:
    if isinstance(exc, MCPGatewayError):
        return str(exc)[:800]
    return (str(exc) or exc.__class__.__name__).replace("\n", " ")[:800]
