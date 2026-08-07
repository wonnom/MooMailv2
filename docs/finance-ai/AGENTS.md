# Agent Design

## Agent Tree

```text
Future Main Finance Orchestrator
└── Investment Agent [current focus]
    ├── Portfolio Agent
    └── Sentiment Agent

Future branch:
└── Budgeting / Expenses / Savings Agent
```

The current runtime supports the Investment Agent branch: a thin LangGraph
Investment Agent supervisor over the Portfolio Agent and a Sentiment Agent stub.
The future Main Finance Orchestrator can route between investment and budgeting
domains later, but it is not part of the current runtime. A deterministic
backend portfolio data lane handles dashboard status, page-load, and manual
refresh; that service is application infrastructure, not a Portfolio Agent run.

## Investment Agent

The Investment Agent is the primary user-facing reasoning agent for investment questions.

Responsibilities:

- Interpret the user's investment query and infer the mode when useful.
- Load the Investment Policy Statement.
- Retrieve relevant long-term memory from Pinecone in a future version.
- Request portfolio diagnostics from the Portfolio Agent.
- Request research and sentiment context from the Sentiment Agent in most investment analysis flows.
- Synthesize portfolio facts, market context, research evidence, and policy
  constraints. In the current runtime this synthesis is deterministic/template-style;
  richer LLM synthesis remains future work.
- Produce source-backed investment analysis and optimization recommendations.
- Run final guardrail review before responding.
- Propose memory writes when durable investment context should be preserved in
  a future version.
- Store audit records and simple output summaries in a future persistence pass.

The Investment Agent owns the Portfolio Agent and Sentiment Agent from an
orchestration perspective. The subagents should not freely message each other.
The Investment Agent coordinates them through structured inputs and outputs.

### Investment Agent

The Investment Agent is implemented as a thin LangGraph supervisor:

- load the IPS
- load the compact deterministic portfolio baseline
- plan the user query as one typed `InvestmentTurnDecision`, including the
  direct answer when baseline evidence appears sufficient
- validate original-query safety, source integrity, planner output, and
  baseline evidence coverage before subagent calls
- decide whether portfolio context is required
- decide whether sentiment/research context is required
- call Portfolio Agent when needed
- call Sentiment Agent stub when needed
- convert covered direct output or delegated evidence into the final answer
- run guardrails
- emit structured terminal/frontend output and sanitized trace

The Investment Agent, not the Portfolio Agent, decides whether sentiment is
needed. The Portfolio Agent may return candidate sentiment scope, but it should
not invoke the Sentiment Agent directly.

Current limitations:

- Investment planning is LLM-backed structured output with no keyword/regex
  fallback. Planner unavailability or invalid output fails closed.
- Ticker/asset-scope selection is now explicit `AssetHint` planner output at the
  Investment Agent layer, and the Portfolio Agent has a bounded
  `PortfolioRequest` evidence-planning and evidence-packet execution path.
  Legacy `PortfolioTask` compatibility remains for older callers.
- Baseline-covered answers are composed in the first Investment LLM turn.
  Delegated final synthesis remains deterministic/template-style; detailed
  Portfolio handoffs may use one portfolio-only evaluator call after evidence.
- Pinecone memory is not connected.
- The runtime does not place, prepare, or suggest executable trades.

### Planning Responsibility

Target planning ownership:

- Investment Agent planner: user intent, mode, subagent needs, broad
  logical ticker/theme/time-horizon scope, bounded portfolio request, freshness
  requirement, and final synthesis constraints.
- Portfolio Agent compiler: deterministic asset resolution, canonical portfolio
  ticker/asset scope, SQL history scope, metric groups, current-value dependency,
  persistence mode, and portfolio-only pattern detection from the validated
  bounded request.
- Deterministic policy: freshness enforcement, OpenD connection checks, SQL
  freshness checks, permission validation, tool execution, finance math, and
  persistence.
- Sentiment Agent planner: future research scope and evidence strategy. This is
  not implemented in V1.4.

Investment Agent should plan enough to decide which subagents are needed and
what bounded evidence request to send. It should not micromanage exact
SQL/OpenD/metric tool calls, and it should not need to know broker-specific
symbols such as `US.AAPL` or SQL asset ids. Portfolio Agent should resolve
logical asset hints against actual portfolio data and plan only inside the
portfolio evidence domain. Sentiment Agent should eventually plan research
retrieval, but it should not make portfolio allocation or trade decisions.

