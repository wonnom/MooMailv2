# Architecture

## Overview

The system is a local-first multi-agent investment analysis platform. The
current runtime is version-agnostic: frontend code calls backend APIs,
deterministic backend services own fixed portfolio data flows, agents own
analytical reasoning, and both lanes use MCP through a backend-owned
`MCPToolGateway`.

Current portfolio-analysis flow:

```text
User query
  -> Portfolio Agent workflow
      -> OpenD/MooMoo read-only current portfolio data
      -> canonical local SQL portfolio history
      -> deterministic finance metrics
      -> portfolio-only LLM evaluator
  -> terminal or local frontend output
```

Current investment-analysis flow:

```text
User query
  -> Thin LangGraph Investment Agent supervisor
      -> classify/query plan
      -> call Portfolio Agent bounded-planning path when needed
      -> call Sentiment Agent stub when needed
      -> synthesize answer
      -> run guardrails
  -> terminal or local frontend output
```

Neo4j GraphRAG, Pinecone memory, and real research retrieval remain planned
architecture. They should be built against the current agent contracts rather
than ahead of them.

## Current Runtime Entrypoints

- Frontend/static assets: `web/index.html`, `web/static/app.js`, and
  `web/static/styles.css`.
- Backend API/chat server: `scripts/serve_chat.py`.
- CLI: `.venv/bin/python -m moomail_finance_ai --agent investment "..."` or the
  `finance-ai` console script.
- Deterministic portfolio data service:
  `src/moomail_finance_ai/portfolio_data_service.py`.
- Investment Agent: `src/moomail_finance_ai/investment_agent.py`.
- Portfolio Agent: `src/moomail_finance_ai/portfolio_agent.py`.
- Sentiment stub: `src/moomail_finance_ai/sentiment_agent_stub.py`.
- MCP gateway/runtime: `src/moomail_finance_ai/mcp/gateway.py`.
- FastMCP server scripts: `scripts/mcp_opend_server.py`,
  `scripts/mcp_portfolio_sql_server.py`, and
  `scripts/mcp_finance_metrics_server.py`.

## Local-First Deployment

The system runs locally:

- Python commands run through the project-local `.venv`.
- OpenD gateway runs locally and is assumed to already be started by the user.
- Python agent service runs locally.
- MCP servers run locally.
- SQL database runs locally or on a trusted private host.
- Neo4j will run locally or in a controlled private instance when GraphRAG work
  begins.
- Pinecone or a local vector store may be used for long-term memory after the
  Investment Agent memory contract is implemented.
- A basic TypeScript/static frontend runs locally; larger frontend work should follow stable backend contracts.

No brokerage credentials, database credentials, or MCP secrets should be exposed to the frontend.

## Investment Orchestration Shape

The Investment Agent uses LangGraph as a thin supervisor. It owns state,
routing, subagent calls, deterministic/template synthesis, guardrails, and
streaming status. It does not reimplement OpenD, SQL, metrics, or GraphRAG logic
directly.

Implemented graph:

```text
InvestmentAgentGraph
  -> receive_user_query
  -> load_investment_policy
  -> plan_investment with typed InvestmentPlan
  -> validate_investment_plan
  -> portfolio_agent_bounded_path when portfolio context is needed
  -> sentiment_agent_stub when research context is needed
  -> synthesize_answer
  -> guardrail_review
  -> emit_final_output
```

The Portfolio Agent now has a bounded-planning Python path. It can accept a
bounded V1.4 `PortfolioRequest`, resolve logical asset hints, produce a
`PortfolioEvidencePlan`, enforce deterministic freshness/tool policy, then
execute selected MCP tools and assemble a separated `PortfolioEvidencePacket`.
Existing query/`PortfolioTask` behavior is preserved as an explicit fallback
planner with compatibility result fields. Full review and deep-dive
tasks keep broad review context; cash/allocation fact tasks can skip broad SQL
history and persistence; and what-changed tasks request portfolio growth plus
allocation/position-state history. This is not yet a separate compiled LangGraph
subgraph. It should not call the Sentiment Agent. It can return candidate
sentiment scope such as important tickers, large contributors, or concerning
allocation changes.

The Investment Agent decides whether sentiment is needed and calls the Sentiment
Agent. The Sentiment Agent is currently a structured stub so the project can
lock the task and response contracts before building Neo4j ingestion and
retrieval.

