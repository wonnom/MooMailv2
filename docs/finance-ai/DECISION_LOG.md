# Project History and Decision Log

This file is the durable project memory for the personal Finance AI build. It
captures the design decisions, implementation reality, tradeoffs, and lessons
learned as the project evolves.

Update this file after each major version, implementation closeout, or design
review. It is intentionally written so it can be pasted into an LLM later for a
fast recap before interviews, presentations, or future planning sessions.

Do not store secrets, account numbers, credentials, private broker IDs, raw
holdings exports, or hidden model reasoning in this file.

## How To Update

For every version or meaningful design session, add:

- Date
- Goal
- Design intent
- Actual implementation
- Decisions made
- Tradeoffs accepted
- Tests or verification
- Open questions
- Lessons learned

The most useful updates are honest about gaps between design and actual
implementation. This project uses that gap as learning material, not as a
failure signal.

## Current Snapshot

Date: 2026-06-29

Current status:

- V1.1 is complete as a Portfolio Agent proof of concept with OpenD and local SQL
  portfolio history.
- V1.2 skeleton is complete: the thin LangGraph Investment Agent supervisor,
  bounded-planning Portfolio Agent path, Sentiment Agent stub, deterministic
  guardrails, sanitized trace, and deterministic test coverage are implemented.
- V1.3.2 gateway modes are complete: `DirectToolGateway` exists for parity tests
  and `StdioMCPToolGateway` uses the official MCP client against FastMCP stdio
  servers.
- V1.3.3 deterministic portfolio data lane is complete: backend APIs and the
  frontend dashboard can load status, latest SQL-backed dashboard data, manual
  refresh, metrics, canonical SQL updates, and stale fallback without invoking
  agents or LLMs.
- V1.3.4 agent gateway migration is complete: Portfolio Agent and Investment
  Agent now use the backend `MCPToolGateway`; `StdioMCPToolGateway` is the
  default local runtime and `DirectToolGateway` remains test/dev parity support.
- V1.4 is complete: typed planner contracts, deterministic asset
  resolution/validation, live Investment Agent `InvestmentPlan` planning,
  Portfolio Agent `PortfolioEvidencePlan` planning, deterministic evidence-plan
  execution, separated `PortfolioEvidencePacket` output, and trace/evaluation
  closeout are implemented.
- The root `README.md` is used for GitHub visibility.
- Detailed design docs live under `docs/finance-ai/`.
- Historical V1.1 task tracking lives under `docs/finance-ai/V1_1_Tasks/`.
- V1.2 task maps and closeout notes live under `docs/finance-ai/V1_2_Tasks/`.
- V1.3 MCP runtime task maps live under `docs/finance-ai/V1_3_Tasks/`.
- V1.4 structured planning notes live under `docs/finance-ai/V1_4_Tasks/`.
- The canonical portfolio database is `data/portfolio-history.sqlite`.
- Trading remains fully out of scope.

## Version Map

| Version | Status | Meaning |
| --- | --- | --- |
| Concept / V0 | Complete | Architecture interview, requirements, agent boundaries, and tool-store choices. |
| V1.1 | Complete | Portfolio Agent POC with OpenD, canonical local SQL history, deterministic metrics, MCP boundaries, terminal path, and local chat frontend. |
| V1.2 | Complete skeleton | LangGraph Investment Agent supervisor, bounded-planning Portfolio Agent path, Sentiment Agent stub, contracts, deterministic synthesis, guardrails, sanitized trace, and tests. |
| V1.3.0 | Complete | MCP backend boundary definition for deterministic app flows and agentic analysis flows. |
| V1.3.1 | Complete | FastMCP server migration for OpenD, portfolio SQL, and finance metrics while preserving Python business logic. |
| V1.3.2 | Complete | Gateway modes: direct parity adapter and stdio MCP client runtime with permission profiles. |
| V1.3.3 | Complete | Deterministic portfolio data lane for backend APIs and frontend dashboard refresh independent from agent runs. |
| V1.3.4 | Complete | Portfolio Agent and Investment Agent migrated to the gateway runtime; legacy custom stdio removed from runtime code. |
| V1.4 | Complete | Structured Investment/Portfolio planning, deterministic asset resolution, policy-aware evidence execution, separated evidence packets, trace/evaluation closeout, and docs/tests. |

## Timeline

### 1. Initial Product Concept

Goal:

Build a personal multi-agent Finance AI focused on the user's own investments.

Original target architecture:

```text
Main Finance Orchestrator
  -> Budgeting / Expenses / Savings Agent
  -> Investment Agent
      -> Portfolio Agent
      -> Sentiment Agent
```

Early scope decisions:

- Build the Investment Agent branch first.
- Defer the Budgeting / Expenses / Savings Agent.
- Defer the main finance orchestrator.
- Never allow trade placement.
- Use the system for analysis, source-backed reasoning, portfolio breakdowns,
  and optimization guidance, not execution.

Important user preferences:

- The system should emphasize the user's real holdings, not generic market
  commentary.
- Outputs should adapt to the user's query.
- Financial modelling and metric calculators should be available as tools.
- The final system should be source-backed and truthful.
- No confidence score is needed; uncertainty should be expressed through
  missing data, source quality, limitations, and assumptions.

Learning note:

The first major architecture insight was that "multi-agent" should not mean
every component gets full autonomy. The system needs clear ownership boundaries:
the Investment Agent reasons across domains, while specialized subagents produce
bounded packets of evidence and analysis.

### 2. Agent Responsibility Design

Finalized target responsibilities:

- Investment Agent:
  - Owns final user-facing investment reasoning.
  - Decides whether a query needs portfolio context, sentiment context, memory,
    or guardrail review.
  - Synthesizes Portfolio Agent and Sentiment Agent outputs.
  - Applies the Investment Policy Statement where recommendations are involved.
  - Owns long-term investment memory in the future.

- Portfolio Agent:
  - Owns quantitative portfolio understanding.
  - Reads current portfolio data from OpenD through MCP.
  - Reads historical portfolio data from the SQL MCP.
  - Calls deterministic finance metric tools.
  - Produces holdings, allocation, concentration, liquidity, risk, and history
    analysis.
  - May suggest tickers or themes that deserve sentiment review.
  - Must not directly call the Sentiment Agent.

- Sentiment Agent:
  - Owns qualitative research and sentiment retrieval.
  - Future implementation should use curated documents and GraphRAG.
  - Should retrieve source-backed evidence from filings, earnings documents,
    stakeholder letters, transcripts, and curated research.
  - Must not fabricate sentiment when retrieval is unavailable.

Key decision:

The Portfolio Agent does not decide whether sentiment is needed. It can identify
candidate tickers or issues, but the Investment Agent decides whether to invoke
the Sentiment Agent. This keeps cross-domain orchestration in one place.

Learning note:

Agent boundaries are cleaner when each agent owns a type of truth. Portfolio
truth is numeric and account-derived. Sentiment truth is document-derived.
Investment reasoning is synthesis over both.

### 3. Storage And Memory Separation

Finalized store separation:

- Portfolio SQL:
  - Source of truth for portfolio history.
  - Stores account, asset, position-state, value-snapshot, allocation-weight,
    data-quality, and run-summary records.

