# Milestone 3 Task Map

Milestone 3 goal: persist portfolio history and calculate deterministic metrics.

## Scope Clarification

The SQL store should preserve portfolio growth, current/changed position state,
historical allocation weights, and audit summaries without becoming a raw
OpenD dump or stock-price-history warehouse.

Design review decision, 2026-06-02:

- Store parsed OpenD funds fields in `portfolio_value_snapshots`, not raw source
  observations.
- Store one daily portfolio value snapshot per portfolio/account/date.
- Store child `portfolio_weight_snapshots` rows so historical allocation can be
  rebuilt without storing all price-history data.
- Store compact `position_states`. Insert a new row when quantity, average cost,
  side, active status, or asset identity changes. Update the active row when
  only market price, market value, unrealized P&L, or last-observed timestamp
  changes.
- Use `average_cost` as canonical cost basis.
- Preserve options, cash-equivalent funds, future crypto rows, literal cash, and
  configured cash-sweep rows in allocation history even when V1 analysis scopes
  down to US equities.
- Store unsupported quotes and other missing-data issues as
  `data_quality_events`.
- Do not persist raw OpenD blobs, full quote history, hidden reasoning, metric
  input scopes, or full final responses.

Account-level OpenD `fund_assets` remains stored as reported. When
`MOOMAIL_MOOMOO_TREAT_FUND_ASSETS_AS_CASH_SWEEP=true`, MCP/tool logic exposes
`cash + fund_assets` as interpreted cash-equivalent liquidity for the agent.

## Exit Criteria

1. A portfolio review can use OpenD data and persisted SQL portfolio history.
2. Metrics are deterministic, tested, and produce overall portfolio weights.
3. The system detects missing or stale portfolio history.
4. SQL stores run metadata and concise summaries, not hidden reasoning or full final responses.

## Dependency Graph

```text
A. OpenD field report from Milestone 2
   ├── B. Lean SQL schema design
   │   ├── C. SQLite portfolio store
   │   │   ├── D. Upsert portfolios, accounts, and assets
   │   │   ├── E. Upsert compact position states
   │   │   ├── F. Store daily portfolio value snapshots
   │   │   ├── G. Store portfolio weight snapshots
   │   │   ├── H. Store data-quality events
   │   │   └── I. Store audit/run summaries
   │   └── J. History freshness/status and growth/allocation queries
   ├── K. Deterministic metric contracts
   │   ├── L. Overall portfolio cash, allocation, and concentration metrics
   │   └── M. Unit tests with known inputs
   └── R. Recorded OpenD workflow
       ├── N. Build normalized packet from recorded report
       ├── O. Persist lean history rows to SQL
       ├── P. Calculate weights and attach them to snapshots
       └── Q. Emit terminal summary for inspection
```

## Task Breakdown by Exit Criteria

### EC1: Portfolio review can use OpenD data and persisted SQL history

| Task | Description | Depends on | Status |
| --- | --- | --- | --- |
| A | Use recorded OpenD field report from Milestone 2 | None | Done |
| B | Redesign SQLite schema around value snapshots, weight snapshots, and position states | A | Planned |
| C | Add new `PortfolioSqlStore` tables alongside prototype tables | B | Planned |
| D | Upsert portfolio, account, and asset identity rows | C | Planned |
| E | Upsert compact position states | C, D | Planned |
| F | Store idempotent daily portfolio value snapshot | C, D | Planned |
| G | Store child portfolio weight snapshots for holdings and cash rows | F | Planned |
| H | Store data-quality events instead of raw quote/source rows | C, F | Planned |
| N | Build normalized packet from recorded report | A | Done |
| O | Persist recorded packet through lean history tools | C, N | Planned |

### EC2: Metrics are deterministic, tested, and produce overall weights

| Task | Description | Depends on | Status |
| --- | --- | --- | --- |
| K | Define deterministic metric result contract | None | Done |
| L | Implement overall portfolio weights for holdings, literal cash, and configured cash sweep | K | Planned |
| M | Add unit tests with known inputs | L | Planned |
| P | Store portfolio weights in `portfolio_weight_snapshots` rather than a broad metric-history table | F, L | Planned |

### EC3: Missing or stale portfolio history is detected

