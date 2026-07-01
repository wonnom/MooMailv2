# Task V1.4.2: Investment Agent Planner

## Goal

Replace hidden keyword routing in the Investment Agent with a structured planner
that emits a typed `InvestmentPlan`.

The planner decides the user mission, subagent needs, logical scope, freshness
requirement, bounded Portfolio request, optional Sentiment stub task, and answer
constraints. It does not choose SQL queries, OpenD tools, SQL asset ids, or
broker-specific symbols.

## Status

Complete as of 2026-06-25. Updated on 2026-07-01 to remove the
deterministic keyword fallback from runtime planning.

## Implemented In

- `src/moomail_finance_ai/investment_planner.py`
  - Added the `InvestmentPlanner` protocol, `LLMInvestmentPlanner`,
    `UnavailableInvestmentPlanner`, planner validation, and adapter from V1.4
    `InvestmentPlan` to the existing `InvestmentQueryPlan`/`PortfolioTask`
    runtime path.
  - Planner emits logical `AssetHint` values, not OpenD-prefixed symbols or SQL
    asset ids.
  - The LLM planner maps cash/fact, recent purchase/history, full review, risk,
    comparison, and sentiment/research prompts into bounded `PortfolioRequest`
    and optional `SentimentTask` contracts. If the LLM planner is unavailable or
    emits invalid JSON, the agent returns an explicit planning-unavailable
    report instead of falling back to keyword routing.
- `src/moomail_finance_ai/investment_agent.py`
  - Replaced the graph's classifier entry with `load_ips -> plan_investment ->
    validate_plan -> call_portfolio`.
  - Stores `InvestmentAgentState.investment_plan` before subagent calls,
    validates planner output before Portfolio Agent/Sentiment Agent routing,
    and emits sanitized planner/validator trace phases.
  - Keeps the existing `query_plan`/`PortfolioTask` adapter so the current
    Portfolio Agent runtime remains stable until V1.4.3/V1.4.4.
- `src/moomail_finance_ai/chat_api.py`, `scripts/serve_chat.py`,
  `web/index.html`, and frontend trace types/rendering
  - Chat responses now include `investment_plan`.
  - The frontend selector now sends `investment_agent`/`portfolio_agent`, and
    backend alias normalization accepts both old and new names.
- Tests and fixtures
  - Added `tests/test_investment_planner.py`.
  - Updated `tests/test_investment_agent.py`, `tests/test_chat_app.py`,
    `tests/test_agent_trace.py`, and `tests/test_agent_schemas.py`.
  - Added `tests/fixtures/agent/investment_plan_cash_query.json` and
    `tests/fixtures/agent/investment_plan_recent_purchase.json`.

## Exit Criteria

1. Investment Agent produces an `InvestmentPlan` before subagent calls.
2. Portfolio-bound queries produce a bounded `PortfolioRequest` with logical
   asset hints and output goals.
3. Broad investment queries can request both Portfolio Agent and Sentiment Agent
   stub without the Portfolio Agent deciding sentiment need.
4. No deterministic keyword planner is used for tests/offline mode; tests inject
   explicit fake planner outputs and runtime returns graceful failure if the LLM
   planner is unavailable.
5. Planner decisions are visible in sanitized trace/status output.

## Dependency Graph

```text
V1.4.0 contracts
  ├── V1.4.1 validation
  │   ├── A. Add Investment planner interface
  │   ├── B. Implement LLM structured-output planner
  │   ├── C. Return graceful failure when LLM planning is unavailable
  │   ├── D. Validate planner output
  │   ├── E. Integrate plan into LangGraph nodes
  │   ├── F. Route PortfolioRequest and SentimentTask
  │   └── G. Emit planner trace
  └── H. Add route and golden prompt tests