- Neo4j GraphRAG:
  - Future research graph for documents, entities, events, topics, and
    relationships.
  - Separate from portfolio history.

- Pinecone / long-term memory:
  - Future Investment Agent memory for durable summaries, preferences,
    investment theses, prior review summaries, and observations.
  - Separate from both the portfolio SQL database and Neo4j research graph.

Key decisions:

- Neo4j research retrieval and Pinecone investment memory should not be merged.
- Portfolio Agent and Sentiment Agent should not directly access Pinecone.
- Pinecone memory should not override current portfolio data, IPS rules, or
  cited source data.
- Store only a simple summary of run outputs, not the entire final answer.
- The system does not need to learn whether prior recommendations were "right"
  based on later news. It needs sound reasoning and source-backed data at the
  time of analysis.

Learning note:

Different data stores represent different epistemic roles. A portfolio database
is a financial record, GraphRAG is an evidence system, and long-term memory is
personal context. Mixing them would make provenance and precedence harder to
reason about.

### 4. Tooling And MCP Direction

MCP design intent:

Use MCP as the backend boundary between application services, agents, and
tools/resources. MCP servers expose read-only broker access, portfolio history,
finance metric calculators, future research retrieval, and future memory tools.

V1.3.0 clarification:

MCP is backend infrastructure, not only an LLM-agent tool surface. OpenD MCP is
the standardized backend data boundary for both deterministic dashboard
refresh/status flows and agentic portfolio analysis flows. The frontend calls
backend APIs only; the backend owns MCP client/host lifecycle, gateway
permissions, timeouts, traces, and sanitized errors.

Implemented V1.1 MCP surfaces:

- `moomail-opend-mcp`
  - Read-only OpenD/MooMoo access.
  - Retrieves account funds, positions, quotes where supported, and normalized
    portfolio context.

- `moomail-portfolio-sql-mcp`
  - SQLite portfolio-history access.
  - Initializes schema, upserts portfolio data, reads history, records runs,
    and reports data-quality events.

- `moomail-finance-metrics-mcp`
  - Deterministic finance metric calculations.
  - Handles allocation, concentration, liquidity, cash-equivalent treatment,
    and portfolio diagnostics.

V1.1 implementation reality at the time:

- MCP-style tool modules and stdio JSON-RPC servers exist.
- The current V1.1 Portfolio Agent calls the MCP modules in process.
- The current V1.1 Portfolio Agent is MCP-backed but not MCP-autonomous.
- An official MCP SDK/client-host runtime migration is deferred.

Current V1.3.4 reality:

- The three local MCP server scripts run FastMCP over stdio.
- Backend consumers call tools through `MCPToolGateway`.
- `PortfolioDataService` uses the gateway as `dashboard_refresh`.
- `PortfolioAgent` uses the gateway as `portfolio_agent`.
- `InvestmentAgent` calls a gateway-backed Portfolio Agent by default.
- The old custom `JsonRpcMCPServer` has been removed from runtime code.

Key decision:

Use specific tool allowlists by agent, rather than giving every agent access to
one central unrestricted tool server. This keeps permissions clear and makes it
easier to reason about what each agent can do.

Learning note:

Having MCP servers is not the same thing as having an autonomous tool-calling
agent. A deterministic Python workflow can call MCP tools, but an LLM only
"chooses" tools if the runtime gives it a planning/tool-calling loop.

V1.3 learning note:

Having MCP servers is also not the same thing as saying only agents can use MCP.
Some OpenD calls are application infrastructure: connection checks, current
funds/positions retrieval, portfolio normalization, metrics calculation, SQL
history updates, and dashboard freshness should be deterministic backend flows.

### 5. OpenD Exploration And Hardening

OpenD operating reality:

- OpenD must be manually opened and logged in by the user.
- The local gateway port must be configured.
- The selected security firm for the live setup is `FUTUSG`.
- OpenD is treated as read-only.

Important OpenD findings:

- `accinfo_query()` returns account-level funds fields.
- `position_list_query()` returns positions.
- The funds fields are not a separate `funds` table from OpenD; they are
  normalized into the project's own portfolio context.
- OpenD quote retrieval may reject unsupported symbols, such as OTC `US.TCEHY`,
  while still returning the position row.
- Crypto holdings under a separate crypto cash/account surface are not part of
  the V1.1 securities-account ingestion.
- Auto-invested USD money market fund assets can be treated as effective cash
  only when explicitly enabled in local config.

Implementation decisions:

- Unsupported quotes are warnings, not fatal errors, when the position itself is
  available.
- The OpenD adapter should prefer partial success over all-or-nothing failure.
- A recorded/local report path is useful during development so repeated tests do
  not constantly call OpenD.
- Live connector tests remain opt-in.

Learning note:

Broker APIs often expose account reality in product-specific shapes. The project
should normalize those shapes into its own domain model, but the docs must stay
honest about what comes from OpenD versus what the project derives.

### 6. Portfolio SQL Design Review

Original worry:

The database should not become a bloated warehouse full of duplicated raw broker
payloads or quote history that the project does not need.

Final V1.1 SQL principles:

- Store portfolio history, not broad market history.
- Store enough to reconstruct portfolio evolution.
- Avoid storing full raw OpenD observations.
- Avoid storing full quote history for every holding.
- Avoid storing hidden model reasoning.
- Keep daily value snapshots compact.
- Keep position states compact and change-aware.

Final table design:

- `portfolios`
  - Portfolio identity and configuration.

- `broker_accounts`
  - Broker/account identity within the portfolio.

- `assets`
  - Asset identity, ticker, name, asset type, currency, exchange, and aliases
    where needed.

- `position_states`
  - Compact observed position states.
  - New rows are inserted when economically meaningful position fields change,
    such as quantity, average cost, side, or asset identity.
  - If only market price changes, the row can update market fields and
    `last_observed_at`.

- `portfolio_value_snapshots`
  - Daily account/portfolio value snapshots.
  - Stores total assets, securities value, literal cash, fund assets, effective
    cash, market value, unrealized P/L, realized P/L, and source timestamps.
  - One row per portfolio/account/date/scope, updated for same-day refreshes.

- `portfolio_weight_snapshots`
  - Allocation weights by asset for each value snapshot.
  - Stores weights from the metric calculation state so historical portfolio
    composition can be reviewed without storing full price histories.

- `data_quality_events`
  - Missing quotes, unsupported symbols, stale data, OpenD partial failures, and
    other quality warnings.

- `agent_runs`
  - Run metadata, query, status, guardrail result, and simple output summary.

- `agent_run_sources`
  - Links a run to source records such as snapshots, positions, data-quality
    events, and tool reports.

Rejected storage ideas:

- Raw source observation table for every OpenD response.
- Broad quote history warehouse.
- Margin fields, risk level/status, per-currency cash/asset fields, and
  `available_funds` in account-level history.
- Derived metric metadata fields such as metric version and input scope.
- Full final responses in the DB.

Key decision:

Position weights should be stored in `portfolio_weight_snapshots`, derived from
metric calculations at snapshot time. This preserves historical allocation
without requiring the database to store every price change for every holding.

