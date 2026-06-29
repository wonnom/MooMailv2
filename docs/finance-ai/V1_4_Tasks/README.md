# V1.4 Task Notes

Status: current planning and execution notes. V1.3 MCP gateway, deterministic
portfolio data lane, and agent gateway migration are complete. V1.4 structured
planning work has started; V1.4.0 and V1.4.1 are complete as of 2026-06-24,
V1.4.2 and V1.4.3 are complete as of 2026-06-25, and V1.4.4 and V1.4.5
are complete as of 2026-06-29.

## V1.4 Goal

V1.4 should replace temporary deterministic interpretation inside the agent paths
with explicit structured planning while keeping tool execution deterministic.

V1.4 is not a request to make every tool call autonomous. The intended split is:

```text
LLM or guided planner chooses typed intent and scope
  -> deterministic policy validates/refines the plan
  -> MCP tools execute deterministically
  -> LLM synthesizes or explains evidence where useful
  -> deterministic guardrails check final output
```

## Scope

In scope:

- Structured Investment Agent planner.
- Structured Investment-to-Portfolio request contract.
- Structured Portfolio Agent evidence planner.
- Typed plan contracts for task intent, ticker/asset scope, history window,
  freshness requirement, subagent calls, metric groups, and persistence mode.
- Deterministic asset resolution from user-facing symbols/names to portfolio
  assets, SQL asset ids, and OpenD-compatible symbols.
- Deterministic validation and fallback planners for tests/offline mode.
- Trace output showing planner decisions and deterministic policy decisions.

Out of scope:

- Sentiment Agent implementation.
- Neo4j GraphRAG ingestion/retrieval.
- Pinecone memory.
- Trading, order preparation, trade unlock, or executable trade tooling.
- LLM-calculated finance math.

The Sentiment Agent contract may be referenced in V1.4, but implementation remains
a later version.

## Implementation Progress

Completed as of 2026-06-24:

- V1.4.0 added additive Pydantic contracts for typed Investment plans, bounded
  `PortfolioRequest` handoffs, logical `AssetHint` inputs, deterministic
  `AssetResolution` outputs, Portfolio evidence plans, separated Portfolio
  evidence packets, and planner/policy trace phases.
- V1.4.1 added `src/moomail_finance_ai/asset_resolver.py`, a deterministic
  resolver and request-validator module that maps logical hints against supplied
  SQL/current-snapshot/fixture candidates, returns explicit resolution statuses,
  blocks unsafe trade/order intent, and emits sanitized trace events.

Completed as of 2026-06-25:

- V1.4.2 added `src/moomail_finance_ai/investment_planner.py`, moved the
  Investment Agent graph onto a typed `InvestmentPlan` planner/validator node
  before subagent calls, preserved the existing `query_plan`/`PortfolioTask`
  adapter for the current Portfolio Agent runtime, and exposed planner decisions
  in sanitized trace and chat responses.
- V1.4.2 also normalized frontend/backend chat agent names so the website can
  send `investment_agent` or `portfolio_agent` while older `investment` and
  `portfolio` values remain accepted.
- V1.4.3 added `src/moomail_finance_ai/portfolio_evidence_planner.py`, moved
  bounded PortfolioRequest planning into an explicit `PortfolioEvidencePlan`
  planner with deterministic asset resolution before tool scope selection, and
  preserved current keyword behavior as an explicit fallback planner.
- V1.4.3 also lets the Portfolio Agent accept a bounded `PortfolioRequest`,
  exposes `PortfolioAgentResult.evidence_plan`, and adapts resolved
  `asset_id`/canonical-symbol scope into the current `PortfolioContextPlan`
  execution path.

Completed as of 2026-06-29:

- V1.4.4 added policy-aware deterministic execution for bounded
  `PortfolioEvidencePlan` runs and first-class `PortfolioEvidencePacket`
  assembly on `PortfolioAgentResult`.
