from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from pydantic import Field

from moomail_finance_ai.metrics import MetricResult
from moomail_finance_ai.opend import OpenDFieldReport
from moomail_finance_ai.schemas import AuditRecord, DataQuality, PortfolioSnapshot, StrictModel


SCHEMA_VERSION = 1


class PortfolioHistoryStatus(StrictModel):
    portfolio_id: str
    snapshot_count: int
    latest_as_of: datetime | None
    data_quality: DataQuality


class StoredSnapshotResult(StrictModel):
    snapshot_id: str
    portfolio_id: str
    as_of: datetime
    holdings_count: int
    quotes_count: int
    metrics_count: int = 0
    warnings: list[str] = Field(default_factory=list)


class DailySnapshotStoreResult(StrictModel):
    status: Literal["inserted", "skipped"]
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
            conn.executescript(SCHEMA_SQL)
            _ensure_column(conn, "portfolio_snapshots", "last_observed_at", "TEXT")
            conn.execute(
                """
                UPDATE portfolio_snapshots
                SET last_observed_at = created_at
                WHERE last_observed_at IS NULL OR last_observed_at = ''
                """
            )
            conn.execute(
                """
                INSERT OR REPLACE INTO schema_metadata (key, value)
                VALUES ('schema_version', ?)
                """,
                (str(SCHEMA_VERSION),),
            )

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def store_snapshot(
        self,
        snapshot: PortfolioSnapshot,
        *,
        source_report: OpenDFieldReport | None = None,
        observed_at: datetime | None = None,
    ) -> StoredSnapshotResult:
        self.initialize()
        snapshot_id = f"snap_{uuid4().hex}"
        quote_rows = _quote_rows(source_report)
        warnings = list(snapshot.data_quality.warnings)
        observed_at = observed_at or datetime.now(UTC)

        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO portfolio_snapshots (
                    snapshot_id, portfolio_id, as_of, base_currency,
                    total_value_amount, total_value_currency,
                    data_quality_json, raw_snapshot_json, created_at, last_observed_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot_id,
                    snapshot.portfolio_id,
                    snapshot.as_of.isoformat(),
                    snapshot.base_currency,
                    snapshot.total_value.amount,
                    snapshot.total_value.currency,
                    _json(snapshot.data_quality.model_dump(mode="json")),
                    _json(snapshot.model_dump(mode="json")),
                    _now_iso(),
                    observed_at.isoformat(),
                ),
            )
            for cash in snapshot.cash:
                conn.execute(
                    """
                    INSERT INTO cash_balances (
                        snapshot_id, account_id, amount, currency, weight
                    )
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        snapshot_id,
                        cash.account_id,
                        cash.amount,
                        cash.currency,
                        cash.weight,
                    ),
                )
            for holding in snapshot.holdings:
                conn.execute(
                    """
                    INSERT INTO position_snapshots (
                        snapshot_id, asset_id, ticker, name, asset_type, exchange,
                        currency, quantity, market_price, market_value,
                        portfolio_weight, unrealized_pnl, sector, source, as_of
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        snapshot_id,
                        holding.asset_id,
                        holding.ticker,
                        holding.name,
                        holding.asset_type,
                        holding.exchange,
                        holding.currency,
                        holding.quantity,
                        holding.market_price,
                        holding.market_value,
                        holding.portfolio_weight,
                        holding.unrealized_pnl,
                        holding.sector,
                        holding.source,
                        holding.as_of.isoformat(),
                    ),
                )
            for row in quote_rows:
                conn.execute(
                    """
                    INSERT INTO quote_snapshots (
                        snapshot_id, code, as_of, last_price, raw_quote_json
                    )
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        snapshot_id,
                        row.get("code"),
                        source_report.generated_at.isoformat() if source_report else snapshot.as_of.isoformat(),
                        _optional_float(row.get("last_price")),
                        _json(row),
                    ),
                )

        return StoredSnapshotResult(
            snapshot_id=snapshot_id,
            portfolio_id=snapshot.portfolio_id,
            as_of=snapshot.as_of,
            holdings_count=len(snapshot.holdings),
            quotes_count=len(quote_rows),
            warnings=warnings,
        )

    def store_daily_snapshot_if_needed(
        self,
        snapshot: PortfolioSnapshot,
        *,
        source_report: OpenDFieldReport | None = None,
        observed_at: datetime | None = None,
    ) -> DailySnapshotStoreResult:
        self.initialize()
        observed_at = observed_at or datetime.now(UTC)
        snapshot_date = snapshot.as_of.date().isoformat()
        with self.connect() as conn:
            existing = conn.execute(
                """
                SELECT snapshot_id, as_of
                FROM portfolio_snapshots
                WHERE portfolio_id = ?
                  AND substr(as_of, 1, 10) = ?
                ORDER BY as_of DESC
                LIMIT 1
                """,
                (snapshot.portfolio_id, snapshot_date),
            ).fetchone()
            if existing is not None:
                conn.execute(
                    """
                    UPDATE portfolio_snapshots
                    SET last_observed_at = ?
                    WHERE snapshot_id = ?
                    """,
                    (observed_at.isoformat(), existing["snapshot_id"]),
                )
                return DailySnapshotStoreResult(
                    status="skipped",
                    portfolio_id=snapshot.portfolio_id,
                    snapshot_date=snapshot_date,
                    existing_snapshot_id=existing["snapshot_id"],
                    as_of=_parse_dt(existing["as_of"]),
                    last_observed_at=observed_at,
                    holdings_count=len(snapshot.holdings),
                    quotes_count=len(_quote_rows(source_report)),
                    reason="Daily snapshot already exists for this portfolio/date.",
                    warnings=list(snapshot.data_quality.warnings),
                )

        stored = self.store_snapshot(snapshot, source_report=source_report, observed_at=observed_at)
        return DailySnapshotStoreResult(
            status="inserted",
            portfolio_id=stored.portfolio_id,
            snapshot_date=snapshot_date,
            snapshot_id=stored.snapshot_id,
            as_of=stored.as_of,
            last_observed_at=observed_at,
            holdings_count=stored.holdings_count,
            quotes_count=stored.quotes_count,
            reason="No daily snapshot existed for this portfolio/date.",
            warnings=stored.warnings,
        )

    def store_metrics(self, snapshot_id: str, metrics: list[MetricResult]) -> int:
        self.initialize()
        with self.connect() as conn:
            for metric in metrics:
                conn.execute(
                    """
                    INSERT INTO calculated_metrics (
                        metric_id, snapshot_id, metric_name, metric_value_json,
                        metric_version, input_scope_json, source_inputs_json,
                        warnings_json, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        f"metric_{uuid4().hex}",
                        snapshot_id,
                        metric.metric_name,
                        _json(metric.value),
                        metric.metric_version,
                        _json(metric.input_scope),
                        _json(metric.source_inputs),
                        _json(metric.warnings),
                        _now_iso(),
                    ),
                )
        return len(metrics)

    def store_audit_record(self, audit_record: AuditRecord) -> None:
        self.initialize()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO agent_runs (
                    run_id, timestamp, user_query, mode, tools_called_json,
                    data_timestamps_json, source_ids_json, assumptions_json,
                    guardrail_result_json, output_summary, memory_updates_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    audit_record.run_id,
                    audit_record.timestamp.isoformat(),
                    audit_record.user_query,
                    audit_record.mode,
                    _json(audit_record.tools_called),
                    _json(audit_record.data_timestamps),
                    _json(audit_record.source_ids),
                    _json(audit_record.assumptions),
                    _json(audit_record.guardrail_result.model_dump(mode="json")),
                    audit_record.output_summary,
                    _json([memory.model_dump(mode="json") for memory in audit_record.memory_updates]),
                ),
            )

    def latest_snapshot(self, portfolio_id: str) -> sqlite3.Row | None:
        self.initialize()
        with self.connect() as conn:
            return conn.execute(
                """
                SELECT *
                FROM portfolio_snapshots
                WHERE portfolio_id = ?
                ORDER BY as_of DESC
                LIMIT 1
                """,
                (portfolio_id,),
            ).fetchone()

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
                FROM portfolio_snapshots
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
            missing_fields.append("portfolio_snapshots")
            warnings.append("No portfolio snapshots are stored.")
        else:
            freshness_status = "fresh"
            if latest_as_of and now - latest_as_of > stale_after:
                freshness_status = "stale"
                warnings.append("Latest portfolio snapshot is stale.")
            if len(rows) < min_snapshots_for_history:
                missing_fields.append("historical_depth")
                warnings.append(
                    f"Only {len(rows)} snapshot(s) stored; historical analysis needs "
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

    def table_count(self, table_name: str) -> int:
        if table_name not in ALLOWED_COUNT_TABLES:
            raise ValueError(f"Unsupported table count: {table_name}")
        self.initialize()
        with self.connect() as conn:
            row = conn.execute(f"SELECT COUNT(*) AS count FROM {table_name}").fetchone()
        return int(row["count"])


def _quote_rows(source_report: OpenDFieldReport | None) -> list[dict[str, Any]]:
    if source_report is None:
        return []
    quotes = next((table for table in source_report.tables if table.name == "quotes"), None)
    return list(quotes.rows) if quotes else []


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True)


