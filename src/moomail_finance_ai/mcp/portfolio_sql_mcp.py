from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from moomail_finance_ai.mcp.registry import (
    MCPResourceSpec,
    MCPToolSpec,
    RegisteredMCPModule,
    object_schema,
)
from moomail_finance_ai.metrics import MetricResult
from moomail_finance_ai.opend import OpenDFieldReport
from moomail_finance_ai.schemas import AuditRecord, PortfolioSnapshot
from moomail_finance_ai.sql_store import ALLOWED_COUNT_TABLES, SCHEMA_SQL, PortfolioSqlStore


SERVER_NAME = "moomail-portfolio-sql-mcp"
SERVER_VERSION = "0.1.0"


def build_portfolio_sql_mcp_module(
    *,
    store: PortfolioSqlStore | None = None,
    db_path: str | Path = "data/portfolio-history.sqlite",
) -> RegisteredMCPModule:
    store = store or PortfolioSqlStore(db_path)
    module = RegisteredMCPModule(server_name=SERVER_NAME, version=SERVER_VERSION)

    module.add_tool(
        MCPToolSpec(
            name="portfolio_sql_initialize",
            description="Initialize the local portfolio SQL schema.",
            input_schema=object_schema(),
            read_only=False,
        ),
        lambda _arguments: _initialize(store),
    )
    module.add_tool(
        MCPToolSpec(
            name="portfolio_sql_store_snapshot",
            description="Store a normalized PortfolioSnapshot and optional OpenD source report.",
            input_schema=object_schema(
                {
                    "snapshot": {"type": "object", "description": "PortfolioSnapshot JSON."},
                    "source_report": {
                        "type": "object",
                        "description": "Optional OpenDFieldReport JSON used for quote rows.",
                    },
                },
                required=["snapshot"],
            ),
            read_only=False,
        ),
        lambda arguments: store.store_snapshot(
            PortfolioSnapshot.model_validate(arguments["snapshot"]),
            source_report=_optional_source_report(arguments),
        ),
    )
    module.add_tool(
        MCPToolSpec(
            name="portfolio_sql_store_daily_snapshot_if_needed",
            description=(
                "Store one portfolio snapshot per portfolio/date. If a daily snapshot already "
                "exists, update its last observed timestamp and return a skipped result."
            ),
            input_schema=object_schema(
                {
                    "snapshot": {"type": "object", "description": "PortfolioSnapshot JSON."},
                    "source_report": {
                        "type": "object",
                        "description": "Optional OpenDFieldReport JSON used for quote rows.",
                    },
                    "observed_at": {
                        "type": "string",
                        "description": "Optional ISO timestamp for deterministic tests.",
                    },
                },
                required=["snapshot"],
            ),
            read_only=False,
        ),
        lambda arguments: store.store_daily_snapshot_if_needed(
            PortfolioSnapshot.model_validate(arguments["snapshot"]),
            source_report=_optional_source_report(arguments),
            observed_at=_optional_datetime(arguments.get("observed_at")),
        ),
    )
    module.add_tool(
        MCPToolSpec(
            name="portfolio_sql_store_metrics",
            description="Store deterministic MetricResult rows for a stored snapshot.",
            input_schema=object_schema(
                {
                    "snapshot_id": {"type": "string"},
                    "metrics": {
                        "type": "array",
                        "items": {"type": "object"},
                        "description": "MetricResult JSON rows.",
                    },
                },
                required=["snapshot_id", "metrics"],
            ),
            read_only=False,
        ),
        lambda arguments: {
            "metrics_stored": store.store_metrics(
                str(arguments["snapshot_id"]),
                [MetricResult.model_validate(item) for item in arguments["metrics"]],
            )
        },
    )
    module.add_tool(
        MCPToolSpec(
            name="portfolio_sql_store_audit_record",
            description="Store a compact agent audit record with output summary only.",
            input_schema=object_schema(
                {"audit_record": {"type": "object", "description": "AuditRecord JSON."}},
                required=["audit_record"],
            ),
            read_only=False,
        ),
        lambda arguments: _store_audit_record(store, arguments),
    )
    module.add_tool(
        MCPToolSpec(
            name="portfolio_sql_history_status",
            description="Report snapshot count, latest timestamp, freshness, and depth warnings.",
            input_schema=object_schema(
                {
                    "portfolio_id": {"type": "string", "default": "portfolio_default"},
                    "now": {
                        "type": "string",
                        "description": "Optional ISO timestamp for deterministic tests.",
                    },
                    "stale_after_hours": {"type": "number", "default": 24},
                    "min_snapshots_for_history": {"type": "integer", "default": 2},
                },
                required=["portfolio_id"],
            ),
        ),
        lambda arguments: store.history_status(
            str(arguments["portfolio_id"]),
            now=_optional_datetime(arguments.get("now")),
            stale_after=timedelta(hours=float(arguments.get("stale_after_hours", 24))),
            min_snapshots_for_history=int(arguments.get("min_snapshots_for_history", 2)),
        ),
    )
    module.add_tool(
        MCPToolSpec(
            name="portfolio_sql_latest_snapshot",
            description="Read the latest stored snapshot metadata and raw snapshot JSON.",
            input_schema=object_schema(
                {"portfolio_id": {"type": "string", "default": "portfolio_default"}},
                required=["portfolio_id"],
            ),
        ),
        lambda arguments: _latest_snapshot(store, str(arguments["portfolio_id"])),
    )
    module.add_tool(
        MCPToolSpec(
            name="portfolio_sql_table_count",
            description="Count rows in an allowed portfolio SQL table.",
            input_schema=object_schema(
                {
                    "table_name": {
                        "type": "string",
                        "enum": sorted(ALLOWED_COUNT_TABLES),
                    }
                },
                required=["table_name"],
            ),
        ),
        lambda arguments: {
            "table_name": str(arguments["table_name"]),
            "count": store.table_count(str(arguments["table_name"])),
        },
    )
    module.add_resource(
        MCPResourceSpec(
            uri="portfolio-sql://schema",
            name="Portfolio SQL Schema",
            description="SQLite schema for portfolio history, metrics, and audit summaries.",
        ),
        lambda: {"schema_sql": SCHEMA_SQL, "allowed_count_tables": sorted(ALLOWED_COUNT_TABLES)},
    )
    module.add_resource(
        MCPResourceSpec(
            uri="portfolio-sql://status",
            name="Portfolio SQL Store Status",
            description="Database path and row counts for known tables.",
        ),
        lambda: _store_status(store),
    )
    return module


