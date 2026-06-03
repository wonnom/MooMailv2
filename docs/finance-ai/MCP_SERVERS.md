# MCP Servers

This project now has local MCP-facing modules for the first three Investment
Agent tool surfaces:

- `moomail-opend-mcp`: read-only OpenD/MooMoo data access.
- `moomail-portfolio-sql-mcp`: local SQLite portfolio history and audit store.
- `moomail-finance-metrics-mcp`: deterministic finance metric calculations.

The implementation is split into two layers:

1. Tool modules in `src/moomail_finance_ai/mcp/` register tools, resources, input
   schemas, and Python handlers.
2. `JsonRpcMCPServer` exposes those modules over local stdio using MCP-style
   JSON-RPC methods: `initialize`, `tools/list`, `tools/call`,
   `resources/list`, and `resources/read`.

This keeps the business logic independent from the transport. The optional
`mcp` Python SDK dependency can be added when the project is ready to use the
official FastMCP server runtime directly.

## Server Boundaries

### `moomail-opend-mcp`

Tools:

- `opend_check_connection`
- `opend_get_account_list`
- `opend_get_account_funds`
- `opend_get_positions`
- `opend_get_market_snapshots`
- `opend_explore_fields`
- `opend_get_normalized_portfolio_snapshot`
- `opend_get_portfolio_context`

Resources:

- `opend://capabilities/read-only`
- `opend://config/summary`

This server is read-only. It does not expose trade unlock, order placement,
order modification, cancellation, withdrawal, or transfer tools.

Notes:

- `opend_get_account_funds` wraps OpenD/moomoo `accinfo_query`; it is account
  fund/balance data, not positions.
- `opend_get_positions` wraps `position_list_query`.
- OpenD may reject OTC quote snapshots. The adapter retries per symbol and keeps
  supported quote rows while recording unsupported symbols as warnings. The
  position can still display when `position_list_query` returned it.
- Account-level `fund_assets` is treated as auto-invested money-market fund
  assets/effective cash-equivalent purchasing power only when
  `MOOMAIL_MOOMOO_TREAT_FUND_ASSETS_AS_CASH_SWEEP=true`.

### `moomail-portfolio-sql-mcp`

Current tools:

- `portfolio_sql_initialize`
- `portfolio_sql_upsert_portfolio`
- `portfolio_sql_upsert_broker_account`
- `portfolio_sql_upsert_assets`
- `portfolio_sql_upsert_position_states`
- `portfolio_sql_store_daily_value_snapshot`
- `portfolio_sql_store_weight_snapshots`
- `portfolio_sql_store_data_quality_events`
- `portfolio_sql_get_history_status`
- `portfolio_sql_get_latest_portfolio_state`
- `portfolio_sql_get_portfolio_growth`
- `portfolio_sql_get_allocation_history`
- `portfolio_sql_store_agent_run`
- `portfolio_sql_link_agent_run_sources`
- `portfolio_sql_table_count`

Resources:

- `portfolio-sql://schema`
- `portfolio-sql://status`

This server owns lean portfolio value history, allocation weight history,
compact position states, data-quality events, and run summaries. It stores
summaries and structured records, not hidden model reasoning.

Implemented schema from the 2026-06-02 portfolio-history design review:

- Replace broad raw snapshot persistence with lean parsed tables:
  `portfolios`, `broker_accounts`, `assets`, `position_states`,
  `portfolio_value_snapshots`, `portfolio_weight_snapshots`,
  `data_quality_events`, `agent_runs`, and `agent_run_sources`.
- Do not store a raw OpenD source-observation table or full raw final responses.
- Do not store daily quote history. Store quote failures and missing data as
  `data_quality_events`; fetch market prices from external APIs when a query
  needs price history.
- Store one portfolio value snapshot per portfolio/account/date.
- Store one set of portfolio weight rows per value snapshot, including holdings,
  options, cash-equivalent funds, literal cash, and configured cash-sweep rows.
- Store compact position states. Insert a new state when quantity, average cost,
  side, active status, or asset identity changes. Update the active state when
  only market price, market value, unrealized P&L, or last-observed timestamp
  changes.
- If the same daily value snapshot is observed again, update the value row's
  latest parsed values and `last_observed_at`, then replace its child weight
  rows so the daily allocation view stays coherent.

### `moomail-finance-metrics-mcp`

Tools:

- `calculate_cash_weight`
- `calculate_position_weights`
- `calculate_single_position_concentration`
- `calculate_asset_type_allocation`
- `calculate_benchmark_reference`
- `calculate_snapshot_metrics`
- `list_metric_definitions`

