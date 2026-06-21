from __future__ import annotations

import asyncio
import queue
import sys
import tempfile
import threading
import time
from collections.abc import Iterable
from contextlib import AsyncExitStack
from concurrent.futures import Future
from pathlib import Path
from typing import Any, Protocol

import anyio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from pydantic import Field

from moomail_finance_ai.mcp.finance_metrics_mcp import SERVER_NAME as FINANCE_METRICS_SERVER
from moomail_finance_ai.mcp.opend_mcp import SERVER_NAME as OPEND_SERVER
from moomail_finance_ai.mcp.portfolio_sql_mcp import SERVER_NAME as PORTFOLIO_SQL_SERVER
from moomail_finance_ai.mcp.registry import MCPModule, MCPResourceSpec, MCPToolSpec
from moomail_finance_ai.schemas import StrictModel


ROOT = Path(__file__).resolve().parents[3]
GLOBAL_DENIED_TOOL_FRAGMENTS = (
    "place_order",
    "modify_order",
    "cancel_order",
    "trade_unlock",
    "unlock_trade",
    "withdraw",
    "transfer",
    "order",
)


class MCPGatewayResult(StrictModel):
    server_name: str
    tool_name: str
    structured_content: Any = None
    content: list[dict[str, Any]] = Field(default_factory=list)
    is_error: bool = False
    duration_ms: float | None = None
    error_type: str | None = None
    error_message: str | None = None


class MCPServerConfig(StrictModel):
    server_name: str
    command: str
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] | None = None
    cwd: str | None = None
    timeout_seconds: float = 15.0


class GatewayPermissionProfile(StrictModel):
    consumer: str
    allowed_tools: dict[str, list[str]] = Field(default_factory=dict)
    allowed_resources: dict[str, list[str]] = Field(default_factory=dict)


class MCPToolGateway(Protocol):
    def call_tool(
        self,
        server_name: str,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
        *,
        consumer: str,
    ) -> MCPGatewayResult: ...

    def list_tools(self, server_name: str, *, consumer: str) -> list[MCPToolSpec]: ...

    def read_resource(self, server_name: str, uri: str, *, consumer: str) -> dict[str, Any]: ...

    def list_resources(self, server_name: str, *, consumer: str) -> list[MCPResourceSpec]: ...


class MCPGatewayError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        server_name: str | None = None,
        tool_name: str | None = None,
        consumer: str | None = None,
    ):
        super().__init__(message)
        self.server_name = server_name
        self.tool_name = tool_name
        self.consumer = consumer


class MCPPermissionError(MCPGatewayError):
    pass


class MCPServerUnavailableError(MCPGatewayError):
    pass


class MCPToolExecutionError(MCPGatewayError):
    pass


DEFAULT_GATEWAY_PERMISSION_PROFILES: dict[str, GatewayPermissionProfile] = {
    "dashboard_refresh": GatewayPermissionProfile(
        consumer="dashboard_refresh",
        allowed_tools={
            OPEND_SERVER: [
                "opend_check_connection",
                "opend_get_portfolio_context",
                "opend_get_normalized_portfolio_snapshot",
            ],
            FINANCE_METRICS_SERVER: [
                "calculate_snapshot_metrics",
                "calculate_cash_weight",
                "calculate_position_weights",
                "calculate_asset_type_allocation",
                "calculate_single_position_concentration",
                "calculate_benchmark_reference",
                "list_metric_definitions",
            ],
            PORTFOLIO_SQL_SERVER: [
                "portfolio_sql_initialize",
                "portfolio_sql_upsert_portfolio",
                "portfolio_sql_upsert_broker_account",
                "portfolio_sql_upsert_assets",
                "portfolio_sql_upsert_position_states",
                "portfolio_sql_store_daily_value_snapshot",
                "portfolio_sql_store_weight_snapshots",
                "portfolio_sql_store_data_quality_events",
                "portfolio_sql_get_history_status",
                "portfolio_sql_get_latest_portfolio_state",
                "portfolio_sql_get_portfolio_growth",
                "portfolio_sql_get_allocation_history",
                "portfolio_sql_table_count",
            ],
        },
        allowed_resources={
            OPEND_SERVER: ["opend://capabilities/read-only", "opend://config/summary"],
            FINANCE_METRICS_SERVER: ["finance-metrics://definitions", "finance-metrics://version"],
            PORTFOLIO_SQL_SERVER: ["portfolio-sql://schema", "portfolio-sql://status"],
        },
    ),
    "portfolio_agent": GatewayPermissionProfile(
        consumer="portfolio_agent",
        allowed_tools={
            OPEND_SERVER: ["*"],
            FINANCE_METRICS_SERVER: ["*"],
            PORTFOLIO_SQL_SERVER: ["*"],
        },
        allowed_resources={
            OPEND_SERVER: ["*"],
            FINANCE_METRICS_SERVER: ["*"],
            PORTFOLIO_SQL_SERVER: ["*"],
        },
    ),
    "investment_agent": GatewayPermissionProfile(
        consumer="investment_agent",
        allowed_tools={
            FINANCE_METRICS_SERVER: ["*"],
            PORTFOLIO_SQL_SERVER: [
                "portfolio_sql_get_history_status",
                "portfolio_sql_get_latest_portfolio_state",
                "portfolio_sql_get_portfolio_growth",
                "portfolio_sql_get_allocation_history",
                "portfolio_sql_get_position_state_changes",
            ],
        },
        allowed_resources={
            FINANCE_METRICS_SERVER: ["*"],
            PORTFOLIO_SQL_SERVER: ["portfolio-sql://schema", "portfolio-sql://status"],
        },
    ),
    "sentiment_agent": GatewayPermissionProfile(
        consumer="sentiment_agent",
        allowed_tools={FINANCE_METRICS_SERVER: ["*"]},
        allowed_resources={FINANCE_METRICS_SERVER: ["*"]},
    ),
}