def _initialize(store: PortfolioSqlStore) -> dict[str, Any]:
    store.initialize()
    return {"initialized": True, "db_path": str(store.db_path)}


def _optional_source_report(arguments: dict[str, Any]) -> OpenDFieldReport | None:
    if not arguments.get("source_report"):
        return None
    return OpenDFieldReport.model_validate(arguments["source_report"])


def _store_audit_record(store: PortfolioSqlStore, arguments: dict[str, Any]) -> dict[str, Any]:
    audit_record = AuditRecord.model_validate(arguments["audit_record"])
    store.store_audit_record(audit_record)
    return {"stored": True, "run_id": audit_record.run_id}


def _latest_snapshot(store: PortfolioSqlStore, portfolio_id: str) -> dict[str, Any] | None:
    row = store.latest_snapshot(portfolio_id)
    if row is None:
        return None
    return {
        "snapshot_id": row["snapshot_id"],
        "portfolio_id": row["portfolio_id"],
        "as_of": row["as_of"],
        "base_currency": row["base_currency"],
        "total_value_amount": row["total_value_amount"],
        "total_value_currency": row["total_value_currency"],
        "data_quality": json.loads(row["data_quality_json"]),
        "snapshot": json.loads(row["raw_snapshot_json"]),
        "last_observed_at": row["last_observed_at"],
    }


def _store_status(store: PortfolioSqlStore) -> dict[str, Any]:
    store.initialize()
    return {
        "db_path": str(store.db_path),
        "exists": store.db_path.exists(),
        "row_counts": {
            table_name: store.table_count(table_name)
            for table_name in sorted(ALLOWED_COUNT_TABLES)
        },
    }


def _optional_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed
