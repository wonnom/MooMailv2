# Testing Map

The test suite is intentionally layered. Files with similar names are usually
testing different responsibilities rather than duplicating each other.

## MCP Tests

| File | Scope | Real OpenD? | Real SQL? | Keep because |
| --- | --- | --- | --- | --- |
| `tests/test_mcp_tool_contracts.py` | Individual MCP tool contracts for OpenD, portfolio SQL, and metrics | No | No | Proves each tool's structured inputs/outputs without live services |
| `tests/test_mcp_stdio_round_trips.py` | Starts each local FastMCP server script and calls it through the official MCP stdio client | No | No | Proves process-level FastMCP server wiring works |
| `tests/test_mcp_fastmcp_parity.py` | Compares representative FastMCP stdio results with direct module results | No | Temp SQLite only | Proves FastMCP servers preserve the structured payload shapes from direct modules |
| `tests/test_mcp_gateway_contract.py` | Gateway protocol/result/error contract | No | No | Defines the V1.3.2 gateway boundary |
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
| `tests/test_opend_health.py` | One-command OpenD health report and CLI recorded mode | Partially | Proves the V1.1 live gate can surface pass/warn/fail, expected holding mismatches, OTC quote gaps, and fund-assets cash sweep without requiring live OpenD |
| `tests/test_opend_portfolio.py` | Normalizing OpenD field reports into portfolio snapshots and packets | Partially | Covers portfolio accounting edge cases such as options, missing funds, cash-equivalent funds, opt-in fund-assets effective-cash handling, negative cash, and v1 US-equity scoping |
| `tests/test_mcp_tool_contracts.py` | MCP wrapper around OpenD tools | Yes | Verifies the wrapper exposes the adapter safely and returns JSON-compatible results |

The MCP tests do not replace adapter or normalization tests. They prove that the
MCP boundary calls those layers correctly.

Runtime note: the three local MCP server scripts use the official FastMCP runtime
over stdio. The deterministic dashboard lane, Portfolio Agent, and Investment
Agent use `MCPToolGateway`; the default local runtime is
`StdioMCPToolGateway`, while `DirectToolGateway` remains test/dev parity
support.

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
| `tests/test_llm_observability.py` | LLM lifecycle/usage instrumentation, safe LangSmith span hierarchy, run/thread correlation, external allowlisting, opt-in checkpoint summaries, no-network sink, and observability failure isolation |
| `tests/test_research.py` | Local research store and Sentiment Agent contracts |
| `tests/test_portfolio_agent.py` | MCP-backed Portfolio Agent pipeline, evidence-before-analysis assembly, conditional evaluator, call/retry budgets, failure isolation, pattern thresholds, daily SQL idempotency, LLM input boundaries, and evaluator JSON recovery |
| `tests/test_agent_schemas.py` | Agent Pydantic contracts, V1.4 planner/evidence fixtures, guardrail schema, and trace schema |
| `tests/test_asset_resolver.py` | V1.4 deterministic asset resolver behavior, candidate precedence, explicit failure statuses, non-blocking warnings, and sanitized trace |
| `tests/test_investment_planner.py` | V1.4 compatibility planning plus V1.5 baseline-aware InvestmentTurnDecision prompt/parsing, prompt privacy, graceful failure, bounded requests, evidence coverage, source integrity, and fixtures |
| `tests/test_investment_agent.py` | Baseline-before-planner LangGraph flow, one-call direct/deterministic-delegate routes, strict delegation, two-call detailed budgets, Portfolio failure isolation, sentiment ownership, guarded reports, and route trace |
| `tests/test_portfolio_planner.py` | V1.5 deterministic PortfolioEvidencePlan compilation/exhaustiveness plus isolated V1.4 LLM compatibility parsing, direct-query graceful failure, freshness, asset scope, history/persistence, and tool trace entries |
| `tests/test_sentiment_agent_stub.py` | Sentiment Agent stub validation, missing-research packets, no fake citations, and future success fixture shape |
| `tests/test_investment_guardrails.py` | Deterministic investment no-trading, no exact share-count, validated baseline/Portfolio fact support, unsupported research, IPS, and missing-sentiment guardrails |
| `tests/test_agent_trace.py` | Agent trace sanitizer, route/coverage/LLM metadata, graph/tool/sentiment/guardrail trace, error trace, and terminal summary rendering |
| `tests/test_chat_app.py` | Investment-only local HTTP/chat API, legacy alias provenance, baseline/route/call state payloads, evidence trace, and static frontend expectations |
| `tests/test_portfolio_data_service.py` | Deterministic backend portfolio data lane: status, SQL-backed dashboard reads, OpenD refresh, metrics, SQL persistence, stale fallback, no-agent/no-LLM independence, and API route delegation |
| `tests/test_portfolio_baseline.py` | V1.5 deterministic baseline packet: no-OpenD/no-agent boundary, bounded history, 7-day/30-day trends and changes, cash semantics, evidence refs, limitations, privacy, sorting, and caps |

