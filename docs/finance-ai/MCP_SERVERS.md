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
  supported quote rows while recording unsupported symbols as warnings.
- Account-level `fund_assets` is treated as cash sweep only when
  `MOOMAIL_MOOMOO_TREAT_FUND_ASSETS_AS_CASH_SWEEP=true`.

### `moomail-portfolio-sql-mcp`

Tools:

- `portfolio_sql_initialize`
- `portfolio_sql_store_snapshot`
- `portfolio_sql_store_daily_snapshot_if_needed`
- `portfolio_sql_store_metrics`
- `portfolio_sql_store_audit_record`
- `portfolio_sql_history_status`
- `portfolio_sql_latest_snapshot`
- `portfolio_sql_table_count`

Resources:

- `portfolio-sql://schema`
- `portfolio-sql://status`

This server owns durable portfolio snapshots, calculated metric rows, and
compact audit summaries. It stores summaries and structured records, not hidden
model reasoning.

The daily snapshot tool is idempotent. It inserts one snapshot per portfolio and
snapshot date, and skips duplicate writes while updating the row's
`last_observed_at` timestamp.

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

`calculate_cash_weight` reports effective cash weight. It includes cash balances
plus holdings classified as `cash_equivalent`.

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
- `moomail-portfolio-sql-mcp` for idempotent daily snapshot persistence,
  metric storage, and history status.
- A provider-neutral LLM evaluator for portfolio-only evaluation after
  deterministic tools finish. Gemini and OpenAI adapters are supported; Gemini is
  the current default.

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
