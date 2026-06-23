# Action Plan

## Status

V1 is complete as of 2026-06-06.

V2 skeleton is complete as of 2026-06-15.

V3 MCP runtime migration is complete as of 2026-06-23: gateway modes,
deterministic portfolio data lane, and Portfolio/V2 Investment Agent gateway
migration are implemented.

V1 is a Portfolio Agent proof of concept with:

- Read-only OpenD/MooMoo securities-account retrieval.
- OpenD portfolio normalization for funds, positions, supported quotes, and
  non-blocking unsupported quote warnings.
- One canonical local portfolio-history database:
  `data/portfolio-history.sqlite`.
- Lean SQL history through `moomail-portfolio-sql-mcp`: portfolio/account/asset
  identities, compact position states, daily value snapshots, allocation weight
  snapshots, data-quality events, and run summaries.
- Deterministic finance metric tools through `moomail-finance-metrics-mcp`.
- MCP-backed Portfolio Agent using OpenD, SQL history, finance metrics, and a
  provider-neutral portfolio-only LLM evaluator.
- Local terminal and static chat frontend paths over the same backend contracts.
- No trading tools, no trade unlock, no order placement, and no executable
  order-preparation path.

The old milestone task files under `docs/finance-ai/V1_TASKS/` are
historical implementation tracking. They are not the active plan for V2.

## Current Truth

Implemented and useful today:

- `moomail-opend-mcp`: local read-only OpenD tool surface.
- `moomail-portfolio-sql-mcp`: local SQLite portfolio-history tool surface.
- `moomail-finance-metrics-mcp`: deterministic calculation tool surface.
- FastMCP server scripts for OpenD, portfolio SQL, and finance metrics over
  stdio.
- `DirectToolGateway`: test/dev parity gateway over in-process modules.
- `StdioMCPToolGateway`: backend-owned local MCP client gateway over FastMCP
  stdio servers.
- `PortfolioDataService`: deterministic backend service for OpenD status,
  latest SQL-backed dashboard snapshots, manual refresh, metrics, and canonical
  SQL history updates without invoking agents or LLMs.
- `MCPPortfolioAgent`: bounded-planning Python Portfolio Agent that interprets
  a portfolio task, produces a `PortfolioContextPlan`, executes selected MCP
  tools deterministically, then asks an LLM evaluator to answer portfolio-only
  questions from the collected packet.
- `V2InvestmentAgent`: thin LangGraph supervisor that routes portfolio-only
  and portfolio-plus-sentiment queries through structured V2 packets.
- `V2SentimentAgentStub`: deterministic missing-research Sentiment Agent stub
  that cements the future Neo4j GraphRAG contract without requiring Neo4j.
- `v2_guardrails`: deterministic V2 output guardrails for no-trading,
  no-exact-share-count instructions, unsupported claims, IPS-gated
  optimization, and missing-sentiment visibility.
- `v2_trace`: sanitized V2 operational trace for graph progress, subagent
  calls, Portfolio Agent tool summaries, sentiment stub status, guardrail
  outcome, and errors.
- `scripts/portfolio_agent_review.py`: terminal Portfolio Agent review.
- `scripts/investment_agent_v2_review.py`: terminal V2 Investment Agent review.
- `scripts/serve_chat.py`: local chat frontend server.
- Local frontend portfolio dashboard flow: page load reads stored dashboard
  data; refresh button calls deterministic backend APIs.
- `data/portfolio-history.sqlite`: canonical local portfolio-history DB.
- Deterministic tests and live OpenD connector smoke tests.

Important limitations:

- The Portfolio Agent is MCP-backed with a deterministic bounded planner. It
  does not let the LLM decide which OpenD, SQL, or metrics tools to call.
- The V2 Investment Agent is intentionally thin; richer LLM planning,
  checkpointing, and memory are still future work.
- V2 synthesis is deterministic/template-style. It does not yet perform a rich
  LLM synthesis pass over portfolio, sentiment, memory, and market context.
- The Sentiment Agent is a V2 stub only. Neo4j GraphRAG is not implemented, and
  the stub must not invent research claims, citations, or sentiment.
- The Portfolio Agent bounded planner is implemented inside the existing Python
  Portfolio Agent path, not as a separate compiled LangGraph subgraph.
- Pinecone memory is not connected.
- The deterministic dashboard lane, Portfolio Agent, and V2 Investment Agent
  path use the gateway. `RegisteredMCPModule` remains underneath FastMCP and
  DirectToolGateway tests, not as the agent runtime dependency.
- Crypto holdings and OTC quote fallback are deferred.

