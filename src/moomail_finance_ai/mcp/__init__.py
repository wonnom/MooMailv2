"""Local MCP adapters for the personal finance agent stack."""

from moomail_finance_ai.mcp.gateway import (
    MCPGatewayError,
    MCPGatewayResult,
    MCPPermissionError,
    MCPServerUnavailableError,
    MCPToolExecutionError,
    MCPToolGateway,
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
    "MCPGatewayError",
    "MCPGatewayResult",
    "MCPPermissionError",
    "MCPResourceSpec",
    "MCPServerUnavailableError",
    "MCPToolExecutionError",
    "MCPToolGateway",
    "MCPToolCallResult",
    "MCPToolSpec",
    "RegisteredMCPModule",
]