Historical prototype/full-agent tests were removed after the canonical
Investment Agent became the supported chat/CLI path. Historical design context
remains under `docs/finance-ai/V1_1_Tasks/` and `docs/finance-ai/V1_2_Tasks/`.

## V1.2 Closeout Test Gate

V1.2 deterministic closeout uses:

```bash
.venv/bin/python -m pytest tests --ignore=tests/live -q
```

Latest V1.2 closeout result on 2026-06-15:

```text
156 passed, 1 warning
```

The warning is a LangGraph dependency deprecation warning. The deterministic
suite does not require live OpenD, Neo4j, Pinecone, hosted LLM calls, or
`MOOMAIL_RUN_LIVE_CONNECTOR_TESTS=1`.

Live tests remain opt-in under `tests/live/`; see
[CONNECTOR_TESTS.md](CONNECTOR_TESTS.md).

## V1.3 Targeted Gates

Gateway and deterministic dashboard lane:

```bash
.venv/bin/python -m pytest \
  tests/test_mcp_gateway.py \
  tests/test_mcp_stdio_gateway.py \
  tests/test_mcp_gateway_contract.py \
  tests/test_portfolio_data_service.py \
  tests/test_chat_app.py -q
```

Latest targeted V1.3.4 result on 2026-06-23:

```text
39 passed, 1 warning
```

The warning is the existing LangGraph dependency deprecation warning.

## V1.3 Closeout Test Gate

V1.3.4 deterministic closeout uses:

```bash
.venv/bin/python -m pytest tests --ignore=tests/live -q
```

Latest V1.3.4 closeout result on 2026-06-23:

```text
183 passed, 1 warning
```

The warning is the existing LangGraph dependency deprecation warning.

## V1.4 Targeted Gates

V1.4.0 planner-contract closeout uses:

```bash
.venv/bin/python -m pytest tests/test_agent_schemas.py -q
.venv/bin/python -m pytest tests/test_sentiment_agent_stub.py -q
```

Latest V1.4.0 result on 2026-06-24:

```text
tests/test_agent_schemas.py: 55 passed
tests/test_sentiment_agent_stub.py: 6 passed
```

V1.4.1 asset-resolution and validation closeout uses:

```bash
.venv/bin/python -m pytest tests/test_asset_resolver.py tests/test_agent_schemas.py -q
.venv/bin/python -m pytest tests/test_portfolio_planner.py -q
```

Latest V1.4.1 result on 2026-06-24:

```text
tests/test_asset_resolver.py tests/test_agent_schemas.py: 67 passed
tests/test_portfolio_planner.py: 14 passed
```

V1.4.2 Investment Agent planner closeout uses:

```bash
.venv/bin/python -m pytest tests/test_investment_planner.py tests/test_investment_agent.py -q
.venv/bin/python -m pytest tests/test_chat_app.py -q
.venv/bin/python -m pytest tests/test_agent_schemas.py tests/test_agent_trace.py -q
```

Latest V1.4.2 result on 2026-06-25:

```text
tests/test_investment_planner.py tests/test_investment_agent.py: 22 passed, 1 warning
tests/test_chat_app.py: 10 passed, 1 warning
tests/test_agent_schemas.py tests/test_agent_trace.py: 60 passed, 1 warning
```

V1.4.3 Portfolio Evidence Planner closeout uses:

```bash
.venv/bin/python -m pytest tests/test_portfolio_planner.py tests/test_asset_resolver.py -q
.venv/bin/python -m pytest tests/test_portfolio_agent.py -q
.venv/bin/python -m pytest tests/test_agent_schemas.py -q
```

Latest V1.4.3 result on 2026-06-26:

```text
.venv/bin/python -m py_compile src/moomail_finance_ai/portfolio_evidence_planner.py src/moomail_finance_ai/portfolio_agent.py src/moomail_finance_ai/agent_schemas.py: passed
tests/test_portfolio_planner.py tests/test_asset_resolver.py tests/test_portfolio_agent.py tests/test_agent_schemas.py: 112 passed
```

Latest deterministic non-live regression after V1.4.3 on 2026-06-26:

```text
.venv/bin/python -m pytest tests --ignore=tests/live -q
243 passed, 1 warning
```

The warning is the existing LangGraph dependency deprecation warning. Live
connector tests remain opt-in and were not required for deterministic V1.4.0,
V1.4.1, V1.4.2, or V1.4.3 completion.