- V1.4.5 wired the Investment Agent runtime to pass the typed
  `PortfolioRequest` into Portfolio Agent calls, exposed evidence-plan and
  evidence-packet trace phases, added golden/safety/regression coverage, and
  closed out the V1.4 docs/test gate.

## Task Files

| Task | Status | File | Purpose |
| --- | --- | --- | --- |
| V1.4.0 | complete as of 2026-06-24 | [TASK_0_PLANNER_CONTRACTS.md](TASK_0_PLANNER_CONTRACTS.md) | Define typed contracts for Investment planning, bounded Portfolio requests, asset resolution, Portfolio evidence plans, and evidence packets. |
| V1.4.1 | complete as of 2026-06-24 | [TASK_1_ASSET_RESOLUTION_AND_VALIDATION.md](TASK_1_ASSET_RESOLUTION_AND_VALIDATION.md) | Add deterministic asset resolution and validators so logical hints map to actual portfolio assets and invalid plans fail safely. |
| V1.4.2 | complete as of 2026-06-25 | [TASK_2_INVESTMENT_AGENT_PLANNER.md](TASK_2_INVESTMENT_AGENT_PLANNER.md) | Replace hidden keyword routing with a structured Investment Agent planner that emits bounded subagent requests. |
| V1.4.3 | complete as of 2026-06-25 | [TASK_3_PORTFOLIO_EVIDENCE_PLANNER.md](TASK_3_PORTFOLIO_EVIDENCE_PLANNER.md) | Refactor Portfolio Agent planning into evidence planning over bounded requests, resolved assets, history scope, metrics, and freshness needs. |
| V1.4.4 | complete as of 2026-06-29 | [TASK_4_DETERMINISTIC_EXECUTION_AND_EVIDENCE_PACKET.md](TASK_4_DETERMINISTIC_EXECUTION_AND_EVIDENCE_PACKET.md) | Execute Portfolio evidence plans deterministically and return facts, metrics, patterns, interpretations, limitations, and trace. |
| V1.4.5 | complete as of 2026-06-29 | [TASK_5_TRACE_EVALUATION_AND_CLOSEOUT.md](TASK_5_TRACE_EVALUATION_AND_CLOSEOUT.md) | Expose planner/execution trace, add golden prompt evaluations, update docs, and close the V1.4 gate. |

## Cross-Task Dependency Map

```text
V1.4.0. Planner contracts [complete]
  ├── V1.4.1. Asset resolution and validation [complete]
  │   ├── V1.4.2. Investment Agent planner [complete]
  │   │   └── V1.4.3. Portfolio evidence planner [complete]
  │   │       └── V1.4.4. Deterministic execution and evidence packet [complete]
  │   │           └── V1.4.5. Trace, evaluations, docs, and closeout [complete]
  │   └── V1.4.4. Deterministic execution uses validated resolved assets [complete]
  └── V1.4.5. Docs and tests validate the final contract set [complete]
```

## Core Design Clarification

The Investment Agent should not send a free-form natural-language instruction
and hope the Portfolio Agent understands it. It should send a bounded structured
portfolio request with typed options plus the original user query for context.

Recommended contract shape:

```text
Investment Agent sends:
  - bounded portfolio task intent
  - logical ticker/name/entity hints, not broker-specific identifiers
  - time range
  - freshness requirement
  - output goals
  - original user query

Portfolio Agent returns:
  - resolved portfolio assets and canonical identifiers
  - deterministic tool evidence
  - derived metrics and position changes
  - portfolio-only patterns, anomalies, and caveats
  - limitations and any evidence needs for sentiment/fundamentals
```

This means the Portfolio Agent is not a second mission planner. It should not
override the Investment Agent's goal or decide whether the Sentiment Agent is
needed. Its planning is portfolio-evidence planning: translating the bounded
request into actual portfolio data access, calculations, and portfolio-specific
insight extraction.

The Portfolio Agent should add value by acting like a portfolio analyst
assistant. It should surface what is important or unusual so the Investment
Agent does not need to inspect every holding, metric, and history row manually.
It must clearly separate:

- deterministic facts
- derived metrics
- detected patterns and outliers
- portfolio-only interpretation
- limitations that require sentiment, fundamentals, or market context

## Responsibility Split

### Investment Agent

The Investment Agent owns mission-level planning and final synthesis.

Its planner should decide:

- user intent and mode
- whether Portfolio Agent is needed
- whether Sentiment Agent is needed
- bounded portfolio task intent requested from the Portfolio Agent
- logical ticker, company, asset, theme, and time-horizon hints
- sentiment task requested from the Sentiment Agent stub or future agent
- freshness requirement: `latest_required`, `cached_ok`, or `history_only`
- answer style and constraints
- guardrail-relevant constraints such as no trade execution

Its planner should not decide:

- broker-specific symbols such as OpenD's `US.AAPL`
- SQL asset ids
- whether a user-provided ticker/name actually exists in the portfolio
- exact SQL query sequence
- exact OpenD calls
- metric formulas
- cost-basis calculations
- final freshness enforcement

Investment Agent ticker scope is logical, not canonical. For example, it may
request `AAPL` or `Apple`, but Portfolio Agent or a deterministic Asset
Resolver should map that to the actual portfolio asset and OpenD-compatible
symbol such as `US.AAPL`, or return an unresolved/ambiguous asset warning.

### Portfolio Agent

The Portfolio Agent owns portfolio evidence planning and portfolio facts.

Its planner should decide:

- how to resolve logical ticker/name/entity hints into portfolio assets
- whether the Investment Agent's requested portfolio task needs refinement into
  portfolio evidence subtasks
- relevant canonical tickers, SQL asset ids, and OpenD symbols for portfolio
  evidence
- SQL history tools needed for the requested evidence
- whether position-state changes should be asset-scoped, ticker-scoped, or
  portfolio-wide
- metric groups required
- whether current portfolio context is needed by the requested portfolio task
- persistence mode: `persist`, `skip`, or policy-driven `auto`
- portfolio-only patterns, anomalies, concentration issues, allocation drift,
  cash/cash-equivalent effects, and historical changes worth highlighting

Its planner should not decide:

- the user's main investment mission if the Investment Agent already provided a
  valid bounded task
- whether market sentiment is needed for the final user answer
- whether to invoke Sentiment Agent
- final investment recommendation
- trade sizing or execution instructions

If the Investment Agent sends an incomplete or inconsistent portfolio request,
the Portfolio Agent should normalize it within bounded rules, emit warnings, or
return a request-validation error. It should not silently invent a new mission.

The Portfolio Agent may use an LLM for compact portfolio-only explanation and
pattern ranking, but it should not use an LLM for finance math, asset
resolution, broker calls, SQL reads, or persistence decisions.

### Asset Resolver

A deterministic Asset Resolver should sit inside or immediately beside the
Portfolio Agent. It maps user-facing asset hints to canonical local portfolio
entities.

Inputs:

- raw user hint such as `AAPL`, `Apple`, or an existing portfolio display name
- optional market hint from the Investment Agent
- portfolio/account scope
- latest SQL asset identities and/or current OpenD positions

Outputs:

- canonical symbol used by the portfolio, for example `US.AAPL`
- SQL `asset_id` when known
- display name
- resolution status: `resolved`, `ambiguous`, `not_in_portfolio`,
  `unsupported_market`, or `unknown`
- warnings for misspellings, OTC limitations, crypto/cash-sweep exclusions, or
  non-US assets outside the current scope

The Investment Agent should not need to know OpenD symbol conventions. It should
send logical intent; the Portfolio Agent resolves that intent against the actual
portfolio.

### Deterministic Portfolio Policy

Freshness and tool execution should be deterministic after planning.

The Investment Agent may set a freshness requirement, and the Portfolio Agent
may state whether its portfolio task depends on current values. The backend or
Portfolio Agent policy then decides:

- if `latest_required`, call OpenD through the MCP gateway
- if `cached_ok` and the latest SQL snapshot is fresh enough, avoid OpenD
- if `history_only`, read SQL history without OpenD
- if cached data is stale and the task needs current values, call OpenD or
  return a stale-data warning if OpenD is unavailable
