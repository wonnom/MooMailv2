# Task V1.5.1: Deterministic Baseline Portfolio Context

## Goal

Build a compact, read-only `PortfolioBaselinePacket` that gives Investment Agent
enough current and recent portfolio evidence to answer common breakdown, rough
trend, and recent-change questions without invoking Portfolio Agent.

The baseline lane is application infrastructure. It must not call an agent or
LLM, perform semantic query interpretation, or replace deeper Portfolio Agent
evidence execution.

## Status

Complete as of 2026-08-03.

## Implemented In

- `src/moomail_finance_ai/portfolio_baseline.py`
  - Added `PortfolioBaselineService` and its default builder.
  - Reads only bounded SQL history and deterministic effective-cash metrics
    through consumer `portfolio_baseline`; it does not call OpenD, agents, or an
    LLM.
  - Reuses `snapshot_from_latest_state()` for current stored portfolio
    reconstruction.
  - Produces capped current allocation/effective-cash summaries, valid 7-day
    and 30-day value trends, 7-day allocation changes, and 7-day quantity
    changes with stable evidence refs and deterministic sorting.
  - Omits uncovered capabilities and returns explicit stale, shallow-history,
    unsupported-quote, SQL-unavailable, and no-live-refresh limitations.
- `src/moomail_finance_ai/portfolio_data_service.py`
  - SQL reconstruction now preserves configured cash sweep as a distinct cash
    component and cash-equivalent holdings as holdings, keeping deterministic
    effective-cash semantics intact.
- `src/moomail_finance_ai/mcp/gateway.py`
  - Added a least-privilege `portfolio_baseline` profile with bounded SQL reads
    and `calculate_cash_weight`; OpenD and SQL writes are denied.
- `src/moomail_finance_ai/chat_api.py`
  - Added lazy `portfolio_baseline_service()` and `portfolio_baseline()` access
    for later Investment runtime adoption.
- Tests
  - Added `tests/test_portfolio_baseline.py` and extended dashboard, gateway,
    metrics, and ChatService regression coverage.

## Scope And Boundaries

Owns:

- Latest stored snapshot, allocation, effective cash, and freshness summary.
- Compact 7-day/30-day total-value, allocation, and position-change summaries.
- Capability coverage and evidence-reference construction.
- Stable size, row, and latency bounds.
- Clear missing/stale/insufficient-history limitations.

Does not own:

- Deciding whether a user query is covered; V1.5.2 owns route selection and
  invokes V1.5.0 coverage policy.
- Live OpenD refresh during baseline load.
- Asset-specific cost-basis inference or arbitrary time windows.
- LLM prose or portfolio recommendations.

## Exit Criteria

1. A deterministic service assembles a baseline packet from existing dashboard
   and SQL data without calling Investment Agent, Portfolio Agent, or an LLM.
2. The packet covers current breakdown, allocation, effective cash, freshness,
   and compact 7-day/30-day trends/changes when sufficient history exists.
3. Missing rows, partial history, stale data, unsupported quotes, and unavailable
   SQL/OpenD context are represented as limitations rather than fabricated data.
4. Packet size, holdings/change counts, sorting, and evidence references are
   deterministic and stable.
5. Existing dashboard status/latest/refresh behavior remains independent and
   regression-tested.

## Dependency Graph

```text
V1.5.0 baseline contracts
  ├── A. Reuse latest dashboard/snapshot reconstruction
  ├── B. Read bounded SQL history windows
  │   ├── C. Calculate 7-day/30-day value trends
  │   ├── D. Summarize allocation changes
  │   └── E. Summarize position changes
  ├── F. Build capability coverage and evidence refs
  ├── G. Apply size/freshness/quality limits
  └── H. Expose baseline service to Investment runtime
          └── I. Deterministic and dashboard regression tests
```

## Task Breakdown By Exit Criteria

### EC1: Baseline packet is assembled without agents or LLMs

| Task | Description | Depends on | Test |
| --- | --- | --- | --- |
| A | Add a baseline-context service beside `PortfolioDataService`, reusing latest-state-to-snapshot conversion instead of duplicating portfolio normalization. | V1.5.0 | `test_baseline_context_reuses_deterministic_snapshot_lane` |
| A1 | Read the latest stored snapshot without forcing OpenD refresh. | A | `test_baseline_context_does_not_call_opend_refresh` |
| A2 | Prove the module does not import or instantiate Investment Agent, Portfolio Agent, an evaluator, or an LLM client. | A | `test_baseline_context_does_not_call_agents_or_llm` |
| H | Add a narrow service method that Investment Agent can invoke before planning. | A through G | `test_chat_service_can_load_baseline_context` |

### EC2: Common current and trend evidence is available

