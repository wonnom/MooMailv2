# V4 Task Notes

Status: future planning notes. V4 is not scheduled until the V3 MCP gateway,
deterministic portfolio data lane, and agent gateway migration are complete.

## Core Direction

V4 should move the Portfolio Agent from temporary deterministic bounded
planning toward an explicit planning architecture.

The current V2/V3 Portfolio Agent uses hardcoded keyword and regex helpers for:

- task type selection
- ticker extraction
- history window choice
- required history/tool scope

This is acceptable only as a testable bridge while the MCP/runtime foundations
are being built. It should not become the long-term architecture.

## Portfolio Planner Migration

The Portfolio Agent should eventually perform a structured planning step before
tool execution, similar to the existing `PortfolioTask` and
`PortfolioContextPlan` contracts but produced by a guided planner rather than
inline regex logic.

The planner should decide:

- task type
- relevant tickers or asset ids
- history window
- which SQL history tools to call
- whether position-state change history should be ticker-scoped or portfolio-wide
- whether current OpenD context is required
- which metric groups are required
- whether persistence should occur

Execution after the plan is selected should remain deterministic and auditable.
The LLM or LangGraph planning node should choose the plan; Python/MCP tools
should execute it.

## Ticker Scope Note

Current implementation note:

- `interpret_portfolio_task()` still extracts tickers with a deterministic
  regex helper.
- `portfolio_sql_get_position_state_changes` can receive a ticker parameter,
  but the choice of which ticker to pass is still made by the temporary bounded
  planner.

V4 target:

- Move ticker and asset-scope selection out of `interpret_portfolio_task()`.
- Represent ticker/asset scope as planner output.
- Keep a deterministic fallback planner for tests and offline mode, but make it
  explicit that it is a fallback implementation.
- Add tests proving a planner can choose `AMZN` for a query like "What price did
  I buy my recent AMZN shares at?" and that execution passes that ticker to
  `portfolio_sql_get_position_state_changes`.

## Non-Goals

- Do not let the LLM directly calculate cost basis or inferred purchase price.
- Do not make tool execution autonomous after planning.
- Do not remove deterministic tests; use fake planner outputs for stable tests.
