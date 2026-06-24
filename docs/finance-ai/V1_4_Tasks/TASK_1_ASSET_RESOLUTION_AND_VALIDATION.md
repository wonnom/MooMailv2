# Task V1.4.1: Asset Resolution And Validation

## Goal

Add deterministic asset resolution and plan validation so the Portfolio Agent can
translate logical asset hints into actual portfolio assets before any portfolio
tools run.

Investment Agent should be allowed to send `AAPL`, `Apple`, or a user-facing
holding name. It should not need to send `US.AAPL`, SQL asset ids, or OpenD
field conventions. Portfolio Agent or a nearby resolver owns that mapping.

## Status

Planned.

## Exit Criteria

1. `AAPL` or `Apple` can resolve to the held portfolio asset and OpenD-compatible
   symbol when that asset exists.
2. Unknown, ambiguous, unsupported-market, and not-in-portfolio hints return
   explicit resolution statuses and warnings.
3. Validation rejects invalid or unsafe plans before OpenD, SQL, or metric tools
   run.
4. Resolution is deterministic and testable without an LLM or live OpenD.
5. Portfolio Agent trace records asset-resolution decisions without leaking
   account secrets or raw broker payloads.

## Dependency Graph

```text
V1.4.0 contracts
  ├── A. Choose resolver module boundary
  │   ├── B. Load candidate assets from SQL/latest snapshot/current positions
  │   ├── C. Normalize user-facing hints
  │   │   ├── D. Resolve exact symbol/name matches
  │   │   ├── E. Resolve market-prefixed symbols
  │   │   └── F. Detect ambiguity and not-in-portfolio cases
  │   ├── G. Validate InvestmentPlan and PortfolioRequest
  │   └── H. Emit sanitized resolver trace
  └── I. Add deterministic tests and fixtures
```

## Task Breakdown By Exit Criteria

### EC1: Held assets resolve deterministically

| Task | Description | Depends on | Test |
| --- | --- | --- | --- |
| A | Decide resolver placement: `asset_resolver.py`, `portfolio_agent.py`, or a small Portfolio Agent service module. | V1.4.0 | Import smoke test |
| B | Define candidate asset source order: latest SQL asset identities first, current OpenD positions when a live snapshot is already present, then in-memory snapshot fixtures. | A | `test_resolver_prefers_current_portfolio_candidates` |
| C | Normalize hints by trimming, case-folding, and comparing symbol forms without losing the raw input. | A | `test_resolver_preserves_raw_hint_and_normalizes_match_key` |
| D | Resolve `AMZN` to `US.AMZN` when that canonical symbol exists in portfolio candidates. | B, C | `test_resolver_maps_us_symbol_hint_to_canonical_symbol` |
| D1 | Resolve company/display-name hints such as `Amazon` when unambiguous. | B, C | `test_resolver_maps_display_name_hint_to_asset` |
| E | Accept already-prefixed symbols such as `US.AMZN` without double-prefixing. | C, D | `test_resolver_accepts_prefixed_symbol` |

### EC2: Failure states are explicit

| Task | Description | Depends on | Test |
| --- | --- | --- | --- |
| F | Return `not_in_portfolio` when the hint is valid-looking but not held. | C | `test_resolver_returns_not_in_portfolio_for_unheld_symbol` |
| F1 | Return `ambiguous` when multiple assets match a hint. | C, D1 | `test_resolver_returns_ambiguous_for_multiple_matches` |
| F2 | Return `unsupported_market` for known out-of-scope markets in V1.4. | C | `test_resolver_flags_unsupported_market_hint` |
| F3 | Return `unknown` when the hint is too vague to map. | C | `test_resolver_returns_unknown_for_vague_hint` |
| F4 | Preserve warnings for OTC, crypto, cash-sweep, and non-US-equity cases without failing the whole plan unless the task requires that asset. | F through F3 | `test_resolver_preserves_non_blocking_asset_warnings` |

### EC3: Plans validate before tool execution

| Task | Description | Depends on | Test |
| --- | --- | --- | --- |
| G | Validate that `PortfolioRequest.task_intent` and `output_goals` are allowlisted. | V1.4.0 | `test_portfolio_request_rejects_unknown_task_intent` |
| G1 | Validate that trade/order/execution intents are blocked before Portfolio Agent execution. | G | `test_plan_validator_rejects_trade_execution_request` |
| G2 | Validate freshness values and time ranges before SQL/OpenD calls. | G | `test_plan_validator_rejects_invalid_freshness_or_time_range` |
| G3 | Validate that unresolved required assets produce an actionable warning or blocked request, depending on task type. | F, G | `test_plan_validator_blocks_required_unresolved_asset` |
| H | Emit sanitized trace entries for resolution status, not raw account payloads. | F, G | `test_asset_resolution_trace_is_sanitized` |

## Tests To Add Or Update

- `tests/test_asset_resolver.py`
- `tests/test_agent_schemas.py`
- `tests/test_portfolio_planner.py`
- `tests/fixtures/agent/asset_resolution_*.json`

## Required Test Commands

```bash
.venv/bin/python -m pytest tests/test_asset_resolver.py tests/test_agent_schemas.py -q
.venv/bin/python -m pytest tests/test_portfolio_planner.py -q
```

## Notes

- Do not call live OpenD just to resolve a ticker if SQL/current snapshot
  candidates are already available.
- Do not put regex ticker extraction back into hidden execution paths. If a
  deterministic fallback extracts a hint, make it an explicit fallback planner
  output.
