from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from moomail_finance_ai.agent_schemas import (
    BASELINE_MAX_ALLOCATION_ROWS,
    BASELINE_MAX_CHANGE_ROWS,
    BaselineCapability,
    BaselineSummary,
    EvidenceQuality,
    EvidenceRef,
    PortfolioBaselinePacket,
)
from moomail_finance_ai.mcp.finance_metrics_mcp import (
    SERVER_NAME as FINANCE_METRICS_SERVER,
    build_finance_metrics_mcp_module,
)
from moomail_finance_ai.mcp.gateway import (
    DirectToolGateway,
    MCPToolGateway,
    StdioMCPToolGateway,
    local_stdio_server_configs,
)
from moomail_finance_ai.mcp.portfolio_sql_mcp import (
    SERVER_NAME as PORTFOLIO_SQL_SERVER,
    build_portfolio_sql_mcp_module,
)
from moomail_finance_ai.metrics import OPEND_FUND_ASSETS_CASH_SWEEP_ID
from moomail_finance_ai.portfolio_data_service import snapshot_from_latest_state
from moomail_finance_ai.schemas import PortfolioSnapshot


BASELINE_CONSUMER = "portfolio_baseline"
BASELINE_GROWTH_ROW_LIMIT = 64
BASELINE_ALLOCATION_HISTORY_ROW_LIMIT = 512
BASELINE_POSITION_CHANGE_ROW_LIMIT = 64
DEFAULT_ALLOCATION_SUMMARY_LIMIT = 10
DEFAULT_CHANGE_SUMMARY_LIMIT = 5
ANCHOR_TOLERANCE_DAYS = {7: 3, 30: 5}