V1.4.4 deterministic execution and evidence-packet closeout uses:

```bash
.venv/bin/python -m pytest tests/test_portfolio_agent.py tests/test_portfolio_planner.py -q
.venv/bin/python -m pytest tests/test_portfolio_data_service.py tests/test_mcp_gateway.py -q
.venv/bin/python -m pytest tests/test_mcp_tool_contracts.py -q
```

Latest V1.4.4 result on 2026-06-29:

```text
tests/test_portfolio_agent.py tests/test_portfolio_planner.py: 51 passed
tests/test_portfolio_data_service.py tests/test_mcp_gateway.py: 11 passed, 1 warning
tests/test_mcp_tool_contracts.py: 6 passed
```

V1.4.5 trace, evaluation, and closeout uses:

```bash
.venv/bin/python -m pytest tests/test_investment_planner.py tests/test_asset_resolver.py -q
.venv/bin/python -m pytest tests/test_portfolio_planner.py tests/test_portfolio_agent.py -q
.venv/bin/python -m pytest tests/test_investment_agent.py tests/test_chat_app.py -q
.venv/bin/python -m pytest tests/test_portfolio_data_service.py -q
.venv/bin/python -m pytest tests --ignore=tests/live -q
git diff --check
```

Latest V1.4.5 result on 2026-06-29:

```text
tests/test_investment_planner.py tests/test_asset_resolver.py: 23 passed
tests/test_portfolio_planner.py tests/test_portfolio_agent.py: 51 passed
tests/test_investment_agent.py tests/test_chat_app.py: 22 passed, 1 warning
tests/test_portfolio_data_service.py: 7 passed, 1 warning
tests --ignore=tests/live: 251 passed, 1 warning
git diff --check: passed
```

The warnings are the existing LangGraph dependency deprecation warning. Live
connector tests remain opt-in and were not required for deterministic V1.4.4 or
V1.4.5 completion.

V1.5.0 routing and observability contract closeout uses:

```bash
.venv/bin/python -m pytest tests/test_agent_schemas.py tests/test_agent_trace.py -q
.venv/bin/python -m pytest tests/test_investment_planner.py tests/test_portfolio_planner.py -q
.venv/bin/python -m pytest tests/test_opend_config.py -q
.venv/bin/python -m pytest tests/test_investment_agent.py tests/test_chat_app.py tests/test_asset_resolver.py -q
.venv/bin/python -m pytest tests --ignore=tests/live -q
git diff --check
```

Latest V1.5.0 result on 2026-08-03:

```text
tests/test_agent_schemas.py tests/test_agent_trace.py: 74 passed, 1 warning
tests/test_investment_planner.py tests/test_portfolio_planner.py: 63 passed
tests/test_opend_config.py: 6 passed
tests/test_investment_agent.py tests/test_chat_app.py tests/test_asset_resolver.py: 36 passed, 1 warning
tests --ignore=tests/live: 281 passed, 1 warning
git diff --check: passed
```

The warning is the existing LangGraph dependency deprecation warning. Live
connector tests were not required because V1.5.0 adds deterministic contracts
and validation without hosted LLM, LangSmith, or OpenD calls. Ruff was not run
because the repository virtual environment does not contain it.

V1.5.1 deterministic baseline closeout uses:

```bash
.venv/bin/python -m pytest tests/test_portfolio_baseline.py -q
.venv/bin/python -m pytest tests/test_portfolio_data_service.py -q
.venv/bin/python -m pytest tests/test_chat_app.py -q
.venv/bin/python -m pytest tests/test_mcp_gateway.py tests/test_metrics.py -q
.venv/bin/python -m pytest tests --ignore=tests/live -q
git diff --check
```

Latest V1.5.1 result on 2026-08-03:

```text
tests/test_portfolio_baseline.py: 18 passed
tests/test_portfolio_data_service.py: 9 passed, 1 warning
tests/test_chat_app.py: 13 passed, 1 warning
tests/test_mcp_gateway.py tests/test_metrics.py: 11 passed
tests --ignore=tests/live: 303 passed, 1 warning
git diff --check: passed
```

The warning is the existing LangGraph dependency deprecation warning. Live
tests are not part of this gate because the baseline must use stored SQL and
must not call live OpenD or a hosted model. Ruff remains unavailable in the
project virtual environment.

V1.5.2 Investment-default strict-routing closeout uses:

```bash
.venv/bin/python -m pytest tests/test_investment_planner.py tests/test_investment_agent.py -q
.venv/bin/python -m pytest tests/test_chat_app.py tests/test_agent_trace.py -q
.venv/bin/python -m pytest tests/test_investment_guardrails.py -q
.venv/bin/python -m pytest tests --ignore=tests/live -q
git diff --check
```