| Task | Description | Depends on | Test |
| --- | --- | --- | --- |
| B | Read bounded SQL history for 7-day and 30-day comparison anchors using existing MCP/store contracts. | A | `test_baseline_context_reads_bounded_history_windows` |
| C | Calculate total-value absolute/percentage trend with explicit start/end timestamps and missing-anchor behavior. | B | `test_baseline_context_calculates_7d_and_30d_value_trends` |
| D | Calculate top allocation changes from deterministic weight snapshots. | B | `test_baseline_context_summarizes_top_allocation_changes` |
| E | Summarize top quantity/weight position changes without performing cost-basis inference. | B | `test_baseline_context_summarizes_recent_position_changes` |
| E1 | Preserve literal cash, configured cash sweep, and cash-equivalent distinctions already used by dashboard metrics. | A, E | `test_baseline_context_preserves_effective_cash_semantics` |

### EC3: Data limitations are explicit

| Task | Description | Depends on | Test |
| --- | --- | --- | --- |
| G | Add history-coverage, freshness, unsupported-quote, and data-quality limitations to the packet. | B through E | `test_baseline_context_reports_partial_history` |
| G1 | Do not advertise 7-day/30-day capabilities when a valid comparison anchor is unavailable. | G | `test_baseline_context_omits_uncovered_trend_capability` |
| G2 | Mark cached values with their actual `as_of`; do not relabel them as current/live. | A, G | `test_baseline_context_preserves_actual_as_of` |
| G3 | Return a valid empty/limited packet when SQL or the stored dashboard is unavailable. | A, G | `test_baseline_context_degrades_to_explicit_limitations` |

### EC4: Packet output is bounded and reproducible

| Task | Description | Depends on | Test |
| --- | --- | --- | --- |
| F | Attach an evidence reference to every baseline field or summary row usable in a direct answer. | A through E | `test_baseline_context_assigns_stable_evidence_refs` |
| F1 | Sort changes deterministically by materiality then stable asset key. | D, E | `test_baseline_change_sort_is_deterministic` |
| F2 | Enforce configured caps for holdings, allocation changes, position changes, and serialized packet size. | F | `test_baseline_context_enforces_compact_limits` |
| F3 | Exclude raw broker payloads, account identifiers, and unnecessary history rows. | F | `test_baseline_context_excludes_sensitive_raw_fields` |

### EC5: Dashboard lane remains stable

| Task | Description | Depends on | Test |
| --- | --- | --- | --- |
| I | Preserve existing `portfolio_connection_status`, `portfolio_dashboard`, and `portfolio_refresh` APIs. | H | Existing `tests/test_portfolio_data_service.py` |
| I1 | Prove loading baseline context never mutates or replaces the last valid dashboard. | H | `test_baseline_load_does_not_mutate_dashboard` |
| I2 | Prove manual refresh behavior and persistence policy remain unchanged. | I | `test_dashboard_refresh_remains_independent_from_baseline` |

## Tests To Add Or Update

- `tests/test_portfolio_data_service.py`
- new `tests/test_portfolio_baseline.py`
- `tests/test_chat_app.py`
- SQL/MCP fixtures needed for 7-day/30-day anchors

## Required Test Commands

```bash
.venv/bin/python -m pytest tests/test_portfolio_baseline.py -q
.venv/bin/python -m pytest tests/test_portfolio_data_service.py -q
.venv/bin/python -m pytest tests/test_chat_app.py -q
git diff --check
```

## Verification

Run on 2026-08-03:

```text
.venv/bin/python -m pytest tests/test_portfolio_baseline.py -q
18 passed

.venv/bin/python -m pytest tests/test_portfolio_data_service.py -q
9 passed, 1 warning

.venv/bin/python -m pytest tests/test_chat_app.py -q
13 passed, 1 warning

.venv/bin/python -m pytest tests/test_mcp_gateway.py tests/test_metrics.py -q
11 passed

.venv/bin/python -m pytest tests --ignore=tests/live -q
303 passed, 1 warning

git diff --check
passed
```

The warning is the existing LangGraph dependency deprecation warning.

Not run:

- `tests/live`: baseline construction is a deterministic stored-SQL path and
  must not depend on live OpenD or hosted model calls.
- Ruff: the project virtual environment does not contain a Ruff executable.

## Remaining

No remaining V1.5.1 exit criteria. V1.5.2 must load this packet before the
Investment planner, adopt `InvestmentTurnDecision`, and apply V1.5.0 coverage
validation. The baseline is available through `ChatService`, but the live
Investment graph does not consume it yet.

## Notes And Risks

- “Changed since last week” is one-call eligible only when the packet contains a
  valid 7-day anchor and the required change dimensions. A current snapshot
  alone is insufficient.
- Keep the baseline prompt payload substantially smaller than a full portfolio
  evidence packet. Prefer top-N summaries plus evidence refs.
- Baseline reads should have a bounded latency budget and no implicit live
  connector dependency.
- Reuse current finance math and cash semantics; do not recalculate them in the
  LLM prompt.