class PortfolioBaselineService:
    """Build bounded read-only context from stored portfolio SQL and metrics."""

    def __init__(
        self,
        gateway: MCPToolGateway,
        *,
        portfolio_id: str = "portfolio_default",
        base_currency: str = "USD",
        allocation_summary_limit: int = DEFAULT_ALLOCATION_SUMMARY_LIMIT,
        change_summary_limit: int = DEFAULT_CHANGE_SUMMARY_LIMIT,
    ):
        if not 1 <= allocation_summary_limit <= BASELINE_MAX_ALLOCATION_ROWS:
            raise ValueError("allocation_summary_limit exceeds the baseline contract cap.")
        if not 1 <= change_summary_limit <= BASELINE_MAX_CHANGE_ROWS:
            raise ValueError("change_summary_limit exceeds the baseline contract cap.")
        self.gateway = gateway
        self.portfolio_id = portfolio_id
        self.base_currency = base_currency
        self.allocation_summary_limit = allocation_summary_limit
        self.change_summary_limit = change_summary_limit

    def load(self, *, now: datetime | None = None) -> PortfolioBaselinePacket:
        generated_at = _as_utc(now or datetime.now(UTC))
        capabilities: list[BaselineCapability] = []
        summaries: list[BaselineSummary] = []
        evidence_refs: list[EvidenceRef] = []
        warnings: list[str] = []
        limitations: list[str] = [
            "Baseline context uses stored SQL data and does not refresh or verify live OpenD."
        ]

        history_status = self._read(
            "portfolio_sql_get_history_status",
            {
                "portfolio_id": self.portfolio_id,
                "now": generated_at.isoformat(),
                "stale_after_hours": 24,
                "min_snapshots_for_history": 2,
            },
            limitations,
            "Portfolio history status is unavailable.",
        )
        latest_state = self._read(
            "portfolio_sql_get_latest_portfolio_state",
            {"portfolio_id": self.portfolio_id},
            limitations,
            "No stored portfolio snapshot is available.",
        )
        snapshot = snapshot_from_latest_state(
            latest_state if isinstance(latest_state, dict) else None,
            base_currency=self.base_currency,
        )
        if snapshot is not None and isinstance(history_status, dict):
            data_quality = history_status.get("data_quality") or {}
            freshness = str(data_quality.get("freshness_status") or "unknown")
            if freshness in {"fresh", "stale", "unknown"}:
                snapshot = snapshot.model_copy(
                    update={
                        "data_quality": snapshot.data_quality.model_copy(
                            update={
                                "freshness_status": freshness,
                            }
                        )
                    }
                )

        history_quality = _history_quality(history_status)
        _add_history_freshness(
            history_status,
            capabilities,
            summaries,
            evidence_refs,
            warnings,
            limitations,
        )

        if snapshot is None:
            limitations.append("Current portfolio breakdown is unavailable from stored SQL.")
            return PortfolioBaselinePacket(
                portfolio_id=self.portfolio_id,
                generated_at=generated_at,
                capabilities=capabilities,
                summaries=summaries,
                evidence_refs=evidence_refs,
                warnings=_bounded_messages(warnings),
                limitations=_bounded_messages(limitations),
            )

        current_quality = _current_quality(snapshot, latest_state, history_quality)
        _collect_data_quality(latest_state, snapshot, warnings, limitations)
        _add_latest_snapshot(
            snapshot,
            current_quality,
            capabilities,
            summaries,
            evidence_refs,
        )
        _add_allocation_breakdown(
            snapshot,
            current_quality,
            self.allocation_summary_limit,
            capabilities,
            summaries,
            evidence_refs,
        )

        metrics = self._metric_rows(snapshot, limitations)
        _add_effective_cash(
            snapshot,
            metrics,
            current_quality,
            capabilities,
            summaries,
            evidence_refs,
            limitations,
        )

        growth = self._read(
            "portfolio_sql_get_portfolio_growth",
            {"portfolio_id": self.portfolio_id, "limit": BASELINE_GROWTH_ROW_LIMIT},
            limitations,
            "Portfolio value history is unavailable.",
        )
        growth_rows = _growth_rows(growth)
        anchors: dict[int, dict[str, Any]] = {}
        for days, capability in (
            (7, "portfolio_value_trend_7d"),
            (30, "portfolio_value_trend_30d"),
        ):
            anchor = _add_value_trend(
                growth_rows,
                days,
                capability,
                current_quality,
                capabilities,
                summaries,
                evidence_refs,
                limitations,
            )
            if anchor is not None:
                anchors[days] = anchor

        allocation_history = self._read(
            "portfolio_sql_get_allocation_history",
            {
                "portfolio_id": self.portfolio_id,
                "limit": BASELINE_ALLOCATION_HISTORY_ROW_LIMIT,
            },
            limitations,
            "Portfolio allocation history is unavailable.",
        )
        allocation_deltas = _add_allocation_changes(
            _dict_rows(allocation_history),
            growth_rows[-1] if growth_rows else None,
            anchors.get(7),
            snapshot.as_of,
            current_quality,
            self.change_summary_limit,
            capabilities,
            summaries,
            evidence_refs,
            limitations,
        )

        position_changes = self._read(
            "portfolio_sql_get_position_state_changes",
            {
                "portfolio_id": self.portfolio_id,
                "until": snapshot.as_of.isoformat(),
                "lookback_days": 7,
                "limit": BASELINE_POSITION_CHANGE_ROW_LIMIT,
                "include_initial_observations": False,
            },
            limitations,
            "Recent position-state history is unavailable.",
        )
        _add_position_changes(
            position_changes if isinstance(position_changes, dict) else None,
            anchors.get(7),
            allocation_deltas,
            snapshot.as_of,
            current_quality,
            self.change_summary_limit,
            capabilities,
            summaries,
            evidence_refs,
            limitations,
        )

        return PortfolioBaselinePacket(
            portfolio_id=self.portfolio_id,
            generated_at=generated_at,
            as_of=snapshot.as_of,
            capabilities=capabilities,
            summaries=summaries,
            evidence_refs=evidence_refs,
            warnings=_bounded_messages(warnings),
            limitations=_bounded_messages(limitations),
        )

    def _read(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        limitations: list[str],
        failure_message: str,
    ) -> Any:
        try:
            return self.gateway.call_tool(
                PORTFOLIO_SQL_SERVER,
                tool_name,
                arguments,
                consumer=BASELINE_CONSUMER,
            ).structured_content
        except Exception:
            limitations.append(failure_message)
            return None

    def _metric_rows(
        self,
        snapshot: PortfolioSnapshot,
        limitations: list[str],
    ) -> list[dict[str, Any]]:
        try:
            result = self.gateway.call_tool(
                FINANCE_METRICS_SERVER,
                "calculate_cash_weight",
                {"snapshot": snapshot.model_dump(mode="json")},
                consumer=BASELINE_CONSUMER,
            )
            payload = result.structured_content
            return [dict(payload)] if isinstance(payload, dict) else []
        except Exception:
            limitations.append("Deterministic effective-cash metrics are unavailable.")
            return []


