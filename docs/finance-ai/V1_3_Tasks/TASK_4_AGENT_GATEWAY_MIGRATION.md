# Task V1.3.4: Agent Gateway Migration

Status: complete.

## Goal

Move Portfolio Agent and V1.2 Investment Agent onto the backend MCP gateway.

After this task, agents should no longer receive `RegisteredMCPModule` objects
or call in-process MCP modules directly. They should call a permissioned
`MCPToolGateway` that can use the StdioMCPToolGateway runtime.

## Target Shape

```text
Portfolio Agent
  -> gateway.call_tool("moomail-opend-mcp", "opend_get_portfolio_context", ...)
  -> gateway.call_tool("moomail-finance-metrics-mcp", "calculate_snapshot_metrics", ...)
  -> gateway.call_tool("moomail-portfolio-sql-mcp", "portfolio_sql_...", ...)

V1.2 Investment Agent
  -> calls Portfolio Agent as subagent
  -> Portfolio Agent uses gateway
  -> Sentiment Agent stub remains deterministic
  -> Investment Agent does not directly call OpenD by default
```

The deterministic dashboard portfolio data lane should already be implemented
in V1.3.3. This task moves analytical agents onto the same gateway without
turning dashboard refresh into an agent call.

Implemented files:

- `src/moomail_finance_ai/portfolio_agent.py`
- `src/moomail_finance_ai/investment_agent.py`
- `src/moomail_finance_ai/chat_api.py`
- `scripts/portfolio_agent_review.py`
- `scripts/investment_agent_review.py`
- `scripts/serve_chat.py`
- `src/moomail_finance_ai/mcp/fastmcp.py`
- `src/moomail_finance_ai/mcp/gateway.py`
- `tests/test_portfolio_agent.py`
- `tests/test_portfolio_planner.py`
- `tests/test_mcp_stdio_gateway.py`
- `tests/live/test_portfolio_agent_live.py`

## Exit Criteria

1. Complete. Portfolio Agent constructor and default builder use `MCPToolGateway` instead
   of direct MCP modules.
2. Complete. V1.2 Investment Agent default builder builds or receives a gateway-backed
   Portfolio Agent.
3. Complete. Chat backend and terminal scripts run through the gateway path.
4. Complete. Agent migration does not disturb the V1.3.3 deterministic dashboard data lane.
5. Complete. Tests and docs are updated, and old in-process MCP runtime usage is either
   removed or marked as test-only migration support.

Implementation notes:

- `MCPPortfolioAgent` now has a single `gateway: MCPToolGateway` dependency.
- `MCPPortfolioAgent._call()` uses `gateway.call_tool(..., consumer="portfolio_agent")`.
- `build_default_portfolio_agent()` defaults to `StdioMCPToolGateway`.
- `DirectToolGateway` remains available only for fast deterministic tests and
  parity/migration fixtures.
- `ChatService` owns one shared backend gateway and passes it to Portfolio
  Agent, V1.2 Investment Agent, and `PortfolioDataService`.
- CLI scripts close gateway sessions after runs.
- The custom `JsonRpcMCPServer` is marked legacy/test-only. It is no longer the
  target runtime path.
- FastMCP/gateway handling now supports list-valued structured tool payloads
  such as `calculate_snapshot_metrics` by parsing JSON text fallback when the
  MCP SDK cannot place a list in `structuredContent`.

## Dependency Graph

```text
V1.3.3. Deterministic portfolio data lane
  ├── A. Portfolio Agent gateway refactor
  │   ├── B. Portfolio Agent tests with fake gateway
  │   ├── C. Portfolio Agent tests with StdioMCPToolGateway
  │   └── D. Remove direct module injection from default builder
  ├── E. V1.2 Investment Agent builder migration
  │   ├── F. Chat backend migration
  │   └── G. Terminal script migration
  └── J. Docs, retirement, and closeout checks
```

## Task Breakdown By Exit Criteria

### EC1: Portfolio Agent uses gateway

| Task | Description | Depends on | Test or check |
| --- | --- | --- | --- |
| A | Replace `opend_mcp`, `finance_metrics_mcp`, and `portfolio_sql_mcp` fields with a gateway dependency. | V1.3.2, V1.3.3 | Type/unit tests. |
| A1 | Update `_call` helper to use `gateway.call_tool(server, tool, args, consumer="portfolio_agent")`. | A | Fake gateway test verifies server/tool names. |
| A2 | Preserve `PortfolioAgentResult.tool_calls` planned/actual/skipped trace semantics. | A1 | Existing planner trace tests updated. |
| A3 | Preserve V1.2 optimization where SQL history is read before LLM evaluation and persistence happens after evaluation when appropriate. | A1 | Existing Portfolio Agent tests updated. |
| A4 | Preserve OpenD recorded report mode through gateway config. | A1 | Recorded fixture test. |
| A5 | Preserve SQL canonical DB behavior through gateway config. | A1 | Temp DB and canonical path tests. |

### EC2: V1.2 Investment Agent uses gateway-backed Portfolio Agent

| Task | Description | Depends on | Test or check |
| --- | --- | --- | --- |
| E | Update `build_default_investment_agent` to construct a gateway-backed Portfolio Agent. | A | V1.2 Investment Agent route tests. |
| E1 | Keep fake Portfolio Agent injection available for graph routing tests. | E | Existing fake subagent tests still pass. |
| E2 | Ensure Investment Agent itself does not directly call OpenD tools by default. | E | Gateway permission deny test. |
| E3 | Keep Sentiment Agent stub unchanged except for any gateway-compatible trace metadata. | E | Sentiment stub tests still pass. |