- whether a run should persist a new observation based on policy and task type

This policy should be testable without an LLM.

### Sentiment Agent

Sentiment Agent implementation is not part of V1.4.

Future responsibilities remain:

- research/retrieval planning
- ticker/entity/theme/document-type scope
- GraphRAG/vector retrieval
- evidence synthesis with citations
- contradictions, risks, catalysts, and missing-data warnings

In V1.4, Sentiment Agent can remain a stub that receives structured tasks. The
Investment Agent planner may decide that sentiment would be needed, but V1.4 does
not build the real GraphRAG system.

## LLM Needed Or Not

### Investment Agent Tasks

| Task | LLM or guided planner? | Deterministic? | Notes |
| --- | --- | --- | --- |
| Interpret ambiguous user query | Yes | No | Main use of the Investment Agent planner. |
| Classify mode/task | Yes, with deterministic fallback | Fallback only | Current keyword classifier is temporary. |
| Select subagents | Yes | Validated deterministically | Planner chooses Portfolio/Sentiment needs. |
| Select logical tickers/entities/themes/time horizon | Yes | Validated deterministically | Logical hints only; not OpenD/SQL identifiers. |
| Choose broker symbols or SQL asset ids | No | No | Belongs to Portfolio Agent Asset Resolver. |
| Set freshness requirement | Yes | Policy enforces | Planner chooses `latest_required`, `cached_ok`, or `history_only`. |
| Enforce freshness | No | Yes | Deterministic backend/Portfolio policy. |
| Synthesize portfolio + sentiment + IPS | Yes | No | Rich final reasoning belongs here. |
| Guardrails | Optional LLM later | Yes first | Deterministic guardrails remain mandatory. |

### Portfolio Agent Tasks

| Task | LLM or guided planner? | Deterministic? | Notes |
| --- | --- | --- | --- |
| Validate bounded portfolio request | No | Yes | Ensure Investment Agent request is allowed and coherent. |
| Resolve logical ticker/name to portfolio asset | No | Yes | Asset Resolver maps to SQL asset ids and OpenD symbols. |
| Refine evidence subtasks from request | Optional, bounded | Validated deterministically | Only within the requested portfolio mission. |
| Select SQL history tools | Optional, bounded | Validated deterministically | Tool names come from allowlisted plan fields. |
| Decide current-context dependency | Optional, bounded | Policy validated | Planner can say task needs current values. |
| Check SQL freshness | No | Yes | Deterministic. |
| Check OpenD connection | No | Yes | Deterministic. |
| Pull OpenD snapshot | No | Yes | Deterministic MCP call. |
| Read SQL history | No | Yes | Deterministic MCP call. |
| Calculate metrics | No | Yes | Deterministic finance tools. |
| Calculate position-state changes | No | Yes | Deterministic SQL/MCP tool. |
| Detect threshold-based outliers | No | Yes | Concentration, drift, cash, stale data, large changes. |
| Rank or explain portfolio-only patterns | Optional | No | Useful for analyst-style evidence summaries. |
| Decide market sentiment or final thesis | No | No | Belongs to Sentiment Agent / Investment Agent synthesis. |

### Sentiment Agent Tasks

Not implemented in V1.4. Future classification:

| Task | LLM or guided planner? | Deterministic? | Notes |
| --- | --- | --- | --- |
| Select research query expansions | Yes | No | Future GraphRAG phase. |
| Retrieve by ticker/entity/date/type | No | Yes | Deterministic retrieval once query is formed. |
| Rank retrieved chunks | Mostly no | Yes | Retrieval scoring. |
| Summarize source evidence | Yes | No | Source-backed synthesis. |
| Extract citations mechanically | No | Yes | Citation mechanics should be deterministic. |

## Proposed V1.4 Flow

