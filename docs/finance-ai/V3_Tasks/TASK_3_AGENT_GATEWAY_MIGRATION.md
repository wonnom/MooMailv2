# Task V3.3: Agent Gateway Migration

Status: planned.

## Goal

Move Portfolio Agent and V2 Investment Agent onto the backend MCP gateway.

After this task, agents should no longer receive `RegisteredMCPModule` objects
or call in-process MCP modules directly. They should call a permissioned
`MCPToolGateway` that can use the StdioMCPToolGateway runtime.

## Target Shape

```text
Portfolio Agent
  -> gateway.call_tool("moomail-opend-mcp", "opend_get_portfolio_context", ...)
  -> gateway.call_tool("moomail-finance-metrics-mcp", "calculate_snapshot_metrics", ...)
  -> gateway.call_tool("moomail-portfolio-sql-mcp", "portfolio_sql_...", ...)

V2 Investment Agent
  -> calls Portfolio Agent as subagent
  -> Portfolio Agent uses gateway
  -> Sentiment Agent stub remains deterministic
  -> Investment Agent does not directly call OpenD by default
```

The deterministic dashboard portfolio data lane should also use the gateway,
but it is owned by backend services rather than agents.

## Exit Criteria

1. Portfolio Agent constructor and default builder use `MCPToolGateway` instead
   of direct MCP modules.
2. V2 Investment Agent default builder builds or receives a gateway-backed
   Portfolio Agent.
3. Chat backend and terminal scripts can run through the gateway path.
4. Deterministic dashboard refresh/status service can use the same gateway path
   without invoking an agent.
5. Tests and docs are updated, and old in-process MCP runtime usage is either
   removed or marked as test-only migration support.

## Dependency Graph

```text
V3.2. Gateway modes
  ├── A. Portfolio Agent gateway refactor
  │   ├── B. Portfolio Agent tests with fake gateway
  │   ├── C. Portfolio Agent tests with StdioMCPToolGateway
  │   └── D. Remove direct module injection from default builder
  ├── E. V2 Investment Agent builder migration
  │   ├── F. Chat backend migration
  │   └── G. Terminal script migration
  ├── H. Deterministic portfolio data service
  │   └── I. Dashboard API tests
  └── J. Docs, retirement, and closeout checks
```

## Task Breakdown By Exit Criteria

### EC1: Portfolio Agent uses gateway

| Task | Description | Depends on | Test or check |
| --- | --- | --- | --- |
| A | Replace `opend_mcp`, `finance_metrics_mcp`, and `portfolio_sql_mcp` fields with a gateway dependency. | V3.2 | Type/unit tests. |
| A1 | Update `_call` helper to use `gateway.call_tool(server, tool, args, consumer="portfolio_agent")`. | A | Fake gateway test verifies server/tool names. |
| A2 | Preserve `PortfolioAgentResult.tool_calls` planned/actual/skipped trace semantics. | A1 | Existing planner trace tests updated. |
| A3 | Preserve V2 optimization where SQL history is read before LLM evaluation and persistence happens after evaluation when appropriate. | A1 | Existing Portfolio Agent tests updated. |
| A4 | Preserve OpenD recorded report mode through gateway config. | A1 | Recorded fixture test. |
| A5 | Preserve SQL canonical DB behavior through gateway config. | A1 | Temp DB and canonical path tests. |

### EC2: V2 Investment Agent uses gateway-backed Portfolio Agent

| Task | Description | Depends on | Test or check |
| --- | --- | --- | --- |
| E | Update `build_default_v2_investment_agent` to construct a gateway-backed Portfolio Agent. | A | V2 Investment Agent route tests. |
| E1 | Keep fake Portfolio Agent injection available for graph routing tests. | E | Existing fake subagent tests still pass. |
| E2 | Ensure Investment Agent itself does not directly call OpenD tools by default. | E | Gateway permission deny test. |
| E3 | Keep Sentiment Agent stub unchanged except for any gateway-compatible trace metadata. | E | Sentiment stub tests still pass. |

### EC3: Chat backend and terminal scripts use gateway path