```

## Task Breakdown By Exit Criteria

### EC1: InvestmentPlan exists before subagent calls

| Task | Description | Depends on | Test |
| --- | --- | --- | --- |
| A | Define a planner interface, for example `InvestmentPlanner.plan(query, ips) -> InvestmentPlan`. | V1.4.0 | `test_investment_planner_protocol_returns_plan` |
| B | Implement an LLM structured-output planner that emits typed contracts. | A | `test_llm_investment_planner_protocol_returns_plan` |
| D | Validate planner output with the V1.4 plan validator before any subagent call. | V1.4.1, B | `test_investment_agent_validates_plan_before_subagent_calls` |
| E | Replace the current query-classification node with a planner node in `InvestmentAgent`. | A, B, D | `test_investment_agent_emits_plan_before_portfolio_call` |

### EC2: Portfolio-bound queries produce bounded requests

| Task | Description | Depends on | Test |
| --- | --- | --- | --- |
| B1 | Map portfolio-fact queries to `PortfolioRequest(task_intent="portfolio_fact")`. | B | `test_planner_maps_cash_query_to_portfolio_fact_request` |
| B2 | Map recent-purchase/history queries to `PortfolioRequest(task_intent="what_changed", output_goals=["position_changes"])`. | B | `test_planner_maps_recent_purchase_query_to_position_change_request` |
| B3 | Preserve logical asset hints such as `AMZN` without converting them to `US.AMZN`. | B2 | `test_planner_keeps_asset_hints_logical` |
| B4 | Set freshness to `history_only`, `cached_ok`, or `latest_required` based on user intent and mode. | B | `test_planner_sets_freshness_requirement` |
| B5 | Preserve the original user query in the request for downstream explanation context. | B | `test_portfolio_request_carries_source_query` |

### EC3: Broad queries can request sentiment stub

| Task | Description | Depends on | Test |
| --- | --- | --- | --- |
| F | Keep sentiment routing at Investment Agent level. | E | `test_investment_agent_routes_sentiment_without_portfolio_agent_deciding` |
| F1 | For broad review/risk/deep-dive queries, emit a future-compatible `SentimentTask` while keeping the current stub behavior. | F | `test_planner_emits_sentiment_task_for_broad_review` |
| F2 | For mechanical portfolio-only queries, skip Sentiment Agent unless the query explicitly asks for market/research context. | F | `test_planner_skips_sentiment_for_mechanical_portfolio_fact` |

### EC4: Fallback and trace are stable

| Task | Description | Depends on | Test |
| --- | --- | --- | --- |
| C | Add an unavailable-planner path that returns graceful failure instead of deterministic keyword routing. | A | `test_unavailable_planner_raises_graceful_failure_message` |
| G | Emit trace entries for planner start, planner output summary, validation result, and subagent routing. | E, D | `test_investment_planner_trace_is_sanitized` |
| H | Add explicit structured-output fixtures for cash query, AMZN recent purchase, full review, risk check, and market-sentiment query. | B, F, G | `test_investment_plan_fixtures_validate` |

## Tests To Add Or Update

- `tests/test_investment_planner.py`
- `tests/test_investment_agent.py`
- `tests/test_chat_app.py`
- `tests/fixtures/agent/investment_plan_*.json`

## Required Test Commands

```bash
.venv/bin/python -m pytest tests/test_investment_planner.py tests/test_investment_agent.py -q
.venv/bin/python -m pytest tests/test_chat_app.py -q
```

## Verification

Run on 2026-06-25:

```text
.venv/bin/python -m pytest tests/test_investment_planner.py tests/test_investment_agent.py -q
22 passed, 1 warning in 0.38s

.venv/bin/python -m pytest tests/test_chat_app.py -q
10 passed, 1 warning in 5.08s

.venv/bin/python -m pytest tests/test_agent_schemas.py tests/test_agent_trace.py -q
60 passed, 1 warning in 0.28s

.venv/bin/python -m pytest tests --ignore=tests/live -q
218 passed, 1 warning in 8.31s
```

The warning is the existing LangGraph dependency deprecation warning.

Not run yet in this closeout section:

- `tests/live`: opt-in live connector/OpenD tests are not required because this
  task uses deterministic fake/recorded Portfolio Agent paths.

## Remaining

No remaining exit criteria for V1.4.2. V1.4.3 later replaced the Portfolio
Agent planning side with `PortfolioEvidencePlan`; V1.4.4 still needs direct
deterministic evidence-packet execution.

## Notes

- The Investment Agent should send logical scope. It should not know or produce
  OpenD-specific symbols.
- This task does not implement rich final LLM synthesis. It only creates better
  planning and routing.
- Closeout note: the expected `references/finance-ai-grounding.md` file was not
  present in this checkout. Grounding used this task file, the sibling V1.4
  README, and the current finance AI architecture/agent/testing/protocol docs.