Learning note:

For a personal portfolio project, the useful history is often "what did my
portfolio look like and how did it change?" not "what was every asset price at
every moment?" The schema should match the intended analysis.

### 7. One Canonical Database Architecture

Issue discovered:

Two SQLite databases existed during the prototype:

- `data/portfolio-history.sqlite`
- `data/chat-portfolio-history.sqlite`

The second database was created by prototype chat defaults and accidentally
continued to store portfolio data from chat runs.

Decision:

Use one canonical portfolio database: `data/portfolio-history.sqlite`.

Implementation outcome:

- Chat backend defaults were shifted to the canonical database.
- Terminal and chat paths now point at the same portfolio-history store.
- Existing useful chat history was migrated/archived rather than treated as a
  separate source of truth.
- Docs now describe a one-DB architecture.

Learning note:

Prototype defaults can silently become product architecture. Data paths need to
be treated as design decisions, not incidental configuration.

### 8. Portfolio Agent V1.1 Implementation

V1.1 implemented flow:

```text
User query
  -> Portfolio Agent service
      -> initialize SQL
      -> retrieve current OpenD portfolio context
      -> normalize funds, positions, quotes, and warnings
      -> calculate deterministic metrics
      -> persist compact portfolio history
      -> read configured history slices
      -> call portfolio-only LLM evaluator
      -> stream trace/events to terminal or local chat UI
```

Current behavior:

- The Portfolio Agent uses deterministic orchestration.
- The LLM evaluator answers from the collected portfolio packet.
- The LLM does not independently decide which MCP tools to call.
- Query-specific behavior is limited because the tool sequence is mostly fixed.
- This is acceptable for V1.1 because V1.1 is a proof of concept, not the final
  Investment Agent architecture.

Designed versus actual:

- Designed target: autonomous Investment Agent decides which subagents and tools
  are needed.
- Actual V1.1: deterministic Portfolio Agent path retrieves broad current context
  and then asks an LLM evaluator to summarize/analyze it.
- Designed target: Portfolio Agent is a subagent under Investment Agent.
- Actual V1.1: Portfolio Agent can be called directly by CLI/chat for portfolio
  review.

Learning note:

The V1.1 agent is best understood as a deterministic workflow with an LLM
evaluation step. That is still valuable because it hardens the data layer,
normalization, metrics, and frontend trace before adding more autonomy.

### 9. Frontend And Local Interaction

Frontend direction chosen:

- Keep frontend minimal until backend contracts are stable.
- Use local terminal and static chatbot paths for V1.
- Do not build a richer React/TypeScript frontend until V1.2 contracts are
  clearer.

Implemented frontend capabilities:

- Chat-style input at the bottom.
- Send button instead of a run button.
- Resizable and hideable chat rail.
- Portfolio report panels.
- Allocation bar sorting.
- Pie chart allocation view.
- Streaming status/audit messages.
- Technical trace.
- Backend stream errors rendered in the chat and trace instead of silently
  hanging.

Learning note:

The frontend should expose what the backend actually knows and does. In this
project, trace output is not decoration; it is part of learning and debugging
agentic systems.

### 10. Guardrails And Safety

Core guardrail decisions:

- No trade placement.
- No order modification.
- No order cancellation.
- No executable order-preparation path.
- No exact share-count recommendations.
- No unsupported research claims.
- No unsupported portfolio facts.
- Missing critical portfolio data blocks portfolio recommendations.
- Missing research data must be stated clearly.
- IPS is required for optimization/rebalancing recommendations.

Implementation reality:

- V1.1 has no trading tools.
- MCP surfaces are read-only or analysis-only.
- V1.1 guardrail behavior is present around output framing and tool scope.
- V1.2 moves final guardrail review into the Investment Agent path as a structured
  graph node.
- V1.2 guardrails are deterministic and cover no-trading, no exact share-count
  instructions, unsupported research claims, unsupported portfolio facts,
  missing IPS for optimization/rebalancing framing, and missing sentiment
  limitation visibility.

Learning note:

Finance guardrails are not only about preventing trades. They also need to
control unsupported claims, stale data, missing evidence, and recommendation
framing.

### 11. LangChain, LangGraph, And Agentic Design Understanding

Clarified distinction:

- LangChain provides building blocks:
  - model calls
  - tools
  - prompts
  - retrievers
  - structured outputs
  - chains

- LangGraph provides graph orchestration:
  - state
  - routing
  - loops
  - branching
  - checkpointing
  - streaming graph progress
  - supervisor/subgraph patterns

Project interpretation:

- Deterministic Python code in V1.1 acts as the orchestration spine.
- LangChain could still be deterministic if used as a fixed chain.
- Autonomy comes from giving a model a planning/tool-selection role, but that
  autonomy should be bounded by schemas, state, and allowed tools.
- LangGraph is the better next step for this project because the desired V1.2
  shape is a supervisor with subgraphs and controlled routing.

Key decision:

Build the thin LangGraph Investment Agent before building the full Neo4j
GraphRAG Sentiment Agent. The Investment Agent will cement the contracts the
future Sentiment Agent must satisfy.

Learning note:

GraphRAG should be designed against the agent contract that will consume it.
Building the graph first risks optimizing the retrieval system for unclear
downstream needs.

### 12. V1.1 Closeout

V1.1 definition:

V1.1 is complete when the local app can run a portfolio-only review from OpenD,
persist compact local SQL history, calculate deterministic metrics, and show
results in terminal and web UI without any trading capability.

Implemented:

- Read-only OpenD adapter.
- OpenD MCP surface.
- Portfolio SQL MCP surface.
- Finance metrics MCP surface.
- One canonical SQLite portfolio-history database.
- Compact SQL schema.
- Current holdings, cash, effective cash sweep, allocation, concentration, and
  risk diagnostics.
- Unsupported quote warnings.
- Portfolio-only LLM evaluator with structured-output recovery.
- Agent run summaries and source links.
- Terminal review script.
- Local static chat frontend.

Latest recorded verification:

- Deterministic suite: `77 passed, 10 skipped`
- Live OpenD-only connector gate: `2 passed, 1 warning`

Known V1.1 limitations:

- Portfolio Agent is deterministic, not a planning subgraph.
- Investment Agent is not yet the target LangGraph supervisor.
- Sentiment Agent is a stub/placeholder.
- Neo4j GraphRAG is not implemented.
- Pinecone memory is not connected.
- Crypto account ingestion is deferred.
- OTC quote fallback provider is deferred.
- Official MCP SDK/client runtime migration is deferred.
- Rich React frontend migration is deferred.

### 13. V1.2 Direction

V1.2 goal:

Turn the V1.1 Portfolio Agent POC into the first real Investment Agent
architecture.

Planned V1.2 flow, now implemented as the V1.2 skeleton:

```text
User query
  -> Investment Agent LangGraph supervisor
      -> classify query and load relevant policy context
      -> decide whether portfolio context is needed
      -> decide whether sentiment context is needed
      -> call Portfolio Agent bounded-planning path
      -> call Sentiment Agent stub when needed
      -> synthesize answer
      -> run guardrail review
      -> return structured response and trace
```

Portfolio Agent V1.2 direction:

- Convert current deterministic flow into a bounded-planning path. The current
  implementation is not a separate compiled LangGraph subgraph.
- Planner decides:
  - whether current OpenD is needed
  - whether SQL history is needed
  - which history window or row limits are relevant
  - which tickers/assets are relevant
  - which metric groups are needed
  - whether persistence should happen
- Execution remains deterministic after the plan is selected.

Sentiment Agent V1.2 direction:

- Implement a stub, not real GraphRAG yet.
- Accept the future task shape:
  - tickers
  - companies/entities
  - research reasons
  - time window
  - requested evidence types
  - key questions
- Return a structured response with `retrieval_status: not_implemented`.
- Never fabricate research.

Designed versus planned actual:

- V1.2 is not trying to finish the full investment research system.
- V1.2 is trying to prove the orchestration pattern, contracts, trace, and
  guardrail placement.
- GraphRAG and Pinecone should come after the Investment Agent contracts are
  stable.

### 14. V1.2 Closeout / 2026-06-15

Goal:

Close the V1.2 skeleton by making the V1.1 Portfolio Agent POC usable through a
real LangGraph Investment Agent supervisor, with structured subagent contracts,
missing-research behavior, guardrails, trace, and deterministic tests.

Actual implementation:

- Added V1.2 Pydantic contracts in `src/moomail_finance_ai/agent_schemas.py`.
- Added `InvestmentAgent` in `src/moomail_finance_ai/investment_agent.py`
  as a real LangGraph `StateGraph`.
- Routed portfolio-only and portfolio-plus-sentiment queries through structured
  `InvestmentQueryPlan`, `PortfolioTask`, and `SentimentTask` objects.
- Added bounded Portfolio Agent context planning to the existing Python
  Portfolio Agent path.
- Added `SentimentAgentStub`, which returns
  `retrieval_status: not_implemented`, explicit missing research documents, no
  citations, no holdings, and no sentiment stance.
- Added deterministic V1.2 guardrails in `investment_guardrails.py`.
- Added sanitized public trace helpers in `agent_trace.py`.
- Added chat and terminal V1.2 output paths.
- Added V1.2 deterministic tests and fixtures.

Designed versus actual:

- Designed target: Portfolio Agent as a bounded-planning LangGraph subgraph.
  Actual V1.2: bounded planning is implemented inside the existing Python
  Portfolio Agent path, not as a separate compiled graph.
- Designed target: Investment Agent synthesizes portfolio, sentiment, memory,
  and current market outlook. Actual V1.2: synthesis is
  deterministic/template-style, with missing-research limitations surfaced.
- Designed target: Sentiment Agent uses Neo4j GraphRAG. Actual V1.2: Sentiment
  Agent is a deterministic stub to lock contracts before retrieval work.
- Designed target: long-term memory through Pinecone. Actual V1.2: memory remains
  disconnected.
- Designed target: MCP server/tool runtime behind each agent. Actual V1.2:
  MCP-style modules and stdio servers exist, but agent calls are still
  in-process rather than through an official MCP client/host runtime.

Verification:

- Deterministic closeout command:
  `.venv/bin/python -m pytest tests --ignore=tests/live -q`
- Latest V1.2 closeout result:
  `156 passed, 1 warning`
- The warning is a LangGraph dependency deprecation warning.
- Live connector tests remain opt-in under `tests/live/`.

Lessons learned:

- Building the Investment Agent skeleton before GraphRAG clarified the exact
  input/output contract research retrieval must satisfy.
- Deterministic planners are useful as a scaffold, but richer query
  interpretation will likely need a bounded structured-output LLM planner later.
- Trace is part of the product. It should show operational truth without
  exposing hidden reasoning, prompts, secrets, or raw account identifiers.
- Closing V1.2 honestly means marking stubs as stubs, not dressing them up as
  finished research features.

### 15. V1.3.2 And V1.3.3 Closeout / 2026-06-21

Goal:

Move MCP from a custom/in-process tool shape toward a real backend runtime
boundary, and implement the deterministic portfolio data lane separately from
agent analysis.

Actual implementation:

- `src/moomail_finance_ai/mcp/gateway.py` now implements:
  - `MCPToolGateway`
  - `DirectToolGateway`
  - `StdioMCPToolGateway`
  - `GatewayManager`
  - local stdio server configuration helpers
  - gateway result/error models
  - permission profiles for `dashboard_refresh`, `portfolio_agent`,
    `investment_agent`, and `sentiment_agent`
- `StdioMCPToolGateway` uses the official MCP Python client against FastMCP
  stdio servers and reuses sessions instead of spawning a server per tool call.
- `dashboard_refresh` can call OpenD status/context, finance metrics, and SQL
  dashboard update/read tools.
- `investment_agent` is denied direct OpenD by default.
- Trade/order-like tool names are globally denied.
- `src/moomail_finance_ai/portfolio_data_service.py` owns deterministic
  portfolio status, latest-dashboard, and refresh flows.
- `scripts/serve_chat.py` exposes:
  - `GET /api/portfolio/status`
  - `GET /api/portfolio/dashboard`
  - `POST /api/portfolio/refresh`
- The static frontend loads stored dashboard data on page load, checks OpenD
  status independently, and has a manual refresh button that calls the
  deterministic backend API.
- Refresh pulls OpenD context, calculates metrics, updates canonical SQL
  history, and returns dashboard-ready state without constructing Portfolio
  Agent, Investment Agent, Sentiment Agent, or an LLM evaluator.
- Refresh failures return stale last-known SQL dashboard data when available
  plus a sanitized error.

Designed versus actual:

- Designed target: all agents use the MCP gateway. Actual V1.3.3: the
  deterministic dashboard lane used the gateway, while agent migration was
  intentionally deferred to V1.3.4. V1.3.4 later moved Portfolio Agent and V1.2
  Investment Agent to the gateway.
- Designed target: frontend eventually becomes a richer app. Actual V1.3.3:
  static TypeScript/JavaScript frontend now has the correct backend lane and
  refresh behavior, but it is still not a React app.
- Designed target: delete old MCP wrappers after migration. Actual V1.3.3:
  no MCP tools or legacy wrappers were deleted because agent migration was not
  complete yet.

Verification:

```text
.venv/bin/python -m pytest tests/test_mcp_gateway.py tests/test_mcp_stdio_gateway.py tests/test_mcp_gateway_contract.py tests/test_portfolio_data_service.py tests/test_chat_app.py -q
22 passed, 1 warning
```

Lessons learned:

- MCP is useful as a backend boundary for deterministic services, not only as an
  LLM tool surface.
- Page-load dashboard freshness should be application infrastructure. It should
  not depend on an LLM planner deciding whether OpenD is needed.
- The correct split is now:
  - frontend calls backend APIs
  - deterministic backend services own refresh/status/dashboard state
  - agents own analytical reasoning
  - MCP servers remain shared read-only/analysis tool boundaries

### 16. V1.3.4 Agent Gateway Migration / 2026-06-23

Goal:

Complete the V1.3 MCP runtime migration by moving analytical agents onto the same
backend gateway used by the deterministic portfolio data lane.

Actual implementation:

- `PortfolioAgent` now receives a single `MCPToolGateway` dependency instead
  of direct `RegisteredMCPModule` instances.
- Portfolio Agent tool calls now go through `gateway.call_tool(...,
  consumer="portfolio_agent")`.
- `build_default_portfolio_agent()` defaults to `StdioMCPToolGateway` over the
  local FastMCP server configs.
- `DirectToolGateway` remains available for deterministic tests and migration
  parity only.
- `build_default_investment_agent()` constructs a gateway-backed Portfolio
  Agent unless a fake/injected subagent is supplied for tests.
- `ChatService` owns one shared backend gateway for portfolio chat, investment
  chat, and deterministic portfolio dashboard APIs.
- Terminal scripts close gateway sessions after runs.
- `JsonRpcMCPServer` has been removed; the runtime boundary is FastMCP plus the
  official MCP client through `StdioMCPToolGateway`.
- FastMCP/gateway handling supports list-valued tool payloads, such as finance
  metric lists, by parsing JSON text fallback when the MCP SDK cannot place the
  list in `structuredContent`.

Designed versus actual:

- Designed target: agents consume tools through the gateway. Actual V1.3.4:
  Portfolio Agent and Investment Agent now use the gateway path.
- Designed target: Investment Agent has direct dynamic tool planning. Actual
  V1.3.4: the thin Investment Agent still routes to subagents; Portfolio Agent
  remains the live portfolio retrieval owner.
- Designed target: retire old custom MCP runtime. Actual V1.3.4:
  `JsonRpcMCPServer` was later removed, while the `RegisteredMCPModule`
  registry remains underneath FastMCP and `DirectToolGateway` parity tests.

Verification:

```text
.venv/bin/python -m pytest tests/test_mcp_stdio_gateway.py tests/test_portfolio_agent.py tests/test_portfolio_planner.py tests/test_investment_agent.py tests/test_chat_app.py tests/test_portfolio_data_service.py -q
39 passed, 1 warning

.venv/bin/python -m pytest tests --ignore=tests/live -q
183 passed, 1 warning
```

Lessons learned:

- The gateway is now the right dependency boundary for agents and deterministic
  backend services. Business logic should remain plain Python underneath it.
- Direct in-process module calls are still useful for parity tests, but they
  should not be the application runtime dependency.
- The deterministic portfolio data lane and analytical agent lane can share the
  same MCP servers without becoming the same workflow.

## Major Decisions

### No Trading, Ever

The system must never place trades or expose hidden trade execution paths.
MooMoo/OpenD is used for read-only portfolio retrieval only.

### Investment Agent Owns Cross-Agent Routing

Portfolio Agent should not call Sentiment Agent. Sentiment requests are selected
by the Investment Agent based on the user's query, Portfolio Agent packet, and
missing-context needs.

### Bounded Planning Over Open-Ended Autonomy

The system should add autonomy only where it improves query handling. For
finance, model planning should produce structured plans, then deterministic code
should execute the data retrieval, calculations, persistence, and guardrails.

### Portfolio History Is Not Quote History

The SQL database stores portfolio evolution. It does not attempt to become a
general stock price database.

### Memory, Portfolio History, And Research Are Separate

Portfolio SQL, Neo4j GraphRAG, and Pinecone memory have different purposes and
different precedence rules.

### Current Backend Contracts Come Before Rich Frontend Work

The frontend should not assume final data shapes before the agent contracts are
stable. The local chat UI is useful for exercising contracts, but backend
orchestration remains the source of truth.

## Implementation Artifacts

Important current files and areas:

- `README.md`
  - GitHub-facing overview.

- `docs/finance-ai/`
  - Detailed architecture, requirements, protocol, MCP, testing, and planning
    docs.

- `docs/finance-ai/V1_1_Tasks/`
  - Historical V1.1 implementation tracking and closeout.

- `docs/finance-ai/V1_2_Tasks/`
  - V1.2 skeleton task maps and closeout notes.

- `docs/finance-ai/V1_3_Tasks/`
  - V1.3 MCP runtime, deterministic portfolio data lane, and gateway migration
    task maps.

- `docs/finance-ai/V1_4_Tasks/`
  - V1.4 structured planning notes for Investment Agent and Portfolio Agent.

- `src/moomail_finance_ai/portfolio_agent.py`
  - Portfolio Agent deterministic orchestration, bounded context planning, and
    LLM evaluator path.

- `src/moomail_finance_ai/investment_agent.py`
  - Thin LangGraph Investment Agent supervisor.

- `src/moomail_finance_ai/agent_schemas.py`
  - Agent state, task, packet, synthesis, guardrail, and trace contracts.

- `src/moomail_finance_ai/sentiment_agent_stub.py`
  - Missing-research Sentiment Agent stub.

- `src/moomail_finance_ai/investment_guardrails.py`
  - Deterministic investment output guardrails.

- `src/moomail_finance_ai/agent_trace.py`
  - Sanitized operational trace helpers.

- `src/moomail_finance_ai/opend_adapter.py`
  - Read-only OpenD interaction.

- `src/moomail_finance_ai/opend_portfolio.py`
  - OpenD portfolio normalization.

- `src/moomail_finance_ai/sql_store.py`
  - Canonical SQLite portfolio-history schema and persistence.

- `src/moomail_finance_ai/mcp/opend_mcp.py`
  - OpenD MCP tool surface.

- `src/moomail_finance_ai/mcp/portfolio_sql_mcp.py`
  - Portfolio SQL MCP tool surface.

- `src/moomail_finance_ai/mcp/finance_metrics_mcp.py`
  - Finance metrics MCP tool surface.

- `scripts/portfolio_agent_review.py`
  - Terminal review path.

- `scripts/investment_agent_review.py`
  - Terminal Investment Agent review path.

- `scripts/serve_chat.py`
  - Local chat frontend server.

- `data/portfolio-history.sqlite`
  - Canonical local portfolio-history database.

## V1.2 Task 3 Closeout / 2026-06-13

Goal:

- Convert the Portfolio Agent from a fixed broad workflow into a bounded
  planner that can minimize tool usage for narrow questions while keeping
  broad-review behavior available.

Actual implementation:

- Added `interpret_portfolio_task(query)` for direct Portfolio Agent calls.
- Added `plan_portfolio_context(task)` for schema-validated
  `PortfolioContextPlan` generation.
- Updated `MCPPortfolioAgent.run()` to accept an optional `PortfolioTask` from
  the Investment Agent and execute deterministic helper nodes from the plan.
- Preserved broad context and SQL persistence for full review and deep-dive
  tasks.
- Let cash/allocation/holding fact tasks skip broad SQL history and persistence
  by default.
- Let what-changed tasks request history status, latest state, portfolio
  growth, and allocation history.
- Added planned, actual, and skipped tool trace entries to
  `PortfolioAgentResult.tool_calls` and carried them into the V1.2 portfolio
  packet.

Tradeoffs accepted:

- Metric execution still uses the existing broad `calculate_snapshot_metrics`
  MCP tool. The trace records the requested metric groups and that broad
  snapshot metrics were used until granular metric MCP tools exist.
