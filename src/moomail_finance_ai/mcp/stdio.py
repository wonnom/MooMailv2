from __future__ import annotations

import json
import sys
from typing import Any, BinaryIO

from moomail_finance_ai.mcp.registry import MCPModule


PROTOCOL_VERSION = "2025-06-18"


class JsonRpcMCPServer:
    """Minimal local MCP stdio server for this project.

    It implements the subset the agents and smoke tests need: initialize,
    tools/list, tools/call, resources/list, and resources/read. The tool registry
    underneath stays independent from this transport.
    """

    def __init__(self, module: MCPModule):
        self.module = module

    def handle_request(self, request: dict[str, Any]) -> dict[str, Any] | None:
        if "id" not in request:
            return None
        try:
            result = self._result_for(request)
        except Exception as exc:
            return self._error(request, -32000, str(exc))
        return {"jsonrpc": "2.0", "id": request["id"], "result": result}

    def _result_for(self, request: dict[str, Any]) -> dict[str, Any]:
        method = request.get("method")
        params = request.get("params") or {}
        if method == "initialize":
            return {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {
                    "tools": {"listChanged": False},
                    "resources": {"subscribe": False, "listChanged": False},
                },
                "serverInfo": {
                    "name": self.module.server_name,
                    "version": self.module.version,
                },
            }
        if method == "tools/list":
            return {"tools": [tool.to_mcp_tool() for tool in self.module.list_tools()]}
        if method == "tools/call":
            result = self.module.call_tool(
                str(params.get("name")),
                dict(params.get("arguments") or {}),
            )
            return result.to_mcp_result()
        if method == "resources/list":
            return {
                "resources": [
                    resource.to_mcp_resource() for resource in self.module.list_resources()
                ]
            }
        if method == "resources/read":
            return self.module.read_resource(str(params.get("uri")))
        raise ValueError(f"Unknown method: {method}")

    def _error(self, request: dict[str, Any], code: int, message: str) -> dict[str, Any]:
        return {
            "jsonrpc": "2.0",
            "id": request.get("id"),
            "error": {"code": code, "message": message},
        }

    def serve_forever(
        self,
        *,
        input_stream: BinaryIO | None = None,
        output_stream: BinaryIO | None = None,
    ) -> None:
        input_stream = input_stream or sys.stdin.buffer
        output_stream = output_stream or sys.stdout.buffer
        while True:
            request = read_message(input_stream)
            if request is None:
                return
            response = self.handle_request(request)
            if response is not None:
                write_message(output_stream, response)


def read_message(input_stream: BinaryIO) -> dict[str, Any] | None:
    headers: dict[str, str] = {}
    while True:
        line = input_stream.readline()
        if not line:
            return None
        if line in {b"\r\n", b"\n"}:
            break
        key, value = line.decode("ascii").split(":", 1)
        headers[key.lower()] = value.strip()

    content_length = int(headers["content-length"])
    raw = input_stream.read(content_length)
    return json.loads(raw.decode("utf-8"))


def write_message(output_stream: BinaryIO, payload: dict[str, Any]) -> None:
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    output_stream.write(f"Content-Length: {len(body)}\r\n\r\n".encode("ascii"))
    output_stream.write(body)
    output_stream.flush()