The Investment Agent passes its V1.4 `PortfolioRequest` into the Portfolio
Agent at runtime and still exposes the older `query_plan`/`PortfolioTask`
compatibility fields for reports and tests.

Current non-goals:

- no real GraphRAG retrieval
- no Pinecone memory retrieval or writes
- no real research/memory MCP tools inside the agent loop yet
- no LLM planner for query classification or tool selection
- no rich LLM synthesis at the Investment Agent layer
- no trade execution or executable order-preparation path

## V1.4 Planning Target

V1.4 should introduce explicit structured planning for the Investment Agent and
Portfolio Agent while preserving deterministic tool execution.

Implementation status as of 2026-06-29: V1.4.0 through V1.4.5 have landed the
additive planner contracts, deterministic asset resolver/validator primitives,
live Investment Agent `InvestmentPlan` planner/validator node, Portfolio Agent
`PortfolioEvidencePlan` planner, policy-aware deterministic evidence execution,
direct `PortfolioEvidencePacket` assembly, and final trace/evaluation/docs
closeout.

The target pattern is:

```text
LLM/guided planner creates a typed plan
  -> deterministic validator/policy checks scope, permissions, and freshness
  -> MCP tools execute deterministic reads/calculations/persistence
  -> LLM synthesis explains evidence where useful
  -> deterministic guardrails review final output
```

Investment Agent planning should decide the mission: user intent, mode,
subagents needed, broad logical tickers/themes/time horizon, bounded portfolio
request, freshness requirement, and answer constraints. It should not choose
exact SQL/OpenD call sequences, broker-specific symbols, SQL asset ids, or
perform finance calculations.

Portfolio Agent planning should decide portfolio evidence scope: resolve
logical asset hints to actual portfolio assets and OpenD-compatible symbols,
refine the bounded request into evidence subtasks, choose SQL history tools,
position-state change scope, metric groups, current-value dependency, and
persistence mode.

The Portfolio Agent should return an evidence packet that separates facts,
derived metrics, detected patterns, portfolio-only interpretation, and
limitations that require sentiment or fundamental context. It should not decide
whether the Sentiment Agent is needed or produce the final investment thesis.

Freshness enforcement remains deterministic. The planner may request
`latest_required`, `cached_ok`, or `history_only`; backend/Portfolio policy
then decides whether OpenD must be called, whether SQL cached data is fresh
enough, or whether a stale-data warning should be returned.

Sentiment Agent implementation is out of V1.4 scope. The Investment Agent may
still produce a future-compatible `SentimentTask`, but real GraphRAG retrieval
belongs to a later version.

## MCP Backend Boundary

MCP is backend infrastructure, not only an LLM-agent tool surface. OpenD MCP
is the standardized backend boundary for MooMoo/OpenD data access, and both
deterministic app services and agents must use that same read-only,
permissioned, tested interface.

The frontend must not call MCP directly. It calls backend APIs. The backend owns
the MCP host/client runtime, server lifecycle, permissions, timeouts, retries,
traces, and sanitized errors.

The runtime has two portfolio data lanes:

```text
Deterministic portfolio data lane
  -> app startup, page load, or manual refresh
  -> backend PortfolioDataService
  -> MCP gateway
  -> OpenD status/current portfolio context
  -> finance metrics calculation
  -> portfolio SQL history update
  -> dashboard response with last-updated metadata

Agentic analysis lane
  -> user asks analytical query
  -> Investment Agent plans subagent calls
  -> Portfolio Agent requests current or historical context through gateway
  -> Sentiment Agent stub/future research tools are invoked when relevant
  -> final analysis, guardrails, and trace
```

This split is important: dashboard freshness is an application responsibility,
while analytical reasoning is an agent responsibility. The dashboard should not
wait for an LLM or agent planner to decide that OpenD data is needed.

Implementation note: both lanes call MCP through
`MCPToolGateway`. The deterministic lane uses consumer `dashboard_refresh`; the
Portfolio Agent uses consumer `portfolio_agent`; the Investment Agent still
does not call OpenD directly by default.

### Backend API Contracts

Implemented through `PortfolioDataService`, `ChatService`, and
`scripts/serve_chat.py`.

`PortfolioConnectionStatus` is returned by `GET /api/portfolio/status`:

