from __future__ import annotations

import json
import re
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from pydantic import Field

from moomail_finance_ai.metrics import OPEND_FUND_ASSETS_CASH_SWEEP_ID, MetricResult
from moomail_finance_ai.opend import OpenDFieldReport, OpenDTableResult
from moomail_finance_ai.schemas import AuditRecord, DataQuality, Holding, PortfolioSnapshot, StrictModel


SCHEMA_VERSION = 2
DEFAULT_ACCOUNT_ID = "opend_securities_account"
DEFAULT_PROVIDER = "moomoo"
DEFAULT_ACCOUNT_TYPE = "securities"
FLOAT_TOLERANCE = 1e-9


class PortfolioHistoryStatus(StrictModel):
    portfolio_id: str
    snapshot_count: int
    latest_as_of: datetime | None
    data_quality: DataQuality


class PortfolioIdentityResult(StrictModel):
    portfolio_id: str
    status: Literal["inserted", "updated"]


class BrokerAccountResult(StrictModel):
    account_id: str
    portfolio_id: str
    status: Literal["inserted", "updated"]


class AssetUpsertResult(StrictModel):
    assets_upserted: int
    asset_ids: list[str]


class PositionStateUpsertResult(StrictModel):
    inserted: int
    updated: int
    marked_inactive: int
    active_position_count: int


class ValueSnapshotStoreResult(StrictModel):
    status: Literal["inserted", "updated"]
    value_snapshot_id: str
    portfolio_id: str
    account_id: str
    snapshot_date: str
    as_of: datetime
    last_observed_at: datetime
    total_assets: float
    cash: float
    fund_assets: float
    securities_assets: float | None = None
    market_val: float | None = None
    currency: str
    warnings: list[str] = Field(default_factory=list)


class WeightSnapshotStoreResult(StrictModel):
    value_snapshot_id: str
    rows_stored: int
    replaced_existing_rows: bool


class DataQualityEventStoreResult(StrictModel):
    value_snapshot_id: str | None = None
    events_stored: int
    event_ids: list[str] = Field(default_factory=list)


class AgentRunStoreResult(StrictModel):
    stored: bool
    run_id: str
    portfolio_id: str


class AgentRunSourceLinkResult(StrictModel):
    run_id: str
    sources_linked: int


class PortfolioObservationStoreResult(StrictModel):
    status: Literal["inserted", "updated"]
    portfolio_id: str
    account_id: str
    value_snapshot_id: str
    snapshot_date: str
    as_of: datetime
    last_observed_at: datetime
    assets_upserted: int
    position_states_inserted: int
    position_states_updated: int
    position_states_marked_inactive: int
    weight_rows_stored: int
    data_quality_events_stored: int
    warnings: list[str] = Field(default_factory=list)


class PositionStateChangeResult(StrictModel):
    portfolio_id: str
    account_id: str
    asset_id: str
    ticker: str | None = None
    name: str | None = None
    change_type: str
    change_at: datetime
    previous_quantity: float | None = None
    current_quantity: float | None = None
    quantity_delta: float | None = None
    previous_average_cost: float | None = None
    current_average_cost: float | None = None
    average_cost_delta: float | None = None
    previous_cost_basis: float | None = None
    current_cost_basis: float | None = None
    cost_basis_delta: float | None = None
    implied_added_average_cost: float | None = None
    implied_removed_average_cost: float | None = None
    previous_state: dict[str, Any] | None = None
    current_state: dict[str, Any] | None = None
    warnings: list[str] = Field(default_factory=list)


class PositionStateChangesResult(StrictModel):
    portfolio_id: str
    account_id: str
    since: datetime | None = None
    until: datetime | None = None
    ticker: str | None = None
    asset_id: str | None = None
    changes: list[PositionStateChangeResult] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class StoredSnapshotResult(StrictModel):
    """Compatibility result for older callers.

    `snapshot_id` now aliases the lean `portfolio_value_snapshots.value_snapshot_id`.
    No raw snapshot, quote, or metric-history rows are written.
    """

    snapshot_id: str
    portfolio_id: str
    as_of: datetime
    holdings_count: int
    quotes_count: int = 0
    metrics_count: int = 0
    warnings: list[str] = Field(default_factory=list)


class DailySnapshotStoreResult(StrictModel):
    """Compatibility result for older daily-snapshot callers."""

    status: Literal["inserted", "updated"]
    portfolio_id: str
    snapshot_date: str
    snapshot_id: str | None = None
    existing_snapshot_id: str | None = None
    as_of: datetime
    last_observed_at: datetime
    holdings_count: int
    quotes_count: int = 0
    metrics_count: int = 0
    reason: str
    warnings: list[str] = Field(default_factory=list)