def _optional_float(value: Any) -> float | None:
    if value in (None, "", "N/A"):
        return None
    return float(value)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _parse_dt(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def _ensure_column(conn: sqlite3.Connection, table_name: str, column_name: str, ddl: str) -> None:
    columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()}
    if column_name not in columns:
        conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {ddl}")


ALLOWED_COUNT_TABLES = {
    "portfolio_snapshots",
    "cash_balances",
    "position_snapshots",
    "quote_snapshots",
    "calculated_metrics",
    "agent_runs",
}


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS schema_metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS portfolio_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    portfolio_id TEXT NOT NULL,
    as_of TEXT NOT NULL,
    base_currency TEXT NOT NULL,
    total_value_amount REAL NOT NULL,
    total_value_currency TEXT NOT NULL,
    data_quality_json TEXT NOT NULL,
    raw_snapshot_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    last_observed_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_portfolio_snapshots_portfolio_asof
ON portfolio_snapshots (portfolio_id, as_of);

CREATE TABLE IF NOT EXISTS cash_balances (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id TEXT NOT NULL REFERENCES portfolio_snapshots(snapshot_id) ON DELETE CASCADE,
    account_id TEXT NOT NULL,
    amount REAL NOT NULL,
    currency TEXT NOT NULL,
    weight REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS position_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id TEXT NOT NULL REFERENCES portfolio_snapshots(snapshot_id) ON DELETE CASCADE,
    asset_id TEXT NOT NULL,
    ticker TEXT NOT NULL,
    name TEXT NOT NULL,
    asset_type TEXT NOT NULL,
    exchange TEXT,
    currency TEXT NOT NULL,
    quantity REAL NOT NULL,
    market_price REAL NOT NULL,
    market_value REAL NOT NULL,
    portfolio_weight REAL NOT NULL,
    unrealized_pnl REAL,
    sector TEXT,
    source TEXT NOT NULL,
    as_of TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_position_snapshots_snapshot
ON position_snapshots (snapshot_id);

CREATE TABLE IF NOT EXISTS quote_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id TEXT NOT NULL REFERENCES portfolio_snapshots(snapshot_id) ON DELETE CASCADE,
    code TEXT,
    as_of TEXT NOT NULL,
    last_price REAL,
    raw_quote_json TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_quote_snapshots_snapshot
ON quote_snapshots (snapshot_id);

CREATE TABLE IF NOT EXISTS calculated_metrics (
    metric_id TEXT PRIMARY KEY,
    snapshot_id TEXT NOT NULL REFERENCES portfolio_snapshots(snapshot_id) ON DELETE CASCADE,
    metric_name TEXT NOT NULL,
    metric_value_json TEXT NOT NULL,
    metric_version TEXT NOT NULL,
    input_scope_json TEXT NOT NULL,
    source_inputs_json TEXT NOT NULL,
    warnings_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_calculated_metrics_snapshot
ON calculated_metrics (snapshot_id);

CREATE TABLE IF NOT EXISTS agent_runs (
    run_id TEXT PRIMARY KEY,
    timestamp TEXT NOT NULL,
    user_query TEXT NOT NULL,
    mode TEXT NOT NULL,
    tools_called_json TEXT NOT NULL,
    data_timestamps_json TEXT NOT NULL,
    source_ids_json TEXT NOT NULL,
    assumptions_json TEXT NOT NULL,
    guardrail_result_json TEXT NOT NULL,
    output_summary TEXT NOT NULL,
    memory_updates_json TEXT NOT NULL
);
"""