```json
{
  "ok": true,
  "status": "connected",
  "checked_at": "2026-06-17T00:00:00Z",
  "message": "ok",
  "source": "moomail-opend-mcp",
  "warnings": [],
  "error": null
}
```

The response must never expose API keys, login credentials, raw account secrets,
or hidden backend configuration.

`PortfolioDashboardSnapshot` is returned by `GET /api/portfolio/dashboard`.
This endpoint reads the latest SQL state and calculates metrics from the
reconstructed snapshot. It does not call OpenD:

```json
{
  "portfolio_id": "portfolio_default",
  "as_of": "2026-06-17T00:00:00Z",
  "last_updated_at": "2026-06-17T00:00:00Z",
  "freshness_status": "fresh",
  "connection": null,
  "portfolio_snapshot": {},
  "metrics": [],
  "history_status": {},
  "latest_state": {},
  "storage_result": null,
  "warnings": [],
  "errors": [],
  "source_summary": {
    "source": "portfolio_sql_latest_state"
  }
}
```

`PortfolioRefreshResult` is returned by `POST /api/portfolio/refresh`.
This endpoint checks OpenD, retrieves a normalized current portfolio context,
calculates metrics, updates canonical SQL history, and returns dashboard-ready
state:

```json
{
  "status": "refreshed",
  "dashboard": {},
  "connection": {},
  "storage_result": {},
  "warnings": [],
  "errors": []
}
```

If refresh fails, the backend returns a structured sanitized error and, when
available, the last-known dashboard snapshot with a stale freshness status.

The current static frontend calls these backend APIs directly on page load and
manual refresh. It converts `PortfolioDashboardSnapshot` into the existing
report/table/chart UI shape so the dashboard can render holdings, cash,
allocation bars/pie, metrics, warnings, and trace metadata without starting a
chat agent run.

### Gateway Consumers

The MCP gateway must enforce consumer-specific permissions:

| Consumer | Allowed MCP access | Notes |
| --- | --- | --- |
| `dashboard_refresh` | OpenD status/context, finance metrics, portfolio SQL history update/read needed for dashboard state | Deterministic, no LLM, no agent planner. |
| `portfolio_agent` | OpenD, finance metrics, and portfolio SQL tools needed for portfolio analysis | Agentic lane; still read-only/analysis-only. |
| `investment_agent` | Portfolio SQL and finance metrics by default; no direct OpenD by default | Should call Portfolio Agent for live portfolio retrieval unless this is deliberately changed later. |
| `sentiment_agent` | Finance metrics only until research MCP exists | Future GraphRAG/research MCP will have its own permission profile. |

No consumer may access trade placement, order modification, order cancellation,
trade unlock, withdrawal, transfer, or executable order-preparation tools.

## MCP Server Boundaries

MCP servers are the backend tool boundary. Deterministic backend services
and analytical agents call FastMCP servers through the backend-owned MCP
gateway rather than directly integrating with every external service. The old
in-process module path is retained only where it supports registry adapters,
FastMCP parity checks, or `DirectToolGateway` tests.

### `moomail-opend-mcp`

Purpose: read-only MooMoo/OpenD access.

Capabilities:

- Check OpenD connection
- List accounts
- Get account balances
- Get cash balances
- Get current positions
- Get quotes for held assets
- Get order or transaction history only if OpenD exposes it read-only
- Return provider metadata and freshness warnings

Constraints:

- No trading tools.
- No order placement.
- No executable order preparation.
- Fail clearly if OpenD is unavailable.
- Cache data only within the run unless explicitly persisted elsewhere.

`moomail-opend-mcp` should be implemented before final SQL design. The project should first inspect exactly what OpenD provides and design persistence around available fields.

### `moomail-portfolio-sql-mcp`

Purpose: lean portfolio history, value snapshots, allocation weights, position
states, run records, and audit logs.

Canonical local database:

- `data/portfolio-history.sqlite`

Terminal reviews, the chat frontend, and the portfolio SQL MCP server must all
write to this same database unless a command explicitly passes a temporary
`--db` path for testing. The frontend must not keep a separate
`chat-portfolio-history.sqlite` portfolio-history store.

Capabilities:

- Store portfolio value snapshots
- Store compact position states
- Store per-snapshot portfolio weights
- Read historical portfolio growth and allocation snapshots
- Store audit records
- Store simple output summaries
- Store agent run metadata

