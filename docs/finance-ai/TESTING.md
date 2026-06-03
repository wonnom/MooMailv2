# Testing Map

The test suite is intentionally layered. Files with similar names are usually
testing different responsibilities rather than duplicating each other.

## MCP Tests

| File | Scope | Real OpenD? | Real SQL? | Keep because |
| --- | --- | --- | --- | --- |
| `tests/test_mcp_tool_contracts.py` | Individual MCP tool contracts for OpenD, portfolio SQL, and metrics | No | No | Proves each tool's structured inputs/outputs without live services |
| `tests/test_mcp_stdio_round_trips.py` | Starts each local MCP server script and calls it over stdio JSON-RPC | No | No | Proves process-level MCP server wiring works |
| `tests/test_mcp_servers.py` | Registry behavior, resources, manifests, and basic module smoke tests | No | No | Proves agent allowlists and common MCP module mechanics |
| `tests/live/test_connector_targets.py` | Opt-in live connector smoke tests | Yes, for OpenD tests | Temp SQLite only | Proves the real machine/API/gateway path works |
| `tests/live/test_portfolio_agent_live.py` | Opt-in live Portfolio Agent LLM evaluation over recorded OpenD data and MCP modules, currently using Gemini | No | Temp SQLite only | Proves the agent-level LLM boundary works without requiring live OpenD |

## OpenD Tests

| File | Scope | Covered by MCP tests? | Keep because |
| --- | --- | --- | --- |
| `tests/test_opend_config.py` | Env parsing and `OpenDConfig` defaults | No | Bad config loading would break live OpenD before MCP gets involved |
| `tests/test_opend_adapter.py` | Low-level `MoomooOpenDClient` and `RecordedOpenDClient` behavior | Partially | Covers missing SDK handling, batch quote fallback, read-only method surface, and recorded report behavior |
| `tests/test_opend_health.py` | One-command OpenD health report and CLI recorded mode | Partially | Proves the V1 live gate can surface pass/warn/fail, expected holding mismatches, OTC quote gaps, and fund-assets cash sweep without requiring live OpenD |
| `tests/test_opend_portfolio.py` | Normalizing OpenD field reports into portfolio snapshots and packets | Partially | Covers portfolio accounting edge cases such as options, missing funds, cash-equivalent funds, opt-in fund-assets effective-cash handling, negative cash, and v1 US-equity scoping |
| `tests/test_mcp_tool_contracts.py` | MCP wrapper around OpenD tools | Yes | Verifies the wrapper exposes the adapter safely and returns JSON-compatible results |

The MCP tests do not replace adapter or normalization tests. They prove that the
MCP boundary calls those layers correctly.

## SQL Tests

| File | Scope | Covered by MCP tests? | Keep because |
| --- | --- | --- | --- |
| `tests/test_sql_store.py` | Lean SQLite schema, value snapshots, position states, allocation weights, data-quality events, audit links, stale-history detection | Partially | Protects the storage implementation and audit table shape |
| `tests/test_mcp_tool_contracts.py` | MCP wrapper around SQL storage tools | Yes | Verifies tool names, arguments, resources, and JSON-compatible return payloads |

The portfolio SQL MCP server currently uses local SQLite. It does not connect to
the future proprietary SQL backend yet. Add a separate opt-in live SQL connector
test when that backend exists.

## Other Test Areas

| File | Scope |
| --- | --- |
| `tests/test_metrics.py` | Deterministic finance calculations underneath `moomail-finance-metrics-mcp`, including effective cash weight |
| `tests/test_llm.py` | Provider-neutral LLM config/client selection for Gemini and OpenAI |
| `tests/test_research.py` | Local research store and Sentiment Agent contracts |
| `tests/test_portfolio_agent.py` | MCP-backed Portfolio Agent pipeline, daily SQL idempotency, and LLM evaluator JSON parsing/recovery |
| `tests/test_full_agent.py` | Full local Investment Agent flow, guardrails, audit, and memory summary writes |
| `tests/test_chat_app.py` | Local HTTP/chat API and static frontend expectations |
| `tests/test_prototype.py` | Milestone 1 static Investment Agent prototype contracts |

## When To Delete A Test

Delete or merge a test only when both are true:

- Another test covers the same layer and the same failure mode.
- The underlying implementation path is no longer used.

For example, if the OpenD adapter were removed and all access went through an
official SDK-backed MCP client with no local adapter underneath, then
`tests/test_opend_adapter.py` would be a candidate for removal. That is not the
current architecture.