def build_default_portfolio_baseline_service(
    *,
    db_path: str | Path = "data/portfolio-history.sqlite",
    env_file: str | Path | None = "config/local.env",
    gateway: MCPToolGateway | None = None,
    gateway_mode: Literal["stdio", "direct"] = "stdio",
) -> PortfolioBaselineService:
    if gateway is None and gateway_mode == "direct":
        gateway = DirectToolGateway(
            [
                build_portfolio_sql_mcp_module(db_path=db_path),
                build_finance_metrics_mcp_module(),
            ]
        )
    if gateway is None:
        gateway = StdioMCPToolGateway(
            local_stdio_server_configs(env_file=env_file, db_path=db_path)
        )
    return PortfolioBaselineService(gateway)


def _add_history_freshness(
    history_status: Any,
    capabilities: list[BaselineCapability],
    summaries: list[BaselineSummary],
    evidence_refs: list[EvidenceRef],
    warnings: list[str],
    limitations: list[str],
) -> None:
    if not isinstance(history_status, dict):
        return
    data_quality = history_status.get("data_quality") or {}
    warnings.extend(str(value) for value in data_quality.get("warnings") or [])
    missing_fields = [str(value) for value in data_quality.get("missing_fields") or []]
    latest_as_of = _parse_datetime(history_status.get("latest_as_of"))
    if latest_as_of is None:
        limitations.append("Portfolio history has no latest observation timestamp.")
        return
    quality = _history_quality(history_status)
    ref_id = "sql.history.freshness"
    evidence_refs.append(
        EvidenceRef(
            ref_id=ref_id,
            source="portfolio_sql",
            field_path="history_status.data_quality",
            as_of=latest_as_of,
            quality=quality,
            limitations=missing_fields[:8],
        )
    )
    summaries.append(
        BaselineSummary(
            summary_id="history.freshness",
            capability="history_freshness",
            label="Stored portfolio history freshness",
            facts={
                "snapshot_count": int(history_status.get("snapshot_count") or 0),
                "freshness_status": str(data_quality.get("freshness_status") or "unknown"),
                "missing_field_count": len(missing_fields),
            },
            evidence_refs=[ref_id],
        )
    )
    capabilities.append("history_freshness")
    if quality != "complete":
        limitations.append("Stored portfolio history is stale or incomplete.")


def _add_latest_snapshot(
    snapshot: PortfolioSnapshot,
    quality: EvidenceQuality,
    capabilities: list[BaselineCapability],
    summaries: list[BaselineSummary],
    evidence_refs: list[EvidenceRef],
) -> None:
    ref_id = "dashboard.snapshot.total_value"
    evidence_refs.append(
        EvidenceRef(
            ref_id=ref_id,
            source="portfolio_dashboard",
            field_path="portfolio_snapshot.total_value",
            as_of=snapshot.as_of,
            quality=quality,
        )
    )
    summaries.append(
        BaselineSummary(
            summary_id="snapshot.total_value",
            capability="latest_snapshot",
            label="Latest stored portfolio snapshot",
            facts={
                "total_value": _number(snapshot.total_value.amount),
                "currency": snapshot.total_value.currency,
                "holdings_count": len(snapshot.holdings),
                "cash_component_count": len(snapshot.cash),
                "freshness_status": snapshot.data_quality.freshness_status,
            },
            evidence_refs=[ref_id],
        )
    )
    capabilities.append("latest_snapshot")