class PortfolioSqlStore:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        if self.db_path.parent != Path("."):
            self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def initialize(self) -> None:
        with self.connect() as conn:
            _prepare_schema_for_current_schema(conn)
            conn.executescript(SCHEMA_SQL)

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def upsert_portfolio(
        self,
        portfolio_id: str,
        *,
        name: str | None = None,
        base_currency: str = "USD",
        observed_at: datetime | None = None,
    ) -> PortfolioIdentityResult:
        self.initialize()
        observed_at = observed_at or datetime.now(UTC)
        with self.connect() as conn:
            existing = conn.execute(
                "SELECT portfolio_id FROM portfolios WHERE portfolio_id = ?",
                (portfolio_id,),
            ).fetchone()
            conn.execute(
                """
                INSERT INTO portfolios (portfolio_id, name, base_currency, created_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(portfolio_id) DO UPDATE SET
                    name = excluded.name,
                    base_currency = excluded.base_currency
                """,
                (
                    portfolio_id,
                    name or portfolio_id,
                    base_currency,
                    observed_at.isoformat(),
                ),
            )
        return PortfolioIdentityResult(
            portfolio_id=portfolio_id,
            status="updated" if existing else "inserted",
        )

    def upsert_broker_account(
        self,
        *,
        portfolio_id: str,
        account_id: str = DEFAULT_ACCOUNT_ID,
        provider: str = DEFAULT_PROVIDER,
        security_firm: str | None = None,
        account_type: str = DEFAULT_ACCOUNT_TYPE,
        base_currency: str = "USD",
        observed_at: datetime | None = None,
    ) -> BrokerAccountResult:
        self.initialize()
        observed_at = observed_at or datetime.now(UTC)
        self.upsert_portfolio(portfolio_id, base_currency=base_currency, observed_at=observed_at)
        with self.connect() as conn:
            existing = conn.execute(
                "SELECT account_id FROM broker_accounts WHERE account_id = ?",
                (account_id,),
            ).fetchone()
            conn.execute(
                """
                INSERT INTO broker_accounts (
                    account_id, portfolio_id, provider, security_firm, account_type,
                    base_currency, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(account_id) DO UPDATE SET
                    portfolio_id = excluded.portfolio_id,
                    provider = excluded.provider,
                    security_firm = excluded.security_firm,
                    account_type = excluded.account_type,
                    base_currency = excluded.base_currency
                """,
                (
                    account_id,
                    portfolio_id,
                    provider,
                    security_firm,
                    account_type,
                    base_currency,
                    observed_at.isoformat(),
                ),
            )
        return BrokerAccountResult(
            account_id=account_id,
            portfolio_id=portfolio_id,
            status="updated" if existing else "inserted",
        )

    def upsert_assets(
        self,
        snapshot: PortfolioSnapshot,
        *,
        observed_at: datetime | None = None,
        include_cash_assets: bool = True,
    ) -> AssetUpsertResult:
        self.initialize()
        observed_at = observed_at or snapshot.as_of
        rows = _asset_rows_from_snapshot(snapshot, include_cash_assets=include_cash_assets)
        with self.connect() as conn:
            for row in rows:
                conn.execute(
                    """
                    INSERT INTO assets (
                        asset_id, provider_code, ticker, name, asset_type, exchange,
                        currency, first_seen_at, last_seen_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(asset_id) DO UPDATE SET
                        provider_code = excluded.provider_code,
                        ticker = excluded.ticker,
                        name = excluded.name,
                        asset_type = excluded.asset_type,
                        exchange = excluded.exchange,
                        currency = excluded.currency,
                        last_seen_at = excluded.last_seen_at
                    """,
                    (
                        row["asset_id"],
                        row["provider_code"],
                        row["ticker"],
                        row["name"],
                        row["asset_type"],
                        row["exchange"],
                        row["currency"],
                        observed_at.isoformat(),
                        observed_at.isoformat(),
                    ),
                )
        return AssetUpsertResult(
            assets_upserted=len(rows),
            asset_ids=[row["asset_id"] for row in rows],
        )

    def upsert_position_states(
        self,
        snapshot: PortfolioSnapshot,
        *,
        account_id: str = DEFAULT_ACCOUNT_ID,
        source_report: OpenDFieldReport | None = None,
        observed_at: datetime | None = None,
        mark_missing_inactive: bool = True,
    ) -> PositionStateUpsertResult:
        self.initialize()
        observed_at = observed_at or snapshot.as_of
        self.upsert_portfolio(
            snapshot.portfolio_id,
            base_currency=snapshot.base_currency,
            observed_at=observed_at,
        )
        self.upsert_broker_account(
            portfolio_id=snapshot.portfolio_id,
            account_id=account_id,
            base_currency=snapshot.base_currency,
            observed_at=observed_at,
        )
        self.upsert_assets(snapshot, observed_at=observed_at, include_cash_assets=False)

        position_rows = _position_rows_by_code(source_report)
        observed_asset_ids = {holding.asset_id for holding in snapshot.holdings}
        inserted = 0
        updated = 0
        marked_inactive = 0

        with self.connect() as conn:
            for holding in snapshot.holdings:
                source_row = position_rows.get(_provider_code_from_asset_id(holding.asset_id), {})
                average_cost = _average_cost(holding, source_row)
                position_side = _position_side(holding, source_row)
                active = conn.execute(
                    """
                    SELECT *
                    FROM position_states
                    WHERE portfolio_id = ?
                      AND account_id = ?
                      AND asset_id = ?
                      AND is_active = 1
                    ORDER BY first_observed_at DESC
                    LIMIT 1
                    """,
                    (snapshot.portfolio_id, account_id, holding.asset_id),
                ).fetchone()

                if active is not None and not _source_has_cost_basis(source_row):
                    average_cost = float(active["average_cost"])

                if active is None:
                    _insert_position_state(
                        conn,
                        snapshot=snapshot,
                        holding=holding,
                        account_id=account_id,
                        average_cost=average_cost,
                        position_side=position_side,
                        observed_at=observed_at,
                    )
                    inserted += 1
                    continue

                if _same_position_state(active, holding, average_cost, position_side):
                    conn.execute(
                        """
                        UPDATE position_states
                        SET market_price = ?,
                            market_value = ?,
                            unrealized_pl = ?,
                            currency = ?,
                            last_observed_at = ?
                        WHERE position_state_id = ?
                        """,
                        (
                            holding.market_price,
                            holding.market_value,
                            holding.unrealized_pnl,
                            holding.currency,
                            observed_at.isoformat(),
                            active["position_state_id"],
                        ),
                    )
                    updated += 1
                else:
                    conn.execute(
                        """
                        UPDATE position_states
                        SET is_active = 0,
                            last_observed_at = ?
                        WHERE position_state_id = ?
                        """,
                        (observed_at.isoformat(), active["position_state_id"]),
                    )
                    marked_inactive += 1
                    _insert_position_state(
                        conn,
                        snapshot=snapshot,
                        holding=holding,
                        account_id=account_id,
                        average_cost=average_cost,
                        position_side=position_side,
                        observed_at=observed_at,
                    )
                    inserted += 1

            if mark_missing_inactive:
                active_rows = conn.execute(
                    """
                    SELECT position_state_id, asset_id
                    FROM position_states
                    WHERE portfolio_id = ?
                      AND account_id = ?
                      AND is_active = 1
                    """,
                    (snapshot.portfolio_id, account_id),
                ).fetchall()
                for row in active_rows:
                    if row["asset_id"] in observed_asset_ids:
                        continue
                    conn.execute(
                        """
                        UPDATE position_states
                        SET is_active = 0,
                            last_observed_at = ?
                        WHERE position_state_id = ?
                        """,
                        (observed_at.isoformat(), row["position_state_id"]),
                    )
                    marked_inactive += 1

            active_count = conn.execute(
                """
                SELECT COUNT(*) AS count
                FROM position_states
                WHERE portfolio_id = ?
                  AND account_id = ?
                  AND is_active = 1
                """,
                (snapshot.portfolio_id, account_id),
            ).fetchone()["count"]

        return PositionStateUpsertResult(
            inserted=inserted,
            updated=updated,
            marked_inactive=marked_inactive,
            active_position_count=int(active_count),
        )

    def store_daily_value_snapshot(
        self,
        snapshot: PortfolioSnapshot,
        *,
        account_id: str = DEFAULT_ACCOUNT_ID,
        source_report: OpenDFieldReport | None = None,
        observed_at: datetime | None = None,
    ) -> ValueSnapshotStoreResult:
        self.initialize()
        observed_at = observed_at or datetime.now(UTC)
        funds = _funds_values(snapshot, source_report)
        snapshot_date = snapshot.as_of.date().isoformat()
        self.upsert_portfolio(
            snapshot.portfolio_id,
            base_currency=snapshot.base_currency,
            observed_at=observed_at,
        )
        self.upsert_broker_account(
            portfolio_id=snapshot.portfolio_id,
            account_id=account_id,
            base_currency=snapshot.base_currency,
            observed_at=observed_at,
        )

        with self.connect() as conn:
            existing = conn.execute(
                """
                SELECT value_snapshot_id
                FROM portfolio_value_snapshots
                WHERE portfolio_id = ?
                  AND account_id = ?
                  AND snapshot_date = ?
                """,
                (snapshot.portfolio_id, account_id, snapshot_date),
            ).fetchone()
            if existing is None:
                value_snapshot_id = f"value_snap_{uuid4().hex}"
                status: Literal["inserted", "updated"] = "inserted"
                created_at = observed_at.isoformat()
            else:
                value_snapshot_id = existing["value_snapshot_id"]
                status = "updated"
                created_at = None

            if status == "inserted":
                conn.execute(
                    """
                    INSERT INTO portfolio_value_snapshots (
                        value_snapshot_id, portfolio_id, account_id, snapshot_date,
                        as_of, total_assets, cash, fund_assets, securities_assets,
                        market_val, currency, created_at, last_observed_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        value_snapshot_id,
                        snapshot.portfolio_id,
                        account_id,
                        snapshot_date,
                        snapshot.as_of.isoformat(),
                        funds["total_assets"],
                        funds["cash"],
                        funds["fund_assets"],
                        funds["securities_assets"],
                        funds["market_val"],
                        funds["currency"],
                        created_at,
                        observed_at.isoformat(),
                    ),
                )
            else:
                conn.execute(
                    """
                    UPDATE portfolio_value_snapshots
                    SET as_of = ?,
                        total_assets = ?,
                        cash = ?,
                        fund_assets = ?,
                        securities_assets = ?,
                        market_val = ?,
                        currency = ?,
                        last_observed_at = ?
                    WHERE value_snapshot_id = ?
                    """,
                    (
                        snapshot.as_of.isoformat(),
                        funds["total_assets"],
                        funds["cash"],
                        funds["fund_assets"],
                        funds["securities_assets"],
                        funds["market_val"],
                        funds["currency"],
                        observed_at.isoformat(),
                        value_snapshot_id,
                    ),
                )

        return ValueSnapshotStoreResult(
            status=status,
            value_snapshot_id=value_snapshot_id,
            portfolio_id=snapshot.portfolio_id,
            account_id=account_id,
            snapshot_date=snapshot_date,
            as_of=snapshot.as_of,
            last_observed_at=observed_at,
            total_assets=funds["total_assets"],
            cash=funds["cash"],
            fund_assets=funds["fund_assets"],
            securities_assets=funds["securities_assets"],
            market_val=funds["market_val"],
            currency=funds["currency"],
            warnings=list(snapshot.data_quality.warnings),
        )

    def store_weight_snapshots(
        self,
        snapshot: PortfolioSnapshot,
        *,
        value_snapshot_id: str,
        account_id: str = DEFAULT_ACCOUNT_ID,
        source_report: OpenDFieldReport | None = None,
    ) -> WeightSnapshotStoreResult:
        self.initialize()
        self.upsert_assets(snapshot, observed_at=snapshot.as_of, include_cash_assets=True)
        position_rows = _position_rows_by_code(source_report)
        rows = _weight_rows(snapshot, account_id=account_id, source_rows=position_rows)
        with self.connect() as conn:
            existing_count = conn.execute(
                """
                SELECT COUNT(*) AS count
                FROM portfolio_weight_snapshots
                WHERE value_snapshot_id = ?
                """,
                (value_snapshot_id,),
            ).fetchone()["count"]
            conn.execute(
                "DELETE FROM portfolio_weight_snapshots WHERE value_snapshot_id = ?",
                (value_snapshot_id,),
            )
            for row in rows:
                conn.execute(
                    """
                    INSERT INTO portfolio_weight_snapshots (
                        weight_snapshot_id, value_snapshot_id, portfolio_id,
                        account_id, asset_id, quantity, average_cost, market_value,
                        weight, unrealized_pl, asset_type, currency, as_of
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        f"weight_snap_{uuid4().hex}",
                        value_snapshot_id,
                        snapshot.portfolio_id,
                        account_id,
                        row["asset_id"],
                        row["quantity"],
                        row["average_cost"],
                        row["market_value"],
                        row["weight"],
                        row["unrealized_pl"],
                        row["asset_type"],
                        row["currency"],
                        snapshot.as_of.isoformat(),
                    ),
                )
        return WeightSnapshotStoreResult(
            value_snapshot_id=value_snapshot_id,
            rows_stored=len(rows),
            replaced_existing_rows=bool(existing_count),
        )

    def store_data_quality_events(
        self,
        snapshot: PortfolioSnapshot,
        *,
        value_snapshot_id: str | None = None,
        account_id: str | None = DEFAULT_ACCOUNT_ID,
        source_report: OpenDFieldReport | None = None,
        run_id: str | None = None,
    ) -> DataQualityEventStoreResult:
        self.initialize()
        events = _data_quality_event_rows(
            snapshot,
            account_id=account_id,
            value_snapshot_id=value_snapshot_id,
            source_report=source_report,
            run_id=run_id,
        )
        event_ids: list[str] = []
        with self.connect() as conn:
            if value_snapshot_id is not None:
                conn.execute(
                    "DELETE FROM data_quality_events WHERE value_snapshot_id = ?",
                    (value_snapshot_id,),
                )
            for event in events:
                event_id = f"dq_{uuid4().hex}"
                conn.execute(
                    """
                    INSERT INTO data_quality_events (
                        event_id, portfolio_id, account_id, asset_id,
                        value_snapshot_id, run_id, event_type, severity,
                        message, source, as_of, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event_id,
                        snapshot.portfolio_id,
                        account_id,
                        event["asset_id"],
                        value_snapshot_id,
                        run_id,
                        event["event_type"],
                        event["severity"],
                        event["message"],
                        event["source"],
                        snapshot.as_of.isoformat(),
                        datetime.now(UTC).isoformat(),
                    ),
                )
                event_ids.append(event_id)
        return DataQualityEventStoreResult(
            value_snapshot_id=value_snapshot_id,
            events_stored=len(event_ids),
            event_ids=event_ids,
        )

    def store_portfolio_observation(
        self,
        snapshot: PortfolioSnapshot,
        *,
        account_id: str = DEFAULT_ACCOUNT_ID,
        provider: str = DEFAULT_PROVIDER,
        security_firm: str | None = None,
        account_type: str = DEFAULT_ACCOUNT_TYPE,
        source_report: OpenDFieldReport | None = None,
        observed_at: datetime | None = None,
    ) -> PortfolioObservationStoreResult:
        observed_at = observed_at or datetime.now(UTC)
        self.upsert_portfolio(
            snapshot.portfolio_id,
            base_currency=snapshot.base_currency,
            observed_at=observed_at,
        )
        self.upsert_broker_account(
            portfolio_id=snapshot.portfolio_id,
            account_id=account_id,
            provider=provider,
            security_firm=security_firm,
            account_type=account_type,
            base_currency=snapshot.base_currency,
            observed_at=observed_at,
        )
        assets = self.upsert_assets(snapshot, observed_at=observed_at)
        position_states = self.upsert_position_states(
            snapshot,
            account_id=account_id,
            source_report=source_report,
            observed_at=observed_at,
        )
        value_snapshot = self.store_daily_value_snapshot(
            snapshot,
            account_id=account_id,
            source_report=source_report,
            observed_at=observed_at,
        )
        weights = self.store_weight_snapshots(
            snapshot,
            value_snapshot_id=value_snapshot.value_snapshot_id,
            account_id=account_id,
            source_report=source_report,
        )
        events = self.store_data_quality_events(
            snapshot,
            value_snapshot_id=value_snapshot.value_snapshot_id,
            account_id=account_id,
            source_report=source_report,
        )
        return PortfolioObservationStoreResult(
            status=value_snapshot.status,
            portfolio_id=snapshot.portfolio_id,
            account_id=account_id,
            value_snapshot_id=value_snapshot.value_snapshot_id,
            snapshot_date=value_snapshot.snapshot_date,
            as_of=value_snapshot.as_of,
            last_observed_at=value_snapshot.last_observed_at,
            assets_upserted=assets.assets_upserted,
            position_states_inserted=position_states.inserted,
            position_states_updated=position_states.updated,
            position_states_marked_inactive=position_states.marked_inactive,
            weight_rows_stored=weights.rows_stored,
            data_quality_events_stored=events.events_stored,
            warnings=list(snapshot.data_quality.warnings),
        )

    def store_agent_run(
        self,
        audit_record: AuditRecord,
        *,
        portfolio_id: str = "portfolio_default",
        agent_type: str = "investment_agent",
        started_at: datetime | None = None,
        completed_at: datetime | None = None,
        snapshot_refs: list[str] | None = None,
        missing_data: list[str] | None = None,
    ) -> AgentRunStoreResult:
        self.initialize()
        self.upsert_portfolio(portfolio_id, observed_at=audit_record.timestamp)
        started_at = started_at or audit_record.timestamp
        completed_at = completed_at or audit_record.timestamp
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO agent_runs (
                    run_id, portfolio_id, agent_type, user_query, mode,
                    started_at, completed_at, tools_called_json,
                    snapshot_refs_json, guardrail_result_json, missing_data_json,
                    output_summary, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    portfolio_id = excluded.portfolio_id,
                    agent_type = excluded.agent_type,
                    user_query = excluded.user_query,
                    mode = excluded.mode,
                    started_at = excluded.started_at,
                    completed_at = excluded.completed_at,
                    tools_called_json = excluded.tools_called_json,
                    snapshot_refs_json = excluded.snapshot_refs_json,
                    guardrail_result_json = excluded.guardrail_result_json,
                    missing_data_json = excluded.missing_data_json,
                    output_summary = excluded.output_summary
                """,
                (
                    audit_record.run_id,
                    portfolio_id,
                    agent_type,
                    audit_record.user_query,
                    audit_record.mode,
                    started_at.isoformat(),
                    completed_at.isoformat(),
                    _json(audit_record.tools_called),
                    _json(snapshot_refs or audit_record.data_timestamps),
                    _json(audit_record.guardrail_result.model_dump(mode="json")),
                    _json(missing_data or audit_record.assumptions),
                    audit_record.output_summary,
                    audit_record.timestamp.isoformat(),
                ),
            )
        return AgentRunStoreResult(stored=True, run_id=audit_record.run_id, portfolio_id=portfolio_id)

    def link_agent_run_sources(
        self,
        run_id: str,
        sources: list[dict[str, str]],
    ) -> AgentRunSourceLinkResult:
        self.initialize()
        with self.connect() as conn:
            conn.execute("DELETE FROM agent_run_sources WHERE run_id = ?", (run_id,))
            for source in sources:
                conn.execute(
                    """
                    INSERT INTO agent_run_sources (run_id, source_type, source_id, created_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        run_id,
                        source["source_type"],
                        source["source_id"],
                        datetime.now(UTC).isoformat(),
                    ),
                )
        return AgentRunSourceLinkResult(run_id=run_id, sources_linked=len(sources))

    def store_audit_record(self, audit_record: AuditRecord) -> None:
        self.store_agent_run(audit_record)

    def store_snapshot(
        self,
        snapshot: PortfolioSnapshot,
        *,
        source_report: OpenDFieldReport | None = None,
        observed_at: datetime | None = None,
    ) -> StoredSnapshotResult:
        stored = self.store_portfolio_observation(
            snapshot,
            source_report=source_report,
            observed_at=observed_at,
        )
        return StoredSnapshotResult(
            snapshot_id=stored.value_snapshot_id,
            portfolio_id=stored.portfolio_id,
            as_of=stored.as_of,
            holdings_count=len(snapshot.holdings),
            warnings=stored.warnings,
        )

    def store_daily_snapshot_if_needed(
        self,
        snapshot: PortfolioSnapshot,
        *,
        source_report: OpenDFieldReport | None = None,
        observed_at: datetime | None = None,
    ) -> DailySnapshotStoreResult:
        stored = self.store_portfolio_observation(
            snapshot,
            source_report=source_report,
            observed_at=observed_at,
        )
        return DailySnapshotStoreResult(
            status=stored.status,
            portfolio_id=stored.portfolio_id,
            snapshot_date=stored.snapshot_date,
            snapshot_id=stored.value_snapshot_id if stored.status == "inserted" else None,
            existing_snapshot_id=stored.value_snapshot_id if stored.status == "updated" else None,
            as_of=stored.as_of,
            last_observed_at=stored.last_observed_at,
            holdings_count=len(snapshot.holdings),
            reason=(
                "Inserted a new daily value snapshot."
                if stored.status == "inserted"
                else "Updated the existing daily value snapshot and replaced weight rows."
            ),
            warnings=stored.warnings,
        )

    def store_metrics(self, snapshot_id: str, metrics: list[MetricResult]) -> int:
        self.initialize()
        return 0

    def history_status(
        self,
        portfolio_id: str,
        *,
        now: datetime | None = None,
        stale_after: timedelta = timedelta(hours=24),
        min_snapshots_for_history: int = 2,
    ) -> PortfolioHistoryStatus:
        self.initialize()
        now = now or datetime.now(UTC)
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT as_of
                FROM portfolio_value_snapshots
                WHERE portfolio_id = ?
                ORDER BY as_of DESC
                """,
                (portfolio_id,),
            ).fetchall()

        warnings: list[str] = []
        missing_fields: list[str] = []
        latest_as_of = _parse_dt(rows[0]["as_of"]) if rows else None
        freshness_status = "unknown"

        if not rows:
            missing_fields.append("portfolio_value_snapshots")
            warnings.append("No portfolio value snapshots are stored.")
        else:
            freshness_status = "fresh"
            if latest_as_of and now - latest_as_of > stale_after:
                freshness_status = "stale"
                warnings.append("Latest portfolio value snapshot is stale.")
            if len(rows) < min_snapshots_for_history:
                missing_fields.append("historical_depth")
                warnings.append(
                    f"Only {len(rows)} value snapshot(s) stored; historical analysis needs "
                    f"{min_snapshots_for_history}."
                )

        return PortfolioHistoryStatus(
            portfolio_id=portfolio_id,
            snapshot_count=len(rows),
            latest_as_of=latest_as_of,
            data_quality=DataQuality(
                freshness_status=freshness_status,
                missing_fields=missing_fields,
                warnings=warnings,
            ),
        )

    def latest_portfolio_state(
        self,
        portfolio_id: str,
        *,
        account_id: str = DEFAULT_ACCOUNT_ID,
    ) -> dict[str, Any] | None:
        self.initialize()
        with self.connect() as conn:
            value = conn.execute(
                """
                SELECT *
                FROM portfolio_value_snapshots
                WHERE portfolio_id = ?
                  AND account_id = ?
                ORDER BY as_of DESC
                LIMIT 1
                """,
                (portfolio_id, account_id),
            ).fetchone()
            if value is None:
                return None
            weights = conn.execute(
                """
                SELECT w.*, a.ticker, a.name, a.provider_code, a.exchange
                FROM portfolio_weight_snapshots w
                JOIN assets a ON a.asset_id = w.asset_id
                WHERE w.value_snapshot_id = ?
                ORDER BY ABS(w.weight) DESC, a.ticker
                """,
                (value["value_snapshot_id"],),
            ).fetchall()
            active_positions = conn.execute(
                """
                SELECT p.*, a.ticker, a.name, a.provider_code, a.asset_type, a.exchange
                FROM position_states p
                JOIN assets a ON a.asset_id = p.asset_id
                WHERE p.portfolio_id = ?
                  AND p.account_id = ?
                  AND p.is_active = 1
                ORDER BY ABS(p.market_value) DESC, a.ticker
                """,
                (portfolio_id, account_id),
            ).fetchall()
            events = conn.execute(
                """
                SELECT *
                FROM data_quality_events
                WHERE value_snapshot_id = ?
                ORDER BY created_at
                """,
                (value["value_snapshot_id"],),
            ).fetchall()

        return {
            "value_snapshot": _row_dict(value),
            "weights": [_row_dict(row) for row in weights],
            "active_positions": [_row_dict(row) for row in active_positions],
            "data_quality_events": [_row_dict(row) for row in events],
        }

    def portfolio_growth(
        self,
        portfolio_id: str,
        *,
        account_id: str = DEFAULT_ACCOUNT_ID,
        limit: int = 30,
    ) -> list[dict[str, Any]]:
        self.initialize()
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT snapshot_date, as_of, total_assets, cash, fund_assets,
                       securities_assets, market_val, currency
                FROM portfolio_value_snapshots
                WHERE portfolio_id = ?
                  AND account_id = ?
                ORDER BY snapshot_date DESC
                LIMIT ?
                """,
                (portfolio_id, account_id, limit),
            ).fetchall()
        return [_row_dict(row) for row in reversed(rows)]

    def allocation_history(
        self,
        portfolio_id: str,
        *,
        account_id: str = DEFAULT_ACCOUNT_ID,
        limit: int = 30,
    ) -> list[dict[str, Any]]:
        self.initialize()
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT v.snapshot_date, v.as_of, w.asset_id, a.ticker, a.name,
                       w.asset_type, w.market_value, w.weight, w.currency
                FROM portfolio_value_snapshots v
                JOIN portfolio_weight_snapshots w
                  ON w.value_snapshot_id = v.value_snapshot_id
                JOIN assets a ON a.asset_id = w.asset_id
                WHERE v.portfolio_id = ?
                  AND v.account_id = ?
                ORDER BY v.snapshot_date DESC, ABS(w.weight) DESC, a.ticker
                LIMIT ?
                """,
                (portfolio_id, account_id, limit),
            ).fetchall()
        return [_row_dict(row) for row in rows]

    def position_state_changes(
        self,
        portfolio_id: str,
        *,
        account_id: str = DEFAULT_ACCOUNT_ID,
        ticker: str | None = None,
        asset_id: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        lookback_days: float | None = None,
        limit: int = 100,
        include_initial_observations: bool = False,
    ) -> PositionStateChangesResult:
        self.initialize()
        if lookback_days is not None and since is None:
            until_for_window = until or datetime.now(UTC)
            since = until_for_window - timedelta(days=float(lookback_days))

        clauses = ["p.portfolio_id = ?", "p.account_id = ?"]
        params: list[Any] = [portfolio_id, account_id]
        if ticker:
            clauses.append("UPPER(a.ticker) = ?")
            params.append(ticker.upper())
        if asset_id:
            clauses.append("p.asset_id = ?")
            params.append(asset_id)

        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT p.*, a.ticker, a.name, a.provider_code, a.asset_type, a.exchange
                FROM position_states p
                JOIN assets a ON a.asset_id = p.asset_id
                WHERE {' AND '.join(clauses)}
                ORDER BY p.asset_id, p.first_observed_at, p.last_observed_at
                """,
                params,
            ).fetchall()

        changes: list[PositionStateChangeResult] = []
        for asset_rows in _group_position_rows_by_asset(rows).values():
            if include_initial_observations and asset_rows:
                initial_change = _initial_position_state_change(
                    asset_rows[0],
                    since=since,
                    until=until,
                )
                if initial_change is not None:
                    changes.append(initial_change)

            for previous, current in zip(asset_rows, asset_rows[1:], strict=False):
                change = _position_state_delta_change(
                    previous,
                    current,
                    since=since,
                    until=until,
                )
                if change is not None:
                    changes.append(change)

            if asset_rows and not bool(asset_rows[-1]["is_active"]):
                close_change = _closed_position_state_change(
                    asset_rows[-1],
                    since=since,
                    until=until,
                )
                if close_change is not None:
                    changes.append(close_change)

        changes.sort(key=lambda change: (change.change_at, change.ticker or "", change.asset_id))
        warnings = []
        if not changes and (ticker or asset_id):
            warnings.append("No position-state changes matched the requested asset and time range.")
        return PositionStateChangesResult(
            portfolio_id=portfolio_id,
            account_id=account_id,
            since=since,
            until=until,
            ticker=ticker.upper() if ticker else None,
            asset_id=asset_id,
            changes=changes[: max(0, int(limit))],
            warnings=warnings,
        )

    def latest_snapshot(self, portfolio_id: str) -> sqlite3.Row | None:
        self.initialize()
        with self.connect() as conn:
            return conn.execute(
                """
                SELECT *
                FROM portfolio_value_snapshots
                WHERE portfolio_id = ?
                ORDER BY as_of DESC
                LIMIT 1
                """,
                (portfolio_id,),
            ).fetchone()

    def table_count(self, table_name: str) -> int:
        if table_name not in ALLOWED_COUNT_TABLES:
            raise ValueError(f"Unsupported table count: {table_name}")
        self.initialize()
        with self.connect() as conn:
            row = conn.execute(f"SELECT COUNT(*) AS count FROM {table_name}").fetchone()
        return int(row["count"])


def _insert_position_state(
    conn: sqlite3.Connection,
    *,
    snapshot: PortfolioSnapshot,
    holding: Holding,
    account_id: str,
    average_cost: float,
    position_side: str,
    observed_at: datetime,
) -> None:
    conn.execute(
        """
        INSERT INTO position_states (
            position_state_id, portfolio_id, account_id, asset_id, quantity,
            average_cost, market_price, market_value, unrealized_pl, currency,
            position_side, first_observed_at, last_observed_at, is_active
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
        """,
        (
            f"pos_state_{uuid4().hex}",
            snapshot.portfolio_id,
            account_id,
            holding.asset_id,
            holding.quantity,
            average_cost,
            holding.market_price,
            holding.market_value,
            holding.unrealized_pnl,
            holding.currency,
            position_side,
            observed_at.isoformat(),
            observed_at.isoformat(),
        ),
    )


def _prepare_schema_for_current_schema(conn: sqlite3.Connection) -> None:
    for table_name, required_columns in LEAN_TABLE_REQUIRED_COLUMNS.items():
        existing_columns = _table_columns(conn, table_name)
        if existing_columns is None:
            continue
        if required_columns <= existing_columns:
            continue
        _rename_legacy_table(conn, table_name)


def _table_columns(conn: sqlite3.Connection, table_name: str) -> set[str] | None:
    if not _table_exists(conn, table_name):
        return None
    return {
        str(row["name"])
        for row in conn.execute(f'PRAGMA table_info("{table_name}")').fetchall()
    }


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        """
        SELECT 1
        FROM sqlite_master
        WHERE type = 'table'
          AND name = ?
        """,
        (table_name,),
    ).fetchone()
    return row is not None


def _rename_legacy_table(conn: sqlite3.Connection, table_name: str) -> None:
    legacy_name = _available_legacy_table_name(conn, table_name)
    conn.execute(f'ALTER TABLE "{table_name}" RENAME TO "{legacy_name}"')


def _available_legacy_table_name(conn: sqlite3.Connection, table_name: str) -> str:
    base_name = f"{table_name}_legacy_v1"
    if not _table_exists(conn, base_name):
        return base_name
    suffix = 2
    while _table_exists(conn, f"{base_name}_{suffix}"):
        suffix += 1
    return f"{base_name}_{suffix}"


LEAN_TABLE_REQUIRED_COLUMNS = {
    "portfolios": {"portfolio_id", "name", "base_currency", "created_at"},
    "broker_accounts": {
        "account_id",
        "portfolio_id",
        "provider",
        "security_firm",
        "account_type",
        "base_currency",
        "created_at",
    },
    "assets": {
        "asset_id",
        "provider_code",
        "ticker",
        "name",
        "asset_type",
        "exchange",
        "currency",
        "first_seen_at",
        "last_seen_at",
    },
    "position_states": {
        "position_state_id",
        "portfolio_id",
        "account_id",
        "asset_id",
        "quantity",
        "average_cost",
        "market_price",
        "market_value",
        "unrealized_pl",
        "currency",
        "position_side",
        "first_observed_at",
        "last_observed_at",
        "is_active",
    },
    "portfolio_value_snapshots": {
        "value_snapshot_id",
        "portfolio_id",
        "account_id",
        "snapshot_date",
        "as_of",
        "total_assets",
        "cash",
        "fund_assets",
        "securities_assets",
        "market_val",
        "currency",
        "created_at",
        "last_observed_at",
    },
    "portfolio_weight_snapshots": {
        "weight_snapshot_id",
        "value_snapshot_id",
        "portfolio_id",
        "account_id",
        "asset_id",
        "quantity",
        "average_cost",
        "market_value",
        "weight",
        "unrealized_pl",
        "asset_type",
        "currency",
        "as_of",
    },
    "data_quality_events": {
        "event_id",
        "portfolio_id",
        "account_id",
        "asset_id",
        "value_snapshot_id",
        "run_id",
        "event_type",
        "severity",
        "message",
        "source",
        "as_of",
        "created_at",
    },
    "agent_runs": {
        "run_id",
        "portfolio_id",
        "agent_type",
        "user_query",
        "mode",
        "started_at",
        "completed_at",
        "tools_called_json",
        "snapshot_refs_json",
        "guardrail_result_json",
        "missing_data_json",
        "output_summary",
        "created_at",
    },
    "agent_run_sources": {"id", "run_id", "source_type", "source_id", "created_at"},
}


def _same_position_state(
    row: sqlite3.Row,
    holding: Holding,
    average_cost: float,
    position_side: str,
) -> bool:
    return (
        _same_float(row["quantity"], holding.quantity)
        and _same_float(row["average_cost"], average_cost)
        and str(row["position_side"] or "") == position_side
    )


def _group_position_rows_by_asset(
    rows: list[sqlite3.Row],
) -> dict[str, list[sqlite3.Row]]:
    grouped: dict[str, list[sqlite3.Row]] = {}
    for row in rows:
        grouped.setdefault(str(row["asset_id"]), []).append(row)
    return grouped


def _initial_position_state_change(
    row: sqlite3.Row,
    *,
    since: datetime | None,
    until: datetime | None,
) -> PositionStateChangeResult | None:
    change_at = _parse_db_datetime(row["first_observed_at"])
    if not _datetime_in_range(change_at, since=since, until=until):
        return None
    return PositionStateChangeResult(
        portfolio_id=str(row["portfolio_id"]),
        account_id=str(row["account_id"]),
        asset_id=str(row["asset_id"]),
        ticker=row["ticker"],
        name=row["name"],
        change_type="initial_observation",
        change_at=change_at,
        current_quantity=float(row["quantity"]),
        current_average_cost=float(row["average_cost"]),
        current_cost_basis=_cost_basis(row),
        current_state=_position_state_summary(row),
        warnings=[
            "No prior position state exists in SQL; this may be the first stored observation."
        ],
    )


def _position_state_delta_change(
    previous: sqlite3.Row,
    current: sqlite3.Row,
    *,
    since: datetime | None,
    until: datetime | None,
) -> PositionStateChangeResult | None:
    change_at = _parse_db_datetime(current["first_observed_at"])
    if not _datetime_in_range(change_at, since=since, until=until):
        return None

    previous_quantity = float(previous["quantity"])
    current_quantity = float(current["quantity"])
    previous_average_cost = float(previous["average_cost"])
    current_average_cost = float(current["average_cost"])
    quantity_delta = current_quantity - previous_quantity
    average_cost_delta = current_average_cost - previous_average_cost
    previous_cost_basis = previous_quantity * previous_average_cost
    current_cost_basis = current_quantity * current_average_cost
    cost_basis_delta = current_cost_basis - previous_cost_basis
    warnings: list[str] = []
    implied_added_average_cost = None
    implied_removed_average_cost = None

    if not _same_float(quantity_delta, 0.0):
        implied_delta_average_cost = cost_basis_delta / quantity_delta
        if quantity_delta > 0:
            implied_added_average_cost = implied_delta_average_cost
        else:
            implied_removed_average_cost = implied_delta_average_cost
    elif not _same_float(average_cost_delta, 0.0):
        warnings.append(
            "Average cost changed without a quantity delta; trade price is not inferable."
        )

    if str(previous["position_side"] or "") != str(current["position_side"] or ""):
        warnings.append("Position side changed; cost-basis inference may not be comparable.")

    return PositionStateChangeResult(
        portfolio_id=str(current["portfolio_id"]),
        account_id=str(current["account_id"]),
        asset_id=str(current["asset_id"]),
        ticker=current["ticker"],
        name=current["name"],
        change_type=_position_state_change_type(
            quantity_delta=quantity_delta,
            average_cost_delta=average_cost_delta,
            previous_side=str(previous["position_side"] or ""),
            current_side=str(current["position_side"] or ""),
        ),
        change_at=change_at,
        previous_quantity=previous_quantity,
        current_quantity=current_quantity,
        quantity_delta=quantity_delta,
        previous_average_cost=previous_average_cost,
        current_average_cost=current_average_cost,
        average_cost_delta=average_cost_delta,
        previous_cost_basis=previous_cost_basis,
        current_cost_basis=current_cost_basis,
        cost_basis_delta=cost_basis_delta,
        implied_added_average_cost=implied_added_average_cost,
        implied_removed_average_cost=implied_removed_average_cost,
        previous_state=_position_state_summary(previous),
        current_state=_position_state_summary(current),
        warnings=warnings,
    )


def _closed_position_state_change(
    row: sqlite3.Row,
    *,
    since: datetime | None,
    until: datetime | None,
) -> PositionStateChangeResult | None:
    change_at = _parse_db_datetime(row["last_observed_at"])
    if not _datetime_in_range(change_at, since=since, until=until):
        return None
    return PositionStateChangeResult(
        portfolio_id=str(row["portfolio_id"]),
        account_id=str(row["account_id"]),
        asset_id=str(row["asset_id"]),
        ticker=row["ticker"],
        name=row["name"],
        change_type="closed_or_missing",
        change_at=change_at,
        previous_quantity=float(row["quantity"]),
        previous_average_cost=float(row["average_cost"]),
        previous_cost_basis=_cost_basis(row),
        previous_state=_position_state_summary(row),
        warnings=["Position was not observed in the latest state and was marked inactive."],
    )


def _position_state_change_type(
    *,
    quantity_delta: float,
    average_cost_delta: float,
    previous_side: str,
    current_side: str,
) -> str:
    if previous_side != current_side:
        return "side_changed"
    quantity_changed = not _same_float(quantity_delta, 0.0)
    cost_changed = not _same_float(average_cost_delta, 0.0)
    if quantity_changed and cost_changed:
        return "quantity_and_average_cost_changed"
    if quantity_delta > 0:
        return "quantity_increased"
    if quantity_delta < 0:
        return "quantity_decreased"
    if cost_changed:
        return "average_cost_changed"
    return "state_changed"


def _position_state_summary(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "position_state_id": row["position_state_id"],
        "asset_id": row["asset_id"],
        "ticker": row["ticker"],
        "quantity": row["quantity"],
        "average_cost": row["average_cost"],
        "market_price": row["market_price"],
        "market_value": row["market_value"],
        "unrealized_pl": row["unrealized_pl"],
        "currency": row["currency"],
        "position_side": row["position_side"],
        "first_observed_at": row["first_observed_at"],
        "last_observed_at": row["last_observed_at"],
        "is_active": bool(row["is_active"]),
    }


def _cost_basis(row: sqlite3.Row) -> float:
    return float(row["quantity"]) * float(row["average_cost"])


def _parse_db_datetime(value: Any) -> datetime:
    parsed = datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def _datetime_in_range(
    value: datetime,
    *,
    since: datetime | None,
    until: datetime | None,
) -> bool:
    if since is not None and value < since:
        return False
    if until is not None and value > until:
        return False
    return True


def _asset_rows_from_snapshot(
    snapshot: PortfolioSnapshot,
    *,
    include_cash_assets: bool,
) -> list[dict[str, Any]]:
    rows = [
        {
            "asset_id": holding.asset_id,
            "provider_code": _provider_code_from_asset_id(holding.asset_id),
            "ticker": holding.ticker,
            "name": holding.name,
            "asset_type": holding.asset_type,
            "exchange": holding.exchange,
            "currency": holding.currency,
        }
        for holding in snapshot.holdings
    ]
    if include_cash_assets:
        rows.extend(_cash_asset_row(cash.account_id, cash.currency) for cash in snapshot.cash)
    return _dedupe_asset_rows(rows)


def _cash_asset_row(account_id: str, currency: str) -> dict[str, Any]:
    if account_id == OPEND_FUND_ASSETS_CASH_SWEEP_ID:
        asset_id = f"cash_sweep:{currency}"
        return {
            "asset_id": asset_id,
            "provider_code": asset_id,
            "ticker": currency,
            "name": f"Auto-invested fund assets {currency}",
            "asset_type": "cash_sweep",
            "exchange": None,
            "currency": currency,
        }
    asset_id = f"cash:{currency}"
    return {
        "asset_id": asset_id,
        "provider_code": asset_id,
        "ticker": currency,
        "name": f"Cash {currency}",
        "asset_type": "cash",
        "exchange": None,
        "currency": currency,
    }


def _dedupe_asset_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = set()
    result = []
    for row in rows:
        if row["asset_id"] in seen:
            continue
        seen.add(row["asset_id"])
        result.append(row)
    return result


def _weight_rows(
    snapshot: PortfolioSnapshot,
    *,
    account_id: str,
    source_rows: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    rows = []
    for holding in snapshot.holdings:
        source_row = source_rows.get(_provider_code_from_asset_id(holding.asset_id), {})
        rows.append(
            {
                "asset_id": holding.asset_id,
                "quantity": holding.quantity,
                "average_cost": _average_cost(holding, source_row),
                "market_value": holding.market_value,
                "weight": holding.portfolio_weight,
                "unrealized_pl": holding.unrealized_pnl,
                "asset_type": holding.asset_type,
                "currency": holding.currency,
            }
        )
    for cash in snapshot.cash:
        row = _cash_asset_row(cash.account_id, cash.currency)
        rows.append(
            {
                "asset_id": row["asset_id"],
                "quantity": cash.amount,
                "average_cost": 1.0,
                "market_value": cash.amount,
                "weight": cash.weight,
                "unrealized_pl": None,
                "asset_type": row["asset_type"],
                "currency": cash.currency,
            }
        )
    return rows


def _funds_values(
    snapshot: PortfolioSnapshot,
    source_report: OpenDFieldReport | None,
) -> dict[str, Any]:
    fund_row = _fund_row(source_report)
    literal_cash = sum(
        cash.amount for cash in snapshot.cash if cash.account_id != OPEND_FUND_ASSETS_CASH_SWEEP_ID
    )
    holdings_value = sum(holding.market_value for holding in snapshot.holdings)
    currency = str(fund_row.get("currency") or snapshot.total_value.currency)
    return {
        "total_assets": _first_available_number(
            fund_row,
            ["total_assets", f"{snapshot.base_currency.lower()}_assets"],
            default=snapshot.total_value.amount,
        ),
        "cash": _first_available_number(
            fund_row,
            ["cash", f"{snapshot.base_currency.lower()}_cash"],
            default=literal_cash,
        ),
        "fund_assets": _optional_number(fund_row.get("fund_assets"), default=0.0),
        "securities_assets": _optional_number(fund_row.get("securities_assets")),
        "market_val": _optional_number(fund_row.get("market_val"), default=holdings_value),
        "currency": currency,
    }


def _fund_row(source_report: OpenDFieldReport | None) -> dict[str, Any]:
    if source_report is None:
        return {}
    funds = _table_by_name(source_report, "funds")
    if funds is None or not funds.rows:
        return {}
    return funds.rows[0]


def _position_rows_by_code(source_report: OpenDFieldReport | None) -> dict[str, dict[str, Any]]:
    if source_report is None:
        return {}
    positions = _table_by_name(source_report, "positions")
    if positions is None:
        return {}
    return {
        str(row["code"]): row
        for row in positions.rows
        if isinstance(row.get("code"), str) and row.get("code")
    }


def _table_by_name(source_report: OpenDFieldReport, name: str) -> OpenDTableResult | None:
    return next((table for table in source_report.tables if table.name == name), None)


def _average_cost(holding: Holding, source_row: dict[str, Any]) -> float:
    return _first_available_number(
        source_row,
        ["average_cost", "cost_price", "diluted_cost"],
        default=holding.market_price,
    )


def _source_has_cost_basis(source_row: dict[str, Any]) -> bool:
    return any(
        source_row.get(key) not in (None, "", "N/A")
        for key in ("average_cost", "cost_price", "diluted_cost")
    )


def _position_side(holding: Holding, source_row: dict[str, Any]) -> str:
    value = source_row.get("position_side")
    if isinstance(value, str) and value:
        return value
    return "SHORT" if holding.quantity < 0 else "LONG"


def _data_quality_event_rows(
    snapshot: PortfolioSnapshot,
    *,
    account_id: str | None,
    value_snapshot_id: str | None,
    source_report: OpenDFieldReport | None,
    run_id: str | None,
) -> list[dict[str, Any]]:
    del account_id, value_snapshot_id, run_id
    warnings = list(snapshot.data_quality.warnings)
    missing_fields = list(snapshot.data_quality.missing_fields)
    if source_report is not None:
        warnings.extend(source_report.warnings)
        for table in source_report.tables:
            warnings.extend(table.warnings)

    rows: list[dict[str, Any]] = []
    for field in missing_fields:
        rows.append(
            {
                "asset_id": _asset_id_from_message(field),
                "event_type": "missing_field",
                "severity": "medium",
                "message": f"Missing field: {field}",
                "source": "opend",
            }
        )
    for warning in _dedupe_strings(warnings):
        rows.append(
            {
                "asset_id": _asset_id_from_message(warning),
                "event_type": _event_type(warning),
                "severity": _event_severity(warning),
                "message": warning,
                "source": "opend",
            }
        )
    return rows


def _asset_id_from_message(message: str) -> str | None:
    match = re.search(r"\b[A-Z]{2,}\.[A-Z0-9]+(?:[CP]\d+)?\b", message)
    if not match:
        return None
    return f"opend:{match.group(0)}"


def _event_type(message: str) -> str:
    lowered = message.lower()
    if "quote" in lowered and ("failed" in lowered or "missing" in lowered or "otc" in lowered):
        return "unsupported_quote"
    if "fund_assets" in lowered or "cash-equivalent" in lowered or "auto-invested" in lowered:
        return "cash_sweep_assumption"
    if "missing" in lowered or "unavailable" in lowered:
        return "missing_data"
    return "data_warning"


def _event_severity(message: str) -> str:
    lowered = message.lower()
    if "critical" in lowered or "failed" in lowered:
        return "medium"
    if "fund_assets" in lowered or "auto-invested" in lowered:
        return "low"
    return "medium"


def _provider_code_from_asset_id(asset_id: str) -> str:
    if asset_id.startswith("opend:"):
        return asset_id.split(":", 1)[1]
    return asset_id


def _first_available_number(
    row: dict[str, Any],
    keys: list[str],
    *,
    default: float = 0.0,
) -> float:
    for key in keys:
        if key in row:
            return _optional_number(row.get(key), default=default) or 0.0
    return default


def _optional_number(value: Any, default: float | None = None) -> float | None:
    if value in (None, "", "N/A"):
        return default
    return float(value)


def _same_float(left: Any, right: Any) -> bool:
    return abs(float(left) - float(right)) <= FLOAT_TOLERANCE


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True)


def _parse_dt(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def _row_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {key: row[key] for key in row.keys()}


def _dedupe_strings(values: list[str]) -> list[str]:
    seen = set()
    result = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


ALLOWED_COUNT_TABLES = {
    "portfolios",
    "broker_accounts",
    "assets",
    "position_states",
    "portfolio_value_snapshots",
    "portfolio_weight_snapshots",
    "data_quality_events",
    "agent_runs",
    "agent_run_sources",
}


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS portfolios (
    portfolio_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    base_currency TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS broker_accounts (
    account_id TEXT PRIMARY KEY,
    portfolio_id TEXT NOT NULL REFERENCES portfolios(portfolio_id) ON DELETE CASCADE,
    provider TEXT NOT NULL,
    security_firm TEXT,
    account_type TEXT NOT NULL,
    base_currency TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_broker_accounts_portfolio
ON broker_accounts (portfolio_id);

CREATE TABLE IF NOT EXISTS assets (
    asset_id TEXT PRIMARY KEY,
    provider_code TEXT NOT NULL,
    ticker TEXT NOT NULL,
    name TEXT NOT NULL,
    asset_type TEXT NOT NULL,
    exchange TEXT,
    currency TEXT NOT NULL,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_assets_ticker
ON assets (ticker);

CREATE TABLE IF NOT EXISTS position_states (
    position_state_id TEXT PRIMARY KEY,
    portfolio_id TEXT NOT NULL REFERENCES portfolios(portfolio_id) ON DELETE CASCADE,
    account_id TEXT NOT NULL REFERENCES broker_accounts(account_id) ON DELETE CASCADE,
    asset_id TEXT NOT NULL REFERENCES assets(asset_id) ON DELETE CASCADE,
    quantity REAL NOT NULL,
    average_cost REAL NOT NULL,
    market_price REAL NOT NULL,
    market_value REAL NOT NULL,
    unrealized_pl REAL,
    currency TEXT NOT NULL,
    position_side TEXT,
    first_observed_at TEXT NOT NULL,
    last_observed_at TEXT NOT NULL,
    is_active INTEGER NOT NULL CHECK (is_active IN (0, 1))
);

CREATE INDEX IF NOT EXISTS idx_position_states_active
ON position_states (portfolio_id, account_id, asset_id, is_active);

CREATE TABLE IF NOT EXISTS portfolio_value_snapshots (
    value_snapshot_id TEXT PRIMARY KEY,
    portfolio_id TEXT NOT NULL REFERENCES portfolios(portfolio_id) ON DELETE CASCADE,
    account_id TEXT NOT NULL REFERENCES broker_accounts(account_id) ON DELETE CASCADE,
    snapshot_date TEXT NOT NULL,
    as_of TEXT NOT NULL,
    total_assets REAL NOT NULL,
    cash REAL NOT NULL,
    fund_assets REAL NOT NULL,
    securities_assets REAL,
    market_val REAL,
    currency TEXT NOT NULL,
    created_at TEXT NOT NULL,
    last_observed_at TEXT NOT NULL,
    UNIQUE (portfolio_id, account_id, snapshot_date)
);

CREATE INDEX IF NOT EXISTS idx_portfolio_value_snapshots_portfolio_asof
ON portfolio_value_snapshots (portfolio_id, account_id, as_of);

CREATE TABLE IF NOT EXISTS portfolio_weight_snapshots (
    weight_snapshot_id TEXT PRIMARY KEY,
    value_snapshot_id TEXT NOT NULL REFERENCES portfolio_value_snapshots(value_snapshot_id) ON DELETE CASCADE,
    portfolio_id TEXT NOT NULL REFERENCES portfolios(portfolio_id) ON DELETE CASCADE,
    account_id TEXT NOT NULL REFERENCES broker_accounts(account_id) ON DELETE CASCADE,
    asset_id TEXT NOT NULL REFERENCES assets(asset_id) ON DELETE CASCADE,
    quantity REAL NOT NULL,
    average_cost REAL,
    market_value REAL NOT NULL,
    weight REAL NOT NULL,
    unrealized_pl REAL,
    asset_type TEXT NOT NULL,
    currency TEXT NOT NULL,
    as_of TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_portfolio_weight_snapshots_value
ON portfolio_weight_snapshots (value_snapshot_id);

CREATE INDEX IF NOT EXISTS idx_portfolio_weight_snapshots_asset
ON portfolio_weight_snapshots (portfolio_id, account_id, asset_id, as_of);

CREATE TABLE IF NOT EXISTS data_quality_events (
    event_id TEXT PRIMARY KEY,
    portfolio_id TEXT NOT NULL REFERENCES portfolios(portfolio_id) ON DELETE CASCADE,
    account_id TEXT REFERENCES broker_accounts(account_id) ON DELETE SET NULL,
    asset_id TEXT REFERENCES assets(asset_id) ON DELETE SET NULL,
    value_snapshot_id TEXT REFERENCES portfolio_value_snapshots(value_snapshot_id) ON DELETE CASCADE,
    run_id TEXT,
    event_type TEXT NOT NULL,
    severity TEXT NOT NULL,
    message TEXT NOT NULL,
    source TEXT NOT NULL,
    as_of TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_data_quality_events_snapshot
ON data_quality_events (value_snapshot_id);

CREATE INDEX IF NOT EXISTS idx_data_quality_events_portfolio
ON data_quality_events (portfolio_id, as_of);

CREATE TABLE IF NOT EXISTS agent_runs (
    run_id TEXT PRIMARY KEY,
    portfolio_id TEXT NOT NULL REFERENCES portfolios(portfolio_id) ON DELETE CASCADE,
    agent_type TEXT NOT NULL,
    user_query TEXT NOT NULL,
    mode TEXT NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT NOT NULL,
    tools_called_json TEXT NOT NULL,
    snapshot_refs_json TEXT NOT NULL,
    guardrail_result_json TEXT NOT NULL,
    missing_data_json TEXT NOT NULL,
    output_summary TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_agent_runs_portfolio
ON agent_runs (portfolio_id, completed_at);

CREATE TABLE IF NOT EXISTS agent_run_sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES agent_runs(run_id) ON DELETE CASCADE,
    source_type TEXT NOT NULL,
    source_id TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_agent_run_sources_run
ON agent_run_sources (run_id);
"""
