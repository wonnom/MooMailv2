# Task V1.4.4: Deterministic Execution And Evidence Packet

## Goal

Execute validated `PortfolioEvidencePlan` objects through deterministic MCP
tools and return a `PortfolioEvidencePacket`.

This task converts the new plan shape into real Portfolio Agent output. It keeps
OpenD, SQL, finance metrics, cost-basis math, position-state changes, freshness
policy, and persistence deterministic. Any LLM use is limited to optional
portfolio-only explanation or pattern ranking after facts are collected.

## Status

Complete as of 2026-06-29.

## Implemented In

- `src/moomail_finance_ai/portfolio_agent.py`
  - Added policy-aware execution for bounded `PortfolioEvidencePlan` runs:
    `latest_required` calls OpenD, `cached_ok` can use fresh SQL latest state
    without OpenD, and `history_only` reads SQL history without OpenD.
  - Added first-class `PortfolioAgentResult.evidence_packet` assembly with
    separated facts, derived metrics, position changes, deterministic detected
    patterns, portfolio-only interpretation, limitations, sentiment-context
    needs, warnings, and tool refs.
  - Added stable detector thresholds for concentration, effective cash,
    allocation materiality, large quantity changes, and average-cost shifts.
  - Kept legacy `PortfolioTask`/`PortfolioContextPlan` compatibility while
    making bounded `PortfolioRequest` execution follow the evidence plan and
    freshness policy directly.
- `src/moomail_finance_ai/investment_agent.py`
  - Passes the typed `PortfolioRequest` from the Investment planner into the
    Portfolio Agent at runtime and carries the returned evidence packet forward
    in the Investment-facing portfolio packet.
  - Emits sanitized evidence-plan/evidence-packet trace phases plus planned,
    actual, and skipped Portfolio Agent tool trace events.
- `src/moomail_finance_ai/agent_schemas.py`
  - Added optional `evidence_packet` to `PortfolioAgentEvidencePacket` for
    Investment Agent synthesis and chat payloads.
- `src/moomail_finance_ai/portfolio_data_service.py`
  - Exposed the SQL latest-state-to-snapshot conversion for cached Portfolio
    Agent evidence policy reuse.
- Tests
  - Added deterministic coverage for cached SQL freshness, history-only no-OpenD
    execution, stale-cache warnings, evidence packet separation, pattern
    detector thresholds, Portfolio Agent LLM input boundaries, and dashboard
    independence.

## Exit Criteria

1. Portfolio Agent executes only allowlisted tools implied by the validated
   evidence plan.
2. Position-state-change reads are scoped by resolved asset/ticker/time range
   when requested.
3. Evidence packet separates facts, metrics, position changes, detected
   patterns, portfolio-only interpretation, limitations, and sentiment needs.
4. Pattern/outlier detection is deterministic before optional explanation.
5. Existing dashboard deterministic data lane remains separate and does not call
   Portfolio Agent or Investment Agent.

## Dependency Graph

```text
V1.4.3 PortfolioEvidencePlan
  ├── A. Execute freshness policy
  │   ├── B. Retrieve OpenD context when required
  │   └── C. Read SQL latest/history when allowed
  ├── D. Calculate finance metrics
  ├── E. Read position-state changes by resolved scope
  ├── F. Apply deterministic pattern detectors
  ├── G. Assemble PortfolioEvidencePacket
  │   └── H. Optional portfolio-only explanation/ranking
  ├── I. Persist observations only under policy
  └── J. Add trace and regression tests
```

## Task Breakdown By Exit Criteria

### EC1: Tool execution follows the validated plan

| Task | Description | Depends on | Test |
| --- | --- | --- | --- |
| A | Add execution adapter that consumes `PortfolioEvidencePlan` instead of hidden task flags. | V1.4.3 | `test_portfolio_agent_executes_validated_evidence_plan` |
| A1 | Map history query plan entries to existing SQL MCP tool calls. | A | `test_evidence_plan_history_queries_call_expected_sql_tools` |
| A2 | Map metric groups to finance metrics MCP calls. | A | `test_evidence_plan_metric_groups_call_expected_metric_tools` |
| A3 | Preserve permissioned `MCPToolGateway` consumer identity for all calls. | A | `test_portfolio_execution_uses_portfolio_agent_consumer` |
| A4 | Reject or skip tool calls not present in the validated plan. | A | `test_portfolio_execution_rejects_unplanned_tool` |

### EC2: Freshness and history scope are deterministic