def _add_allocation_breakdown(
    snapshot: PortfolioSnapshot,
    quality: EvidenceQuality,
    limit: int,
    capabilities: list[BaselineCapability],
    summaries: list[BaselineSummary],
    evidence_refs: list[EvidenceRef],
) -> None:
    rows: list[dict[str, Any]] = []
    for holding in snapshot.holdings:
        rows.append(
            {
                "key": holding.asset_id,
                "label": holding.ticker,
                "ticker": holding.ticker,
                "asset_type": holding.asset_type,
                "market_value": holding.market_value,
                "weight": holding.portfolio_weight,
                "currency": holding.currency,
            }
        )
    literal_cash = sum(
        cash.amount
        for cash in snapshot.cash
        if cash.account_id != OPEND_FUND_ASSETS_CASH_SWEEP_ID
    )
    cash_sweep = sum(
        cash.amount
        for cash in snapshot.cash
        if cash.account_id == OPEND_FUND_ASSETS_CASH_SWEEP_ID
    )
    for key, label, amount in (
        ("literal_cash", "Literal cash", literal_cash),
        ("configured_cash_sweep", "Configured cash sweep", cash_sweep),
    ):
        if amount:
            rows.append(
                {
                    "key": key,
                    "label": label,
                    "ticker": None,
                    "asset_type": key,
                    "market_value": amount,
                    "weight": _ratio(amount, snapshot.total_value.amount),
                    "currency": snapshot.base_currency,
                }
            )
    rows.sort(key=lambda row: (-abs(float(row["weight"])), str(row["key"])))
    for row in rows[:limit]:
        slug = _slug(str(row["key"]))
        ref_id = f"dashboard.allocation.{slug}"
        evidence_refs.append(
            EvidenceRef(
                ref_id=ref_id,
                source="portfolio_dashboard",
                field_path=f"portfolio_snapshot.allocation.{slug}",
                as_of=snapshot.as_of,
                quality=quality,
            )
        )
        facts = {
            "asset_key": _safe_text(row["key"]),
            "asset_type": _safe_text(row["asset_type"]),
            "market_value": _number(row["market_value"]),
            "weight": _number(row["weight"]),
            "currency": _safe_text(row["currency"]),
        }
        if row["ticker"]:
            facts["ticker"] = _safe_text(row["ticker"])
        summaries.append(
            BaselineSummary(
                summary_id=f"allocation.{slug}",
                capability="allocation_breakdown",
                label=_safe_text(row["label"]),
                facts=facts,
                evidence_refs=[ref_id],
            )
        )
    if rows:
        capabilities.append("allocation_breakdown")


def _add_effective_cash(
    snapshot: PortfolioSnapshot,
    metrics: list[dict[str, Any]],
    quality: EvidenceQuality,
    capabilities: list[BaselineCapability],
    summaries: list[BaselineSummary],
    evidence_refs: list[EvidenceRef],
    limitations: list[str],
) -> None:
    metric = next((row for row in metrics if row.get("metric_name") == "cash_weight"), None)
    if metric is None:
        limitations.append("Effective-cash capability is unavailable.")
        return
    source_inputs = metric.get("source_inputs") or {}
    ref_id = "metrics.effective_cash"
    evidence_refs.append(
        EvidenceRef(
            ref_id=ref_id,
            source="finance_metrics",
            field_path="cash_weight.effective_cash",
            as_of=snapshot.as_of,
            quality=quality,
        )
    )
    summaries.append(
        BaselineSummary(
            summary_id="effective_cash.total",
            capability="effective_cash",
            label="Effective cash and cash-equivalent liquidity",
            facts={
                "literal_cash": _number(source_inputs.get("cash_value")),
                "configured_cash_sweep": _number(
                    source_inputs.get("auto_invested_fund_assets_value")
                ),
                "cash_equivalent_holdings": _number(
                    source_inputs.get("cash_equivalent_value")
                ),
                "effective_cash": _number(source_inputs.get("effective_cash_value")),
                "effective_cash_weight": _number(metric.get("value")),
                "currency": snapshot.base_currency,
            },
            evidence_refs=[ref_id],
        )
    )
    capabilities.append("effective_cash")