class DirectToolGateway:
    """Test/dev gateway over in-process modules. Not the production runtime boundary."""

    def __init__(
        self,
        modules: Iterable[MCPModule],
        *,
        permissions: dict[str, GatewayPermissionProfile] | None = None,
    ):
        self.modules = {module.server_name: module for module in modules}
        self.permissions = permissions or DEFAULT_GATEWAY_PERMISSION_PROFILES

    def call_tool(
        self,
        server_name: str,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
        *,
        consumer: str,
    ) -> MCPGatewayResult:
        started = time.perf_counter()
        self._authorize_tool(consumer, server_name, tool_name)
        module = self._module(server_name)
        try:
            result = module.call_tool(tool_name, arguments or {})
            return MCPGatewayResult(
                server_name=server_name,
                tool_name=tool_name,
                structured_content=result.structured_content,
                content=result.content,
                is_error=result.is_error,
                duration_ms=_duration_ms(started),
            )
        except Exception as exc:
            raise MCPToolExecutionError(
                _sanitize_error(exc),
                server_name=server_name,
                tool_name=tool_name,
                consumer=consumer,
            ) from exc

    def list_tools(self, server_name: str, *, consumer: str) -> list[MCPToolSpec]:
        self._authorize_server(consumer, server_name)
        return self._module(server_name).list_tools()

    def read_resource(self, server_name: str, uri: str, *, consumer: str) -> dict[str, Any]:
        self._authorize_resource(consumer, server_name, uri)
        return self._module(server_name).read_resource(uri)

    def list_resources(self, server_name: str, *, consumer: str) -> list[MCPResourceSpec]:
        self._authorize_server(consumer, server_name)
        return self._module(server_name).list_resources()

    def close(self) -> None:
        return None

    def _module(self, server_name: str) -> MCPModule:
        module = self.modules.get(server_name)
        if module is None:
            raise MCPServerUnavailableError(f"MCP server not configured: {server_name}")
        return module

    def _authorize_server(self, consumer: str, server_name: str) -> None:
        _authorize_server(self.permissions, consumer, server_name)

    def _authorize_tool(self, consumer: str, server_name: str, tool_name: str) -> None:
        _authorize_tool(self.permissions, consumer, server_name, tool_name)

    def _authorize_resource(self, consumer: str, server_name: str, uri: str) -> None:
        _authorize_resource(self.permissions, consumer, server_name, uri)