Resources:

- `finance-metrics://definitions`
- `finance-metrics://version`

This server is pure calculation. It should remain deterministic, versioned, and
free of broker/database side effects.

`calculate_cash_weight` separates literal cash, configured auto-invested fund
assets, and holdings classified as `cash_equivalent`. The portfolio-history
database should store the resulting overall portfolio weights needed for
history; it does not need to persist metric version or input-scope details for
V1.

## Agent Access

Agent tool exposure is controlled in
`src/moomail_finance_ai/mcp/agent_access.py`.

Default allowlist:

- `portfolio_agent`: OpenD, portfolio SQL, finance metrics.
- `sentiment_agent`: finance metrics only for now. Research RAG MCP will be
  added later.
- `investment_agent`: portfolio SQL and finance metrics, but no direct OpenD
  tools. Direct portfolio retrieval should remain owned by the Portfolio Agent.

The manifest qualifies tools as:

```text
<server-name>:<tool-name>
```

Example:

```text
moomail-opend-mcp:opend_get_positions
```

This is the registry layer. The LLM does not need to decide which server exists;
the agent runtime binds the allowed modules for the agent before the model sees
the tool list.

## Running Servers

Finance metrics:

```bash
.venv/bin/python scripts/mcp_finance_metrics_server.py
```

Portfolio SQL:

```bash
.venv/bin/python scripts/mcp_portfolio_sql_server.py --db-path data/portfolio-history.sqlite
```

OpenD with live local gateway:

```bash
.venv/bin/python scripts/mcp_opend_server.py --env-file config/local.env
```

OpenD with a recorded local field report:

```bash
.venv/bin/python scripts/mcp_opend_server.py --from-report reports/opend/field-report.json
```

The recorded report mode is useful for development because it avoids repeatedly
pulling live account data while testing agent orchestration.

## Portfolio Agent

The MCP-backed Portfolio Agent calls:

- `moomail-opend-mcp` for the current OpenD portfolio context.
- `moomail-finance-metrics-mcp` for deterministic metric calculations.
- `moomail-portfolio-sql-mcp` for idempotent daily value snapshots,
  position-state upserts, allocation weight history, data-quality events, and
  history status.
- A provider-neutral LLM evaluator for portfolio-only evaluation after
  deterministic tools finish. Gemini and OpenAI adapters are supported; Gemini is
  the current default.

Portfolio Agent refactor sequence:

1. Retrieve OpenD context as today.
2. Normalize holdings, literal cash, optional configured cash sweep, and
   data-quality warnings.
3. Build asset upserts from normalized holdings plus synthetic cash assets.
4. Upsert compact position states using quantity and `average_cost` as the
   state-changing fields.
5. Store or update the daily `portfolio_value_snapshots` row from parsed OpenD
   funds fields: `total_assets`, `cash`, `fund_assets`, `securities_assets`,
   `market_val`, and currency.
6. Store child `portfolio_weight_snapshots` rows for all holdings and cash rows,
   with overall weight out of total assets.
7. Store unsupported quote, missing data, and cash-sweep assumptions as
   `data_quality_events`.
8. Read history status/growth/allocation context from SQL MCP.
9. Pass current snapshot plus lean historical context to the LLM evaluator.

Run it against live OpenD and Gemini:

```bash
.venv/bin/python scripts/portfolio_agent_review.py --env-file config/local.env
```

Choose OpenAI instead:

```bash
.venv/bin/python scripts/portfolio_agent_review.py \
  --env-file config/local.env \
  --llm-provider openai
```

Run it against a recorded OpenD report:

```bash
.venv/bin/python scripts/portfolio_agent_review.py \
  --env-file config/local.env \
  --from-report reports/opend/field-report.json
```

Diagnose the live OpenD trade-read path without running an agent:

```bash
.venv/bin/python scripts/debug_opend_trade_calls.py --env-file config/local.env
```

The diagnostic script calls only read APIs: account list, account funds, and
positions. It does not call trade unlock or order APIs.

## Verification

Run the focused MCP tests:

```bash
.venv/bin/python -m pytest tests/test_mcp_servers.py
.venv/bin/python -m pytest tests/test_mcp_tool_contracts.py
.venv/bin/python -m pytest tests/test_mcp_stdio_round_trips.py
```

Run the full project suite:

```bash
.venv/bin/python -m pytest
```

For the full test responsibility map, see [TESTING.md](TESTING.md).
