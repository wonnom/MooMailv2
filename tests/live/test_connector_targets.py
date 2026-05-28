from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from moomail_finance_ai.config import load_env_file, load_opend_config
from moomail_finance_ai.metrics import calculate_cash_weight
from moomail_finance_ai.mocks import mock_portfolio_packet
from moomail_finance_ai.opend import MoomooOpenDClient
from moomail_finance_ai.sql_store import PortfolioSqlStore


pytestmark = pytest.mark.live_connector


ROOT = Path(__file__).resolve().parents[2]
LOCAL_ENV_PATH = ROOT / "config/local.env"
LOCAL_ENV = load_env_file(LOCAL_ENV_PATH) if LOCAL_ENV_PATH.exists() else {}
CONNECTOR_OPT_IN = "MOOMAIL_RUN_LIVE_CONNECTOR_TESTS"


def test_live_llm_openai_responses_api_round_trip():
    _require_live_tests()
    api_key = _env("MOOMAIL_OPENAI_API_KEY") or _env("OPENAI_API_KEY") or _env("MOOMAIL_LLM_API_KEY")
    model = _env("MOOMAIL_OPENAI_MODEL") or _env("MOOMAIL_LLM_MODEL")
    if not api_key or not model:
        pytest.skip("Set MOOMAIL_OPENAI_API_KEY/OPENAI_API_KEY and MOOMAIL_OPENAI_MODEL.")

    base_url = (_env("MOOMAIL_OPENAI_BASE_URL") or _env("MOOMAIL_LLM_BASE_URL") or "https://api.openai.com/v1").rstrip("/")
    payload = {
        "model": model,
        "input": "Reply with a short confirmation that the connector works.",
        "max_output_tokens": 64,
    }
    response = _request_json(
        f"{base_url}/responses",
        method="POST",
        headers={"Authorization": f"Bearer {api_key}"},
        payload=payload,
        timeout=60,
    )
    text = _openai_response_text(response)

    assert response.get("id")
    _assert_llm_text_output("OpenAI Responses API", text)


def test_live_llm_gemini_generate_content_round_trip():
    _require_live_tests()
    api_key = _env("MOOMAIL_GEMINI_API_KEY") or _env("GEMINI_API_KEY") or _env("GOOGLE_API_KEY")
    model = _env("MOOMAIL_GEMINI_MODEL")
    if not api_key or not model:
        pytest.skip("Set MOOMAIL_GEMINI_API_KEY/GEMINI_API_KEY and MOOMAIL_GEMINI_MODEL.")

    base_url = (_env("MOOMAIL_GEMINI_BASE_URL") or "https://generativelanguage.googleapis.com/v1beta").rstrip("/")
    model_path = model if model.startswith("models/") else f"models/{model}"
    encoded_model_path = urllib.parse.quote(model_path, safe="/")
    payload = {
        "contents": [{"parts": [{"text": "Reply with a short confirmation that the connector works."}]}],
        "generationConfig": {"maxOutputTokens": 64, "temperature": 0},
    }
    response = _request_json(
        f"{base_url}/{encoded_model_path}:generateContent",
        method="POST",
        headers={"x-goog-api-key": api_key},
        payload=payload,
        timeout=60,
    )
    text = _gemini_response_text(response)

    assert response.get("candidates")
    _assert_llm_text_output("Gemini generateContent API", text)


def test_live_mcp_finance_metrics_server_round_trip():
    _require_live_tests()
    client = _MCPStdioClient([sys.executable, str(ROOT / "scripts/mcp_finance_metrics_server.py")])
    try:
        initialized = client.request("initialize", {"clientInfo": {"name": "pytest"}})
        tools = client.request("tools/list", {})
        result = client.request(
            "tools/call",
            {
                "name": "calculate_cash_weight",
                "arguments": {"total_value": 1000.0, "cash_value": 125.0},
            },
        )
    finally:
        client.close()

    assert initialized["serverInfo"]["name"] == "moomail-finance-metrics-mcp"
    assert tools["tools"][0]["name"] == "calculate_cash_weight"
    assert result["structuredContent"]["metric_name"] == "cash_weight"
    assert result["structuredContent"]["value"] == 0.125