```mermaid
flowchart TD
  UI["Chat / CLI user query"] --> IA_PLAN["Investment Agent planner"]

  IA_PLAN --> IA_VALIDATE["Deterministic plan validation"]
  IA_VALIDATE --> NEED_PORT{"Need Portfolio Agent?"}
  IA_VALIDATE --> NEED_SENT{"Need Sentiment Agent?"}

  NEED_PORT -->|yes| PA_REQ["Bounded PortfolioRequest"]
  PA_REQ --> ASSET_RESOLVE["Deterministic asset resolution"]
  ASSET_RESOLVE --> PA_PLAN["Portfolio evidence planner"]
  PA_PLAN --> PA_VALIDATE["Deterministic portfolio policy"]

  PA_VALIDATE --> FRESH{"Freshness policy"}
  FRESH -->|latest_required| OPEND["OpenD MCP snapshot"]
  FRESH -->|cached_ok| SQL_LATEST["Portfolio SQL latest snapshot"]
  FRESH -->|history_only| SQL_HIST["Portfolio SQL history"]

  PA_VALIDATE --> METRICS["Finance Metrics MCP"]
  PA_VALIDATE --> POS_CHANGES["Portfolio SQL position-state changes"]
  OPEND --> PA_PACKET["Portfolio evidence packet"]
  SQL_LATEST --> PA_PACKET
  SQL_HIST --> PA_PACKET
  METRICS --> PA_PACKET
  POS_CHANGES --> PA_PACKET
  ASSET_RESOLVE --> PA_PACKET

  NEED_SENT -->|yes| SENT_STUB["Sentiment Agent stub in V1.4"]
  NEED_SENT -->|no| NO_SENT["No sentiment packet"]

  PA_PACKET --> IA_SYNTH["Investment Agent synthesis"]
  SENT_STUB --> IA_SYNTH
  NO_SENT --> IA_SYNTH
  IA_VALIDATE --> IA_SYNTH

  IA_SYNTH --> GUARD["Mandatory deterministic guardrails"]
  GUARD --> OUT["Final answer + trace"]
```

## Planner Contracts

V1.4.0 implemented these contracts in
`src/moomail_finance_ai/agent_schemas.py`. The `InvestmentPlan` and
`PortfolioEvidencePlan` contracts are now wired into live planning paths, and
bounded Portfolio Agent runs assemble direct `PortfolioEvidencePacket` output
alongside compatibility result fields.

### Investment Plan

Implemented field shape:

```json
{
  "mode": "review | risk_check | what_changed | deep_dive | compare | portfolio_fact",
  "needs_portfolio_agent": true,
  "needs_sentiment_agent": false,
  "portfolio_request": {},
  "sentiment_task": null,
  "logical_asset_hints": [
    {
      "raw_input": "AMZN",
      "market_hint": null,
      "company_entity_label": "Amazon.com Inc.",
      "source_field": "user_query"
    }
  ],
  "themes": [],
  "time_horizon": "90d",
  "freshness_requirement": "latest_required | cached_ok | history_only",
  "answer_constraints": [
    "no_trade_execution",
    "no_order_preparation",
    "no_exact_share_count"
  ],
  "warnings": []
}
```

### Portfolio Plan

Implemented request fields from Investment Agent:

```json
{
  "task_intent": "full_review | portfolio_fact | risk_check | what_changed | deep_dive | compare",
  "asset_hints": [
    {
      "raw_input": "AMZN",
      "market_hint": null,
      "company_entity_label": "Amazon.com Inc.",
      "source_field": "user_query"
    }
  ],
  "time_range": "90d",
  "freshness_requirement": "latest_required | cached_ok | history_only",
  "output_goals": ["position_changes", "allocation_context", "portfolio_patterns"],
  "source_query": "What price did I buy my recent AMZN shares at?"
}
```

Implemented Portfolio Agent evidence plan fields:

