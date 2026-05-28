from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from moomail_finance_ai.config import OpenDConfig, load_opend_config
from moomail_finance_ai.mcp.registry import (
    MCPResourceSpec,
    MCPToolSpec,
    RegisteredMCPModule,
    object_schema,
)
from moomail_finance_ai.opend import MoomooOpenDClient, ReadOnlyOpenDClient, RecordedOpenDClient
from moomail_finance_ai.opend_portfolio import build_portfolio_snapshot_from_report


SERVER_NAME = "moomail-opend-mcp"
SERVER_VERSION = "0.1.0"


def build_opend_mcp_module(
    *,
    client: ReadOnlyOpenDClient | None = None,
    config: OpenDConfig | None = None,
    env_file: str | Path | None = None,
    from_report: str | Path | None = None,
) -> RegisteredMCPModule:
    config = config or load_opend_config(env_file=env_file)
    client = client or _default_client(config, from_report=from_report)
    module = RegisteredMCPModule(server_name=SERVER_NAME, version=SERVER_VERSION)

    module.add_tool(
        MCPToolSpec(
            name="opend_check_connection",
            description="Check whether the local OpenD gateway is reachable.",
            input_schema=object_schema(),
        ),
        lambda _arguments: client.check_connection(),
    )
    module.add_tool(
        MCPToolSpec(
            name="opend_get_account_list",
            description="Read the selected OpenD account list metadata.",
            input_schema=object_schema(),
        ),
        lambda _arguments: client.get_account_list(),
    )
    module.add_tool(
        MCPToolSpec(
            name="opend_get_account_funds",
            description="Read account funds and total assets from OpenD.",
            input_schema=object_schema(),
        ),
        lambda _arguments: client.get_account_funds(),
    )
    module.add_tool(
        MCPToolSpec(
            name="opend_get_positions",
            description="Read current positions from OpenD.",
            input_schema=object_schema(),
        ),
        lambda _arguments: client.get_positions(),
    )
    module.add_tool(
        MCPToolSpec(
            name="opend_get_market_snapshots",
            description="Read current quote snapshots for OpenD security codes.",
            input_schema=object_schema(
                {
                    "codes": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "OpenD security codes such as US.AAPL.",
                    }
                },
                required=["codes"],
            ),
        ),
        lambda arguments: client.get_market_snapshots(_string_list(arguments, "codes")),
    )
    module.add_tool(
        MCPToolSpec(
            name="opend_explore_fields",
            description="Read account, funds, positions, and available quote fields from OpenD.",
            input_schema=object_schema(),
        ),
        lambda _arguments: client.explore_fields(),
    )
    module.add_tool(
        MCPToolSpec(
            name="opend_get_normalized_portfolio_snapshot",
            description="Build a normalized PortfolioSnapshot from the current OpenD field report.",
            input_schema=object_schema(
                {
                    "portfolio_id": {
                        "type": "string",
                        "default": "portfolio_default",
                    },
                    "base_currency": {
                        "type": "string",
                        "default": config.base_currency,
                    },
                }
            ),
        ),
        lambda arguments: build_portfolio_snapshot_from_report(
            client.explore_fields(),
            portfolio_id=str(arguments.get("portfolio_id") or "portfolio_default"),
            base_currency=str(arguments.get("base_currency") or config.base_currency),
        ),
    )
    module.add_tool(
        MCPToolSpec(
            name="opend_get_portfolio_context",
            description=(
                "Build a normalized PortfolioSnapshot and return the OpenD source report from "
                "the same read cycle."
            ),
            input_schema=object_schema(
                {
                    "portfolio_id": {
                        "type": "string",
                        "default": "portfolio_default",
                    },
                    "base_currency": {
                        "type": "string",
                        "default": config.base_currency,
                    },
                }
            ),
        ),
        lambda arguments: _portfolio_context(client, arguments, config),
    )
    module.add_resource(
        MCPResourceSpec(
            uri="opend://capabilities/read-only",
            name="OpenD Read-Only Capabilities",
            description="Allowed OpenD capabilities exposed by this MCP server.",
        ),
        _read_only_capabilities,
    )
    module.add_resource(
        MCPResourceSpec(
            uri="opend://config/summary",
            name="OpenD Config Summary",
            description="Sanitized OpenD connection settings.",
        ),
        lambda: _config_summary(config, from_report=from_report),
    )
    return module


def _default_client(
    config: OpenDConfig,
    *,
    from_report: str | Path | None = None,
) -> ReadOnlyOpenDClient:
    recording_path = from_report or os.environ.get("MOOMAIL_OPEND_RECORDING_PATH")
    if recording_path and Path(recording_path).expanduser().exists():
        return RecordedOpenDClient.from_path(recording_path)
    return MoomooOpenDClient(config)


def _read_only_capabilities() -> dict[str, Any]:
    return {
        "server": SERVER_NAME,
        "read_only": True,
        "tools": [
            "connection check",
            "account list read",
            "account funds read",
            "positions read",
            "market snapshot read",
            "normalized portfolio snapshot read",
            "normalized portfolio context read",
        ],
        "forbidden": [
            "trade unlock",
            "place order",
            "modify order",
            "cancel order",
            "withdrawal or transfer",
        ],
    }


def _portfolio_context(
    client: ReadOnlyOpenDClient,
    arguments: dict[str, Any],
    config: OpenDConfig,
) -> dict[str, Any]:
    report = client.explore_fields()
    snapshot = build_portfolio_snapshot_from_report(
        report,
        portfolio_id=str(arguments.get("portfolio_id") or "portfolio_default"),
        base_currency=str(arguments.get("base_currency") or config.base_currency),
    )
    return {"source_report": report, "snapshot": snapshot}


def _config_summary(
    config: OpenDConfig,
    *,
    from_report: str | Path | None,
) -> dict[str, Any]:
    return {
        "host": config.host,
        "port": config.port,
        "connection_timeout_seconds": config.connection_timeout_seconds,
        "security_firm": config.security_firm,
        "trade_market": config.trade_market,
        "trade_env": config.trade_env,
        "base_currency": config.base_currency,
        "account_id_configured": config.account_id is not None,
        "account_index": config.account_index,
        "rsa_private_key_configured": config.rsa_private_key_path is not None,
        "recording_path_configured": from_report is not None
        or os.environ.get("MOOMAIL_OPEND_RECORDING_PATH") is not None,
    }


def _string_list(arguments: dict[str, Any], key: str) -> list[str]:
    value = arguments.get(key)
    if not isinstance(value, list):
        raise ValueError(f"{key} must be a list of strings.")
    return [str(item) for item in value]