class StdioMCPToolGateway:
    def __init__(
        self,
        server_configs: Iterable[MCPServerConfig],
        *,
        permissions: dict[str, GatewayPermissionProfile] | None = None,
    ):
        self.server_configs = {config.server_name: config for config in server_configs}
        self.permissions = permissions or DEFAULT_GATEWAY_PERMISSION_PROFILES
        self._requests: queue.Queue[tuple[str, tuple[Any, ...], Future]] = queue.Queue()
        self._exit_stack: AsyncExitStack | None = None
        self._sessions: dict[str, ClientSession] = {}
        self._errlogs: list[Any] = []
        self.started_servers: set[str] = set()
        self.closed = False
        self._thread = threading.Thread(target=self._run_worker, daemon=True)
        self._thread.start()

    def call_tool(
        self,
        server_name: str,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
        *,
        consumer: str,
    ) -> MCPGatewayResult:
        started = time.perf_counter()
        _authorize_tool(self.permissions, consumer, server_name, tool_name)
        try:
            result = self._run("call_tool", server_name, tool_name, arguments or {})
            return MCPGatewayResult(
                server_name=server_name,
                tool_name=tool_name,
                structured_content=result.structuredContent,
                content=[_content_to_dict(item) for item in result.content],
                is_error=bool(result.isError),
                duration_ms=_duration_ms(started),
            )
        except MCPGatewayError:
            raise
        except Exception as exc:
            raise MCPToolExecutionError(
                _sanitize_error(exc),
                server_name=server_name,
                tool_name=tool_name,
                consumer=consumer,
            ) from exc

    def list_tools(self, server_name: str, *, consumer: str) -> list[MCPToolSpec]:
        _authorize_server(self.permissions, consumer, server_name)
        tools = self._run("list_tools", server_name)
        return [
            MCPToolSpec(
                name=tool.name,
                description=tool.description or "",
                input_schema=tool.inputSchema or {"type": "object", "properties": {}},
                read_only=bool(getattr(tool.annotations, "readOnlyHint", False))
                if tool.annotations
                else True,
            )
            for tool in tools.tools
        ]

    def read_resource(self, server_name: str, uri: str, *, consumer: str) -> dict[str, Any]:
        _authorize_resource(self.permissions, consumer, server_name, uri)
        resource = self._run("read_resource", server_name, uri)
        return {
            "contents": [_content_to_dict(item) for item in resource.contents],
        }

    def list_resources(self, server_name: str, *, consumer: str) -> list[MCPResourceSpec]:
        _authorize_server(self.permissions, consumer, server_name)
        resources = self._run("list_resources", server_name)
        return [
            MCPResourceSpec(
                uri=str(resource.uri),
                name=resource.name or str(resource.uri),
                description=resource.description or "",
                mime_type=resource.mimeType or "application/json",
            )
            for resource in resources.resources
        ]

    def close(self) -> None:
        if self.closed:
            return
        self._run("close")
        for errlog in self._errlogs:
            errlog.close()
        self.closed = True
        self._thread.join(timeout=5)

    def _run(self, operation: str, *args):
        if self.closed:
            raise MCPServerUnavailableError("MCP gateway is closed.")
        future: Future = Future()
        self._requests.put((operation, args, future))
        return future.result()

    def _run_worker(self) -> None:
        anyio.run(self._worker)

    async def _worker(self) -> None:
        self._exit_stack = AsyncExitStack()
        while True:
            operation, args, future = await anyio.to_thread.run_sync(self._requests.get)
            try:
                if operation == "call_tool":
                    result = await self._call_tool_async(*args)
                elif operation == "list_tools":
                    result = await self._list_tools_async(*args)
                elif operation == "read_resource":
                    result = await self._read_resource_async(*args)
                elif operation == "list_resources":
                    result = await self._list_resources_async(*args)
                elif operation == "close":
                    result = None
                    if self._exit_stack is not None:
                        await self._exit_stack.aclose()
                    future.set_result(result)
                    break
                else:
                    raise ValueError(f"Unknown gateway operation: {operation}")
                future.set_result(result)
            except Exception as exc:
                future.set_exception(exc)

    async def _session(self, server_name: str) -> ClientSession:
        if server_name in self._sessions:
            return self._sessions[server_name]
        config = self._config(server_name)
        if self._exit_stack is None:
            raise MCPServerUnavailableError("MCP gateway worker is not initialized.")
        errlog = tempfile.TemporaryFile(mode="w+")
        self._errlogs.append(errlog)
        params = StdioServerParameters(
            command=config.command,
            args=config.args,
            env=config.env,
            cwd=config.cwd,
        )
        read_stream, write_stream = await self._exit_stack.enter_async_context(
            stdio_client(params, errlog=errlog)
        )
        session = await self._exit_stack.enter_async_context(
            ClientSession(read_stream, write_stream)
        )
        await asyncio.wait_for(session.initialize(), timeout=config.timeout_seconds)
        self._sessions[server_name] = session
        self.started_servers.add(server_name)
        return session

    async def _call_tool_async(
        self,
        server_name: str,
        tool_name: str,
        arguments: dict[str, Any],
    ):
        config = self._config(server_name)
        session = await self._session(server_name)
        return await asyncio.wait_for(
            session.call_tool(tool_name, arguments),
            timeout=config.timeout_seconds,
        )

    async def _list_tools_async(self, server_name: str):
        config = self._config(server_name)
        session = await self._session(server_name)
        return await asyncio.wait_for(session.list_tools(), timeout=config.timeout_seconds)

    async def _read_resource_async(self, server_name: str, uri: str):
        config = self._config(server_name)
        session = await self._session(server_name)
        return await asyncio.wait_for(session.read_resource(uri), timeout=config.timeout_seconds)

    async def _list_resources_async(self, server_name: str):
        config = self._config(server_name)
        session = await self._session(server_name)
        return await asyncio.wait_for(session.list_resources(), timeout=config.timeout_seconds)

    def _config(self, server_name: str) -> MCPServerConfig:
        config = self.server_configs.get(server_name)
        if config is None:
            raise MCPServerUnavailableError(f"MCP server not configured: {server_name}")
        return config


