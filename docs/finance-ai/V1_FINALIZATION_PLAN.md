# V1 Finalization Plan

This is the short path from the current prototype to a usable first version of
the Investment Agent branch.

## Current State

Implemented and locally verified:

- Read-only OpenD adapter and `moomail-opend-mcp`.
- Portfolio normalization from OpenD account funds, positions, and quote rows.
- Per-symbol quote retry when OpenD rejects one symbol, such as OTC `US.TCEHY`.
- Optional account-level `fund_assets` cash-sweep treatment through
  `MOOMAIL_MOOMOO_TREAT_FUND_ASSETS_AS_CASH_SWEEP`.
- SQLite portfolio snapshot, quote, metric, audit, and run-summary storage.
- `moomail-portfolio-sql-mcp` and `moomail-finance-metrics-mcp`.
- MCP-backed Portfolio Agent using OpenD, SQL, metrics, and a provider-neutral
  LLM evaluator.
- LLM structured-output recovery for malformed or truncated portfolio evaluator
  JSON.
- Local file-backed memory placeholder.
- Deterministic local research fixtures and Sentiment Agent placeholder.
- Full local Investment Agent prototype.
- Local chatbot frontend with bottom composer, Send button, streaming status
  messages, technical trace, resizable chat rail, and hide/show controls.

Verified deterministic suite:

```text
64 passed, 10 skipped
```

## V1 Definition

V1 should be considered complete when the local app can reliably run a
portfolio-only review from live OpenD and show the result in terminal and web UI.

V1 includes:

- Live OpenD securities account read path.
- Current portfolio snapshot with holdings, cash, optional cash sweep, and quote
  warnings.
- Deterministic metrics and allocation views.
- SQLite daily snapshot persistence.
- Portfolio-only LLM evaluation with structured output.
- No trading tools, no trade unlock, no order placement, and no executable
  order-preparation path.
- Clear missing-data warnings for unsupported quotes, insufficient history, and
  unavailable research.

V1 does not include:

- Crypto account ingestion.
- OTC quote fallback provider.
- Pinecone memory.
- Neo4j GraphRAG.
- Official MCP SDK runtime migration.
- Full Investment Agent synthesis over real research.
- Scheduled daily checks.

## Remaining Work

### 1. OpenD Hardening

- Keep `fund_assets` cash-sweep treatment opt-in.
- Document the exact local env needed for your MooMoo setup.
- Add a one-command live OpenD health report that runs connection, account list,
  funds, positions, quotes, and normalized snapshot summary.
- Keep OTC quote failures non-blocking when the holding row itself is available.
- Keep crypto account discovery separate from the securities v1 path.

Exit criteria:

- Live snapshot builds from OpenD with expected holdings count.
- Unsupported OTC quotes appear as warnings, not crashes.
- Cash sweep behavior is controlled by env and visible in data-quality warnings.

### 2. Portfolio Agent Output Contract

- Freeze the `PortfolioAgentResult` and `final_report.portfolio_analysis`
  shapes used by the frontend.
- Include effective cash fields in the structured output.
- Keep LLM evaluator lists compact and recover malformed JSON gracefully.
- Add one recorded fixture that includes OTC quote failure and cash sweep.

Exit criteria:

- Frontend and terminal render the same core facts.
- Parser never exposes raw fenced JSON as the report summary.

### 3. Frontend Stabilization

- Restart and verify `scripts/serve_chat.py` against the live OpenD path.
- Add a visible warning area for missing quote rows and cash-sweep assumptions.
- Keep trace output for tool calls and storage status.
- Add a simple loading/failure reset path if the backend request fails mid-run.

Exit criteria:

- Chat review works from the Send button.
- Streaming status events remain visible in the chat rail.
- Resizing and hide/show controls do not break report layout.

### 4. Documentation and Runbook

- Keep `README.md`, `ENVIRONMENT.md`, `CONNECTOR_TESTS.md`, and milestone docs
  aligned with the actual commands.
- Add a short local runbook for:
  - first-time setup,
  - live OpenD diagnosis,
  - portfolio review in terminal,
  - portfolio review in web UI,
  - deterministic tests,
  - live connector tests.

Exit criteria:

- A future session can start the project and run a live portfolio review without
  rediscovering OpenD setup details.

### 5. Release Gate

- Run deterministic tests.
- Run live OpenD-only connector tests.
- Run one terminal Portfolio Agent review.
- Run one web Portfolio Agent review.
- Inspect warnings and confirm no trade tools are exposed.

Exit criteria:

- Deterministic tests pass.
- Live OpenD path passes on the local machine.
- The output is useful enough to inspect your portfolio without manual JSON
  digging.

## V1.1 Backlog

- Add OTC quote fallback through a separate market-data provider MCP.
- Add `OpenCryptoTradeContext` exploration for crypto holdings.
- Replace local research fixtures with `research-rag-mcp`.
- Add Pinecone-backed memory after the output contract is stable.
- Move from in-process MCP modules to official MCP SDK/client transport if it
  adds real value.
- Add saved report browsing and export.