Constraints:

- No destructive writes from agents.
- Writes are limited to approved tables.
- Keep storage lean; do not persist raw duplicated OpenD blobs when parsed
  fields already exist in first-class tables.
- Do not store hidden model reasoning.
- Store output summaries rather than full final responses.

### `moomail-finance-metrics-mcp`

Purpose: deterministic financial calculations.

Capabilities:

- Allocation and weights
- Concentration
- Sector exposure aggregation
- Cash weight and cash drag
- Volatility
- Drawdown
- Sharpe ratio
- Sortino ratio
- VaR and CVaR
- Beta
- Correlation
- Benchmark comparison
- Scenario analysis
- Contribution to risk where supported

Design:

- Implement as normal Python functions with unit tests.
- Expose through MCP for agent use.
- Prefer structured inputs over direct database access.
- Return structured metric values, assumptions, and warnings. The
  portfolio-history database should store only the metrics needed for portfolio
  history and display, not every calculation input/scope artifact.

### `research-rag-mcp`

Purpose: curated research retrieval and GraphRAG.

Capabilities:

- Retrieve evidence by ticker
- Retrieve evidence by company/entity
- Expand graph context around events, risks, people, products, competitors, claims, and sectors
- Return document chunks with parent document metadata
- Return source quality and citation data
- Surface contradictory evidence

Constraints:

- The current Sentiment Agent is a stub only; real retrieval is deferred.
- The stub lives in `src/moomail_finance_ai/sentiment_agent_stub.py` and
  implements the `SentimentTask -> SentimentPacket` boundary.
- The stub returns `retrieval_status: not_implemented`, explicit missing
  documents, no holdings, no citations, no source metadata, and no sentiment
  stance.
- The first real GraphRAG implementation should use a manually populated corpus.
- No external web/news ingestion is required for the first GraphRAG build.
- Retrieval scope starts with portfolio holdings selected by the Investment
  Agent.
- User-authored notes are not included in the first Neo4j GraphRAG build.

### `memory-mcp`

Purpose: Investment Agent long-term memory.

Capabilities:

- Retrieve relevant memories by query, ticker, mode, and memory type
- Write routine agent-generated review summaries
- Propose user preference or thesis memory changes for explicit approval
- Mark memories as inactive or superseded
- Return memory provenance and timestamps

Constraints:

- Investment Agent only.
- Portfolio Agent and Sentiment Agent do not directly access Pinecone.
- Pinecone does not store source-of-truth financial records.
- Avoid exact raw account values in memory.
- IPS, current portfolio data, and cited source data outrank memory.

## Data Stores

### MooMoo/OpenD

Role: live/current read-only source for securities-account holdings, balances,
cash, and quotes.

Current limitation: historical portfolio data is not assumed to be extractable
from OpenD. The portfolio runtime persists useful observations into SQL when
portfolio reviews run.

Current OpenD behavior:

- `accinfo_query` is normalized as account funds/balances.
- `position_list_query` is normalized as holdings.
- `get_market_snapshot` may reject OTC symbols such as `US.TCEHY`; this is a
  non-critical quote warning when the position row is still available, so the
  holding can still display in the frontend.
- Explicit money-market fund positions can be classified as `cash_equivalent`.
- Account-level `fund_assets` can be treated as auto-invested money-market fund
  assets/effective cash-equivalent purchasing power only when enabled through
  `MOOMAIL_MOOMOO_TREAT_FUND_ASSETS_AS_CASH_SWEEP`.
- Crypto accounts require a separate future `OpenCryptoTradeContext` path and
  are outside the current securities-account workflow.

### SQL Portfolio Store

Role: lean source of truth for portfolio growth, position state, allocation
history, and audit records.

Design review decision, 2026-06-02:

- Store parsed portfolio facts in first-class tables rather than duplicating
  raw OpenD payloads.
- Do not build a stock-price-history warehouse. Pull historic/current prices
  from market-data APIs when a query needs them.
- Preserve portfolio growth and allocation history by storing one daily
  portfolio value snapshot and child weight rows.
- Keep position state compact. Update a position state when only market price,
  market value, unrealized P&L, or last-observed timestamp changes. Insert a new
  position state when quantity, average cost, side, active status, or asset
  identity changes.