Implementation status as of 2026-06-29: V1.4.0 through V1.4.5 added the typed
planner contracts, deterministic asset resolver/validator primitives, live
Investment Agent `InvestmentPlan` planning/validation, Portfolio Agent
`PortfolioEvidencePlan` planning, deterministic evidence-plan execution,
separated `PortfolioEvidencePacket` output, and trace/evaluation closeout
coverage.

V1.5.0 adds the contracts for the next routing shape without changing the live
graph yet. `PortfolioBaselinePacket` can represent bounded deterministic
dashboard/SQL capabilities and evidence references. `InvestmentTurnDecision`
can return a baseline-cited direct answer or an explicit bounded Portfolio
delegation. Deterministic coverage policy checks capability presence,
freshness, requested windows, and evidence refs before a direct answer can be
accepted. Original-query safety and `PortfolioRequest.source_query` integrity
are validated before subagent calls.

The same task adds separate provider-neutral `LLMCallTrace` and concise
`UserProgressEvent` contracts.

V1.5.1 now implements baseline construction as deterministic application
infrastructure. `PortfolioBaselineService` reads the latest stored portfolio,
bounded 7-day/30-day SQL history, and deterministic cash metrics through a
least-privilege no-OpenD gateway profile. It returns compact cited evidence and
limitations without calling an agent or LLM. Live Investment route adoption,
call-budget enforcement, LangSmith instrumentation, and frontend progress
grouping were assigned to V1.5.2 through V1.5.5.

V1.5.2 adopts the baseline and `InvestmentTurnDecision` in the live graph.
Public web chat always enters Investment Agent. Covered breakdown, allocation,
effective-cash, 7-day/30-day rough-trend, and recent-change requests can finish
with the one Investment LLM call. Deterministic policy converts failed direct
coverage to the planner-supplied bounded Portfolio fallback or returns an
explicit limitation; it never invents a new mission.

V1.5.3 compiles Portfolio evidence plans deterministically from the validated
request and resolved asset scope. `analysis_requirement` distinguishes
deterministic-only evidence retrieval from interpretation-required analysis.
The former skips the Portfolio evaluator; the latter permits one Portfolio
analysis call, keeping the normal delegated total at two calls including the
Investment decision.

V1.5.4 instruments those calls at the shared generation boundary. MooMail gets
start/completed/failed lifecycle events even when LangSmith is off. During
delegation, Portfolio compiler, planned/actual/skipped tool, evaluator,
warning, and error statuses stream into the Investment trace with the Portfolio
run retained as `child_run_id`; final result adaptation does not duplicate live
events. Optional LangSmith spans and checkpoint summaries are observability
consumers only and cannot change agent routing, evidence, or dashboard state.

### Supported Modes

The chatbot can infer or suggest these modes through conversation:

- `review`: full portfolio review
- `rebalance`: allocation and drift analysis
- `deep_dive`: focused holding or thesis analysis
- `risk_check`: concentration, volatility, drawdown, and exposure review
- `what_changed`: compare current context with prior thesis or review
- `buy_or_hold`: reasoned position assessment without executable trade instructions
- `compare`: compare assets, holdings, sectors, or scenarios

Modes are not required as rigid UI controls. Terminal output remains
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

Current implementation:

- Deterministic pipeline: `opend_get_portfolio_context`,
  `calculate_snapshot_metrics`, lean SQL identity upserts,
  `portfolio_sql_upsert_position_states`,
  `portfolio_sql_store_daily_value_snapshot`,
  `portfolio_sql_store_weight_snapshots`,
  `portfolio_sql_store_data_quality_events`, and
  `portfolio_sql_get_history_status`.
- `what_changed` and broad review plans can also read
  `portfolio_sql_get_position_state_changes` so the evaluator can explain
  compact quantity/average-cost changes, including inferred added-share average
  cost when SQL has adjacent position states.
- If a bounded portfolio-change request resolves assets, the context adapter
  passes `asset_id` scope into the position-state change read; legacy
  ticker-only plans pass tickers, and unscoped plans scan recent changes across
  the portfolio within the configured history window.
- Conditional LLM evaluator: a provider-neutral LLM adapter produces a
  portfolio-only structured evaluation after deterministic tools complete only
  when the bounded request requires interpretation. Gemini and OpenAI are
  supported, with Gemini as the current default. The evaluator asks for
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

Runtime note: the deterministic dashboard lane and Portfolio Agent both use
the MCP gateway. The Portfolio Agent receives a permissioned `MCPToolGateway`,
not direct `RegisteredMCPModule` objects. This does not change the agent's
responsibility boundary.

### Portfolio Agent Evidence Compilation