Latest V1.5.2 result on 2026-08-03:

```text
tests/test_investment_planner.py tests/test_investment_agent.py: 54 passed, 1 warning
tests/test_chat_app.py tests/test_agent_trace.py: 22 passed, 1 warning
tests/test_investment_guardrails.py: 6 passed
tests --ignore=tests/live: 331 passed, 1 warning
git diff --check: passed
```

The warning is the existing LangGraph dependency deprecation warning. Live
connector/model tests are not part of this deterministic routing gate. Ruff
remains unavailable in the project virtual environment.

V1.5.3 deterministic Portfolio escalation and call-budget closeout uses:

```bash
.venv/bin/python -m pytest tests/test_portfolio_planner.py tests/test_portfolio_agent.py -q
.venv/bin/python -m pytest tests/test_investment_agent.py tests/test_agent_trace.py -q
.venv/bin/python -m pytest tests/test_chat_app.py tests/test_portfolio_data_service.py -q
.venv/bin/python -m pytest tests --ignore=tests/live -q
git diff --check
```

Latest V1.5.3 result on 2026-08-05:

```text
tests/test_portfolio_planner.py tests/test_portfolio_agent.py: 77 passed
tests/test_investment_agent.py tests/test_agent_trace.py: 46 passed, 1 warning
tests/test_chat_app.py tests/test_portfolio_data_service.py: 24 passed, 1 warning
tests --ignore=tests/live: 357 passed, 1 warning
py_compile (V1.5.3 touched runtime modules): passed
git diff --check: passed
```

The warning is the existing LangGraph dependency deprecation warning. Live
connector/model tests are not part of this deterministic compiler/fake-provider
budget gate. Ruff remains unavailable in the project virtual environment.

V1.5.4 LangSmith and MooMail trace instrumentation closeout uses:

```bash
.venv/bin/python -m pytest tests/test_llm.py tests/test_llm_observability.py -q
.venv/bin/python -m pytest tests/test_agent_trace.py tests/test_investment_agent.py tests/test_portfolio_agent.py -q
.venv/bin/python -m pytest tests/test_chat_app.py -q
.venv/bin/python -m pytest tests --ignore=tests/live -q
git diff --check
```

Latest V1.5.4 result on 2026-08-05:

```text
tests/test_llm.py tests/test_llm_observability.py: 15 passed, 1 warning
tests/test_agent_trace.py tests/test_investment_agent.py tests/test_portfolio_agent.py: 61 passed, 1 warning
tests/test_chat_app.py: 15 passed, 1 warning
tests --ignore=tests/live: 369 passed, 1 warning
py_compile (V1.5.4 touched runtime modules): passed
git diff --check: passed
```

The warning is the existing LangGraph serializer deprecation warning. Hosted
LangSmith/model and live OpenD tests are not required for this fake-provider,
no-network observability gate. Ruff remains unavailable in the project virtual
environment.

## V1.5.5 Frontend Trace, Evaluation, And Closeout Gate

V1.5.5 uses the task-file commands exactly. Latest result on 2026-08-05:

```text
tests/test_agent_schemas.py tests/test_agent_trace.py: 77 passed, 1 warning
tests/test_portfolio_baseline.py tests/test_portfolio_data_service.py: 27 passed, 1 warning
tests/test_investment_planner.py tests/test_investment_agent.py: 60 passed, 1 warning
tests/test_portfolio_planner.py tests/test_portfolio_agent.py: 77 passed, 1 warning
tests/test_llm.py tests/test_llm_observability.py: 16 passed, 1 warning
tests/test_chat_app.py tests/test_investment_guardrails.py: 23 passed, 1 warning
tests --ignore=tests/live: 375 passed, 1 warning
node --check for changed browser JavaScript: passed
interactive local browser progress/trace/accessibility check: passed
git diff --check: passed
```

The golden route matrix covers one-call baseline answers, strict evidence
escalation, two-call interpretation budgets, and one-call deterministic-only
delegation. Failure fixtures cover planner integrity, Portfolio compilation/
execution/analysis and call budgets, stream errors, LangSmith exporter failure,
checkpoint finalization, privacy, ownership, and deterministic dashboard
independence. The warning remains the existing LangGraph serializer deprecation
warning. Hosted model/LangSmith and live OpenD tests were intentionally not run.

## When To Delete A Test

Delete or merge a test only when both are true:

- Another test covers the same layer and the same failure mode.
- The underlying implementation path is no longer used.

For example, if the OpenD adapter were removed and all access went through an
official SDK-backed MCP client with no local adapter underneath, then
`tests/test_opend_adapter.py` would be a candidate for removal. That is not the
current architecture.