## V2 Completed Skeleton

V2 turns the V1 Portfolio Agent POC into the first real Investment Agent
skeleton.

It does not finish GraphRAG or memory. It establishes this orchestration shape:

```text
User query
  -> Thin LangGraph Investment Agent supervisor
      -> decide whether portfolio context is needed
      -> decide whether sentiment/research is needed
      -> call Portfolio Agent bounded-planning path
      -> call Sentiment Agent stub when needed
      -> synthesize final answer
      -> run guardrails
```

The Portfolio Agent now has a bounded-planning path:

```text
Portfolio Agent bounded-planning path
  -> interpret portfolio task
  -> produce bounded context plan
  -> retrieve current OpenD snapshot when needed
  -> read SQL history slices when needed
  -> calculate required deterministic metrics
  -> return structured portfolio packet and candidate sentiment scope
```

The Sentiment Agent is a stub in V2:

```text
Sentiment Agent stub
  -> accept requested tickers/themes/questions
  -> return structured placeholder response
  -> expose missing GraphRAG fields clearly
```

This cements agent routing, subagent contracts, trace events, guardrail
behavior, and output schemas before committing to the Neo4j ingestion and
GraphRAG retrieval design.

## V2 Principles

- Use LangGraph for orchestration, routing, state, streaming, and future
  checkpointing.
- Use LangChain model/tool abstractions inside nodes only where they add value.
- Keep finance math, OpenD normalization, SQL persistence, and guardrails
  deterministic and testable.
- Add autonomy only where it is bounded by schemas and allowed tools.
- Keep the Investment Agent as the only cross-agent orchestrator.
- Do not let Portfolio Agent call Sentiment Agent directly.
- Let Portfolio Agent suggest sentiment candidates, but let Investment Agent
  decide whether to invoke Sentiment Agent.
- Keep all tools read-only or analysis-only. No trade execution path.

## V2 Work Plan

Detailed dependency maps for each work-plan item live under
[`docs/finance-ai/V2_Tasks/`](V2_Tasks/).

### 1. Define V2 Contracts

Status: complete as of 2026-06-08.

Create stable Pydantic models for:

- `InvestmentAgentState`
- `InvestmentQueryPlan`
- `PortfolioTask`
- `PortfolioContextPlan`
- `PortfolioAgentPacket`
- `SentimentTask`
- `SentimentPacket`
- `SynthesisInput`
- `GuardrailReview`

Exit criteria:

- Investment Agent can route using structured fields rather than parsing prose.
- Portfolio Agent can tell the Investment Agent which tickers/history changes
  may deserve sentiment review.
- Sentiment Agent stub can return the same shape the future GraphRAG agent will
  fill.

### 2. Build Thin LangGraph Investment Agent

Status: complete as of 2026-06-08.

Implement a small LangGraph supervisor with nodes for:

- receive/query classification
- load IPS
- route portfolio need
- route sentiment need
- call Portfolio Agent
- call Sentiment Agent stub
- synthesize final response
- guardrail review
- emit structured output

Exit criteria:

- Portfolio-only queries call only Portfolio Agent.
- Full review queries call Portfolio Agent and, when appropriate, Sentiment
  Agent stub.
- Missing sentiment data is shown as a clear limitation, not hallucinated
  research.
- Existing terminal/frontend paths can call the new Investment Agent path.

### 3. Convert Portfolio Agent To Bounded Planning Subgraph

Status: complete as of 2026-06-13.

Refactor the current deterministic Portfolio Agent into graph nodes while
preserving V1 behavior as the safe default.

Initial planner output should decide:

- whether current OpenD is required
- whether SQL history is required
- history window or row limits
- relevant tickers/assets
- required metric groups
- whether persistence should occur for this run

Execution remains deterministic once the plan is produced.

Exit criteria:

- A cash-weight query avoids unnecessary broad history reads and persistence.
- A “what changed” query requests portfolio growth/allocation history.
- A full review preserves the existing V1 broad context behavior.
- Tool calls are visible as planned, actual, and skipped trace entries.

### 4. Add Sentiment Agent Stub

Status: complete as of 2026-06-15.

Build a stub that receives the real future task shape:

- tickers
- companies/entities
- reasons for research
- time window
- requested evidence types
- key questions

It returns:

- empty holdings
- explicit `retrieval_status: not_implemented`
- missing document/research fields
- no fabricated sentiment

Exit criteria:

- Investment Agent can call Sentiment Agent without Neo4j.
- Final synthesis can say when research is unavailable.
- Future Neo4j work has a concrete input/output contract to satisfy.