def _add_value_trend(
    rows: list[dict[str, Any]],
    days: int,
    capability: BaselineCapability,
    quality: EvidenceQuality,
    capabilities: list[BaselineCapability],
    summaries: list[BaselineSummary],
    evidence_refs: list[EvidenceRef],
    limitations: list[str],
) -> dict[str, Any] | None:
    if not rows:
        limitations.append(f"A valid {days}-day portfolio value anchor is unavailable.")
        return None
    end = rows[-1]
    end_at = _parse_datetime(end.get("as_of"))
    anchor = _comparison_anchor(rows, end_at, days)
    if end_at is None or anchor is None:
        limitations.append(f"A valid {days}-day portfolio value anchor is unavailable.")
        return None
    start_at = _parse_datetime(anchor.get("as_of"))
    start_value = _float(anchor.get("total_assets"))
    end_value = _float(end.get("total_assets"))
    if start_at is None or start_value is None or end_value is None:
        limitations.append(f"The {days}-day portfolio value rows are incomplete.")
        return None
    absolute_change = end_value - start_value
    percent_change = absolute_change / start_value if start_value else None
    ref_id = f"sql.portfolio_value_trend.{days}d"
    evidence_refs.append(
        EvidenceRef(
            ref_id=ref_id,
            source="portfolio_sql",
            field_path="portfolio_growth.total_assets",
            as_of=end_at,
            window=f"{days}d",
            quality=quality,
        )
    )
    summaries.append(
        BaselineSummary(
            summary_id=f"portfolio_value_trend.{days}d",
            capability=capability,
            label=f"Portfolio value trend over approximately {days} days",
            facts={
                "start_as_of": start_at.isoformat(),
                "end_as_of": end_at.isoformat(),
                "actual_window_days": _number(
                    (end_at - start_at).total_seconds() / 86_400
                ),
                "start_value": _number(start_value),
                "end_value": _number(end_value),
                "absolute_change": _number(absolute_change),
                "percent_change": _number(percent_change),
                "currency": _safe_text(end.get("currency") or anchor.get("currency") or "USD"),
            },
            evidence_refs=[ref_id],
        )
    )
    capabilities.append(capability)
    return anchor


def _add_allocation_changes(
    rows: list[dict[str, Any]],
    end_growth: dict[str, Any] | None,
    anchor_growth: dict[str, Any] | None,
    as_of: datetime,
    quality: EvidenceQuality,
    limit: int,
    capabilities: list[BaselineCapability],
    summaries: list[BaselineSummary],
    evidence_refs: list[EvidenceRef],
    limitations: list[str],
) -> dict[str, dict[str, Any]]:
    if end_growth is None or anchor_growth is None:
        limitations.append("A valid 7-day allocation comparison is unavailable.")
        return {}
    end_key = str(end_growth.get("snapshot_date") or "")
    anchor_key = str(anchor_growth.get("snapshot_date") or "")
    grouped = _allocation_by_date(rows)
    current = grouped.get(end_key)
    previous = grouped.get(anchor_key)
    if not current or not previous:
        limitations.append("Allocation rows do not cover the 7-day comparison anchors.")
        return {}

    deltas: list[dict[str, Any]] = []
    for asset_key in sorted(set(current) | set(previous)):
        current_row = current.get(asset_key) or {}
        previous_row = previous.get(asset_key) or {}
        current_weight = _float(current_row.get("weight")) or 0.0
        previous_weight = _float(previous_row.get("weight")) or 0.0
        delta = current_weight - previous_weight
        deltas.append(
            {
                "asset_key": asset_key,
                "ticker": current_row.get("ticker") or previous_row.get("ticker"),
                "asset_type": current_row.get("asset_type") or previous_row.get("asset_type"),
                "previous_weight": previous_weight,
                "current_weight": current_weight,
                "weight_change": delta,
            }
        )
    deltas.sort(key=lambda row: (-abs(row["weight_change"]), row["asset_key"]))
    material = [row for row in deltas if abs(row["weight_change"]) > 1e-12]
    selected = material[:limit]
    if not selected:
        selected = [
            {
                "asset_key": "none",
                "ticker": None,
                "asset_type": "summary",
                "previous_weight": 0.0,
                "current_weight": 0.0,
                "weight_change": 0.0,
            }
        ]
    for row in selected:
        slug = _slug(row["asset_key"])
        ref_id = f"sql.allocation_change.7d.{slug}"
        evidence_refs.append(
            EvidenceRef(
                ref_id=ref_id,
                source="portfolio_sql",
                field_path=f"allocation_history.{slug}.weight_delta",
                as_of=as_of,
                window="7d",
                quality=quality,
            )
        )
        facts = {
            "asset_key": _safe_text(row["asset_key"]),
            "asset_type": _safe_text(row["asset_type"]),
            "previous_weight": _number(row["previous_weight"]),
            "current_weight": _number(row["current_weight"]),
            "weight_change": _number(row["weight_change"]),
        }
        if row["ticker"]:
            facts["ticker"] = _safe_text(row["ticker"])
        summaries.append(
            BaselineSummary(
                summary_id=f"allocation_change.7d.{slug}",
                capability="top_allocation_changes_7d",
                label=(
                    "No allocation-weight changes in the covered window"
                    if row["asset_key"] == "none"
                    else f"7-day allocation change: {_safe_text(row['ticker'] or row['asset_key'])}"
                ),
                facts=facts,
                evidence_refs=[ref_id],
            )
        )
    capabilities.append("top_allocation_changes_7d")
    return {row["asset_key"]: row for row in deltas}


