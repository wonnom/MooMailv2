# Live Connector Tests

The live connector tests verify real round trips to the connector targets from the next iteration plan.

Normal test runs do not call external services. The live tests are skipped unless explicitly enabled:

```bash
MOOMAIL_RUN_LIVE_CONNECTOR_TESTS=1 .venv/bin/python -m pytest tests/live -q
```

Run one connector at a time while setting up credentials:

```bash
MOOMAIL_RUN_LIVE_CONNECTOR_TESTS=1 .venv/bin/python -m pytest tests/live/test_connector_targets.py -q -k llm
MOOMAIL_RUN_LIVE_CONNECTOR_TESTS=1 .venv/bin/python -m pytest tests/live/test_connector_targets.py -q -k mcp
MOOMAIL_RUN_LIVE_CONNECTOR_TESTS=1 .venv/bin/python -m pytest tests/live/test_connector_targets.py -q -k opend
MOOMAIL_RUN_LIVE_CONNECTOR_TESTS=1 .venv/bin/python -m pytest tests/live/test_connector_targets.py -q -k sqlite
MOOMAIL_RUN_LIVE_CONNECTOR_TESTS=1 .venv/bin/python -m pytest tests/live/test_connector_targets.py -q -k pinecone
MOOMAIL_RUN_LIVE_CONNECTOR_TESTS=1 .venv/bin/python -m pytest tests/live/test_connector_targets.py -q -k neo4j
MOOMAIL_RUN_LIVE_CONNECTOR_TESTS=1 .venv/bin/python -m pytest tests/live/test_portfolio_agent_live.py -q
```

## What Is Covered

| Target | Test | Requires external service | What it verifies |
| --- | --- | --- | --- |
| OpenAI LLM | `test_live_llm_openai_responses_api_round_trip` | Yes | Calls OpenAI Responses API and validates that text output can be extracted |
| Gemini LLM | `test_live_llm_gemini_generate_content_round_trip` | Yes | Calls Gemini `generateContent` API and validates that text output can be extracted |
| MCP metrics | `test_live_mcp_finance_metrics_server_round_trip` | No | Starts local stdio MCP metrics server, lists tools, calls one tool |
| MCP OpenD | `test_live_mcp_opend_server_round_trip_with_local_gateway` | Yes, local OpenD | Starts local stdio MCP OpenD server and reads live OpenD account/funds/positions through the MCP boundary |
| OpenD adapter | `test_live_opend_read_only_connection_and_field_report` | Yes, local OpenD | Connects to OpenD and reads account/funds/positions through read-only adapter |
| SQL | `test_live_sqlite_connector_snapshot_metric_and_audit_round_trip` | No | Writes portfolio snapshot and metric into SQLite |
| Pinecone control plane | `test_live_pinecone_control_plane_connection` | Yes | Lists Pinecone indexes |
| Pinecone vector retrieval | `test_live_pinecone_vector_upsert_query_delete_round_trip` | Yes | Upserts, queries, and deletes a non-sensitive test vector |
| Neo4j graph | `test_live_neo4j_query_api_graph_round_trip` | Yes | Writes, reads, and deletes a tiny synthetic graph node through Neo4j Query API |
| Portfolio Agent LLM path | `test_live_portfolio_agent_llm_evaluator_round_trip_with_gemini` | Yes, Gemini only for this live test | Runs recorded OpenD data through the three MCP modules, then calls the LLM evaluator for structured portfolio-only evaluation |

## Local Env File

Secrets and connector config should live in:

```text
config/local.env
```

Create it from:

```bash
cp config/example.env config/local.env
```

The tests automatically read `config/local.env`. Exported shell variables still override local file values when both are present.

## Required Variables

All live tests:

```bash
export MOOMAIL_RUN_LIVE_CONNECTOR_TESTS=1
```

### OpenAI LLM

The OpenAI test targets the Responses API.

```env
MOOMAIL_OPENAI_API_KEY=...
MOOMAIL_OPENAI_MODEL=...
```

Optional:

```env
MOOMAIL_OPENAI_BASE_URL=https://api.openai.com/v1
```

`OPENAI_API_KEY` is also accepted. Legacy `MOOMAIL_LLM_API_KEY`, `MOOMAIL_LLM_MODEL`, and `MOOMAIL_LLM_BASE_URL` are still accepted for backward compatibility.

### Gemini LLM

The Gemini test targets the `generateContent` REST API.

```env
MOOMAIL_GEMINI_API_KEY=...
MOOMAIL_GEMINI_MODEL=...
```

Optional:

```env
MOOMAIL_GEMINI_BASE_URL=https://generativelanguage.googleapis.com/v1beta
```

`GEMINI_API_KEY` and `GOOGLE_API_KEY` are also accepted.

### MCP

No secrets are required for the finance metrics MCP smoke test. It launches:

```text
scripts/mcp_finance_metrics_server.py
```

It speaks a minimal stdio MCP-compatible JSON-RPC flow and exposes one tool:

```text
calculate_cash_weight
```

The OpenD MCP smoke test launches:

```text
scripts/mcp_opend_server.py
```

It uses the same OpenD env file as the direct OpenD adapter test and requires
OpenD to be open, logged in, and listening on the configured API port.

### OpenD

OpenD must be manually open and logged in.

Default env file:

```text
config/local.env
```

Override path if needed:

```bash
export MOOMAIL_OPEND_ENV_FILE="config/local.env"
```

The file should include:

```env
MOOMAIL_OPEND_HOST=127.0.0.1
MOOMAIL_OPEND_PORT=11111
MOOMAIL_MOOMOO_SECURITY_FIRM=FUTUSG
MOOMAIL_MOOMOO_TRADE_ENV=REAL
MOOMAIL_MOOMOO_TRADE_MARKET=US
```

### SQLite

No secrets are required. The test writes to a pytest temp directory.

### Pinecone

Control-plane listing:

```env
MOOMAIL_PINECONE_API_KEY=...
```

Vector upsert/query/delete:

```env
MOOMAIL_PINECONE_API_KEY=...
MOOMAIL_PINECONE_INDEX_HOST=...
```

Optional:

```env
MOOMAIL_PINECONE_NAMESPACE=moomail-connector-smoke
MOOMAIL_PINECONE_VECTOR_DIMENSION=8
```

The vector test uses a synthetic vector and deletes it at the end.

### Neo4j

The Neo4j test uses the Query API over HTTP(S).

```env
MOOMAIL_NEO4J_URI=http://localhost:7474
MOOMAIL_NEO4J_USERNAME=neo4j
MOOMAIL_NEO4J_PASSWORD=...
MOOMAIL_NEO4J_DATABASE=neo4j
```

The test writes and deletes one synthetic `ConnectorSmoke` node.

## Notes

- These are integration tests, not unit tests.
- LLM connector tests validate the API round trip and text extraction, not exact adherence to a prompt phrase.
- They intentionally fail if credentials are present but the service is unreachable or misconfigured.
- They should not be required for ordinary local development.
- They should not store portfolio values in Pinecone or Neo4j.
- Individual MCP tool contracts live in normal deterministic tests:
  `tests/test_mcp_tool_contracts.py`.
- Local stdio server process round trips live in `tests/test_mcp_stdio_round_trips.py`.
- Live connector tests stay focused on real service/API reachability and should not become exhaustive tool contract tests.
