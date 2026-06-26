# Task V1.4.3: Portfolio Evidence Planner

## Goal

Refactor Portfolio Agent planning so it accepts a bounded `PortfolioRequest`,
resolves assets, and creates a `PortfolioEvidencePlan`.

The Portfolio Agent should not re-decide the user's mission. It should translate
the request into portfolio evidence subtasks, tool scopes, freshness needs,
metric groups, pattern detectors, and persistence policy.

## Status

Complete as of 2026-06-25.

## Implemented In

- `src/moomail_finance_ai/portfolio_evidence_planner.py`
  - Added the `PortfolioEvidencePlanner` protocol, deterministic
    `PortfolioRequest -> PortfolioEvidencePlan` planner, request/task/context
    adapters, and explicit keyword fallback planner for existing query behavior.
  - Planner resolves `AssetHint` values before choosing history queries, metric
    groups, position-change scope, current-value dependency, persistence mode,
    and pattern detectors.
  - Planner surfaces validation warnings for unresolved/ambiguous optional
    assets and rejects required unresolved assets before tool execution.
- `src/moomail_finance_ai/portfolio_agent.py`
  - `PortfolioAgent.run` now accepts an optional bounded `PortfolioRequest`
    with supplied asset candidates and stores the resulting `evidence_plan` in
    `PortfolioAgentResult`.
  - The existing `PortfolioTask` path remains stable; its keyword/rule query
    fallback now delegates to the explicit fallback planner.
  - Position-state change reads can now pass resolved `asset_id` scope to
    `portfolio_sql_get_position_state_changes` when available, falling back to
    ticker or portfolio-wide scope otherwise.
- `src/moomail_finance_ai/agent_schemas.py`
  - Added additive `asset_ids` and `canonical_symbols` scope fields to
    `PortfolioContextPlan` so resolved evidence-plan scope can flow into the
    current execution adapter.
- Tests and fixtures
  - Expanded `tests/test_portfolio_planner.py` with the V1.4.3 planner,
    resolver, scope, pattern-detector, fallback, and trace/status cases.
  - Updated `tests/test_portfolio_agent.py` for the bounded `PortfolioRequest`
    path.
  - Added `tests/fixtures/agent/portfolio_evidence_plan_cash_query.json` and
    `tests/fixtures/agent/portfolio_evidence_plan_amzn_position_changes.json`.

## Exit Criteria

1. Portfolio Agent accepts `PortfolioRequest` and produces a validated
   `PortfolioEvidencePlan`.
2. Asset resolution happens before SQL/OpenD/metric tool selection.
3. Planner scopes position-state-change queries to resolved assets when the
   request requires asset-specific history.
4. Planner chooses portfolio evidence subtasks and pattern detectors without
   deciding sentiment need or final thesis.
5. Current deterministic fallback behavior is preserved as an explicit fallback
   planner, not hidden inline extraction.

## Dependency Graph

```text
V1.4.0 contracts
  ├── V1.4.1 asset resolution and validation
  │   ├── A. Add Portfolio evidence planner interface
  │   ├── B. Adapt existing PortfolioTask/PortfolioContextPlan path
  │   ├── C. Resolve assets before tool planning
  │   ├── D. Map PortfolioRequest to evidence subtasks
  │   ├── E. Select history queries and metric groups
  │   ├── F. Select position-change scope
  │   ├── G. Select freshness/current-value dependency
  │   └── H. Preserve fallback planner behavior explicitly
  └── I. Add planner tests
```

## Task Breakdown By Exit Criteria

### EC1: PortfolioRequest becomes PortfolioEvidencePlan

| Task | Description | Depends on | Test |
| --- | --- | --- | --- |
| A | Define planner interface, for example `PortfolioEvidencePlanner.plan(request, ips, candidates) -> PortfolioEvidencePlan`. | V1.4.0, V1.4.1 | `test_portfolio_evidence_planner_protocol_returns_plan` |
| B | Adapt existing `PortfolioTask` and `PortfolioContextPlan` fields to the new request/plan contracts. | A | `test_existing_portfolio_task_can_be_adapted_to_request` |
| D | Map `task_intent` and `output_goals` to evidence subtasks such as allocation, cash, risk, position changes, growth, and latest state. | B | `test_portfolio_planner_maps_request_to_evidence_subtasks` |
| D1 | Reject or warn on request/output-goal combinations that are incoherent. | D | `test_portfolio_planner_warns_on_incoherent_output_goal` |