- The Portfolio Agent planner is deterministic keyword/task based rather than
  LLM-planned. This keeps autonomy bounded and testable.

Verification:

- Added `tests/test_portfolio_planner.py`.
- Updated Portfolio Agent, V1.2 Investment Agent, and chat tests.
- Full deterministic suite passed with live tests excluded.

## V1.3.0 MCP Backend Boundary / 2026-06-17

Goal:

- Define MCP as backend infrastructure before migrating the custom MCP-shaped
  runtime to FastMCP and an official MCP client/gateway.

Design intent:

- OpenD MCP should be the standardized backend boundary for MooMoo/OpenD data
  access.
- Deterministic dashboard/status/refresh flows and agentic analysis flows
  should share the same read-only, permissioned, tested MCP interface.
- The frontend should never call MCP directly. It should call backend APIs, and
  the backend should own MCP client/host lifecycle, gateway permissions,
  timeouts, traces, and sanitized errors.

Decisions made:

- Add a deterministic portfolio data lane for app startup, page load, and manual
  refresh.
- Keep the agentic analysis lane separate: Investment Agent plans subagent
  calls, Portfolio Agent uses the gateway for portfolio context, and Sentiment
  Agent/future research tools are invoked when relevant.
- Define backend contract shapes for `PortfolioConnectionStatus`,
  `PortfolioDashboardSnapshot`, and `PortfolioRefreshResult`.
- Define gateway consumers: `dashboard_refresh`, `portfolio_agent`,
  `investment_agent`, and `sentiment_agent`.
- Deny direct OpenD access to `investment_agent` by default; live portfolio
  retrieval remains owned by Portfolio Agent unless deliberately changed later.
- Keep all gateway profiles read-only or analysis-only. No trade placement,
  trade unlock, order modification, cancellation, withdrawal, transfer, or
  executable order-preparation tools are allowed.

Designed versus actual:

- Designed target: backend-owned MCP client/gateway shared by deterministic
  services and agents.
- Current actual: V1.2 still uses in-process `RegisteredMCPModule` objects and
  custom stdio JSON-RPC wrappers. FastMCP servers, official MCP client sessions,
  and dashboard refresh APIs are not implemented yet.

Verification:

- Updated `ACTION_PLAN.md`, `ARCHITECTURE.md`, `MCP_SERVERS.md`, and V1.3 task
  maps.
- Updated docs regression coverage in `tests/test_v3_planning_docs.py`.

Lessons learned:

- MCP should be treated as a permissioned backend data boundary, not as a thing
  that only LLM agents call.
- Dashboard freshness should not wait for LLM planning. It is application
  infrastructure.
- Defining deterministic backend consumers before the FastMCP migration reduces
  the risk of building an agent-only runtime that later has to be reworked for
  the web dashboard.

Open questions:

- Should the first concrete dashboard API be implemented in the existing
  lightweight chat server or in a new backend service module before a richer
  React frontend exists?
- Should the gateway configuration live in code, local config, or both during
  the early V1.3 implementation?

## V1.3 Planning Adjustment / 2026-06-17

Goal:

- Promote the deterministic portfolio data lane from a design concern into its
  own implementation task.

Decision made:

- Insert V1.3.3 as `Deterministic Portfolio Data Lane`.
- Shift `Agent Gateway Migration` to V1.3.4.
- V1.3.3 must implement backend and frontend refresh/status/dashboard behavior
  without invoking Portfolio Agent, Investment Agent, a sentiment agent, or an
  LLM.

Reason:

- Dashboard freshness is application infrastructure. Page load and manual
  refresh should always be able to retrieve connection status, balances,
  holdings, metrics, warnings, SQL update state, and last-updated metadata
  through backend APIs.
- Agent migration should happen after this lane exists, so the project can prove
  deterministic app consumers and agentic consumers share the gateway while
  staying separate.

Implementation implications:

- Add a backend `PortfolioDataService` or equivalent.
- Add status, latest dashboard snapshot, and manual refresh API routes.
- Update the frontend so refresh uses these APIs rather than submitting an
  agent query.
- Preserve stale last-known dashboard data when refresh fails.
- Add tests proving no agent or LLM is invoked by the deterministic lane.

## V1.3.1 FastMCP Server Migration / 2026-06-17

Goal:

- Replace the custom MCP server script runtime with official FastMCP while
  preserving existing OpenD, SQL, and metrics business logic.

Actual implementation:

- Added `src/moomail_finance_ai/mcp/fastmcp.py` as an adapter from existing
  `RegisteredMCPModule` instances to official FastMCP servers.
- Rewired `scripts/mcp_finance_metrics_server.py`,
  `scripts/mcp_opend_server.py`, and `scripts/mcp_portfolio_sql_server.py` to
  run FastMCP over stdio.
- Promoted `mcp>=1,<2` from optional extra to normal project dependency.
- Added `src/moomail_finance_ai/mcp/gateway.py` with the V1.3 gateway protocol,
  result model, and gateway error types.
- Updated deterministic MCP stdio tests and live MCP connector tests to use the
  official MCP Python client instead of the custom `_MCPStdioClient`.
- Added FastMCP parity tests comparing representative stdio server outputs with
  direct module outputs.

Designed versus actual:

- Designed target: FastMCP servers behind a backend MCP gateway.
- Actual V1.3.1: FastMCP servers exist and the gateway contract exists, but
  concrete gateway modes do not. Agents still call in-process modules until
  V1.3.4.
- `RegisteredMCPModule` remains the single local registry underneath FastMCP so
  business handlers and direct-module tests stay stable during migration.
- `JsonRpcMCPServer` still exists as legacy/custom-wrapper code, but the three
  MCP server scripts no longer use it.
- FastMCP initialize metadata reports the SDK server version; MooMail module
  versions remain available through resources and structured payloads.

Verification:

- Focused MCP suite passed:
  `tests/test_mcp_stdio_round_trips.py`,
  `tests/test_mcp_fastmcp_parity.py`,
  `tests/test_mcp_servers.py`, `tests/test_mcp_tool_contracts.py`, and
  `tests/test_mcp_gateway_contract.py`.
- Live OpenD/FastMCP smoke tests were updated but remain opt-in.

Lessons learned:

- The safest migration path is to adapt the existing tool registry into
  FastMCP, not to bury domain logic inside decorators.
- Official FastMCP stdio uses the SDK/client newline JSON-RPC transport, not
  the project's old custom `Content-Length` helper.
- Server migration and agent migration are separate concerns. FastMCP servers
  can be real before agents consume them through the future gateway.

## Interview And Presentation Talking Points

- The project began as a broad multi-agent finance system, then narrowed
  deliberately to the Investment Agent branch.
- V1.1 focused on real data plumbing and portfolio history before agentic
  autonomy.
- MCP was used as a permissioned tool boundary.
- The OpenD integration taught that broker APIs require careful normalization
  and partial-failure handling.
- The database design intentionally stores portfolio history instead of raw
  broker payloads or market-wide quote history.
- A prototype accidentally created two databases, which was corrected into a
  one-canonical-DB architecture.
- The V1.1 Portfolio Agent is deterministic with an LLM evaluator; that is a
  deliberate stepping stone, not the final agent architecture.