- Store OpenD `fund_assets` as reported. When
  `MOOMAIL_MOOMOO_TREAT_FUND_ASSETS_AS_CASH_SWEEP=true`, MCP/tool logic should
  expose interpreted cash-equivalent liquidity from `cash + fund_assets`; the
  database value itself remains raw parsed OpenD funds data.
- Store quote failures and other missing-data problems as data-quality events,
  not as a raw source-observation table.

Implemented tables:

```text
portfolios
broker_accounts
assets
position_states
portfolio_value_snapshots
portfolio_weight_snapshots
data_quality_events
agent_runs
agent_run_sources
```

Core relationships:

```text
portfolios
  -> broker_accounts
  -> portfolio_value_snapshots
      -> portfolio_weight_snapshots
          -> assets
      -> data_quality_events
  -> position_states
      -> assets

agent_runs
  -> agent_run_sources
      -> portfolio_value_snapshots
      -> data_quality_events
```

#### `portfolios`

One logical portfolio.

```text
portfolio_id PK
name
base_currency
created_at
```

#### `broker_accounts`

Minimal broker account identity. The current runtime uses the securities account; crypto can be
added later as a separate account type.

```text
account_id PK
portfolio_id FK
provider
security_firm
account_type
base_currency
created_at
```

#### `assets`

Canonical asset identity. Ticker alone is not sufficient because provider codes,
options, OTC symbols, funds, and future crypto holdings can collide or differ by
source.

```text
asset_id PK
provider_code
ticker
name
asset_type
exchange
currency
first_seen_at
last_seen_at
```

#### `position_states`

Compact ownership/cost-basis state. `average_cost` is the canonical cost basis.

```text
position_state_id PK
portfolio_id FK
account_id FK
asset_id FK
quantity
average_cost
market_price
market_value
unrealized_pl
currency
position_side
first_observed_at
last_observed_at
is_active
```

Insert a new row when quantity, average cost, side, active status, or asset
identity changes. Update the existing active row when only market price, market
value, unrealized P&L, or `last_observed_at` changes.

The Portfolio SQL MCP exposes these adjacent state changes through
`portfolio_sql_get_position_state_changes`. The tool supports `since`, `until`,
`lookback_days`, `asset_id`, and `ticker` filters and returns deterministic
quantity, average-cost, cost-basis, and implied added-share average-cost deltas
for agent use.

#### `portfolio_value_snapshots`

The portfolio-growth spine. Store one row per portfolio/account/day. If multiple
reviews run on the same date, update `last_observed_at` rather than inserting a
duplicate daily value snapshot.

```text
value_snapshot_id PK
portfolio_id FK
account_id FK
snapshot_date
as_of
total_assets
cash
fund_assets
securities_assets
market_val
currency
created_at
last_observed_at
```

This table stores parsed OpenD funds data without extra margin, risk,
per-currency, or buying-power fields for the current securities-account scope.

#### `portfolio_weight_snapshots`

The allocation-history spine. This preserves historical portfolio weights
without storing full stock price history.

```text
weight_snapshot_id PK
value_snapshot_id FK
portfolio_id FK
account_id FK
asset_id FK
quantity
average_cost
market_value
weight
unrealized_pl
asset_type
currency
as_of
```

Include normal holdings, options, cash-equivalent funds, and synthetic cash rows
such as `cash:USD` and `cash_sweep:USD`. Analysis can exclude out-of-scope rows,
but the history store should preserve the full portfolio view.

#### `data_quality_events`

Warnings and missing-data events without raw source duplication.

```text
event_id PK
portfolio_id FK
account_id FK nullable
asset_id FK nullable
value_snapshot_id FK nullable
run_id nullable
event_type
severity
message
source
as_of
created_at
```

Examples:

```text
unsupported_quote: OpenD does not support OTC market data for US.TCEHY
missing_history: fewer than the configured historical snapshots are available
cash_sweep_assumption: fund_assets interpreted as cash-equivalent liquidity
```

#### `agent_runs`

Audit summary only.

```text
run_id PK
portfolio_id FK
agent_type
user_query
mode
started_at
completed_at
tools_called_json
snapshot_refs_json
guardrail_result_json
missing_data_json
output_summary
created_at
```

#### `agent_run_sources`

Links an agent run to the value snapshots, weight snapshots, and data-quality
events used in the response.

