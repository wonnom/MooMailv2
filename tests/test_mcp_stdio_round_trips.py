from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from moomail_finance_ai.mocks import mock_portfolio_packet


ROOT = Path(__file__).resolve().parents[1]


def test_finance_metrics_mcp_stdio_server_round_trip():
    client = _MCPStdioClient([sys.executable, str(ROOT / "scripts/mcp_finance_metrics_server.py")])
    try:
        initialized = client.request("initialize", {"clientInfo": {"name": "pytest"}})
        tools = client.request("tools/list", {})
        resources = client.request("resources/list", {})
        result = client.request(
            "tools/call",
            {
                "name": "calculate_cash_weight",
                "arguments": {"total_value": 1000.0, "cash_value": 125.0},
            },
        )
        version = client.request(
            "resources/read",
            {"uri": "finance-metrics://version"},
        )
    finally:
        client.close()

    assert initialized["serverInfo"]["name"] == "moomail-finance-metrics-mcp"
    assert "calculate_cash_weight" in {tool["name"] for tool in tools["tools"]}
    assert "finance-metrics://version" in {resource["uri"] for resource in resources["resources"]}
    assert result["structuredContent"]["value"] == 0.125
    assert "finance-metrics://version" in version["contents"][0]["uri"]


def test_portfolio_sql_mcp_stdio_server_round_trip(tmp_path):
    db_path = tmp_path / "portfolio.sqlite"
    client = _MCPStdioClient(
        [
            sys.executable,
            str(ROOT / "scripts/mcp_portfolio_sql_server.py"),
            "--db-path",
            str(db_path),
        ]
    )
    snapshot = mock_portfolio_packet().snapshot
    try:
        initialized = client.request("initialize", {"clientInfo": {"name": "pytest"}})
        init_result = client.request("tools/call", {"name": "portfolio_sql_initialize"})
        stored = client.request(
            "tools/call",
            {
                "name": "portfolio_sql_store_snapshot",
                "arguments": {"snapshot": snapshot.model_dump(mode="json")},
            },
        )
        count = client.request(
            "tools/call",
            {
                "name": "portfolio_sql_table_count",
                "arguments": {"table_name": "portfolio_snapshots"},
            },
        )
        status = client.request("resources/read", {"uri": "portfolio-sql://status"})
    finally:
        client.close()

    assert initialized["serverInfo"]["name"] == "moomail-portfolio-sql-mcp"
    assert init_result["structuredContent"]["initialized"] is True
    assert stored["structuredContent"]["portfolio_id"] == snapshot.portfolio_id
    assert count["structuredContent"]["count"] == 1
    assert "portfolio-sql://status" in status["contents"][0]["uri"]


def test_opend_mcp_stdio_server_round_trip_with_recorded_report(sample_opend_report_path):
    client = _MCPStdioClient(
        [
            sys.executable,
            str(ROOT / "scripts/mcp_opend_server.py"),
            "--from-report",
            str(sample_opend_report_path),
        ]
    )
    try:
        initialized = client.request("initialize", {"clientInfo": {"name": "pytest"}})
        tools = client.request("tools/list", {})
        connection = client.request("tools/call", {"name": "opend_check_connection"})
        snapshot = client.request(
            "tools/call",
            {
                "name": "opend_get_normalized_portfolio_snapshot",
                "arguments": {"portfolio_id": "portfolio_default"},
            },
        )
        capabilities = client.request("resources/read", {"uri": "opend://capabilities/read-only"})
    finally:
        client.close()

    assert initialized["serverInfo"]["name"] == "moomail-opend-mcp"
    assert "opend_get_positions" in {tool["name"] for tool in tools["tools"]}
    assert connection["structuredContent"]["ok"] is True
    assert snapshot["structuredContent"]["holdings"][0]["ticker"] == "AAPL"
    assert "place order" in capabilities["contents"][0]["text"]


class _MCPStdioClient:
    def __init__(self, command: list[str]):
        self.process = subprocess.Popen(
            command,
            cwd=ROOT,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self._next_id = 1

    def request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        assert self.process.stdin is not None
        request_id = self._next_id
        self._next_id += 1
        payload = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params or {},
        }
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.process.stdin.write(f"Content-Length: {len(body)}\r\n\r\n".encode("ascii") + body)
        self.process.stdin.flush()
        response = self._read_message()
        if "error" in response:
            raise AssertionError(response["error"])
        return response["result"]

    def close(self) -> None:
        if self.process.stdin:
            self.process.stdin.close()
        try:
            self.process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=2)

    def _read_message(self) -> dict[str, Any]:
        assert self.process.stdout is not None
        headers: dict[str, str] = {}
        deadline = time.monotonic() + 10
        while True:
            if time.monotonic() > deadline:
                stderr = _stderr(self.process)
                raise TimeoutError(f"Timed out waiting for MCP response. stderr={stderr}")
            line = self.process.stdout.readline()
            if line in {b"\r\n", b"\n"}:
                break
            if not line:
                stderr = _stderr(self.process)
                raise EOFError(f"MCP server closed stdout. stderr={stderr}")
            key, value = line.decode("ascii").split(":", 1)
            headers[key.lower()] = value.strip()
        raw = self.process.stdout.read(int(headers["content-length"]))
        return json.loads(raw.decode("utf-8"))


def _stderr(process: subprocess.Popen) -> str:
    if process.stderr is None:
        return ""
    return process.stderr.read().decode("utf-8", errors="replace")