### 5. Guardrails And Trace

Status: complete as of 2026-06-15.

Move guardrail review into the V2 Investment Agent path.

Guardrails should check:

- no trade placement or executable order instructions
- no unsupported research claims
- no unsupported price/portfolio facts
- no exact share-count recommendations
- missing IPS where optimization/rebalancing is framed as recommendation
- missing sentiment limitations are visible when GraphRAG is unavailable

Trace should expose only operational information:

- graph node/status progress
- subagent calls
- Portfolio Agent planned/actual/skipped tool summaries
- Sentiment Agent stub retrieval status
- guardrail outcome
- sanitized errors

Exit criteria:

- Guardrail result is included in terminal and chat outputs.
- Streamed trace shows high-level graph node progress and errors.
- Hidden reasoning is never stored or exposed.

### 6. Documentation And Tests

Status: complete as of 2026-06-15.

Keep tests deterministic by default.

Add tests for:

- query routing
- portfolio-only path
- portfolio-plus-sentiment-stub path
- Portfolio Agent bounded planner outputs
- no-trading guardrails
- missing research behavior
- schema validation

Exit criteria:

- Deterministic suite passes without live OpenD, Neo4j, Pinecone, or hosted LLM
  calls.
- Live OpenD connector tests remain opt-in.
- Docs describe V1 as complete and V2 skeleton as complete, including remaining
  mocks, stubs, and deferred pieces.

Closeout verification:

```text
.venv/bin/python -m pytest tests --ignore=tests/live -q
156 passed, 1 warning
```

## Deferred Until After V2 Skeleton

- Real Neo4j GraphRAG ingestion.
- Real GraphRAG retrieval.
- Pinecone memory.
- Official MCP SDK/client runtime migration. Completed later in V3 through
  FastMCP server scripts and `StdioMCPToolGateway`.
- Crypto account ingestion.
- OTC quote fallback provider.
- Scheduled daily checks.
- Rich React frontend migration.

These are still part of the long-term architecture. They should be built after
the V2 Investment Agent and subagent contracts are stable.

## V3 Complete Iteration

The selected V3 track was the official MCP runtime migration, with one important
clarification: MCP is backend infrastructure, not only an LLM-agent tool
surface. V3 is complete as of 2026-06-23.

OpenD MCP must support both:

- deterministic backend portfolio data flows for page load, manual refresh,
  connection status, current funds/positions, normalized snapshots, metrics,
  SQL history updates, and dashboard display
- agentic analysis flows where the Investment Agent and Portfolio Agent use the
  same permissioned data boundary for analytical queries

The frontend should call backend APIs only. The backend owns the MCP client/host
runtime, gateway permissions, server lifecycle, timeouts, traces, and sanitized
errors.

V3 task maps live under [`docs/finance-ai/V3_Tasks/`](V3_Tasks/).

V3 tasks:

| Task | Status | Purpose |
| --- | --- | --- |
| V3.0 | complete as of 2026-06-17 | Define MCP as backend infrastructure boundary for deterministic app flows and agentic flows. |
| V3.1 | complete as of 2026-06-17 | Preserve business logic, replace custom `JsonRpcMCPServer` server scripts with FastMCP servers, and define the gateway contract. |
| V3.2 | complete as of 2026-06-21 | Implement `DirectToolGateway` for parity tests and `StdioMCPToolGateway` for production-ish local runtime. |
| V3.3 | complete as of 2026-06-21 | Implement the deterministic backend/frontend portfolio data lane for dashboard status, latest snapshot, manual refresh, SQL update, and no-agent refresh behavior. |
| V3.4 | complete as of 2026-06-23 | Move Portfolio Agent and V2 Investment Agent to the gateway, then update docs and retirement decisions. |

V3.0 decisions now accepted:

- OpenD MCP is a shared backend data boundary for deterministic dashboard
  refresh/status flows and agentic analysis flows.
- The frontend calls backend APIs only and never calls MCP directly.
- Backend API contracts are defined for portfolio connection status, dashboard
  snapshot, manual refresh result, and last-updated/freshness metadata.
- The backend owns MCP host/client lifecycle, gateway permissions, timeouts,
  traces, and sanitized errors.
- Gateway consumers are `dashboard_refresh`, `portfolio_agent`,
  `investment_agent`, and `sentiment_agent`, each with distinct allowed MCP
  access.

V3 explicitly retired or narrowed the custom V2 MCP-shaped runtime only after
parity tests passed. `mcp/stdio.py` is legacy/test-only, direct
`RegisteredMCPModule` injection into agents has been removed, and
`DirectToolGateway` remains the test/dev parity path.

