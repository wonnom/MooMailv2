# Testing Map

The test suite is intentionally layered. Files with similar names are usually
testing different responsibilities rather than duplicating each other.

## MCP Tests

| File | Scope | Real OpenD? | Real SQL? | Keep because |
| --- | --- | --- | --- | --- |
| `tests/test_mcp_tool_contracts.py` | Individual MCP tool contracts for OpenD, portfolio SQL, and metrics | No | No | Proves each tool's structured inputs/outputs without live services |
| `tests/test_mcp_stdio_round_trips.py` | Starts each local FastMCP server script and calls it through the official MCP stdio client | No | No | Proves process-level FastMCP server wiring works |
| `tests/test_mcp_fastmcp_parity.py` | Compares representative FastMCP stdio results with direct module results | No | Temp SQLite only | Proves V3.1 preserves V2 structured payload shapes during server migration |
| `tests/test_mcp_gateway_contract.py` | Gateway protocol/result/error contract | No | No | Defines the V3.2 gateway boundary |
| `tests/test_mcp_gateway.py` | DirectToolGateway permissions, structured results, resource permissions, and global trade/order denial | No | Temp SQLite only | Proves gateway allowlists and direct parity mode |
| `tests/test_mcp_stdio_gateway.py` | StdioMCPToolGateway calls FastMCP servers through the official MCP client and reuses sessions | No | Temp SQLite only | Proves production-ish local MCP runtime boundary |
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

V3 note: the three local MCP server scripts now use the official FastMCP runtime
over stdio. The deterministic dashboard lane uses `StdioMCPToolGateway` by
default. The current agents still use in-process modules until V3.4.

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
| `tests/test_v2_schemas.py` | V2 Pydantic contracts, fixtures, guardrail schema, and trace schema |
| `tests/test_v2_investment_agent.py` | Thin LangGraph Investment Agent routing, fake subagent call counts, missing-research synthesis, and status events |
| `tests/test_v2_portfolio_planner.py` | Deterministic Portfolio Agent task interpretation, context planning, history/persistence minimization, and tool trace entries |
| `tests/test_sentiment_agent_stub.py` | V2 Sentiment Agent stub validation, missing-research packets, no fake citations, and future success fixture shape |
| `tests/test_v2_guardrails.py` | Deterministic V2 no-trading, no exact share-count, unsupported research, IPS, and missing-sentiment guardrails |
| `tests/test_v2_trace.py` | V2 trace sanitizer, graph/tool/sentiment/guardrail trace, error trace, and terminal summary rendering |
| `tests/test_chat_app.py` | Local HTTP/chat API and static frontend expectations |
| `tests/test_portfolio_data_service.py` | Deterministic backend portfolio data lane: status, SQL-backed dashboard reads, OpenD refresh, metrics, SQL persistence, stale fallback, and API route delegation |
| `tests/test_prototype.py` | Milestone 1 static Investment Agent prototype contracts |

The current Investment Agent/prototype tests are historical contract coverage
from the V1 build. They remain useful until the V2 Investment Agent fully
replaces the older prototype/full-agent paths in CLI/chat/docs. Retirement plan:

- Keep `tests/test_prototype.py` while `src/moomail_finance_ai/agents.py` is
  still present as historical Milestone 1 coverage.
- Keep `tests/test_full_agent.py` while `src/moomail_finance_ai/full_agent.py`
  remains a supported local full-agent path.
- Delete or merge these only after the V2 Investment Agent owns equivalent
  memory/audit/sentiment behavior and the older entrypoints are removed.

## V2 Closeout Test Gate

V2 deterministic closeout uses:

```bash
.venv/bin/python -m pytest tests --ignore=tests/live -q
```

Latest V2 closeout result on 2026-06-15:

```text
156 passed, 1 warning
```

The warning is a LangGraph dependency deprecation warning. The deterministic
suite does not require live OpenD, Neo4j, Pinecone, hosted LLM calls, or
`MOOMAIL_RUN_LIVE_CONNECTOR_TESTS=1`.

Live tests remain opt-in under `tests/live/`; see
[CONNECTOR_TESTS.md](CONNECTOR_TESTS.md).

## V3 Targeted Gates

Gateway and deterministic dashboard lane:

```bash
.venv/bin/python -m pytest \
  tests/test_mcp_gateway.py \
  tests/test_mcp_stdio_gateway.py \
  tests/test_mcp_gateway_contract.py \
  tests/test_portfolio_data_service.py \
  tests/test_chat_app.py -q
```

Latest targeted V3.2/V3.3 result on 2026-06-21:

```text
22 passed, 1 warning
```

The warning is the existing LangGraph dependency deprecation warning.

## When To Delete A Test

Delete or merge a test only when both are true:

- Another test covers the same layer and the same failure mode.
- The underlying implementation path is no longer used.

For example, if the OpenD adapter were removed and all access went through an
official SDK-backed MCP client with no local adapter underneath, then
`tests/test_opend_adapter.py` would be a candidate for removal. That is not the
current architecture.