- V1.2 moves orchestration up to a LangGraph Investment Agent supervisor and
  bounded Portfolio Agent planner.
- The Sentiment Agent is stubbed before Neo4j GraphRAG so the retrieval system
  can be designed against stable contracts.
- V1.3 clarifies that MCP is shared backend infrastructure for deterministic
  portfolio data flows and agentic analysis flows.
- Safety is designed at the tool boundary, orchestration layer, and final
  guardrail layer.

## Open Questions

- Should the next phase build Neo4j GraphRAG first, or first add a
  structured-output LLM planner/synthesizer to the Investment Agent?
- During V1.3, should the first concrete dashboard API live in the existing
  lightweight chat server or in a new backend service module?
- During V1.3, should gateway configuration live in code, local config, or both?
- What is the first useful Neo4j graph schema for research documents,
  companies, events, risks, and management commentary?
- When should Pinecone memory be introduced: before or after real GraphRAG?
- What fallback provider should handle unsupported OTC quotes?
- How should crypto holdings be represented if MooMoo exposes them through a
  separate account surface?
- How much of the current local chat UI should survive the future React
  frontend migration?

## V1.4 Planning Note: Structured Agent Planning Boundaries

Date: 2026-06-21, updated 2026-06-24

Decision:

- Treat the current Portfolio Agent regex ticker extraction as a temporary
  bounded-planning fallback, not the intended long-term architecture.
- V1.4 should move ticker/asset-scope selection, history-window choice, task
  type, freshness requirement, subagent selection, and SQL history tool scope
  into explicit planner output.
- Investment Agent owns mission-level planning: user intent, broad scope,
  subagent selection, bounded portfolio request, freshness requirement, and
  final synthesis constraints.
- Investment Agent sends logical ticker/company/asset hints such as `AAPL` or
  `Apple`; it does not need to know broker-specific OpenD symbols such as
  `US.AAPL` or SQL asset ids.
- Portfolio Agent owns portfolio evidence planning: deterministic asset
  resolution, canonical portfolio ticker/asset scope, evidence subtasks,
  history window, metric groups, SQL history scope, current-value dependency,
  persistence mode, and portfolio-only pattern/outlier detection.
- Portfolio Agent should add value as a portfolio analyst assistant by
  surfacing facts, derived metrics, position-state changes, outliers,
  allocation/concentration issues, and limitations that require sentiment or
  fundamental context.
- Deterministic policy owns freshness enforcement, MCP permission checks,
  OpenD/SQL/metric execution, finance math, and persistence.
- Sentiment Agent implementation is out of V1.4 scope; V1.4 may preserve the
  future-compatible task contract only.
- After a plan is selected, MCP tool execution remains deterministic and
  auditable.

Reasoning:

- Hardcoded extraction hidden inside `interpret_portfolio_task()` is easy to
  forget and hard to reason about as the query space grows.
- The Portfolio Agent should decide which ticker history to extract as part of
  portfolio evidence planning, after resolving logical user/Investment Agent
  hints against actual portfolio assets.
- This keeps finance math and SQL reads deterministic while allowing a future
  LangGraph/LangChain planner node to handle less deterministic interpretation.
- Freshness should not be a free-form LLM decision at execution time. The
  planner may request `latest_required`, `cached_ok`, or `history_only`, but a
  deterministic policy should decide whether OpenD must be called.
- Separating portfolio-only interpretation from final investment synthesis
  reduces bias: the Portfolio Agent can say what changed or looks unusual, but
  the Investment Agent combines that with sentiment, fundamentals, IPS, and
  guardrails before producing the final answer.

Follow-up:

- See `docs/finance-ai/V1_4_Tasks/README.md`.
- V1.4 is split into six planned task maps:
  - V1.4.0 planner contracts
  - V1.4.1 asset resolution and validation
  - V1.4.2 Investment Agent planner
  - V1.4.3 Portfolio evidence planner
  - V1.4.4 deterministic execution and evidence packet
  - V1.4.5 trace, evaluation, and closeout

## Version Naming Convention Update

Date: 2026-06-24

Decision:

- Use a single V1.x line for the current local-first Portfolio/Investment Agent
  build instead of treating each iteration as a separate major version.
- Rename the historical iterations as:
  - Original Portfolio Agent POC: V1.1
  - Investment Agent skeleton iteration: V1.2
  - MCP runtime and deterministic data lane iteration: V1.3
  - Structured planning track: V1.4
- Rename task folders to `V1_1_Tasks`, `V1_2_Tasks`, `V1_3_Tasks`, and
  `V1_4_Tasks`.
- Keep runtime class/module names version-neutral where they have already been
  generalized, such as `InvestmentAgent`, `agent_schemas`, `agent_trace`, and
  `investment_guardrails`.

Reasoning:

- The project is still one product line and has not crossed a major-version
  boundary.
- V1.x makes the roadmap read as an incremental stabilization sequence:
  portfolio POC, investment skeleton, MCP runtime, then structured planning.
- Version-neutral code names avoid carrying historical labels into long-lived
  runtime APIs.

## V1.4.2 Closeout: Investment Agent Planner

Date: 2026-06-25

Decision:

- Move the live Investment Agent graph from hidden query classification to a
  typed `InvestmentPlan` planner/validator step before any subagent calls.
- Keep deterministic fallback planning as the implemented planner for local
  tests/offline use, while preserving a planner interface for a future
  structured-output LLM planner.
- Normalize frontend/backend chat agent names so the website may send
  `investment_agent` or `portfolio_agent` while the backend still routes through
  canonical `investment` and `portfolio` values.

Actual implementation:

- Added `src/moomail_finance_ai/investment_planner.py`.
- Stored `InvestmentAgentState.investment_plan` and exposed it in chat final
  payloads and sanitized trace summaries.
- Adapted the new V1.4 `PortfolioRequest` back to the existing
  `PortfolioTask` runtime path until the Portfolio Agent evidence-planning tasks
  are implemented.

Verification:

- `.venv/bin/python -m pytest tests/test_investment_planner.py tests/test_investment_agent.py -q`
  passed with `22 passed, 1 warning`.
- `.venv/bin/python -m pytest tests/test_chat_app.py -q` passed with
  `10 passed, 1 warning`.
- `.venv/bin/python -m pytest tests/test_agent_schemas.py tests/test_agent_trace.py -q`
  passed with `60 passed, 1 warning`.
- `.venv/bin/python -m pytest tests --ignore=tests/live -q` passed with
  `218 passed, 1 warning`.

Remaining:

- V1.4.4 must replace the remaining Portfolio Agent adapter path with
  deterministic evidence-packet execution.

## V1.4.3 Closeout: Portfolio Evidence Planner

Date: 2026-06-25

Decision:

- Add an explicit Portfolio Agent evidence planner that accepts bounded
  `PortfolioRequest` input, resolves asset hints before tool scope selection,
  and emits validated `PortfolioEvidencePlan` output.
- Preserve the current keyword/rule Portfolio Agent behavior as an explicit
  fallback planner rather than hidden inline extraction inside execution.
- Keep execution on the existing deterministic `PortfolioContextPlan` adapter
  for V1.4.3; V1.4.4 later built direct evidence-plan execution and
  `PortfolioEvidencePacket` assembly.