| Task | Description | Depends on | Test |
| --- | --- | --- | --- |
| B | Execute `latest_required` by calling OpenD through the gateway. | A | `test_latest_required_calls_opend_context` |
| B1 | Execute `cached_ok` by using fresh SQL latest state when available. | A | `test_cached_ok_uses_fresh_sql_without_opend` |
| B2 | Execute `history_only` by reading SQL history and not calling OpenD. | A | `test_history_only_skips_opend` |
| C | Return stale-data warnings when cached data is insufficient and OpenD is unavailable. | B, B1 | `test_stale_cache_returns_warning_in_evidence_packet` |
| E | Pass resolved `asset_id`, canonical symbol, `since`, `until`, and limit into `portfolio_sql_get_position_state_changes` when scoped history is requested. | V1.4.3 | `test_position_state_change_tool_uses_resolved_asset_scope` |

### EC3: Evidence packet has separated sections

| Task | Description | Depends on | Test |
| --- | --- | --- | --- |
| G | Assemble facts from snapshot/latest state/history without mixing in interpretation. | A through E | `test_evidence_packet_contains_facts_section` |
| G1 | Assemble derived metrics from deterministic metric outputs. | D, G | `test_evidence_packet_contains_derived_metrics_section` |
| G2 | Assemble position changes from SQL tool results. | E, G | `test_evidence_packet_contains_position_changes_section` |
| G3 | Add limitations such as no sentiment reviewed, missing history, unsupported quote, stale cache, unresolved asset, or out-of-scope account surface. | C, G | `test_evidence_packet_contains_limitations` |
| G4 | Add `needs_sentiment_context` hints without invoking Sentiment Agent. | G3 | `test_evidence_packet_can_suggest_sentiment_context_without_routing` |

### EC4: Portfolio Agent value-add is explicit and bounded

| Task | Description | Depends on | Test |
| --- | --- | --- | --- |
| F | Add deterministic pattern detectors for concentration, cash/effective cash, large allocation moves, large quantity changes, average-cost shifts, stale data, and unsupported quotes. | D, E, G | `test_pattern_detectors_find_expected_portfolio_outliers` |
| F1 | Store detector thresholds in config/constants that are visible in tests. | F | `test_pattern_detector_thresholds_are_stable` |
| H | Optionally pass facts/metrics/patterns to the portfolio-only evaluator for concise explanation, never for finance math. | G, F | `test_portfolio_llm_receives_evidence_not_raw_tool_authority` |
| H1 | Ensure portfolio-only interpretation is labeled and does not include final thesis/trade instructions. | H | `test_portfolio_interpretation_is_labeled_and_guarded` |

### EC5: Dashboard data lane remains separate

| Task | Description | Depends on | Test |
| --- | --- | --- | --- |
| I | Preserve existing `PortfolioDataService` refresh/status/latest behavior. | A | Existing `tests/test_portfolio_data_service.py` |
| I1 | Ensure dashboard refresh still does not instantiate Portfolio Agent, Investment Agent, sentiment stub, or LLM evaluator. | I | `test_dashboard_refresh_does_not_call_agents_or_llm` |
| J | Update trace to show plan execution phases and actual/skipped tool calls. | A through I | `test_portfolio_execution_trace_records_actual_and_skipped_tools` |

## Tests To Add Or Update

- `tests/test_portfolio_agent.py`
- `tests/test_portfolio_data_service.py`
- `tests/test_portfolio_planner.py`
- `tests/test_mcp_gateway.py`
- `tests/test_mcp_tool_contracts.py`

## Required Test Commands

```bash
.venv/bin/python -m pytest tests/test_portfolio_agent.py tests/test_portfolio_planner.py -q
.venv/bin/python -m pytest tests/test_portfolio_data_service.py tests/test_mcp_gateway.py -q
.venv/bin/python -m pytest tests/test_mcp_tool_contracts.py -q
```

## Verification

Run on 2026-06-29:

```text
.venv/bin/python -m pytest tests/test_portfolio_agent.py tests/test_portfolio_planner.py -q
51 passed in 0.62s

.venv/bin/python -m pytest tests/test_portfolio_data_service.py tests/test_mcp_gateway.py -q
11 passed, 1 warning in 0.39s

.venv/bin/python -m pytest tests/test_mcp_tool_contracts.py -q
6 passed in 0.21s

.venv/bin/python -m pytest tests --ignore=tests/live -q
251 passed, 1 warning in 8.77s

git diff --check
passed
```

The warnings are the existing LangGraph dependency deprecation warning.

Not run:

- `tests/live`: opt-in live connector/OpenD tests are not required for this
  deterministic evidence-execution task.

## Remaining

No remaining exit criteria for V1.4.4. The Portfolio Agent still returns
legacy `context_plan`/`portfolio_packet` fields for compatibility, but bounded
`PortfolioRequest` runs now also return the separated `PortfolioEvidencePacket`
and follow deterministic evidence-plan freshness/tool policy.

## Notes

- Do not introduce LLM-dependent tests for deterministic execution.
- Do not write SQL observations before the evidence packet is produced unless a
  task explicitly preserves the existing persistence policy and tests cover it.
