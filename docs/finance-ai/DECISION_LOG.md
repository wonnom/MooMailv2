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

Date: 2026-06-13

Current status:

- V1 is complete as a Portfolio Agent proof of concept with OpenD and local SQL
  portfolio history.
- V2 is in progress: the thin LangGraph Investment Agent supervisor and
  bounded-planning Portfolio Agent are implemented; Sentiment Agent remains a
  structured stub target to cement future GraphRAG contracts.
- The root `README.md` is used for GitHub visibility.
- Detailed design docs live under `docs/finance-ai/`.
- Historical V1 task tracking lives under `docs/finance-ai/V1_TASKS/`.
- Active V2 task maps live under `docs/finance-ai/V2_Tasks/`.
- The canonical portfolio database is `data/portfolio-history.sqlite`.
- Trading remains fully out of scope.

## Version Map

| Version | Status | Meaning |
| --- | --- | --- |
| Concept / V0 | Complete | Architecture interview, requirements, agent boundaries, and tool-store choices. |
| V1 | Complete | Portfolio Agent POC with OpenD, canonical local SQL history, deterministic metrics, MCP boundaries, terminal path, and local chat frontend. |
| V2 | In progress | LangGraph Investment Agent supervisor, bounded-planning Portfolio Agent subgraph, Sentiment Agent stub, contracts, synthesis, and guardrails. |

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

Use MCP as the boundary between agents and tools/resources. MCP servers expose
read-only broker access, portfolio history, finance metric calculators, future
research retrieval, and future memory tools.

Implemented V1 MCP surfaces:

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

Implementation reality:

- MCP-style tool modules and stdio JSON-RPC servers exist.
- The current V1 Portfolio Agent calls the MCP modules in process.
- The current V1 Portfolio Agent is MCP-backed but not MCP-autonomous.
- An official MCP SDK/client-host runtime migration is deferred.

Key decision:

Use specific tool allowlists by agent, rather than giving every agent access to
one central unrestricted tool server. This keeps permissions clear and makes it
easier to reason about what each agent can do.

Learning note:

Having MCP servers is not the same thing as having an autonomous tool-calling
agent. A deterministic Python workflow can call MCP tools, but an LLM only
"chooses" tools if the runtime gives it a planning/tool-calling loop.

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
  the V1 securities-account ingestion.
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

Final V1 SQL principles:

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

### 8. Portfolio Agent V1 Implementation

V1 implemented flow:

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
- This is acceptable for V1 because V1 is a proof of concept, not the final
  Investment Agent architecture.

Designed versus actual:

- Designed target: autonomous Investment Agent decides which subagents and tools
  are needed.
- Actual V1: deterministic Portfolio Agent path retrieves broad current context
  and then asks an LLM evaluator to summarize/analyze it.
- Designed target: Portfolio Agent is a subagent under Investment Agent.
- Actual V1: Portfolio Agent can be called directly by CLI/chat for portfolio
  review.

Learning note:

The V1 agent is best understood as a deterministic workflow with an LLM
evaluation step. That is still valuable because it hardens the data layer,
normalization, metrics, and frontend trace before adding more autonomy.

### 9. Frontend And Local Interaction

Frontend direction chosen:

- Keep frontend minimal until backend contracts are stable.
- Use local terminal and static chatbot paths for V1.
- Do not build a richer React/TypeScript frontend until V2 contracts are
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

- V1 has no trading tools.
- MCP surfaces are read-only or analysis-only.
- V1 guardrail behavior is present around output framing and tool scope.
- V2 should move final guardrail review into the Investment Agent path as a
  structured graph node.

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

- Deterministic Python code in V1 acts as the orchestration spine.
- LangChain could still be deterministic if used as a fixed chain.
- Autonomy comes from giving a model a planning/tool-selection role, but that
  autonomy should be bounded by schemas, state, and allowed tools.
- LangGraph is the better next step for this project because the desired V2
  shape is a supervisor with subgraphs and controlled routing.

Key decision:

Build the thin LangGraph Investment Agent before building the full Neo4j
GraphRAG Sentiment Agent. The Investment Agent will cement the contracts the
future Sentiment Agent must satisfy.

Learning note:

GraphRAG should be designed against the agent contract that will consume it.
Building the graph first risks optimizing the retrieval system for unclear
downstream needs.

### 12. V1 Closeout

V1 definition:

V1 is complete when the local app can run a portfolio-only review from OpenD,
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

Known V1 limitations:

- Portfolio Agent is deterministic, not a planning subgraph.
- Investment Agent is not yet the target LangGraph supervisor.
- Sentiment Agent is a stub/placeholder.
- Neo4j GraphRAG is not implemented.
- Pinecone memory is not connected.
- Crypto account ingestion is deferred.
- OTC quote fallback provider is deferred.
- Official MCP SDK/client runtime migration is deferred.
- Rich React frontend migration is deferred.

### 13. V2 Direction

V2 goal:

Turn the V1 Portfolio Agent POC into the first real Investment Agent
architecture.

Planned V2 flow:

```text
User query
  -> Investment Agent LangGraph supervisor
      -> classify query and load relevant policy context
      -> decide whether portfolio context is needed
      -> decide whether sentiment context is needed
      -> call Portfolio Agent subgraph
      -> call Sentiment Agent stub when needed
      -> synthesize answer
      -> run guardrail review
      -> return structured response and trace
```

Portfolio Agent V2 direction:

- Convert current deterministic flow into a bounded-planning subgraph.
- Planner decides:
  - whether current OpenD is needed
  - whether SQL history is needed
  - which history window or row limits are relevant
  - which tickers/assets are relevant
  - which metric groups are needed
  - whether persistence should happen
- Execution remains deterministic after the plan is selected.

Sentiment Agent V2 direction:

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

- V2 is not trying to finish the full investment research system.
- V2 is trying to prove the orchestration pattern, contracts, trace, and
  guardrail placement.
- GraphRAG and Pinecone should come after the Investment Agent contracts are
  stable.

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
stable. The local chat UI is useful for exercising contracts, but V2 should
prioritize backend orchestration.

## Implementation Artifacts

Important current files and areas:

- `README.md`
  - GitHub-facing overview.

- `docs/finance-ai/`
  - Detailed architecture, requirements, protocol, MCP, testing, and planning
    docs.

- `docs/finance-ai/V1_TASKS/`
  - Historical V1 implementation tracking and closeout.

- `src/moomail_finance_ai/portfolio_agent.py`
  - V1 Portfolio Agent deterministic orchestration and LLM evaluator path.

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

- `scripts/serve_chat.py`
  - Local chat frontend server.

- `data/portfolio-history.sqlite`
  - Canonical local portfolio-history database.

## V2 Task 3 Closeout / 2026-06-13

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
  `PortfolioAgentResult.tool_calls` and carried them into the V2 portfolio
  packet.

Tradeoffs accepted:

- Metric execution still uses the existing broad `calculate_snapshot_metrics`
  MCP tool. The trace records the requested metric groups and that broad
  snapshot metrics were used until granular metric MCP tools exist.
- The Portfolio Agent planner is deterministic keyword/task based rather than
  LLM-planned. This keeps autonomy bounded and testable.

Verification:

- Added `tests/test_v2_portfolio_planner.py`.
- Updated Portfolio Agent, V2 Investment Agent, and chat tests.
- Full deterministic suite passed with live tests excluded.

## Interview And Presentation Talking Points

- The project began as a broad multi-agent finance system, then narrowed
  deliberately to the Investment Agent branch.
- V1 focused on real data plumbing and portfolio history before agentic
  autonomy.
- MCP was used as a permissioned tool boundary.
- The OpenD integration taught that broker APIs require careful normalization
  and partial-failure handling.
- The database design intentionally stores portfolio history instead of raw
  broker payloads or market-wide quote history.
- A prototype accidentally created two databases, which was corrected into a
  one-canonical-DB architecture.
- The V1 Portfolio Agent is deterministic with an LLM evaluator; that is a
  deliberate stepping stone, not the final agent architecture.
- V2 moves autonomy up to a LangGraph Investment Agent supervisor and bounded
  Portfolio Agent planner.
- The Sentiment Agent is stubbed before Neo4j GraphRAG so the retrieval system
  can be designed against stable contracts.
- Safety is designed at the tool boundary, orchestration layer, and final
  guardrail layer.

## Open Questions

- What exact Pydantic models should define V2 state, tasks, packets, and
  guardrail outputs?
- Should the V2 runtime use the official MCP client/host path immediately, or
  continue with in-process MCP modules until graph contracts stabilize?
- What is the first useful Neo4j graph schema for research documents,
  companies, events, risks, and management commentary?
- When should Pinecone memory be introduced: before or after real GraphRAG?
- What fallback provider should handle unsupported OTC quotes?
- How should crypto holdings be represented if MooMoo exposes them through a
  separate account surface?
- How much of the current local chat UI should survive the future React
  frontend migration?

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