```json
{
  "task_intent": "what_changed",
  "resolved_assets": [
    {
      "input": "AMZN",
      "canonical_symbol": "US.AMZN",
      "sql_asset_id": "asset_123",
      "display_name": "Amazon.com Inc.",
      "resolution_status": "resolved",
      "warnings": [],
      "source": "asset_resolver"
    }
  ],
  "history_queries": [
    "history_status",
    "latest_state",
    "portfolio_growth",
    "allocation_history",
    "position_state_changes"
  ],
  "metric_groups": ["performance"],
  "needs_current_values": false,
  "history_window": "90d",
  "freshness_requirement": "history_only",
  "position_change_scope": "asset_scoped",
  "persistence_mode": "skip",
  "pattern_detectors": [
    "stale_data",
    "unsupported_quote_warnings",
    "large_position_changes",
    "average_cost_shifts",
    "portfolio_outliers"
  ],
  "warnings": []
}
```

Implemented portfolio evidence packet sections:

```json
{
  "portfolio_id": "portfolio_default",
  "task_intent": "what_changed",
  "resolved_assets": [],
  "facts": {},
  "derived_metrics": {},
  "position_changes": [],
  "detected_patterns": [],
  "portfolio_only_interpretation": [],
  "limitations": [
    "No sentiment or fundamental evidence was reviewed by Portfolio Agent."
  ],
  "needs_sentiment_context": [],
  "warnings": [],
  "tool_refs": []
}
```

## Compatibility Fallbacks

Current implementation note:

- `PortfolioAgent.run()` can accept a bounded `PortfolioRequest` and plan
  `PortfolioEvidencePlan` output with resolved assets before tool scope
  selection.
- Bounded `PortfolioRequest` execution applies deterministic freshness policy
  directly from `PortfolioEvidencePlan`: `latest_required` calls OpenD,
  `cached_ok` can use fresh SQL latest state, and `history_only` avoids OpenD.
- `PortfolioAgentResult.evidence_packet` separates facts, derived metrics,
  position changes, detected patterns, portfolio-only interpretation,
  limitations, sentiment-context needs, warnings, and tool refs.
- `interpret_portfolio_task()` delegates to the explicit fallback planner for
  legacy `PortfolioTask` callers; that fallback still extracts tickers with a
  deterministic regex helper.
- `portfolio_sql_get_position_state_changes` can receive resolved `asset_id`
  scope, ticker fallback scope, or portfolio-wide scope.

Completed in V1.4.3:

- Move bounded ticker/asset-scope selection into `PortfolioEvidencePlan`;
  legacy fallback extraction remains explicit.
- Represent ticker/asset scope as planner output.
- Represent the V1.4 Investment-to-Portfolio handoff as a bounded
  `PortfolioRequest`, not free-form natural language.
- Add deterministic asset resolution so logical hints like `AAPL` or `Apple`
  map to portfolio assets and OpenD-compatible symbols such as `US.AAPL`.
- Keep Portfolio Agent task refinement limited to evidence planning. It should
  not re-decide the user mission once the Investment Agent has sent a valid
  bounded request.
- Make Portfolio Agent value-add explicit through pattern/outlier detection,
  portfolio-only interpretation, and limitations that tell the Investment Agent
  what requires sentiment or fundamental context.
- Keep a deterministic fallback planner for tests and offline mode, but make it
  explicit that it is a fallback implementation.
- Add tests proving a planner can resolve `AMZN` for a query like "What changed
  in my AMZN position?" and that execution passes resolved `asset_id` scope to
  `portfolio_sql_get_position_state_changes` when available.

Remaining after V1.4.5:

- No remaining V1.4 task exit criteria. Future work moves to V1.5+ tracks such
  as structured-output LLM planners, rich Investment Agent synthesis, real
  Sentiment Agent GraphRAG retrieval, Pinecone memory, and frontend redesign.

## Non-Goals

- Do not implement real Sentiment Agent retrieval in V1.4.
- Do not let the LLM directly calculate cost basis or inferred purchase price.
- Do not make tool execution autonomous after planning.
- Do not remove deterministic tests; use fake planner outputs for stable tests.
- Do not allow trade placement, order preparation, or executable share-count
  recommendations.
