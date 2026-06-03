from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from moomail_finance_ai.mcp.registry import (
    MCPResourceSpec,
    MCPToolSpec,
    RegisteredMCPModule,
    object_schema,
)
from moomail_finance_ai.opend import OpenDFieldReport
from moomail_finance_ai.schemas import AuditRecord, PortfolioSnapshot
from moomail_finance_ai.sql_store import (
    ALLOWED_COUNT_TABLES,
    DEFAULT_ACCOUNT_ID,
    DEFAULT_ACCOUNT_TYPE,
    DEFAULT_PROVIDER,
    SCHEMA_SQL,
    SCHEMA_VERSION,
    PortfolioSqlStore,
)


SERVER_NAME = "moomail-portfolio-sql-mcp"
SERVER_VERSION = "0.2.0"


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
            description="Initialize the lean portfolio-history SQL schema.",
            input_schema=object_schema(),
            read_only=False,
        ),
        lambda _arguments: _initialize(store),
    )
    module.add_tool(
        MCPToolSpec(
            name="portfolio_sql_upsert_portfolio",
            description="Upsert one logical portfolio identity row.",
            input_schema=object_schema(
                {
                    "portfolio_id": {"type": "string", "default": "portfolio_default"},
                    "name": {"type": "string"},
                    "base_currency": {"type": "string", "default": "USD"},
                    "observed_at": {"type": "string"},
                },
                required=["portfolio_id"],
            ),
            read_only=False,
        ),
        lambda arguments: store.upsert_portfolio(
            str(arguments["portfolio_id"]),
            name=arguments.get("name"),
            base_currency=str(arguments.get("base_currency", "USD")),
            observed_at=_optional_datetime(arguments.get("observed_at")),
        ),
    )
    module.add_tool(
        MCPToolSpec(
            name="portfolio_sql_upsert_broker_account",
            description="Upsert an internal broker account identity row.",
            input_schema=object_schema(
                {
                    "portfolio_id": {"type": "string", "default": "portfolio_default"},
                    "account_id": {"type": "string", "default": DEFAULT_ACCOUNT_ID},
                    "provider": {"type": "string", "default": DEFAULT_PROVIDER},
                    "security_firm": {"type": "string"},
                    "account_type": {"type": "string", "default": DEFAULT_ACCOUNT_TYPE},
                    "base_currency": {"type": "string", "default": "USD"},
                    "observed_at": {"type": "string"},
                },
                required=["portfolio_id"],
            ),
            read_only=False,
        ),
        lambda arguments: store.upsert_broker_account(
            portfolio_id=str(arguments["portfolio_id"]),
            account_id=str(arguments.get("account_id", DEFAULT_ACCOUNT_ID)),
            provider=str(arguments.get("provider", DEFAULT_PROVIDER)),
            security_firm=arguments.get("security_firm"),
            account_type=str(arguments.get("account_type", DEFAULT_ACCOUNT_TYPE)),
            base_currency=str(arguments.get("base_currency", "USD")),
            observed_at=_optional_datetime(arguments.get("observed_at")),
        ),
    )
    module.add_tool(
        MCPToolSpec(
            name="portfolio_sql_upsert_assets",
            description="Upsert canonical assets from a normalized PortfolioSnapshot.",
            input_schema=object_schema(
                {
                    "snapshot": {"type": "object", "description": "PortfolioSnapshot JSON."},
                    "include_cash_assets": {"type": "boolean", "default": True},
                    "observed_at": {"type": "string"},
                },
                required=["snapshot"],
            ),
            read_only=False,
        ),
        lambda arguments: store.upsert_assets(
            PortfolioSnapshot.model_validate(arguments["snapshot"]),
            include_cash_assets=bool(arguments.get("include_cash_assets", True)),
            observed_at=_optional_datetime(arguments.get("observed_at")),
        ),
    )
    module.add_tool(
        MCPToolSpec(
            name="portfolio_sql_upsert_position_states",
            description=(
                "Upsert compact position states. New rows are inserted when quantity, "
                "average cost, side, active status, or asset identity changes."
            ),
            input_schema=object_schema(
                {
                    "snapshot": {"type": "object", "description": "PortfolioSnapshot JSON."},
                    "source_report": {"type": "object", "description": "Optional OpenDFieldReport."},
                    "account_id": {"type": "string", "default": DEFAULT_ACCOUNT_ID},
                    "observed_at": {"type": "string"},
                    "mark_missing_inactive": {"type": "boolean", "default": True},
                },
                required=["snapshot"],
            ),
            read_only=False,
        ),
        lambda arguments: store.upsert_position_states(
            PortfolioSnapshot.model_validate(arguments["snapshot"]),
            account_id=str(arguments.get("account_id", DEFAULT_ACCOUNT_ID)),
            source_report=_optional_source_report(arguments),
            observed_at=_optional_datetime(arguments.get("observed_at")),
            mark_missing_inactive=bool(arguments.get("mark_missing_inactive", True)),
        ),
    )
    module.add_tool(
        MCPToolSpec(
            name="portfolio_sql_store_daily_value_snapshot",
            description="Insert or update one portfolio value snapshot per portfolio/account/date.",
            input_schema=object_schema(
                {
                    "snapshot": {"type": "object", "description": "PortfolioSnapshot JSON."},
                    "source_report": {"type": "object", "description": "Optional OpenDFieldReport."},
                    "account_id": {"type": "string", "default": DEFAULT_ACCOUNT_ID},
                    "observed_at": {"type": "string"},
                },
                required=["snapshot"],
            ),
            read_only=False,
        ),
        lambda arguments: store.store_daily_value_snapshot(
            PortfolioSnapshot.model_validate(arguments["snapshot"]),
            account_id=str(arguments.get("account_id", DEFAULT_ACCOUNT_ID)),
            source_report=_optional_source_report(arguments),
            observed_at=_optional_datetime(arguments.get("observed_at")),
        ),
    )
    module.add_tool(
        MCPToolSpec(
            name="portfolio_sql_store_weight_snapshots",
            description="Replace child allocation weight rows for one value snapshot.",
            input_schema=object_schema(
                {
                    "snapshot": {"type": "object", "description": "PortfolioSnapshot JSON."},
                    "value_snapshot_id": {"type": "string"},
                    "source_report": {"type": "object", "description": "Optional OpenDFieldReport."},
                    "account_id": {"type": "string", "default": DEFAULT_ACCOUNT_ID},
                },
                required=["snapshot", "value_snapshot_id"],
            ),
            read_only=False,
        ),
        lambda arguments: store.store_weight_snapshots(
            PortfolioSnapshot.model_validate(arguments["snapshot"]),
            value_snapshot_id=str(arguments["value_snapshot_id"]),
            account_id=str(arguments.get("account_id", DEFAULT_ACCOUNT_ID)),
            source_report=_optional_source_report(arguments),
        ),
    )
    module.add_tool(
        MCPToolSpec(
            name="portfolio_sql_store_data_quality_events",
            description="Store warning and missing-data events without raw source duplication.",
            input_schema=object_schema(
                {
                    "snapshot": {"type": "object", "description": "PortfolioSnapshot JSON."},
                    "value_snapshot_id": {"type": "string"},
                    "source_report": {"type": "object", "description": "Optional OpenDFieldReport."},
                    "account_id": {"type": "string", "default": DEFAULT_ACCOUNT_ID},
                    "run_id": {"type": "string"},
                },
                required=["snapshot"],
            ),
            read_only=False,
        ),
        lambda arguments: store.store_data_quality_events(
            PortfolioSnapshot.model_validate(arguments["snapshot"]),
            value_snapshot_id=arguments.get("value_snapshot_id"),
            account_id=arguments.get("account_id", DEFAULT_ACCOUNT_ID),
            source_report=_optional_source_report(arguments),
            run_id=arguments.get("run_id"),
        ),
    )
    module.add_tool(
        MCPToolSpec(
            name="portfolio_sql_get_history_status",
            description="Report value snapshot count, latest timestamp, freshness, and depth warnings.",
            input_schema=object_schema(
                {
                    "portfolio_id": {"type": "string", "default": "portfolio_default"},
                    "now": {"type": "string"},
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
            name="portfolio_sql_get_latest_portfolio_state",
            description="Read the latest value snapshot with active position, weight, and event rows.",
            input_schema=object_schema(
                {
                    "portfolio_id": {"type": "string", "default": "portfolio_default"},
                    "account_id": {"type": "string", "default": DEFAULT_ACCOUNT_ID},
                },
                required=["portfolio_id"],
            ),
        ),
        lambda arguments: store.latest_portfolio_state(
            str(arguments["portfolio_id"]),
            account_id=str(arguments.get("account_id", DEFAULT_ACCOUNT_ID)),
        ),
    )
    module.add_tool(
        MCPToolSpec(
            name="portfolio_sql_get_portfolio_growth",
            description="Read daily portfolio value history.",
            input_schema=object_schema(
                {
                    "portfolio_id": {"type": "string", "default": "portfolio_default"},
                    "account_id": {"type": "string", "default": DEFAULT_ACCOUNT_ID},
                    "limit": {"type": "integer", "default": 30},
                },
                required=["portfolio_id"],
            ),
        ),
        lambda arguments: store.portfolio_growth(
            str(arguments["portfolio_id"]),
            account_id=str(arguments.get("account_id", DEFAULT_ACCOUNT_ID)),
            limit=int(arguments.get("limit", 30)),
        ),
    )
    module.add_tool(
        MCPToolSpec(
            name="portfolio_sql_get_allocation_history",
            description="Read historical allocation weight rows.",
            input_schema=object_schema(
                {
                    "portfolio_id": {"type": "string", "default": "portfolio_default"},
                    "account_id": {"type": "string", "default": DEFAULT_ACCOUNT_ID},
                    "limit": {"type": "integer", "default": 30},
                },
                required=["portfolio_id"],
            ),
        ),
        lambda arguments: store.allocation_history(
            str(arguments["portfolio_id"]),
            account_id=str(arguments.get("account_id", DEFAULT_ACCOUNT_ID)),
            limit=int(arguments.get("limit", 30)),
        ),
    )
    module.add_tool(
        MCPToolSpec(
            name="portfolio_sql_store_agent_run",
            description="Store compact agent run metadata and output summary only.",
            input_schema=object_schema(
                {
                    "audit_record": {"type": "object", "description": "AuditRecord JSON."},
                    "portfolio_id": {"type": "string", "default": "portfolio_default"},
                    "agent_type": {"type": "string", "default": "investment_agent"},
                    "snapshot_refs": {"type": "array", "items": {"type": "string"}},
                    "missing_data": {"type": "array", "items": {"type": "string"}},
                },
                required=["audit_record"],
            ),
            read_only=False,
        ),
        lambda arguments: store.store_agent_run(
            AuditRecord.model_validate(arguments["audit_record"]),
            portfolio_id=str(arguments.get("portfolio_id", "portfolio_default")),
            agent_type=str(arguments.get("agent_type", "investment_agent")),
            snapshot_refs=list(arguments.get("snapshot_refs", [])),
            missing_data=list(arguments.get("missing_data", [])),
        ),
    )
    module.add_tool(
        MCPToolSpec(
            name="portfolio_sql_link_agent_run_sources",
            description="Replace source links for an agent run.",
            input_schema=object_schema(
                {
                    "run_id": {"type": "string"},
                    "sources": {
                        "type": "array",
                        "items": {"type": "object"},
                    },
                },
                required=["run_id", "sources"],
            ),
            read_only=False,
        ),
        lambda arguments: store.link_agent_run_sources(
            str(arguments["run_id"]),
            list(arguments["sources"]),
        ),
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
            description="Lean SQLite schema for portfolio history and audit summaries.",
        ),
        lambda: {
            "schema_version": SCHEMA_VERSION,
            "schema_sql": SCHEMA_SQL,
            "allowed_count_tables": sorted(ALLOWED_COUNT_TABLES),
        },
    )
    module.add_resource(
        MCPResourceSpec(
            uri="portfolio-sql://status",
            name="Portfolio SQL Store Status",
            description="Database path and row counts for known lean schema tables.",
        ),
        lambda: _store_status(store),
    )
    return module


def _initialize(store: PortfolioSqlStore) -> dict[str, Any]:
    store.initialize()
    return {"initialized": True, "db_path": str(store.db_path), "schema_version": SCHEMA_VERSION}


def _optional_source_report(arguments: dict[str, Any]) -> OpenDFieldReport | None:
    if not arguments.get("source_report"):
        return None
    return OpenDFieldReport.model_validate(arguments["source_report"])


def _store_status(store: PortfolioSqlStore) -> dict[str, Any]:
    store.initialize()
    return {
        "db_path": str(store.db_path),
        "exists": store.db_path.exists(),
        "schema_version": SCHEMA_VERSION,
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
