# Agent Design

## Agent Tree

```text
Future Main Finance Orchestrator
└── Investment Agent [v2 focus]
    ├── Portfolio Agent
    └── Sentiment Agent

Future branch:
└── Budgeting / Expenses / Savings Agent
```

V1 is complete as a Portfolio Agent proof of concept with OpenD and local SQL
history. V2 focuses on making the Investment Agent a thin LangGraph supervisor
over the Portfolio Agent and a Sentiment Agent stub. The future Main Finance
Orchestrator can route between investment and budgeting domains later, but it is
not required for V2.

## Investment Agent

The Investment Agent is the primary user-facing reasoning agent for investment questions.

Responsibilities:

- Interpret the user's investment query and infer the mode when useful.
- Load the Investment Policy Statement.
- Retrieve relevant long-term memory from Pinecone.
- Request portfolio diagnostics from the Portfolio Agent.
- Request research and sentiment context from the Sentiment Agent in most investment analysis flows.
- Synthesize portfolio facts, market context, research evidence, and policy constraints.
- Produce source-backed investment analysis and optimization recommendations.
- Run final guardrail review before responding.
- Propose memory writes when durable investment context should be preserved.
- Store audit records and simple output summaries.

The Investment Agent owns the Portfolio Agent and Sentiment Agent from an
orchestration perspective. The subagents should not freely message each other.
The Investment Agent coordinates them through structured inputs and outputs.

### V2 Investment Agent Target

V2 should implement the Investment Agent as a thin LangGraph supervisor:

- classify the user query
- load the IPS
- decide whether portfolio context is required
- decide whether sentiment/research context is required
- call Portfolio Agent when needed
- call Sentiment Agent stub when needed
- synthesize the answer
- run guardrails
- emit structured terminal/frontend output

The Investment Agent, not the Portfolio Agent, decides whether sentiment is
needed. The Portfolio Agent may return candidate sentiment scope, but it should
not invoke the Sentiment Agent directly.

### Supported Modes

The chatbot can infer or suggest these modes through conversation:

- `review`: full portfolio review
- `rebalance`: allocation and drift analysis
- `deep_dive`: focused holding or thesis analysis
- `risk_check`: concentration, volatility, drawdown, and exposure review
- `what_changed`: compare current context with prior thesis or review
- `buy_or_hold`: reasoned position assessment without executable trade instructions
- `compare`: compare assets, holdings, sectors, or scenarios

Modes are not required as rigid UI controls in V2. Terminal output remains
acceptable while backend formats mature.

## Portfolio Agent

The Portfolio Agent is quantitative and portfolio-focused.

Responsibilities:

- Read current positions, balances, cash, and quotes from `moomail-opend-mcp`.
- Read portfolio growth, allocation history, and compact position states from
  `moomail-portfolio-sql-mcp`.
- Use `moomail-finance-metrics-mcp` for deterministic calculations.
- Analyze actual portfolio state, allocation, concentration, risk, and performance.
- Detect stale or missing data.
- Return structured diagnostics and candidate concerns to the Investment Agent.
- Treat explicit cash-equivalent holdings as cash for cash-weight/allocation
  metrics while preserving the original holding in the snapshot.
- Treat OpenD account-level `fund_assets` as auto-invested money-market fund
  assets/effective cash-equivalent purchasing power only when the local OpenD
  config explicitly enables that assumption. This is not idle cash.

The Portfolio Agent does not generate final user-facing recommendations. It provides evidence, metrics, and portfolio performance analysis for the Investment Agent to synthesize.

Current V1 implementation:

- Deterministic pipeline: `opend_get_portfolio_context`,
  `calculate_snapshot_metrics`, lean SQL identity upserts,
  `portfolio_sql_upsert_position_states`,
  `portfolio_sql_store_daily_value_snapshot`,
  `portfolio_sql_store_weight_snapshots`,
  `portfolio_sql_store_data_quality_events`, and
  `portfolio_sql_get_history_status`.
- LLM evaluator: a provider-neutral LLM adapter produces a portfolio-only
  structured evaluation after deterministic tools complete. Gemini and OpenAI
  are supported, with Gemini as the current default. The evaluator now asks for
  compact JSON, answers portfolio-only user queries directly before giving a
  broad overview, and recovers partial structured fields when a provider returns
  malformed or truncated fenced JSON.
- Persistence policy: SQL MCP stores one daily value snapshot per
  portfolio/account/date, updates same-day observations in place, and replaces
  child allocation weight rows for coherence.

Implemented persistence policy after the 2026-06-02 portfolio-history refactor:

- Upsert portfolio, account, and asset identity rows.
- Upsert compact position states, using `average_cost` as canonical cost basis.
- Store one daily portfolio value snapshot per portfolio/account/date.
- Store child portfolio weight snapshots for holdings, literal cash, configured
  cash sweep, options, and cash-equivalent funds.
- Store unsupported quote, stale history, and cash-sweep assumption warnings as
  data-quality events.
- Do not store broad raw OpenD blobs or daily quote history.

The Portfolio Agent LLM may interpret portfolio-only facts. It must not decide
whether to write SQL rows, invent market sentiment, or issue trade instructions.

### V2 Portfolio Agent

V2 converts the Portfolio Agent into a bounded-planning subgraph. The planner
decides which portfolio context is needed for the assigned task:

- current OpenD snapshot
- SQL history status
- latest portfolio state
- portfolio growth
- allocation history
- relevant tickers/assets
- required metric groups
- persistence for review-style runs

Execution remains deterministic once the plan is produced. The Portfolio Agent
returns structured portfolio evidence and candidate sentiment scope, not final
investment advice.

Current V2 behavior:

- Full review and deep-dive tasks preserve broad V1 context and persistence.
- Cash/allocation/holding fact tasks avoid broad SQL history reads by default.
- What-changed tasks request history status, latest state, portfolio growth,
  and allocation history.
- Each run returns planned, actual, and skipped tool entries in
  `PortfolioAgentResult.tool_calls`.

### Portfolio Agent Output

The Portfolio Agent should return:

- Portfolio snapshot
- Holdings and weights
- Cash position and cash drag
- Unrealized P&L where available
- Realized P&L where available
- Sector exposure
- Currency exposure
- Top holdings and concentration
- Benchmark comparison, defaulting to `SPY` or `VTI` unless the IPS specifies otherwise
- Historical performance analysis from SQL snapshots when available
- Risk metrics
- Allocation drift
- Data quality warnings
- Candidate issues for Investment Agent review
- Portfolio-only LLM evaluation with strengths, risks, IPS mismatches, history
  observations, and open questions
- Data-quality warnings for unsupported OTC quote snapshots and opt-in
  auto-invested fund-assets assumptions

Frozen V1 output fields:

- `PortfolioAgentResult.effective_cash`
- `PortfolioAgentResult.history_context`
- `final_report.portfolio_analysis.effective_cash`
- `final_report.portfolio_analysis.history_context`
- `final_report.portfolio_analysis.storage_result`
- `final_report.portfolio_analysis.metrics_storage_result`
- `final_report.portfolio_analysis.history_status`
- `final_report.portfolio_analysis.tool_calls`

### Required Metrics

Required v1 metrics:

- Total portfolio value
- Position value and weight
- Cash weight
- Effective cash weight, including literal cash, explicit cash-equivalent
  holdings, and configured auto-invested fund assets
- Unrealized P&L
- Realized P&L if available
- Sector allocation
- Top holdings
- Single-position concentration
- Volatility estimate if historical data exists
- Beta if data exists
- Drawdown if historical snapshots exist
- Correlation if price history exists

Optional advanced metrics:

- Sharpe ratio
- Sortino ratio
- VaR
- CVaR
- Factor exposure
- Tracking error
- Contribution to risk
- Dividend yield
- Scenario sensitivity

Financial calculations should be deterministic Python functions exposed through `moomail-finance-metrics-mcp`. The LLM should not invent calculations in prose.

## Sentiment Agent

The Sentiment Agent is qualitative, source-grounded, and research-focused.

Responsibilities:

- Retrieve relevant company, filing, transcript, report, and research evidence for portfolio holdings.
- Use GraphRAG over Neo4j plus vector retrieval.
- Summarize thesis, management tone, recent developments, risks, catalysts, contradictions, and open questions.
- Prioritize holdings selected by the Investment Agent.
- Search for disconfirming evidence for major thesis claims.
- Return citations and source metadata.

The Investment Agent decides when the Sentiment Agent participates. For full
portfolio reviews, the Investment Agent will usually request sentiment context
for major holdings, large contributors, large weight changes, or named tickers.
For mechanical portfolio questions, such as cash balance or allocation-by-ticker
queries, sentiment can be skipped.

V2 uses a Sentiment Agent stub only. It should accept the future GraphRAG task
shape and return explicit missing-research fields without fabricating sentiment.

### Sentiment Agent Scope

V2 stub scope is limited to stocks currently in the portfolio or explicitly
requested by the Investment Agent. Watchlist and broader market research can be
added later.

The future research corpus will be manually populated by the user during
testing. No automatic web/news ingestion is required for the first GraphRAG
implementation.

### Sentiment Agent Output

For each requested holding, the Sentiment Agent should return:

- Ticker and company
- Thesis summary
- Recent developments from the curated corpus
- Management tone where transcripts or letters exist
- Key risks
- Potential catalysts
- Contradictory evidence
- Source-backed qualitative stance: positive, mixed, negative, or unclear
- Supporting citations
- Open questions and missing research

The Sentiment Agent does not write directly to Pinecone. It can return candidate insights. The Investment Agent decides what, if anything, becomes long-term memory.

## Investment Policy Statement

Optimization recommendations require an Investment Policy Statement. Factual questions can be answered without one.

The IPS should contain:

- Goals
- Time horizon
- Risk tolerance
- Cash needs
- Preferred asset classes
- Forbidden assets
- Maximum single-stock concentration
- Sector concentration limits
- Target cash allocation
- Rebalancing rules
- Benchmark preference
- Personal investment beliefs

The IPS is not editable through chat in V2. It should live as canonical
structured local configuration or local storage. Summaries can eventually be
embedded into Pinecone for retrieval, but Pinecone memory must never override
the canonical IPS.

## Agent Boundaries

- Portfolio Agent: quantitative portfolio state and metrics.
- Sentiment Agent: qualitative source-grounded research and thesis context.
- Investment Agent: synthesis, policy judgment, recommendations, memory, and final response.

The subagents return structured objects, not final prose. The Investment Agent owns the final answer.

## Guardrail Position

All agents must observe the system's no-trading policy. The strongest guardrail is tool design: no MCP server should expose trade placement, order preparation, or execution tools.