def test_live_mcp_opend_server_round_trip_with_local_gateway():
    _require_live_tests()
    env_file = Path(_env("MOOMAIL_OPEND_ENV_FILE") or ROOT / "config/local.env")
    if not env_file.exists():
        pytest.skip(f"OpenD env file missing: {env_file}")

    client = _MCPStdioClient(
        [
            sys.executable,
            str(ROOT / "scripts/mcp_opend_server.py"),
            "--env-file",
            str(env_file),
        ]
    )
    try:
        initialized = client.request("initialize", {"clientInfo": {"name": "pytest"}})
        tools = client.request("tools/list", {})
        connection = client.request("tools/call", {"name": "opend_check_connection"})
        report = client.request("tools/call", {"name": "opend_explore_fields"})
    finally:
        client.close()

    table_names = {table["name"] for table in report["structuredContent"]["tables"]}
    assert initialized["serverInfo"]["name"] == "moomail-opend-mcp"
    assert "opend_get_positions" in {tool["name"] for tool in tools["tools"]}
    assert connection["structuredContent"]["ok"] is True, connection["structuredContent"]["message"]
    assert {"accounts", "funds", "positions"} <= table_names


def test_live_opend_read_only_connection_and_field_report():
    _require_live_tests()
    env_file = Path(_env("MOOMAIL_OPEND_ENV_FILE") or ROOT / "config/local.env")
    if not env_file.exists():
        pytest.skip(f"OpenD env file missing: {env_file}")

    config = load_opend_config(env_file=env_file)
    client = MoomooOpenDClient(config)
    report = client.explore_fields()
    table_names = {table.name for table in report.tables}

    assert report.connection.ok is True, report.connection.message
    assert {"accounts", "funds", "positions"} <= table_names
    assert not any("order" in name or "trade" in name for name in dir(client) if not name.startswith("_"))


def test_live_sqlite_connector_snapshot_metric_and_audit_round_trip(tmp_path):
    _require_live_tests()
    store = PortfolioSqlStore(tmp_path / "connector-smoke.sqlite")
    snapshot = mock_portfolio_packet().snapshot
    stored = store.store_snapshot(snapshot)
    metric_count = store.store_metrics(stored.snapshot_id, [calculate_cash_weight(snapshot)])
    status = store.history_status(snapshot.portfolio_id, min_snapshots_for_history=1)

    assert store.table_count("portfolio_snapshots") == 1
    assert store.table_count("position_snapshots") == len(snapshot.holdings)
    assert store.table_count("calculated_metrics") == metric_count == 1
    assert status.snapshot_count == 1


def test_live_pinecone_control_plane_connection():
    _require_live_tests()
    api_key = _env("MOOMAIL_PINECONE_API_KEY") or _env("PINECONE_API_KEY")
    if not api_key:
        pytest.skip("Set MOOMAIL_PINECONE_API_KEY or PINECONE_API_KEY.")

    response = _request_json(
        "https://api.pinecone.io/indexes",
        method="GET",
        headers={"Api-Key": api_key, "X-Pinecone-Api-Version": "2025-10"},
        timeout=30,
    )

    assert "indexes" in response
    assert isinstance(response["indexes"], list)


def test_live_pinecone_vector_upsert_query_delete_round_trip():
    _require_live_tests()
    api_key = _env("MOOMAIL_PINECONE_API_KEY") or _env("PINECONE_API_KEY")
    index_host = _env("MOOMAIL_PINECONE_INDEX_HOST") or _env("PINECONE_INDEX_HOST")
    if not api_key or not index_host:
        pytest.skip("Set MOOMAIL_PINECONE_API_KEY/PINECONE_API_KEY and MOOMAIL_PINECONE_INDEX_HOST.")

    namespace = _env("MOOMAIL_PINECONE_NAMESPACE") or "moomail-connector-smoke"
    dimension = int(_env("MOOMAIL_PINECONE_VECTOR_DIMENSION") or "8")
    vector_id = f"connector-smoke-{uuid4().hex}"
    vector = [0.125 for _ in range(dimension)]
    base_url = f"https://{index_host.rstrip('/')}"
    headers = {"Api-Key": api_key, "X-Pinecone-Api-Version": "2025-10"}

    try:
        upsert = _request_json(
            f"{base_url}/vectors/upsert",
            method="POST",
            headers=headers,
            payload={
                "namespace": namespace,
                "vectors": [
                    {
                        "id": vector_id,
                        "values": vector,
                        "metadata": {"connector_test": "moomail", "purpose": "smoke"},
                    }
                ],
            },
            timeout=60,
        )
        query = _request_json(
            f"{base_url}/query",
            method="POST",
            headers=headers,
            payload={
                "namespace": namespace,
                "vector": vector,
                "topK": 1,
                "includeValues": True,
                "includeMetadata": True,
            },
            timeout=60,
        )
    finally:
        _request_json(
            f"{base_url}/vectors/delete",
            method="POST",
            headers=headers,
            payload={"namespace": namespace, "ids": [vector_id]},
            timeout=60,
            allow_error=True,
        )

    assert upsert.get("upsertedCount") in {None, 1}
    assert query.get("matches")
    assert query["matches"][0]["id"] == vector_id