### EC3: Chat backend and terminal scripts use gateway path

| Task | Description | Depends on | Test or check |
| --- | --- | --- | --- |
| F | Update `ChatService` to create or receive a backend gateway manager. | E | Chat API tests. |
| F1 | Ensure chat startup does not spawn duplicate MCP server sessions per request when a shared backend gateway is available. | F | Gateway lifecycle test. |
| F2 | Ensure streamed frontend trace receives gateway errors instead of hanging. | F | Error streaming test. |
| G | Update `scripts/portfolio_agent_review.py` and `scripts/investment_agent_review.py` to use gateway-backed builders. | E | CLI smoke tests with recorded OpenD. |
| G1 | Keep command-line flags for `--env-file`, `--from-report`, `--db-path`, and `--llm-provider`. | G | CLI argument tests. |

### EC4: Deterministic dashboard lane remains separate

| Task | Description | Depends on | Test or check |
| --- | --- | --- | --- |
| H | Confirm V1.3.3 `PortfolioDataService` still owns page-load/status/refresh behavior after agent migration. | V1.3.3, A through G | Dashboard service tests still pass. |
| H1 | Confirm frontend manual refresh still calls dashboard refresh API, not Portfolio Agent or Investment Agent chat endpoints. | H | Frontend test. |
| H2 | Confirm agent migration does not change dashboard response models. | H | Contract/schema tests. |
| H3 | Confirm gateway permission profiles still distinguish `dashboard_refresh` from `portfolio_agent`. | H | Permission tests. |

### EC5: Tests/docs updated and old runtime retired or quarantined

| Task | Description | Depends on | Test or check |
| --- | --- | --- | --- |
| J | Update `MCP_SERVERS.md` to describe FastMCP servers and gateway runtime. | A through H | Docs review. |
| J1 | Update `ARCHITECTURE.md` to show deterministic lane and agent lane sharing MCP gateway. | H | Docs review. |
| J2 | Update `ACTION_PLAN.md` with V1.3 completed or in-progress status. | J | Docs review. |
| J3 | Update `TESTING.md` with FastMCP/gateway tests and retirement decisions. | Tests complete | Docs review. |
| J4 | Delete or quarantine obsolete custom stdio tests only after FastMCP/gateway tests cover the same behavior. | Tests complete | Full deterministic suite. |
| J5 | Run full deterministic closeout gate. | J4 | `.venv/bin/python -m pytest tests --ignore=tests/live -q`. |
| J6 | Run opt-in live OpenD/FastMCP gate when OpenD is running. | J5 | `MOOMAIL_RUN_LIVE_CONNECTOR_TESTS=1 ...`. |

## Tests To Add Or Update During Implementation

- Update `tests/test_portfolio_agent.py`
  - use fake gateway for deterministic agent pipeline tests
  - assert planned/actual/skipped trace entries still exist
- Update `tests/test_portfolio_planner.py`
  - use fake gateway or DirectToolGateway test mode
  - keep cash-only/history/full-review minimization tests
- Update `tests/test_investment_agent.py`
  - ensure default builder can produce gateway-backed Portfolio Agent
  - preserve fake subagent tests
- Update `tests/test_chat_app.py`
  - chat agent paths use gateway-backed backend
  - gateway errors stream to trace/error output
- Keep V1.3.3 dashboard tests passing
  - status success/failure
  - refresh success
  - stale last-known data after failure
  - no LLM or agent invocation
- Add or update live tests under `tests/live/`
  - live OpenD through FastMCP and StdioMCPToolGateway
  - still opt-in

## Deletion Candidates After This Task

These were handled in V1.3.4:

- direct MCP module fields on `MCPPortfolioAgent`: removed
- `build_default_portfolio_agent` default direct module construction: replaced
  by gateway construction
- in-process module use in `build_default_investment_agent`: replaced by
  gateway-backed Portfolio Agent
- custom `JsonRpcMCPServer` and `mcp/stdio.py`: quarantined as legacy/test-only
- custom `_MCPStdioClient` test helpers
- custom stdio round-trip tests that are replaced by official MCP client tests
- `agent_access.py` if gateway permission config fully replaces it
- any docs that describe custom stdio JSON-RPC as the target runtime

Verification:

```bash
.venv/bin/python -m pytest \
  tests/test_mcp_stdio_gateway.py \
  tests/test_portfolio_agent.py \
  tests/test_portfolio_planner.py \
  tests/test_investment_agent.py \
  tests/test_chat_app.py \
  tests/test_portfolio_data_service.py -q
```

Latest targeted result during V1.3.4 implementation:

```text
39 passed, 1 warning
```

Full deterministic closeout result:

```text
.venv/bin/python -m pytest tests --ignore=tests/live -q
183 passed, 1 warning
```

The warning is the existing LangGraph dependency deprecation warning.

Keep domain tests:

- `tests/test_opend_adapter.py`
- `tests/test_opend_portfolio.py`
- `tests/test_sql_store.py`
- `tests/test_metrics.py`

Those test business logic and should survive the MCP transport migration.

## Risks

- Moving agents before gateway parity is proven can break the working V1.2 path.
- Reusing gateway sessions incorrectly can leak state between tests. Use temp
  DBs and recorded OpenD fixtures in deterministic tests.
- The dashboard data lane must not wait for agent planning or LLM calls. Keep it
  as a backend service, not a hidden agent query.
