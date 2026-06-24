# Task V1.4.2: Investment Agent Planner

## Goal

Replace hidden keyword routing in the Investment Agent with a structured planner
that emits a typed `InvestmentPlan`.

The planner decides the user mission, subagent needs, logical scope, freshness
requirement, bounded Portfolio request, optional Sentiment stub task, and answer
constraints. It does not choose SQL queries, OpenD tools, SQL asset ids, or
broker-specific symbols.

## Status

Planned.

## Exit Criteria

1. Investment Agent produces an `InvestmentPlan` before subagent calls.
2. Portfolio-bound queries produce a bounded `PortfolioRequest` with logical
   asset hints and output goals.
3. Broad investment queries can request both Portfolio Agent and Sentiment Agent
   stub without the Portfolio Agent deciding sentiment need.
4. The deterministic fallback planner remains available for tests/offline mode.
5. Planner decisions are visible in sanitized trace/status output.

## Dependency Graph

```text
V1.4.0 contracts
  ├── V1.4.1 validation
  │   ├── A. Add Investment planner interface
  │   ├── B. Implement deterministic fallback planner
  │   ├── C. Optional structured-output LLM planner shell
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
| B | Implement a deterministic fallback planner that mirrors current supported modes while outputting typed contracts. | A | `test_fallback_planner_returns_portfolio_request_for_portfolio_query` |
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
| C | Add a structured-output LLM planner shell only if it can be disabled cleanly in tests. | A | Optional: `test_llm_planner_can_be_replaced_with_fake` |
| G | Emit trace entries for planner start, planner output summary, validation result, and subagent routing. | E, D | `test_investment_planner_trace_is_sanitized` |
| H | Add golden prompt cases for cash query, AMZN recent purchase, full review, risk check, and market-sentiment query. | B, F, G | `test_investment_planner_golden_prompts` |

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

## Notes

- The Investment Agent should send logical scope. It should not know or produce
  OpenD-specific symbols.
- This task does not implement rich final LLM synthesis. It only creates better
  planning and routing.