| Task | Description | Depends on | Test or check |
| --- | --- | --- | --- |
| F | Update `ChatService` to create or receive a backend gateway manager. | E | Chat API tests. |
| F1 | Ensure chat startup does not spawn duplicate MCP server sessions per request when a shared backend gateway is available. | F | Gateway lifecycle test. |
| F2 | Ensure streamed frontend trace receives gateway errors instead of hanging. | F | Error streaming test. |
| G | Update `scripts/portfolio_agent_review.py` and `scripts/investment_agent_v2_review.py` to use gateway-backed builders. | E | CLI smoke tests with recorded OpenD. |
| G1 | Keep command-line flags for `--env-file`, `--from-report`, `--db-path`, and `--llm-provider`. | G | CLI argument tests. |

### EC4: Deterministic dashboard lane uses gateway

| Task | Description | Depends on | Test or check |
| --- | --- | --- | --- |
| H | Add backend `PortfolioDataService` or equivalent deterministic refresh/status service. | V3.0, V3.2 | Service tests with fake gateway. |
| H1 | Implement connection status flow: OpenD check plus sanitized config/status. | H | Status test. |
| H2 | Implement dashboard refresh flow: OpenD context, metrics calculation, SQL history update, response. | H | Refresh success test. |
| H3 | Implement last-known state or graceful error behavior when refresh fails after prior data exists. | H | Failure/stale data test. |
| H4 | Ensure this service does not call LLMs or agents. | H | Fake LLM not needed in tests. |
| H5 | Wire backend API route if the frontend needs immediate dashboard support in V3. | H | HTTP test. |

### EC5: Tests/docs updated and old runtime retired or quarantined

| Task | Description | Depends on | Test or check |
| --- | --- | --- | --- |
| J | Update `MCP_SERVERS.md` to describe FastMCP servers and gateway runtime. | A through H | Docs review. |
| J1 | Update `ARCHITECTURE.md` to show deterministic lane and agent lane sharing MCP gateway. | H | Docs review. |
| J2 | Update `ACTION_PLAN.md` with V3 completed or in-progress status. | J | Docs review. |
| J3 | Update `TESTING.md` with FastMCP/gateway tests and retirement decisions. | Tests complete | Docs review. |
| J4 | Delete or quarantine obsolete custom stdio tests only after FastMCP/gateway tests cover the same behavior. | Tests complete | Full deterministic suite. |
| J5 | Run full deterministic closeout gate. | J4 | `.venv/bin/python -m pytest tests --ignore=tests/live -q`. |
| J6 | Run opt-in live OpenD/FastMCP gate when OpenD is running. | J5 | `MOOMAIL_RUN_LIVE_CONNECTOR_TESTS=1 ...`. |

## Tests To Add Or Update During Implementation

- Update `tests/test_portfolio_agent.py`
  - use fake gateway for deterministic agent pipeline tests
  - assert planned/actual/skipped trace entries still exist
- Update `tests/test_v2_portfolio_planner.py`
  - use fake gateway or DirectToolGateway test mode
  - keep cash-only/history/full-review minimization tests
- Update `tests/test_v2_investment_agent.py`
  - ensure default builder can produce gateway-backed Portfolio Agent
  - preserve fake subagent tests
- Update `tests/test_chat_app.py`
  - chat agent paths use gateway-backed backend
  - gateway errors stream to trace/error output
- Add `tests/test_dashboard_portfolio_data_lane.py`
  - status success/failure
  - refresh success
  - stale last-known data after failure
  - no LLM or agent invocation
- Add or update live tests under `tests/live/`
  - live OpenD through FastMCP and StdioMCPToolGateway
  - still opt-in

## Deletion Candidates After This Task

These can be deleted or rewritten once V3.3 is green:

- direct MCP module fields on `MCPPortfolioAgent`
- `build_default_portfolio_agent` logic that constructs in-process MCP modules
- in-process module use in `build_default_v2_investment_agent`
- custom `JsonRpcMCPServer` and `mcp/stdio.py`
- custom `_MCPStdioClient` test helpers
- custom stdio round-trip tests that are replaced by official MCP client tests
- `agent_access.py` if gateway permission config fully replaces it
- any docs that describe custom stdio JSON-RPC as the target runtime

Keep domain tests:

- `tests/test_opend_adapter.py`
- `tests/test_opend_portfolio.py`
- `tests/test_sql_store.py`
- `tests/test_metrics.py`

Those test business logic and should survive the MCP transport migration.

## Risks

- Moving agents before gateway parity is proven can break the working V2 path.
- Reusing gateway sessions incorrectly can leak state between tests. Use temp
  DBs and recorded OpenD fixtures in deterministic tests.
- The dashboard data lane must not wait for agent planning or LLM calls. Keep it
  as a backend service, not a hidden agent query.
