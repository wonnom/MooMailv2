from __future__ import annotations

from collections.abc import Iterable

from moomail_finance_ai.mcp.finance_metrics_mcp import SERVER_NAME as FINANCE_METRICS_SERVER
from moomail_finance_ai.mcp.opend_mcp import SERVER_NAME as OPEND_SERVER
from moomail_finance_ai.mcp.portfolio_sql_mcp import SERVER_NAME as PORTFOLIO_SQL_SERVER
from moomail_finance_ai.mcp.registry import AgentMCPManifest, MCPModule, MCPToolSpec


DEFAULT_AGENT_SERVER_ALLOWLIST: dict[str, tuple[str, ...]] = {
    "portfolio_agent": (
        OPEND_SERVER,
        PORTFOLIO_SQL_SERVER,
        FINANCE_METRICS_SERVER,
    ),
    "sentiment_agent": (
        FINANCE_METRICS_SERVER,
    ),
    "investment_agent": (
        PORTFOLIO_SQL_SERVER,
        FINANCE_METRICS_SERVER,
    ),
}


def build_agent_manifest(
    agent_name: str,
    modules: Iterable[MCPModule],
    *,
    allowlist: dict[str, tuple[str, ...]] | None = None,
) -> AgentMCPManifest:
    allowlist = allowlist or DEFAULT_AGENT_SERVER_ALLOWLIST
    allowed_servers = list(allowlist.get(agent_name, ()))
    allowed_server_set = set(allowed_servers)
    allowed_tools: list[str] = []
    allowed_resources: list[str] = []

    for module in modules:
        if module.server_name not in allowed_server_set:
            continue
        allowed_tools.extend(_qualified_tool_name(module.server_name, tool) for tool in module.list_tools())
        allowed_resources.extend(resource.uri for resource in module.list_resources())

    return AgentMCPManifest(
        agent_name=agent_name,
        allowed_servers=allowed_servers,
        allowed_tools=allowed_tools,
        allowed_resources=allowed_resources,
    )


def tools_for_agent(
    agent_name: str,
    modules: Iterable[MCPModule],
    *,
    allowlist: dict[str, tuple[str, ...]] | None = None,
) -> dict[str, MCPToolSpec]:
    allowlist = allowlist or DEFAULT_AGENT_SERVER_ALLOWLIST
    allowed_server_set = set(allowlist.get(agent_name, ()))
    tools: dict[str, MCPToolSpec] = {}
    for module in modules:
        if module.server_name not in allowed_server_set:
            continue
        for tool in module.list_tools():
            tools[_qualified_tool_name(module.server_name, tool)] = tool
    return tools


def _qualified_tool_name(server_name: str, tool: MCPToolSpec) -> str:
    return f"{server_name}:{tool.name}"