The Portfolio Agent has a bounded compilation path. Exhaustive deterministic
policy maps the already-validated request to the portfolio context needed for
the assigned task:

- deterministic resolution from logical asset hints to canonical portfolio
  symbols, SQL asset ids, and OpenD-compatible symbols
- current OpenD snapshot
- SQL history status
- latest portfolio state
- portfolio growth
- allocation history
- relevant tickers/assets
- required metric groups
- persistence for review-style runs

The active path accepts a bounded `PortfolioRequest`, validates and resolves
asset hints against supplied candidates, produces a
`PortfolioEvidencePlan`, then enforces deterministic freshness/tool policy and
assembles a separated `PortfolioEvidencePacket` before optional interpretation.
The V1.4 LLM evidence-planner classes remain compatibility/test-only and are not
constructed by the normal Portfolio runtime. Compatibility `context_plan` and
`portfolio_packet` fields remain available for current reports. This is
implemented inside the existing Python Portfolio Agent path, not as a separate
compiled LangGraph subgraph. The Portfolio Agent returns structured portfolio
evidence and candidate sentiment scope, not final investment advice.

The Portfolio Agent should add value as a portfolio analyst assistant: it should
surface concentration, allocation drift, cash/cash-equivalent effects,
position-state changes, outliers, stale data, and other portfolio-only patterns
the Investment Agent should consider. It must label those as portfolio-only
observations and avoid inventing sentiment, fundamentals, or a final thesis.

Current behavior:

- Full review and deep-dive tasks preserve broad review context and persistence.
- Cash/allocation/holding fact tasks avoid broad SQL history reads by default.
- What-changed tasks request history status, latest state, portfolio growth,
  allocation history, and position-state changes.
- Bounded `PortfolioRequest` runs can preserve resolved `asset_id` and
  canonical-symbol scope for position-state change reads.
- Bounded `PortfolioRequest` runs obey deterministic freshness policy:
  `latest_required` calls OpenD, `cached_ok` can use fresh SQL latest state
  without OpenD, and `history_only` reads SQL history without OpenD.
- `deterministic_only` handoffs return facts, metrics, changes, patterns, and
  limitations without a Portfolio model call. Detailed review/risk/pattern
  requests require `interpretation_required` and receive at most one call.
- Each run returns planned, actual, and skipped tool entries in
  `PortfolioAgentResult.tool_calls`, plus expected/actual model-call counts.

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

Stable output fields:

- `PortfolioAgentResult.effective_cash`
- `PortfolioAgentResult.history_context`
- `PortfolioAgentResult.evidence_packet`
- `final_report.portfolio_analysis.effective_cash`
- `final_report.portfolio_analysis.evidence_packet`
- `final_report.portfolio_analysis.history_context`
- `final_report.portfolio_analysis.storage_result`
- `final_report.portfolio_analysis.metrics_storage_result`
- `final_report.portfolio_analysis.history_status`
- `final_report.portfolio_analysis.tool_calls`

### Required Metrics

Required metrics:

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

The Sentiment Agent is currently a stub only. It accepts the future GraphRAG task shape
and returns explicit missing-research fields without fabricating sentiment,
citations, holdings, source metadata, or company facts.

### Sentiment Agent Scope

Stub scope is limited to stocks currently in the portfolio or explicitly
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

The IPS is not editable through chat in the current runtime. It should live as canonical
structured local configuration or local storage. Summaries can eventually be
embedded into Pinecone for retrieval, but Pinecone memory must never override
the canonical IPS.

## Agent Boundaries

- Portfolio Agent: quantitative portfolio state and metrics.
- Sentiment Agent: qualitative source-grounded research and thesis context.
- Investment Agent: synthesis, policy judgment, recommendations, memory, and final response.

The subagents return structured objects, not final prose. The Investment Agent owns the final answer.

## User Progress And Audit Ownership

Investment Agent remains the only public chat owner. Internal Investment,
Portfolio, graph-node, model, and tool events are preserved as sanitized
`TraceEvent` records, but the normal chat timeline receives only the bounded
plain-language `UserProgressEvent` stages. Repeated successful tool activity is
grouped in the audit view; warnings and errors remain individually inspectable.

Portfolio Agent remains an internal portfolio-only subagent. Its child run id,
deterministic tools, and conditional analysis model call appear under the parent
Investment run. A frontend report may replace the deterministic dashboard only
after the Investment final guardrails pass and no terminal analytical failure
was recorded.

## Guardrail Position

All agents must observe the system's no-trading policy. The strongest guardrail is tool design: no MCP server should expose trade placement, order preparation, or execution tools.