Actual implementation:

- Added `src/moomail_finance_ai/portfolio_evidence_planner.py`.
- Added optional `portfolio_request` and `asset_candidates` inputs to
  `PortfolioAgent.run`, plus `PortfolioAgentResult.evidence_plan`.
- Added resolved `asset_ids` and `canonical_symbols` to `PortfolioContextPlan`
  so position-state change reads can pass `asset_id` to SQL when available.
- 2026-06-26 no-mistakes review follow-up added explicit
  `position_change_scopes` entries to preserve mixed asset-id/ticker scope,
  converted non-day history windows to SQL lookback days, preserved
  class-share tickers such as `BRK.B`, and surfaced planner/context warnings
  in `PortfolioAgentResult.warnings`.

Verification:

- `.venv/bin/python -m py_compile src/moomail_finance_ai/portfolio_evidence_planner.py src/moomail_finance_ai/portfolio_agent.py src/moomail_finance_ai/agent_schemas.py`
  passed.
- `.venv/bin/python -m pytest tests/test_portfolio_planner.py tests/test_asset_resolver.py tests/test_portfolio_agent.py tests/test_agent_schemas.py -q`
  passed with `112 passed`.
- `.venv/bin/python -m pytest tests --ignore=tests/live -q` passed with
  `243 passed, 1 warning`.

Remaining:

- No remaining exit criteria for V1.4.3. V1.4.4 later completed direct
  evidence-plan execution and separated `PortfolioEvidencePacket` assembly.

## V1.4.4 and V1.4.5 Closeout: Evidence Execution and Trace/Evaluation Gate

Date: 2026-06-29

Decision:

- Execute bounded `PortfolioEvidencePlan` runs through deterministic freshness
  and allowlisted-tool policy, then return a separated
  `PortfolioEvidencePacket` while preserving compatibility result fields.
- Wire the live Investment Agent to pass its typed `PortfolioRequest` into the
  Portfolio Agent at runtime.
- Treat V1.4.5 as a release gate: add trace/evaluation regressions, prove the
  deterministic dashboard lane remains independent, update docs, and run the
  full non-live suite.

Actual implementation:

- `PortfolioAgent.run` now plans bounded evidence from `PortfolioRequest`,
  enforces `latest_required`, `cached_ok`, and `history_only` policy
  deterministically, reads SQL latest/history when allowed, calls OpenD only
  when policy requires or cache fallback needs it, and returns
  `PortfolioAgentResult.evidence_packet`.
- `PortfolioEvidencePacket` separates facts, derived metrics, position changes,
  deterministic detected patterns, portfolio-only interpretation, limitations,
  sentiment-context needs, warnings, and tool refs.
- Stable detector thresholds live in `PORTFOLIO_PATTERN_THRESHOLDS`.
- Investment Agent calls pass the typed `PortfolioRequest` into the Portfolio
  Agent and emit sanitized `portfolio_evidence_plan_ready`,
  `portfolio_evidence_packet_ready`, and deterministic tool-execution trace
  phases.
- Chat API payloads expose the evidence packet under portfolio analysis.
- Tests cover cached SQL without OpenD, history-only no-OpenD execution,
  stale-cache warnings, asset-scoped position-change calls, evidence packet
  sections, pattern thresholds, Portfolio Agent LLM input boundaries, dashboard
  no-agent/no-LLM independence, and golden recent-purchase handoff behavior.

Tradeoffs accepted:

- Legacy `PortfolioContextPlan`, `PortfolioAgentPacket`, and `PortfolioTask`
  compatibility fields remain because existing reports, frontend payloads, and
  tests still consume them.
- The Portfolio Agent can reuse SQL latest-state reconstruction for cached
  evidence runs. If no fresh SQL snapshot exists and OpenD is unavailable, it
  returns explicit stale/missing limitations instead of inventing current
  values.
- Portfolio-only LLM evaluation remains optional explanation over collected
  evidence; it still does not own finance math, freshness decisions, SQL reads,
  OpenD calls, persistence, or sentiment routing.

Verification:

- `.venv/bin/python -m pytest tests/test_portfolio_agent.py tests/test_portfolio_planner.py -q`
  passed with `51 passed`.
- `.venv/bin/python -m pytest tests/test_portfolio_data_service.py tests/test_mcp_gateway.py -q`
  passed with `11 passed, 1 warning`.
- `.venv/bin/python -m pytest tests/test_mcp_tool_contracts.py -q` passed with
  `6 passed`.
- `.venv/bin/python -m pytest tests/test_investment_planner.py tests/test_asset_resolver.py -q`
  passed with `23 passed`.
- `.venv/bin/python -m pytest tests/test_investment_agent.py tests/test_chat_app.py -q`
  passed with `22 passed, 1 warning`.
- `.venv/bin/python -m pytest tests/test_portfolio_data_service.py -q` passed
  with `7 passed, 1 warning`.
- `.venv/bin/python -m pytest tests --ignore=tests/live -q` passed with
  `251 passed, 1 warning`.
- `git diff --check` passed.

Remaining:

- No remaining V1.4 exit criteria. Future work moves to V1.5+ tracks:
  structured-output LLM planners, richer Investment Agent synthesis, real
  Sentiment Agent GraphRAG retrieval, Pinecone memory, and frontend redesign.

## V1.4 Planner Follow-up: Remove Deterministic Planning Fallbacks

Date: 2026-07-01

Decision:

- Remove deterministic keyword/regex planners from Investment Agent and
  Portfolio Agent runtime planning paths.
- Keep deterministic validation, asset resolution, finance metrics, freshness
  policy, SQL/OpenD tool execution, and guardrails.
- If the Investment LLM planner or Portfolio evidence LLM planner is
  unavailable or emits invalid structured output, return an explicit graceful
  failure message rather than falling back to keyword routing.
- Free-text chat should default to Investment Agent. Direct Portfolio Agent
  free-text calls require a bounded `PortfolioRequest` and otherwise return a
  planner-unavailable error.

Actual implementation:

- Replaced `DeterministicInvestmentPlanner` with `LLMInvestmentPlanner` and
  `UnavailableInvestmentPlanner`.
- Replaced `DeterministicPortfolioEvidencePlanner` and fallback query planning
  with `LLMPortfolioEvidencePlanner` and
  `UnavailablePortfolioEvidencePlanner`.
- Removed hidden user-query ticker extraction from Investment-to-Sentiment
  routing.
- Updated web chat default selection to `investment_agent`.

Verification:

- `.venv/bin/python -m pytest tests/test_investment_planner.py tests/test_portfolio_planner.py tests/test_investment_agent.py tests/test_agent_trace.py tests/test_chat_app.py -q`
  passed with `73 passed, 1 warning`.
- `.venv/bin/python -m pytest tests --ignore=tests/live -q` passed with
  `246 passed, 1 warning`.

## Future Update Template

### Version X / Date

Goal:

- ...

Design intent:

- ...

Actual implementation:

- ...

Decisions made:

- ...

Designed versus actual:

- ...

Verification:

- ...

Lessons learned:

- ...

Open questions:

- ...
