from __future__ import annotations

import keyword
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult, ToolAnnotations

from moomail_finance_ai.mcp.registry import MCPModule, MCPToolSpec


def build_fastmcp_server(module: MCPModule) -> FastMCP:
    """Expose a registered MooMail MCP module through the official FastMCP runtime."""

    server = FastMCP(module.server_name, instructions=f"{module.server_name} {module.version}")
    for spec in module.list_tools():
        server.add_tool(
            _make_tool_function(module, spec),
            name=spec.name,
            description=spec.description,
            annotations=ToolAnnotations(readOnlyHint=spec.read_only),
            structured_output=False,
        )
        registered_tool = server._tool_manager.get_tool(spec.name)
        if registered_tool is not None:
            registered_tool.parameters = spec.input_schema or {
                "type": "object",
                "properties": {},
            }

    for resource in module.list_resources():
        server.resource(
            resource.uri,
            name=resource.name,
            description=resource.description,
            mime_type=resource.mime_type,
        )(_make_resource_function(module, resource.uri))

    return server


def _make_tool_function(module: MCPModule, spec: MCPToolSpec):
    properties = dict((spec.input_schema or {}).get("properties") or {})
    required = list((spec.input_schema or {}).get("required") or [])
    ordered_names = [name for name in required if name in properties]
    ordered_names.extend(name for name in properties if name not in ordered_names)

    for name in ordered_names:
        if not name.isidentifier() or keyword.iskeyword(name):
            raise ValueError(
                f"Cannot expose FastMCP tool {spec.name}: unsupported argument name {name!r}."
            )

    params = [
        f"{name}: Any" if name in required else f"{name}: Any = None"
        for name in ordered_names
    ]
    signature = ", ".join(params)
    assignments = "\n".join(
        f"    if {name} is not None:\n"
        f"        arguments[{name!r}] = {name}\n"
        for name in ordered_names
    )
    if not assignments:
        assignments = "    pass\n"

    function_name = f"_fastmcp_tool_{spec.name}"
    source = (
        f"def {function_name}({signature}) -> CallToolResult:\n"
        "    arguments = {}\n"
        f"{assignments}"
        "    result = module.call_tool(tool_name, arguments)\n"
        "    payload = result.to_mcp_result()\n"
        "    if not isinstance(payload.get('structuredContent'), dict):\n"
        "        payload.pop('structuredContent', None)\n"
        "    return CallToolResult.model_validate(payload)\n"
    )
    namespace = {
        "Any": Any,
        "CallToolResult": CallToolResult,
        "module": module,
        "tool_name": spec.name,
    }
    exec(source, namespace)
    return namespace[function_name]


def _make_resource_function(module: MCPModule, uri: str):
    def resource_reader() -> str:
        resource = module.read_resource(uri)
        contents = resource.get("contents") or []
        if not contents:
            return ""
        first = contents[0]
        return str(first.get("text") or first.get("blob") or "")

    resource_reader.__name__ = f"_fastmcp_resource_{uri.replace('://', '_').replace('/', '_')}"
    return resource_reader