| Task | Description | Depends on | Status |
| --- | --- | --- | --- |
| J | Add history status query against value snapshots | C | Planned |
| J1 | Detect empty history | J | Planned |
| J2 | Detect stale latest snapshot | J | Planned |
| J3 | Detect insufficient historical depth | J | Planned |
| J4 | Add portfolio growth and allocation-history reads | J, G | Planned |

### EC4: SQL stores metadata and concise summaries only

| Task | Description | Depends on | Status |
| --- | --- | --- | --- |
| I | Store agent run metadata and output summary | C | Planned |
| I1 | Store tool calls, snapshot refs, missing data, assumptions, and guardrail JSON | I | Planned |
| I2 | Do not store hidden reasoning or full final responses | I | Planned |
| I3 | Link agent runs to snapshots/events through `agent_run_sources` | I | Planned |
| I4 | Add tests for audit storage shape | I | Planned |

## Commands

Use recorded mode to avoid repeated OpenD calls:

```bash
.venv/bin/python scripts/portfolio_history_demo.py \
  --from-report reports/opend/field-report.json \
  --db data/portfolio-history.sqlite \
  --output reports/opend/history-summary.json
```

The SQLite database and generated reports are ignored by git.

## Refactor Implementation Order

1. Add schema version 2 tables alongside the prototype tables.
2. Implement model/serializer helpers that convert a normalized
   `PortfolioSnapshot` plus OpenD funds context into:
   - portfolio/account/asset upserts,
   - position-state upserts,
   - one daily portfolio value snapshot,
   - portfolio weight snapshot rows,
   - data-quality events.
3. Add SQL store methods for those write paths and unit-test them directly.
4. Expose the methods through `moomail-portfolio-sql-mcp` tools.
5. Update `MCPPortfolioAgent` to call the new SQL MCP tools in this order:
   - initialize schema,
   - upsert identities,
   - upsert position states,
   - store daily value snapshot,
   - store weight snapshots,
   - store data-quality events,
   - read history status/growth/allocation context.
6. Keep the current prototype tools available until the Portfolio Agent and
   tests no longer depend on them.
7. Update terminal/frontend output only after SQL persistence is stable.
8. Remove or deprecate prototype tables/tools in a separate cleanup pass.

Non-goals for this refactor:

- Do not add raw OpenD source-observation storage.
- Do not add daily stock price history.
- Do not add proprietary SQL support yet.
- Do not change the no-trading tool surface.

## Current Status

Milestone 3 is implemented as a local SQLite-backed prototype, now exposed through `moomail-portfolio-sql-mcp` and `moomail-finance-metrics-mcp`.

The next Milestone 3 pass is a schema refactor, not a broad feature expansion.
The goal is to move from broad snapshot/quote/metric prototype tables to the
lean portfolio-history design agreed on 2026-06-02.

Latest local run shape:

- Database: `data/portfolio-history.sqlite`
- Summary report: `reports/opend/history-summary.json`
- Portfolio snapshots: written on demand, idempotent by portfolio/date through
  the MCP daily snapshot tool
- Cash balances: base cash plus optional auto-invested fund-assets row when enabled
- Position snapshots: full OpenD position set
- Quote snapshots: all supported OpenD quote rows; unsupported OTC quotes are
  warnings
- Calculated metrics: 5 v1 metrics per inserted snapshot
- History status: fresh/stale/empty plus `historical_depth` warning when fewer
  than the configured minimum snapshots exist

The audit table stores concise metadata and `output_summary`; it does not include hidden reasoning or a full final response column.

Target run shape after refactor:

- Portfolio/account/asset identity rows are upserted.
- Position states remain compact and update in place for price/P&L-only changes.
- Daily portfolio value snapshot stores parsed funds fields:
  `total_assets`, `cash`, `fund_assets`, `securities_assets`, `market_val`, and
  currency.
- Portfolio weight snapshot rows store overall weights for every current
  holding and cash/cash-sweep row.
- Data-quality events store unsupported quote, stale history, and cash-sweep
  assumption warnings.
- Agent runs link to the value snapshot and data-quality events used.

## Verification

Run:

```bash
.venv/bin/python -m pytest
```

Latest result:

```text
66 passed, 10 skipped
```