def _add_position_changes(
    result: dict[str, Any] | None,
    anchor: dict[str, Any] | None,
    allocation_deltas: dict[str, dict[str, Any]],
    as_of: datetime,
    quality: EvidenceQuality,
    limit: int,
    capabilities: list[BaselineCapability],
    summaries: list[BaselineSummary],
    evidence_refs: list[EvidenceRef],
    limitations: list[str],
) -> None:
    if anchor is None or result is None:
        limitations.append("A valid 7-day position-change comparison is unavailable.")
        return
    anchor_at = _parse_datetime(anchor.get("as_of"))
    changes = [
        change
        for change in _dict_rows(result.get("changes"))
        if anchor_at is None
        or (_parse_datetime(change.get("change_at")) or anchor_at) > anchor_at
    ]
    grouped_changes: dict[str, list[dict[str, Any]]] = {}
    for change in changes:
        asset_key = str(change.get("asset_id") or change.get("ticker") or "unknown")
        grouped_changes.setdefault(asset_key, []).append(change)
    rows: list[dict[str, Any]] = []
    for asset_key, asset_changes in grouped_changes.items():
        asset_changes.sort(
            key=lambda change: (
                _parse_datetime(change.get("change_at")) or datetime.min.replace(tzinfo=UTC)
            )
        )
        first = asset_changes[0]
        last = asset_changes[-1]
        previous_quantity = _float(first.get("previous_quantity"))
        current_quantity = _float(last.get("current_quantity"))
        quantity_delta = (
            current_quantity - previous_quantity
            if current_quantity is not None and previous_quantity is not None
            else sum(_float(change.get("quantity_delta")) or 0.0 for change in asset_changes)
        )
        allocation = allocation_deltas.get(asset_key) or {}
        rows.append(
            {
                "asset_key": asset_key,
                "ticker": last.get("ticker") or first.get("ticker"),
                "change_type": (
                    last.get("change_type") or "quantity_changed"
                    if len(asset_changes) == 1
                    else "multiple_quantity_changes"
                ),
                "change_at": last.get("change_at"),
                "previous_quantity": previous_quantity,
                "current_quantity": current_quantity,
                "quantity_delta": quantity_delta,
                "current_weight": allocation.get("current_weight"),
                "weight_change": allocation.get("weight_change"),
            }
        )
    rows.sort(
        key=lambda row: (
            -abs(float(row["weight_change"] or 0.0)),
            -abs(float(row["quantity_delta"] or 0.0)),
            row["asset_key"],
        )
    )
    selected = rows[:limit]
    if not selected:
        selected = [
            {
                "asset_key": "none",
                "ticker": None,
                "change_type": "no_quantity_changes",
                "change_at": None,
                "previous_quantity": None,
                "current_quantity": None,
                "quantity_delta": 0.0,
                "current_weight": None,
                "weight_change": None,
            }
        ]
    for row in selected:
        slug = _slug(row["asset_key"])
        ref_id = f"sql.position_change.7d.{slug}"
        evidence_refs.append(
            EvidenceRef(
                ref_id=ref_id,
                source="portfolio_sql",
                field_path=f"position_state_changes.{slug}.quantity_delta",
                as_of=as_of,
                window="7d",
                quality=quality,
            )
        )
        facts: dict[str, str | int | float | bool | None] = {
            "asset_key": _safe_text(row["asset_key"]),
            "change_type": _safe_text(row["change_type"]),
            "quantity_delta": _number(row["quantity_delta"]),
        }
        for key in (
            "ticker",
            "change_at",
            "previous_quantity",
            "current_quantity",
            "current_weight",
            "weight_change",
        ):
            value = row[key]
            if value is not None:
                facts[key] = (
                    _number(value)
                    if isinstance(value, (int, float))
                    else _safe_text(value)
                )
        summaries.append(
            BaselineSummary(
                summary_id=f"position_change.7d.{slug}",
                capability="top_position_changes_7d",
                label=(
                    "No position quantity changes in the covered window"
                    if row["asset_key"] == "none"
                    else f"7-day position change: {_safe_text(row['ticker'] or row['asset_key'])}"
                ),
                facts=facts,
                evidence_refs=[ref_id],
            )
        )
    capabilities.append("top_position_changes_7d")


