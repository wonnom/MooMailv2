# Task V1.4.0: Planner Contracts

## Goal

Define the typed contracts that make V1.4 planning explicit and bounded.

This task should not change agent behavior yet. It creates the vocabulary that
later tasks execute:

- Investment Agent plan
- bounded Investment-to-Portfolio request
- asset hint and deterministic asset resolution result
- Portfolio Agent evidence plan
- Portfolio evidence packet
- planner and policy trace events

## Status

Planned.

## Exit Criteria

1. Contracts distinguish logical asset hints from canonical portfolio/OpenD/SQL
   identifiers.
2. Investment Agent can request portfolio evidence through a bounded
   `PortfolioRequest`, not free-form natural language.
3. Portfolio Agent can return a packet that separates facts, derived metrics,
   detected patterns, portfolio-only interpretation, limitations, and sentiment
   context needs.
4. Contracts prevent the Investment Agent from sending trade execution intent,
   broker-specific execution instructions, or exact share-count order
   preparation.
5. Fixtures exist for portfolio-only, what-changed, asset-resolution failure,
   and portfolio-plus-sentiment-stub flows.

## Dependency Graph

```text
A. Audit current agent schemas
  ├── B. Define enums and literals
  │   ├── C. Define InvestmentPlan
  │   │   ├── D. Define PortfolioRequest
  │   │   └── E. Define SentimentTask compatibility fields
  │   ├── F. Define AssetHint and AssetResolution
  │   ├── G. Define PortfolioEvidencePlan
  │   └── H. Define PortfolioEvidencePacket
  ├── I. Define trace event extensions
  └── J. Add fixtures and schema tests
```

## Task Breakdown By Exit Criteria

### EC1: Logical hints are separate from canonical identifiers

| Task | Description | Depends on | Test |
| --- | --- | --- | --- |
| A | Audit `agent_schemas.py`, `schemas.py`, `portfolio_agent.py`, and current fixtures for fields that already represent task type, tickers, history window, and trace. | None | No code test; notes in PR/change summary |
| B | Add enums/literals for `task_intent`, `freshness_requirement`, `resolution_status`, `position_change_scope`, `persistence_mode`, and `portfolio_output_goal`. | A | `tests/test_agent_schemas.py::test_v1_4_literals_accept_expected_values` |
| F | Add `AssetHint` with raw input, optional market hint, optional company/entity label, and source field. | B | `test_asset_hint_keeps_raw_logical_input` |
| F1 | Add `AssetResolution` with canonical symbol, SQL asset id, display name, resolution status, warnings, and source. | F | `test_asset_resolution_requires_status_and_preserves_warnings` |
| F2 | Ensure OpenD symbols and SQL ids are optional on unresolved hints. | F1 | `test_unresolved_asset_resolution_does_not_require_canonical_ids` |

### EC2: Investment Agent sends bounded PortfolioRequest

| Task | Description | Depends on | Test |
| --- | --- | --- | --- |
| C | Add `InvestmentPlan` with mode, subagent needs, portfolio request, sentiment task, logical asset hints, themes, time horizon, freshness, answer constraints, and warnings. | B, F | `test_investment_plan_round_trips_with_portfolio_request` |
| D | Add `PortfolioRequest` with task intent, asset hints, time range, freshness requirement, output goals, and source query. | C | `test_portfolio_request_has_bounded_task_intent` |
| D1 | Add validation that `needs_portfolio_agent=true` requires a `PortfolioRequest`. | C, D | `test_investment_plan_requires_portfolio_request_when_needed` |
| D2 | Add validation that the request carries logical hints, not mandatory OpenD symbols or SQL ids. | D | `test_portfolio_request_does_not_require_broker_identifiers` |
| E | Preserve future-compatible `SentimentTask` references without implementing real GraphRAG. | C | Existing sentiment stub schema tests still pass |

### EC3: Portfolio Agent returns separated evidence

| Task | Description | Depends on | Test |
| --- | --- | --- | --- |
| G | Add `PortfolioEvidencePlan` with resolved assets, history queries, metric groups, current-value dependency, position-change scope, persistence mode, and pattern detectors. | F1 | `test_portfolio_evidence_plan_validates_resolved_assets` |
| H | Add `PortfolioEvidencePacket` sections: facts, derived metrics, position changes, detected patterns, portfolio-only interpretation, limitations, needs sentiment context, warnings, and tool refs. | G | `test_portfolio_evidence_packet_separates_sections` |
| H1 | Add constraints that portfolio-only interpretation cannot contain final recommendation/trade execution flags. | H | `test_portfolio_evidence_packet_rejects_trade_execution_language_flags` |
| I | Extend trace/status event schema for planner, validator, asset resolver, portfolio policy, and deterministic tool execution phases. | C, G, H | `test_trace_event_supports_v1_4_planner_phases` |
| J | Add fixtures under `tests/fixtures/agent/` for the new contracts. | C through I | `test_v1_4_fixtures_validate` |

## Tests To Add Or Update

- `tests/test_agent_schemas.py`
- `tests/fixtures/agent/investment_plan_portfolio_request.json`
- `tests/fixtures/agent/portfolio_request_what_changed.json`
- `tests/fixtures/agent/asset_resolution_ambiguous.json`
- `tests/fixtures/agent/portfolio_evidence_packet_stub.json`

## Required Test Commands

```bash
.venv/bin/python -m pytest tests/test_agent_schemas.py -q
.venv/bin/python -m pytest tests/test_sentiment_agent_stub.py -q
```

## Notes

- This task should prefer additive contracts first. Runtime migration belongs
  to later V1.4 tasks.
- Keep naming version-neutral in code where practical. The docs can call this
  V1.4, but runtime classes should describe their domain, not the iteration.