def test_live_neo4j_query_api_graph_round_trip():
    _require_live_tests()
    base_url = _env("MOOMAIL_NEO4J_URI") or _env("NEO4J_URI")
    username = _env("MOOMAIL_NEO4J_USERNAME") or _env("NEO4J_USERNAME")
    password = _env("MOOMAIL_NEO4J_PASSWORD") or _env("NEO4J_PASSWORD")
    database = _env("MOOMAIL_NEO4J_DATABASE") or _env("NEO4J_DATABASE") or "neo4j"
    if not base_url or not username or not password:
        pytest.skip("Set MOOMAIL_NEO4J_URI, MOOMAIL_NEO4J_USERNAME, and MOOMAIL_NEO4J_PASSWORD.")

    node_id = f"connector-smoke-{uuid4().hex}"
    auth = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
    headers = {"Authorization": f"Basic {auth}", "Accept": "application/json"}
    endpoint = f"{base_url.rstrip('/')}/db/{database}/query/v2"
    response = _request_json(
        endpoint,
        method="POST",
        headers=headers,
        payload={
            "statement": (
                "MERGE (c:ConnectorSmoke {id: $id}) "
                "SET c.kind = 'research_graph', c.updated_at = datetime() "
                "RETURN c.id AS id, c.kind AS kind"
            ),
            "parameters": {"id": node_id},
        },
        timeout=30,
    )

    values = response.get("data", {}).get("values", [])
    assert values
    assert values[0][0] == node_id
    assert values[0][1] == "research_graph"

    _request_json(
        endpoint,
        method="POST",
        headers=headers,
        payload={
            "statement": "MATCH (c:ConnectorSmoke {id: $id}) DELETE c",
            "parameters": {"id": node_id},
        },
        timeout=30,
        allow_error=True,
    )


def _require_live_tests() -> None:
    if _env(CONNECTOR_OPT_IN) not in {"1", "true", "TRUE", "yes", "YES"}:
        pytest.skip(f"Set {CONNECTOR_OPT_IN}=1 to run live connector tests.")


def _env(name: str) -> str | None:
    value = os.environ.get(name) or LOCAL_ENV.get(name)
    return value if value else None


def _request_json(
    url: str,
    *,
    method: str,
    headers: dict[str, str] | None = None,
    payload: dict[str, Any] | None = None,
    timeout: int,
    allow_error: bool = False,
) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request_headers = {"Content-Type": "application/json", **(headers or {})}
    request = urllib.request.Request(url, data=body, headers=request_headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        if allow_error:
            return {"error": str(exc), "body": exc.read().decode("utf-8", errors="replace")}
        raise AssertionError(
            f"{method} {url} failed with HTTP {exc.code}: "
            f"{exc.read().decode('utf-8', errors='replace')}"
        ) from exc
    if not raw:
        return {}
    return json.loads(raw.decode("utf-8"))


def _openai_response_text(response: dict[str, Any]) -> str:
    if isinstance(response.get("output_text"), str):
        return response["output_text"]
    parts: list[str] = []
    for item in response.get("output", []):
        for content in item.get("content", []):
            text = content.get("text")
            if isinstance(text, str):
                parts.append(text)
    return "\n".join(parts)


def _gemini_response_text(response: dict[str, Any]) -> str:
    parts: list[str] = []
    for candidate in response.get("candidates", []):
        content = candidate.get("content", {})
        for part in content.get("parts", []):
            text = part.get("text")
            if isinstance(text, str):
                parts.append(text)
    return "\n".join(parts)


def _assert_llm_text_output(provider: str, text: str) -> None:
    assert text.strip(), f"{provider} call succeeded, but no text output could be extracted."


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

    def request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        assert self.process.stdin is not None
        request_id = self._next_id
        self._next_id += 1
        payload = {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
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
                stderr = self.process.stderr.read().decode("utf-8", errors="replace") if self.process.stderr else ""
                raise TimeoutError(f"Timed out waiting for MCP response. stderr={stderr}")
            line = self.process.stdout.readline()
            if line in {b"\r\n", b"\n"}:
                break
            if not line:
                stderr = self.process.stderr.read().decode("utf-8", errors="replace") if self.process.stderr else ""
                raise EOFError(f"MCP server closed stdout. stderr={stderr}")
            key, value = line.decode("ascii").split(":", 1)
            headers[key.lower()] = value.strip()
        raw = self.process.stdout.read(int(headers["content-length"]))
        return json.loads(raw.decode("utf-8"))