class GatewayManager:
    def __init__(self, gateway: MCPToolGateway):
        self.gateway = gateway

    def close(self) -> None:
        close = getattr(self.gateway, "close", None)
        if callable(close):
            close()

    def __enter__(self) -> GatewayManager:
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()


def local_stdio_server_configs(
    *,
    env_file: str | Path | None = "config/local.env",
    from_report: str | Path | None = None,
    db_path: str | Path = "data/portfolio-history.sqlite",
    timeout_seconds: float = 20.0,
) -> list[MCPServerConfig]:
    opend_args = [str(ROOT / "scripts" / "mcp_opend_server.py")]
    if from_report is not None and Path(from_report).expanduser().exists():
        opend_args.extend(["--from-report", str(from_report)])
    elif env_file is not None:
        opend_args.extend(["--env-file", str(env_file)])
    return [
        MCPServerConfig(
            server_name=OPEND_SERVER,
            command=sys.executable,
            args=opend_args,
            cwd=str(ROOT),
            timeout_seconds=timeout_seconds,
        ),
        MCPServerConfig(
            server_name=PORTFOLIO_SQL_SERVER,
            command=sys.executable,
            args=[
                str(ROOT / "scripts" / "mcp_portfolio_sql_server.py"),
                "--db-path",
                str(db_path),
            ],
            cwd=str(ROOT),
            timeout_seconds=timeout_seconds,
        ),
        MCPServerConfig(
            server_name=FINANCE_METRICS_SERVER,
            command=sys.executable,
            args=[str(ROOT / "scripts" / "mcp_finance_metrics_server.py")],
            cwd=str(ROOT),
            timeout_seconds=timeout_seconds,
        ),
    ]


def _authorize_server(
    permissions: dict[str, GatewayPermissionProfile],
    consumer: str,
    server_name: str,
) -> None:
    profile = permissions.get(consumer)
    if profile is None:
        raise MCPPermissionError(
            f"Unknown MCP consumer: {consumer}",
            server_name=server_name,
            consumer=consumer,
        )
    if server_name not in profile.allowed_tools and server_name not in profile.allowed_resources:
        raise MCPPermissionError(
            f"Consumer {consumer} cannot access MCP server {server_name}",
            server_name=server_name,
            consumer=consumer,
        )


def _authorize_tool(
    permissions: dict[str, GatewayPermissionProfile],
    consumer: str,
    server_name: str,
    tool_name: str,
) -> None:
    if _is_globally_denied_tool(tool_name):
        raise MCPPermissionError(
            f"MCP tool is globally denied: {tool_name}",
            server_name=server_name,
            tool_name=tool_name,
            consumer=consumer,
        )
    profile = permissions.get(consumer)
    allowed = profile.allowed_tools.get(server_name, []) if profile else []
    if "*" in allowed or tool_name in allowed:
        return
    raise MCPPermissionError(
        f"Consumer {consumer} cannot call {server_name}:{tool_name}",
        server_name=server_name,
        tool_name=tool_name,
        consumer=consumer,
    )


def _authorize_resource(
    permissions: dict[str, GatewayPermissionProfile],
    consumer: str,
    server_name: str,
    uri: str,
) -> None:
    profile = permissions.get(consumer)
    allowed = profile.allowed_resources.get(server_name, []) if profile else []
    if "*" in allowed or uri in allowed:
        return
    raise MCPPermissionError(
        f"Consumer {consumer} cannot read {server_name}:{uri}",
        server_name=server_name,
        consumer=consumer,
    )


def _is_globally_denied_tool(tool_name: str) -> bool:
    lowered = tool_name.lower()
    return any(fragment in lowered for fragment in GLOBAL_DENIED_TOOL_FRAGMENTS)


def _content_to_dict(item: Any) -> dict[str, Any]:
    if hasattr(item, "model_dump"):
        return item.model_dump(mode="json")
    if isinstance(item, dict):
        return item
    return {"type": "text", "text": str(item)}


def _duration_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 3)


def _sanitize_error(exc: BaseException) -> str:
    message = str(exc) or exc.__class__.__name__
    return message.replace("\n", " ")[:800]
