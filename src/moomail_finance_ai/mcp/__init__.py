"""Local MCP adapters for the personal finance agent stack."""

from moomail_finance_ai.mcp.gateway import (
    DEFAULT_GATEWAY_PERMISSION_PROFILES,
    DirectToolGateway,
    GatewayManager,
    GatewayPermissionProfile,
    MCPGatewayError,
    MCPGatewayResult,
    MCPPermissionError,
    MCPServerConfig,
    MCPServerUnavailableError,
    MCPToolExecutionError,
    MCPToolGateway,
    StdioMCPToolGateway,
    local_stdio_server_configs,
)
from moomail_finance_ai.mcp.registry import (
    AgentMCPManifest,
    MCPResourceSpec,
    MCPToolCallResult,
    MCPToolSpec,
    RegisteredMCPModule,
)

__all__ = [
    "AgentMCPManifest",
    "DEFAULT_GATEWAY_PERMISSION_PROFILES",
    "DirectToolGateway",
    "GatewayManager",
    "GatewayPermissionProfile",
    "MCPGatewayError",
    "MCPGatewayResult",
    "MCPPermissionError",
    "MCPResourceSpec",
    "MCPServerConfig",
    "MCPServerUnavailableError",
    "MCPToolExecutionError",
    "MCPToolGateway",
    "MCPToolCallResult",
    "MCPToolSpec",
    "RegisteredMCPModule",
    "StdioMCPToolGateway",
    "local_stdio_server_configs",
]