### EC2: Asset resolution comes first

| Task | Description | Depends on | Test |
| --- | --- | --- | --- |
| C | Call deterministic resolver before SQL/OpenD/metric planning. | V1.4.1, A | `test_portfolio_planner_resolves_assets_before_tool_scope` |
| C1 | Use resolved `asset_id` and canonical symbol when forming history scopes. | C | `test_portfolio_planner_uses_resolved_asset_id_for_history_scope` |
| C2 | Surface unresolved/ambiguous asset warnings in the plan. | C | `test_portfolio_planner_surfaces_unresolved_asset_warnings` |
| C3 | Do not convert logical hints with ad hoc regex inside execution functions. | C | `test_no_hidden_ticker_extraction_when_request_has_asset_hints` |

### EC3: Tool and history scope are bounded

| Task | Description | Depends on | Test |
| --- | --- | --- | --- |
| E | Select SQL history queries from an allowlist based on evidence subtasks. | D | `test_portfolio_planner_selects_allowlisted_history_queries` |
| E1 | Select metric groups from an allowlist based on task intent and output goals. | D | `test_portfolio_planner_selects_metric_groups` |
| F | Choose `position_change_scope` as `asset_scoped`, `ticker_scoped`, or `portfolio_wide`. | C, E | `test_position_change_scope_is_asset_scoped_for_resolved_asset` |
| F1 | Pass scope metadata needed by `portfolio_sql_get_position_state_changes`. | F | `test_position_change_plan_has_sql_tool_arguments` |
| G | Choose `needs_current_values` and `persistence_mode` based on request freshness and task intent. | D, E | `test_portfolio_planner_sets_current_value_dependency_and_persistence` |

### EC4: Planner stays inside portfolio evidence domain

| Task | Description | Depends on | Test |
| --- | --- | --- | --- |
| H | Make the current keyword planner an explicit fallback implementation. | A, B | `test_fallback_portfolio_planner_matches_current_cash_query_behavior` |
| H1 | Ensure Portfolio Agent planner never emits `needs_sentiment_agent` or final recommendation fields. | A, D | `test_portfolio_evidence_plan_has_no_sentiment_routing_or_final_thesis` |
| H2 | Add pattern detectors for concentration, allocation drift, cash/effective-cash, large position changes, average-cost shifts, stale data, and unsupported quote warnings. | E, F, G | `test_portfolio_planner_selects_pattern_detectors` |
| I | Emit planned, skipped, and validation trace entries for the new planner. | H | `test_portfolio_planner_trace_includes_request_resolution_and_evidence_scope` |

## Tests To Add Or Update

- `tests/test_portfolio_planner.py`
- `tests/test_asset_resolver.py`
- `tests/test_portfolio_agent.py`
- `tests/fixtures/agent/portfolio_evidence_plan_*.json`

## Required Test Commands

```bash
.venv/bin/python -m pytest tests/test_portfolio_planner.py tests/test_asset_resolver.py -q
.venv/bin/python -m pytest tests/test_portfolio_agent.py -q
```

## Verification

Run on 2026-06-25:

```text
.venv/bin/python -m pytest tests/test_portfolio_planner.py tests/test_asset_resolver.py -q
44 passed in 0.32s

.venv/bin/python -m pytest tests/test_portfolio_agent.py -q
7 passed in 0.27s

.venv/bin/python -m pytest tests/test_agent_schemas.py -q
55 passed in 0.04s

.venv/bin/python -m pytest tests --ignore=tests/live -q
237 passed, 1 warning in 8.70s
```

The warning is the existing LangGraph dependency deprecation warning.

Not run:

- `tests/live`: opt-in live connector/OpenD tests are not required because this
  task uses deterministic recorded/fake Portfolio Agent paths.

## Remaining

No remaining exit criteria for V1.4.3. V1.4.4 still owns deterministic
execution directly from `PortfolioEvidencePlan` into a separated
`PortfolioEvidencePacket`; the current runtime adapts evidence plans through
`PortfolioContextPlan` for existing execution.

## Notes

- The Portfolio Agent may refine evidence subtasks, but only within the bounded
  request from the Investment Agent.
- This task should not implement the final evidence packet assembly. That is
  V1.4.4.
- Closeout note: the expected `references/finance-ai-grounding.md` file was not
  present in this checkout. Grounding used this task file, the sibling V1.4
  README, and the current finance AI architecture/agent/testing/protocol docs.