```text
id PK
run_id FK
source_type
source_id
created_at
```

Implementation status: the local SQLite implementation now creates the lean
tables above for fresh databases. It no longer stores broad raw snapshot JSON,
quote-history rows, or calculated metric input-scope rows in the active SQL MCP
path.

Resolved implementation clarifications:

- `broker_accounts.account_id` is an internal stable id
  (`opend_securities_account` by default), not the raw MooMoo account number.
- Position states are marked inactive only when a successful normalized
  portfolio observation omits an active asset.
- Same-day `portfolio_weight_snapshots` are replaced when the same daily value
  snapshot is re-observed, so the latest daily allocation view is coherent.

### Neo4j GraphRAG Store

Role: research graph for company, document, event, claim, risk, catalyst, management, and sector relationships.

First-class nodes:

- `Company`
- `Ticker`
- `Document`
- `Person`
- `Event`
- `Metric`
- `Risk`
- `Catalyst`
- `Claim`
- `Sector`
- `Product`

Key relationships:

- `ISSUED_BY`
- `MENTIONS`
- `ASSERTS`
- `CONTRADICTS`
- `AFFECTS`
- `GUIDED_BY`
- `LED_BY`
- `COMPETES_WITH`
- `EXPOSED_TO`
- `SUPPORTED_BY`

### Research Vector Store

Role: semantic chunk retrieval for documents.

Neo4j should store graph metadata and references to vector chunk IDs. Final citations should point to chunk-level evidence with parent document metadata.

### Pinecone Memory

Role: Investment Agent long-term memory.

Memory types:

- `user_preference`
- `investment_thesis`
- `past_recommendation`
- `decision_record`
- `portfolio_review_summary`
- `risk_concern`
- `watchlist_interest`
- `agent_observation`

Some memories should expire or be superseded. Durable policy preferences should remain in the canonical IPS instead of Pinecone.

## Orchestration

Use LangGraph for the Investment Agent state machine, with LangChain
components inside nodes where useful.

Current nodes:

1. Receive user query
2. Classify query
3. Load IPS
4. Plan subagent calls
5. Call Portfolio Agent bounded-planning path when portfolio context is needed
6. Decide whether sentiment is needed from user intent and portfolio packet
7. Call Sentiment Agent stub when needed
8. Synthesize response
9. Guardrail review
10. Emit final structured output
11. Store audit summary

Portfolio Agent has evolved from the fixed deterministic workflow into a
bounded-planning deterministic Python path. Sentiment Agent begins as a stub
with the same contract the future Neo4j GraphRAG implementation will satisfy.

Investment guardrails are deterministic and live in
`src/moomail_finance_ai/investment_guardrails.py`. The active checks are no trading,
no exact share-count trading instructions, no unsupported research claims, no
unsupported portfolio facts, IPS-required optimization/rebalancing checks, and
missing sentiment limitation visibility.

Agent trace sanitization lives in `src/moomail_finance_ai/agent_trace.py`. The trace
boundary exposes graph progress, subagent calls, planned/actual/skipped tool
summaries, sentiment stub status, guardrail outcome, and sanitized errors. It
does not expose hidden chain-of-thought, raw prompts, secrets, API keys, raw
broker account IDs, or scratchpad fields.

## Frontend Direction

The frontend started as a delayed concern, but a dependency-light local chat UI
now exists over the current backend contracts. Backend agents, tools, memory,
orchestration, and output contracts remain the source of truth for future UI
expansion.

Terminal output remains useful for inspection and regression checks.

When built, the frontend should be:

- TypeScript
- Chat-first
- Capable of rendering structured report panels
- Capable of showing streaming operational status
- Capable of showing citations and a technical trace drawer
- Capable of hiding and resizing the chat rail for full report inspection

Current local UI:

- Uses `scripts/serve_chat.py`.
- Sends chat requests to `/api/chat/stream`.
- Streams status events into the chat rail.
- Renders portfolio evaluation, allocation, missing data, sentiment, citations,
  and trace panels.
- Displays guardrail result and sanitized Agent trace events from the final
  response payload.

Structured panels planned for later:

- Portfolio snapshot
- Allocation
- Risk diagnostics
- Holding deep dives
- Sentiment evidence
- Recommendations
- Missing data
- Audit/source drawer
