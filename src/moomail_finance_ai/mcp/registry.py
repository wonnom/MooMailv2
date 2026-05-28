from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Protocol

from pydantic import BaseModel, Field

from moomail_finance_ai.schemas import StrictModel


ToolHandler = Callable[[dict[str, Any]], Any]
ResourceHandler = Callable[[], Any]


class MCPToolSpec(StrictModel):
    name: str
    description: str
    input_schema: dict[str, Any] = Field(default_factory=dict)
    read_only: bool = True

    def to_mcp_tool(self) -> dict[str, Any]:
        annotations: dict[str, Any] = {"readOnlyHint": self.read_only}
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.input_schema or {"type": "object", "properties": {}},
            "annotations": annotations,
        }


class MCPResourceSpec(StrictModel):
    uri: str
    name: str
    description: str
    mime_type: str = "application/json"

    def to_mcp_resource(self) -> dict[str, Any]:
        return {
            "uri": self.uri,
            "name": self.name,
            "description": self.description,
            "mimeType": self.mime_type,
        }


class MCPToolCallResult(StrictModel):
    content: list[dict[str, Any]]
    structured_content: Any = None
    is_error: bool = False

    def to_mcp_result(self) -> dict[str, Any]:
        payload = {"content": self.content, "isError": self.is_error}
        if self.structured_content is not None:
            payload["structuredContent"] = self.structured_content
        return payload


class AgentMCPManifest(StrictModel):
    agent_name: str
    allowed_servers: list[str]
    allowed_tools: list[str]
    allowed_resources: list[str]


class MCPModule(Protocol):
    server_name: str
    version: str

    def list_tools(self) -> list[MCPToolSpec]: ...

    def call_tool(self, name: str, arguments: dict[str, Any]) -> MCPToolCallResult: ...

    def list_resources(self) -> list[MCPResourceSpec]: ...

    def read_resource(self, uri: str) -> dict[str, Any]: ...


@dataclass(frozen=True)
class ToolRegistration:
    spec: MCPToolSpec
    handler: ToolHandler


@dataclass(frozen=True)
class ResourceRegistration:
    spec: MCPResourceSpec
    handler: ResourceHandler


class RegisteredMCPModule:
    """Small testable MCP module abstraction.

    The official MCP SDK handles transport and protocol details. This class keeps our
    business tools registered in one place so tests, local stdio, and future SDK adapters
    all expose the same surface.
    """

    def __init__(self, *, server_name: str, version: str):
        self.server_name = server_name
        self.version = version
        self._tools: dict[str, ToolRegistration] = {}
        self._resources: dict[str, ResourceRegistration] = {}

    def add_tool(self, spec: MCPToolSpec, handler: ToolHandler) -> None:
        if spec.name in self._tools:
            raise ValueError(f"Duplicate MCP tool registered: {spec.name}")
        self._tools[spec.name] = ToolRegistration(spec=spec, handler=handler)

    def add_resource(self, spec: MCPResourceSpec, handler: ResourceHandler) -> None:
        if spec.uri in self._resources:
            raise ValueError(f"Duplicate MCP resource registered: {spec.uri}")
        self._resources[spec.uri] = ResourceRegistration(spec=spec, handler=handler)

    def list_tools(self) -> list[MCPToolSpec]:
        return [registration.spec for registration in self._tools.values()]

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> MCPToolCallResult:
        registration = self._tools.get(name)
        if registration is None:
            raise ValueError(f"Unknown tool for {self.server_name}: {name}")
        payload = registration.handler(arguments or {})
        if isinstance(payload, MCPToolCallResult):
            return payload
        return structured_result(payload)

    def list_resources(self) -> list[MCPResourceSpec]:
        return [registration.spec for registration in self._resources.values()]

    def read_resource(self, uri: str) -> dict[str, Any]:
        registration = self._resources.get(uri)
        if registration is None:
            raise ValueError(f"Unknown resource for {self.server_name}: {uri}")
        payload = to_jsonable(registration.handler())
        return {
            "contents": [
                {
                    "uri": registration.spec.uri,
                    "mimeType": registration.spec.mime_type,
                    "text": _resource_text(payload, registration.spec.mime_type),
                }
            ]
        }


def structured_result(payload: Any) -> MCPToolCallResult:
    jsonable_payload = to_jsonable(payload)
    return MCPToolCallResult(
        content=[{"type": "text", "text": json.dumps(jsonable_payload, sort_keys=True)}],
        structured_content=jsonable_payload,
    )


def object_schema(
    properties: Mapping[str, Any] | None = None,
    *,
    required: list[str] | None = None,
    additional_properties: bool = False,
) -> dict[str, Any]:
    schema = {
        "type": "object",
        "properties": dict(properties or {}),
        "additionalProperties": additional_properties,
    }
    if required:
        schema["required"] = required
    return schema


def to_jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, Mapping):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple | set):
        return [to_jsonable(item) for item in value]
    if isinstance(value, datetime | date):
        return value.isoformat()
    return value


def _resource_text(payload: Any, mime_type: str) -> str:
    if mime_type == "application/json":
        return json.dumps(payload, sort_keys=True)
    return str(payload)
