from __future__ import annotations

from typing import Any, Protocol

from pydantic import Field

from moomail_finance_ai.mcp.registry import MCPResourceSpec, MCPToolSpec
from moomail_finance_ai.schemas import StrictModel


class MCPGatewayResult(StrictModel):
    server_name: str
    tool_name: str
    structured_content: Any = None
    content: list[dict[str, Any]] = Field(default_factory=list)
    is_error: bool = False
    duration_ms: float | None = None
    error_type: str | None = None
    error_message: str | None = None


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
