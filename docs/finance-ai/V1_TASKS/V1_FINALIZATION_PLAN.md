# V1 Closeout

V1 is complete as of 2026-06-06.

V1 is a Portfolio Agent proof of concept with OpenD and local SQL portfolio
history. It is intentionally narrower than the long-term multi-agent investment
system.

## Implemented

- Read-only OpenD adapter and `moomail-opend-mcp`.
- OpenD normalization from account funds, positions, supported quotes, and
  non-blocking unsupported quote warnings.
- Per-symbol quote retry when OpenD rejects quote snapshots for a position,
  such as OTC `US.TCEHY`; the holding itself still displays from position data.
- Optional account-level `fund_assets` effective-cash treatment through
  `MOOMAIL_MOOMOO_TREAT_FUND_ASSETS_AS_CASH_SWEEP`.
- One canonical local portfolio-history DB: `data/portfolio-history.sqlite`.
- Lean SQLite schema: portfolio/account/assets, position states, daily value
  snapshots, allocation weight snapshots, data-quality events, audit summaries,
  and run-source links.
- `moomail-portfolio-sql-mcp` and `moomail-finance-metrics-mcp`.
- MCP-backed Portfolio Agent using OpenD, SQL, metrics, and a provider-neutral
  portfolio-only LLM evaluator.
- LLM structured-output recovery for malformed or truncated portfolio evaluator
  JSON.
- Local file-backed memory placeholder.
- Deterministic research fixtures and Sentiment Agent placeholders.
- Static local chatbot frontend with Send button, streaming status messages,
  structured stream error handling, technical trace, resizable chat rail, and
  hide/show controls.
- Terminal Portfolio Agent review path.

## Verified

Latest deterministic suite:

```text
77 passed, 10 skipped
```

Latest live OpenD-only connector gate:

```text
2 passed, 1 warning
```

The warning is from the MooMoo SDK deprecation warning seen during live tests,
not from a failed project assertion.

## V1 Definition

V1 is complete when the local app can run a portfolio-only review from OpenD and
show the result in terminal and web UI.

V1 includes:

- Live OpenD securities account read path.
- Current portfolio snapshot with holdings, literal cash, optional
  auto-invested fund assets/effective cash, and quote warnings.
- Deterministic metrics and allocation views.
- SQLite daily portfolio value snapshot persistence.
- Lean portfolio-history schema for daily value snapshots, position states,
  allocation weights, data-quality events, and agent-run summaries.
- Portfolio-only LLM evaluation with structured output.
- No trading tools, no trade unlock, no order placement, and no executable
  order-preparation path.
- Clear missing-data warnings for unsupported quotes, insufficient history, and
  unavailable research.

## Not Included

- Thin LangGraph Investment Agent supervisor.
- Bounded-planning Portfolio Agent subgraph.
- Real Sentiment Agent.
- Neo4j GraphRAG ingestion or retrieval.
- Pinecone memory.
- Official MCP SDK/client runtime migration.
- Crypto account ingestion.
- OTC quote fallback provider.
- Scheduled daily checks.
- Rich React frontend migration.

## V2 Direction

V2 starts from this V1 base and builds:

- a thin LangGraph Investment Agent supervisor
- a bounded-planning Portfolio Agent subgraph
- a Sentiment Agent stub with the future GraphRAG contract
- Investment Agent synthesis and guardrails over those subagent outputs

See [ACTION_PLAN.md](../ACTION_PLAN.md) for the active V2 plan.