The deterministic portfolio data lane is its own implementation step in V3.3.
It must update the backend and frontend so page load/manual refresh can show
connection status, current balances, holdings, metrics, warnings, and
last-updated metadata without invoking Portfolio Agent or Investment Agent.

V3.1 implementation reality:

- `scripts/mcp_finance_metrics_server.py`, `scripts/mcp_opend_server.py`, and
  `scripts/mcp_portfolio_sql_server.py` now run official FastMCP over stdio.
- `src/moomail_finance_ai/mcp/fastmcp.py` adapts existing registered tool
  modules into FastMCP servers so business logic remains plain Python.
- `src/moomail_finance_ai/mcp/gateway.py` defines the gateway protocol/result
  and error contract for V3.2.
- Agents still called in-process modules at V3.1; V3.4 moved Portfolio Agent
  and V2 Investment Agent to the gateway.

V3.2 implementation reality:

- `src/moomail_finance_ai/mcp/gateway.py` now implements `MCPToolGateway`,
  `DirectToolGateway`, `StdioMCPToolGateway`, permission profiles, and local
  stdio server configuration.
- `dashboard_refresh`, `portfolio_agent`, `investment_agent`, and
  `sentiment_agent` have distinct gateway allowlists.
- `investment_agent` is denied direct OpenD by default. Trade/order-like tool
  names are globally denied.

V3.3 implementation reality:

- `src/moomail_finance_ai/portfolio_data_service.py` owns deterministic
  portfolio status, latest-dashboard, and refresh flows.
- `GET /api/portfolio/status`, `GET /api/portfolio/dashboard`, and
  `POST /api/portfolio/refresh` are served by `scripts/serve_chat.py`.
- Page load reads the latest stored SQL dashboard snapshot and OpenD status.
- Manual refresh pulls OpenD context, calculates metrics, updates canonical SQL
  history, and returns dashboard-ready data without constructing Portfolio
  Agent, Investment Agent, sentiment agent, or an LLM evaluator.
- Refresh failure returns stale last-known SQL dashboard data when available
  plus a sanitized error.

V3.4 implementation reality:

- `MCPPortfolioAgent` receives `MCPToolGateway` and calls tools with
  `consumer="portfolio_agent"`.
- `build_default_portfolio_agent()` defaults to `StdioMCPToolGateway`.
- `build_default_v2_investment_agent()` constructs a gateway-backed Portfolio
  Agent unless a fake/injected Portfolio Agent is supplied at the graph level.
- `ChatService` owns a shared backend gateway for portfolio chat, V2 investment
  chat, and deterministic portfolio data APIs.
- Terminal scripts close gateway sessions after runs.
- `JsonRpcMCPServer` is legacy/test-only; FastMCP plus official MCP client is
  the runtime boundary.

## Next Work Options

V2 is closed as a skeleton and V3 is complete for the MCP runtime boundary. The
remaining high-value tracks are:

1. Real Neo4j GraphRAG ingestion and retrieval against the V2 Sentiment Agent
   contract.
2. Bounded structured-output LLM/LangGraph planner for query classification,
   ticker/asset-scope selection, history-window selection, and subagent
   planning. V4 notes live under [`docs/finance-ai/V4_Tasks/`](V4_Tasks/).
3. Richer LLM Investment Agent synthesis over portfolio, sentiment, policy, and
   memory packets.
4. Pinecone/local long-term memory after audit and source-precedence rules are
   clear.
5. Richer React/TypeScript frontend after backend contracts settle.

GraphRAG should be designed against the V2 `SentimentTask` and
`SentimentPacket` contract, not as a separate research demo.

## V4 Planning Track

V4 notes live under [`docs/finance-ai/V4_Tasks/`](V4_Tasks/).

V4 should focus on structured planning for the Investment Agent and Portfolio
Agent:

- Investment Agent planner: classify user intent, decide subagents, set broad
  ticker/theme/time-horizon scope, choose freshness requirement, and provide
  synthesis constraints.
- Portfolio Agent planner: choose portfolio task type, portfolio ticker/asset
  scope, history window, SQL history tools, metric groups, current-value
  dependency, position-state-change scope, and persistence mode.
- Deterministic policy: validate plans, enforce MCP permissions, enforce
  freshness, execute OpenD/SQL/metric tools, calculate portfolio math, and
  write SQL history.

Sentiment Agent implementation is not part of V4. The Investment Agent may
continue to emit future-compatible sentiment tasks, but real Neo4j GraphRAG
retrieval remains a later track.
