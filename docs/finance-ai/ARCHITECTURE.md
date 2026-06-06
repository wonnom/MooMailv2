# Architecture

## Overview

The system is a local-first multi-agent investment analysis platform. It uses
Python for agents, tools, orchestration, analytics, memory, and retrieval. A
basic local TypeScript/static chatbot frontend exists, while backend contracts
remain the source of truth.

V1 is complete as a Portfolio Agent proof of concept:

```text
User query
  -> Portfolio Agent workflow
      -> OpenD/MooMoo read-only current portfolio data
      -> canonical local SQL portfolio history
      -> deterministic finance metrics
      -> portfolio-only LLM evaluator
  -> terminal or local frontend output
```

The V2 target is the first real Investment Agent architecture:

```text
User query
  -> Thin LangGraph Investment Agent supervisor
      -> classify/query plan
      -> call Portfolio Agent bounded-planning subgraph when needed
      -> call Sentiment Agent stub when needed
      -> synthesize answer
      -> run guardrails
  -> terminal or local frontend output
```

Neo4j GraphRAG, Pinecone memory, and real research retrieval remain planned
architecture, but they are not part of the V1 implementation and should not be
built before the V2 contracts are stable.

## Local-First Deployment

V1 runs locally:

- Python commands run through the project-local `.venv`.
- OpenD gateway runs locally and is assumed to already be started by the user.
- Python agent service runs locally.
- MCP servers run locally.
- SQL database runs locally or on a trusted private host.
- Neo4j will run locally or in a controlled private instance when GraphRAG work
  begins.
- Pinecone or a local vector store may be used for long-term memory after the V2
  Investment Agent contracts are stable.
- A basic TypeScript/static frontend runs locally; larger frontend work should follow stable backend contracts.

No brokerage credentials, database credentials, or MCP secrets should be exposed to the frontend.

## V2 Orchestration Shape

V2 should use LangGraph for the Investment Agent supervisor. The supervisor is
thin: it owns state, routing, subagent calls, synthesis, guardrails, and
streaming status. It should not reimplement OpenD, SQL, metrics, or GraphRAG
logic directly.

Recommended V2 graph:

```text
InvestmentAgentGraph
  -> receive_user_query
  -> classify_query
  -> load_investment_policy
  -> plan_subagent_calls
  -> portfolio_agent_subgraph when portfolio context is needed
  -> sentiment_agent_stub when research context is needed
  -> synthesize_answer
  -> guardrail_review
  -> emit_final_output
```

The Portfolio Agent should become a bounded-planning subgraph. It may decide
which portfolio tools it needs, such as current OpenD, SQL history, or metric
groups. It should not call the Sentiment Agent. It can return candidate
sentiment scope such as important tickers, large contributors, or concerning
allocation changes.

The Investment Agent decides whether sentiment is needed and calls the Sentiment
Agent. In V2, the Sentiment Agent is a structured stub so the project can lock
the task and response contracts before building Neo4j ingestion and retrieval.

## MCP Server Boundaries

MCP servers are the tool boundary. Agents call tools through MCP rather than directly integrating with every external service.

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

- V2 uses a Sentiment Agent stub only; real retrieval is deferred.
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
from OpenD. V1 persists useful observations into SQL when portfolio reviews run.

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
  are outside the current v1 securities-account workflow.

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

Implemented V1 tables:

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

Minimal broker account identity. V1 uses the securities account; crypto can be
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
per-currency, or buying-power fields for V1.

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

- `broker_accounts.account_id` is an internal stable id in V1
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

Use LangGraph for the V2 Investment Agent state machine, with LangChain
components inside nodes where useful.

V2 nodes:

1. Receive user query
2. Classify query
3. Load IPS
4. Plan subagent calls
5. Call Portfolio Agent subgraph when portfolio context is needed
6. Decide whether sentiment is needed from user intent and portfolio packet
7. Call Sentiment Agent stub when needed
8. Synthesize response
9. Guardrail review
10. Emit final structured output
11. Store audit summary

Portfolio Agent should evolve from the current deterministic workflow into a
bounded-planning subgraph. Sentiment Agent should begin as a stub with the same
contract the future Neo4j GraphRAG implementation will satisfy.

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

Structured panels planned for later:

- Portfolio snapshot
- Allocation
- Risk diagnostics
- Holding deep dives
- Sentiment evidence
- Recommendations
- Missing data
- Audit/source drawer