def _collect_data_quality(
    latest_state: Any,
    snapshot: PortfolioSnapshot,
    warnings: list[str],
    limitations: list[str],
) -> None:
    warnings.extend(snapshot.data_quality.warnings)
    if not isinstance(latest_state, dict):
        return
    for event in _dict_rows(latest_state.get("data_quality_events")):
        message = _safe_text(event.get("message") or event.get("event_type") or "Data issue")
        warnings.append(message)
        event_type = str(event.get("event_type") or "").casefold()
        if "unsupported_quote" in event_type:
            limitations.append("One or more stored holdings have unsupported quote data.")


def _history_quality(history_status: Any) -> EvidenceQuality:
    if not isinstance(history_status, dict):
        return "partial"
    data_quality = history_status.get("data_quality") or {}
    freshness = str(data_quality.get("freshness_status") or "unknown")
    if freshness == "stale":
        return "stale"
    if freshness != "fresh" or data_quality.get("missing_fields"):
        return "partial"
    return "complete"


def _current_quality(
    snapshot: PortfolioSnapshot,
    latest_state: Any,
    history_quality: EvidenceQuality,
) -> EvidenceQuality:
    if history_quality == "stale" or snapshot.data_quality.freshness_status == "stale":
        return "stale"
    has_events = isinstance(latest_state, dict) and bool(latest_state.get("data_quality_events"))
    if (
        snapshot.data_quality.freshness_status != "fresh"
        or snapshot.data_quality.missing_fields
        or snapshot.data_quality.warnings
        or has_events
    ):
        return "partial"
    return "complete"


def _growth_rows(value: Any) -> list[dict[str, Any]]:
    rows = [row for row in _dict_rows(value) if _parse_datetime(row.get("as_of"))]
    rows.sort(key=lambda row: (_parse_datetime(row.get("as_of")), str(row.get("snapshot_date"))))
    return rows


def _comparison_anchor(
    rows: list[dict[str, Any]],
    end_at: datetime | None,
    days: int,
) -> dict[str, Any] | None:
    if end_at is None:
        return None
    cutoff = end_at - timedelta(days=days)
    candidates = [row for row in rows if (_parse_datetime(row.get("as_of")) or end_at) <= cutoff]
    if not candidates:
        return None
    anchor = candidates[-1]
    anchor_at = _parse_datetime(anchor.get("as_of"))
    if anchor_at is None:
        return None
    age_days = (end_at - anchor_at).total_seconds() / 86_400
    if age_days > days + ANCHOR_TOLERANCE_DAYS[days]:
        return None
    return anchor


def _allocation_by_date(rows: list[dict[str, Any]]) -> dict[str, dict[str, dict[str, Any]]]:
    grouped: dict[str, dict[str, dict[str, Any]]] = {}
    for row in rows:
        date_key = str(row.get("snapshot_date") or "")
        asset_key = str(row.get("asset_id") or row.get("ticker") or "")
        if date_key and asset_key:
            grouped.setdefault(date_key, {})[asset_key] = row
    return grouped


def _dict_rows(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(row) for row in value if isinstance(row, dict)]


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return _as_utc(parsed)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _number(value: Any) -> float | None:
    parsed = _float(value)
    return round(parsed, 10) if parsed is not None else None


def _ratio(numerator: float, denominator: float) -> float:
    return 0.0 if denominator == 0 else numerator / denominator


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", ".", value.casefold()).strip(".")
    return slug[:80] or "unknown"


def _safe_text(value: Any, *, limit: int = 160) -> str:
    return re.sub(r"\s+", " ", str(value)).strip()[:limit]


def _bounded_messages(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = _safe_text(value, limit=300)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
        if len(result) == 20:
            break
    return result
