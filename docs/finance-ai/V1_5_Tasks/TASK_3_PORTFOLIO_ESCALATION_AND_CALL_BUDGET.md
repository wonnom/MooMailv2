# Task V1.5.3: Portfolio Escalation And LLM Call Budget

## Goal

Make Portfolio Agent a true escalation path for evidence that the baseline
packet cannot supply, while removing its redundant evidence-planning LLM call.

A delegated run should compile its evidence plan deterministically from the
validated `PortfolioRequest`, execute MCP tools deterministically, and make at
most one Portfolio analysis LLM call when interpretation is needed. Together
with the Investment turn, the normal delegated budget is two LLM calls total.

## Status

Complete as of 2026-08-05.

## Implemented In

- `src/moomail_finance_ai/portfolio_evidence_planner.py`
  - Added `DeterministicPortfolioEvidenceCompiler` with exhaustive task-intent
    and output-goal mappings for history queries, metrics, current-value need,
    persistence, asset scope, and pattern detectors.
  - Compilation resolves assets, validates the bounded request, constructs the
    allowlisted plan, and validates the result before evidence tools execute.
  - Kept the V1.4 LLM planner classes isolated as compatibility/test surfaces;
    the normal Portfolio constructor no longer builds or invokes them.
- `src/moomail_finance_ai/agent_schemas.py`,
  `src/moomail_finance_ai/asset_resolver.py`, and
  `src/moomail_finance_ai/investment_planner.py`
  - Added explicit `analysis_requirement` to `PortfolioRequest`. Mechanical
    facts, metrics, and scoped changes may use `deterministic_only`; detailed
    review, risk, comparison, and pattern requests must use
    `interpretation_required`.
  - Updated Investment prompts and fixtures so the first Investment turn makes
    this bounded decision without naming tools.
- `src/moomail_finance_ai/portfolio_agent.py`
  - Made deterministic compilation the default runtime, assembled the evidence
    packet before interpretation, skipped the evaluator for deterministic-only
    requests, and bounded analytical requests to one evaluator invocation.
  - Added purpose-scoped call-budget enforcement, explicit retry reservations,
    failed-call records, expected/actual counts, and result consistency checks.
  - Evaluation failure occurs before current-observation persistence, preserving
    prior valid SQL/dashboard data.
- `src/moomail_finance_ai/investment_agent.py` and
  `src/moomail_finance_ai/agent_trace.py`
  - Aggregate Portfolio analysis calls with the Investment call, enforce the
    normal delegated maximum of two, reject unplanned purpose-level calls, and
    emit sanitized route/budget/failure context.
- Tests and fixtures
  - Added exhaustive compiler, freshness/persistence, default-runtime,
    deterministic-skip, single-analysis, retry, cross-agent budget, and failure
    isolation regressions.

## Scope And Boundaries

Owns:

- Deterministic compilation of bounded requests into evidence plans.
- Existing asset resolution, freshness, metric, SQL/OpenD, detector, and
  persistence policies.
- One conditional Portfolio analysis call after evidence exists.
- Per-run call-budget enforcement and traced failure behavior.
- Removal of normal-runtime `LLMPortfolioEvidencePlanner` use.

Does not own:

- User mission interpretation or whether Sentiment Agent is needed.
- Direct-context Investment responses.
- LLM finance math, autonomous tool selection, or trading.
- Frontend trace presentation.

## Exit Criteria

1. A validated bounded `PortfolioRequest` compiles deterministically into the
   complete allowlisted `PortfolioEvidencePlan` needed for execution.
2. Asset resolution, history scope, metrics, freshness, current-value need,
   persistence, and pattern detectors remain deterministic and policy-tested.
3. Normal delegated execution makes no Portfolio evidence-planner LLM request.
4. Portfolio analysis is called at most once and only when the handoff requires
   interpretation beyond deterministic facts/metrics.
5. Call budgets are enforced and traced; retry behavior cannot silently add
   endpoint calls.
6. Portfolio planning/evaluation failures remain explicit and never replace the
   last valid deterministic dashboard.

## Dependency Graph

```text
V1.5.2 validated bounded escalation
  ├── A. Deterministic PortfolioEvidencePlan compiler
  │   ├── B. Asset resolution and scope compilation
  │   ├── C. Freshness/history/metric/persistence compilation
  │   └── D. Deterministic plan validation
  ├── E. Execute compiled evidence plan
  │   ├── F. Assemble PortfolioEvidencePacket
  │   └── G. Decide whether one analysis call is required
  ├── H. Enforce per-run LLM call budget
  └── I. Remove normal evidence-planner LLM path and add regressions
```

## Task Breakdown By Exit Criteria

### EC1: Evidence planning is deterministic compilation

| Task | Description | Depends on | Test |
| --- | --- | --- | --- |
| A | Add a provider-neutral compiler from validated `PortfolioRequest`, resolved assets, IPS, and deterministic requirements to `PortfolioEvidencePlan`. | V1.5.2 | `test_portfolio_evidence_compiler_returns_valid_plan` |
| A1 | Define exhaustive mappings from task intent/output goals to allowlisted history queries, metric groups, current-value dependency, and detectors. | A | `test_evidence_compiler_maps_all_output_goals` |
| B | Reuse deterministic asset resolution and compile asset/ticker/portfolio-wide position-change scope. | A | `test_evidence_compiler_uses_resolved_asset_scope` |
| C | Compile `latest_required`, `cached_ok`, and `history_only` behavior plus persistence mode under existing policy. | A | `test_evidence_compiler_applies_freshness_and_persistence_policy` |
| C1 | Keep exact tool names out of Investment output; only the Portfolio compiler maps evidence fields to execution. | A, C | `test_investment_request_does_not_contain_tool_names` |
| D | Run existing request and evidence-plan validators after compilation and fail before tools on incoherent input. | A through C | `test_compiled_evidence_plan_validates_before_tools` |

### EC2: Existing deterministic execution remains authoritative

| Task | Description | Depends on | Test |
| --- | --- | --- | --- |
| E | Feed the compiled plan into the existing freshness, OpenD, SQL, metric, and persistence execution path. | D | `test_portfolio_agent_executes_compiled_plan` |
| E1 | Preserve history-only no-OpenD and fresh-cache no-OpenD behavior. | E | `test_compiled_history_and_cache_routes_skip_opend` |
| E2 | Preserve position-change/cost-basis math in SQL/finance code, never in an LLM. | E | `test_portfolio_llm_not_used_for_finance_math` |
| F | Assemble the separated evidence packet with facts, metrics, changes, patterns, limitations, and tool refs before any LLM interpretation. | E | `test_evidence_packet_exists_before_portfolio_analysis` |

### EC3: Redundant Portfolio planning LLM is removed

| Task | Description | Depends on | Test |
| --- | --- | --- | --- |
| I | Stop constructing or invoking `LLMPortfolioEvidencePlanner` in the normal Investment-managed Portfolio path. | A through D | `test_delegated_run_does_not_call_portfolio_planner_llm` |
| I1 | Retire or isolate legacy planner classes as migration-only/test compatibility; document removal path. | I | Static/runtime assertion in `tests/test_portfolio_planner.py` |
| I2 | Remove prompt parsing/normalization from active execution only after V1.5.0 fail-closed regressions remain covered for compatibility surfaces. | I1 | `test_legacy_planner_surface_remains_fail_closed` |

### EC4: Portfolio analysis is conditional and bounded

| Task | Description | Depends on | Test |
| --- | --- | --- | --- |
| G | Add an explicit `analysis_requirement` to the validated escalation so deterministic fact retrieval can skip Portfolio LLM analysis when a structured result is sufficient. | V1.5.2, F | `test_portfolio_analysis_requirement_is_explicit` |
| G1 | Invoke the Portfolio evaluator once for deep interpretation, ranking, anomaly explanation, or detailed analytical requests. | G | `test_detailed_escalation_calls_portfolio_evaluator_once` |
| G2 | Skip the evaluator for deterministic-only escalations and return evidence/limitations through deterministic composition. | G | `test_deterministic_only_escalation_skips_portfolio_evaluator` |
| G3 | Keep Portfolio output portfolio-only and prevent final thesis, sentiment claims, or trade instructions. | G1 | `test_portfolio_analysis_remains_bounded_and_guarded` |

### EC5: LLM endpoint call budget is enforced

| Task | Description | Depends on | Test |
| --- | --- | --- | --- |
| H | Add a per-run call budget keyed by purpose and route; default delegated total is Investment 1 plus Portfolio analysis at most 1. | G, V1.5.0 telemetry | `test_delegated_route_enforces_two_call_total_budget` |
| H1 | Reject an unplanned retry or duplicate model invocation with a traced budget error. | H | `test_unplanned_llm_retry_is_blocked_and_traced` |
| H2 | If retry policy is later enabled, require an explicit configured budget, retry reason, and attempt index. | H1 | `test_configured_retry_records_attempt_and_reason` |
| H3 | Include expected and actual call counts by purpose in terminal result/audit trace. | H | `test_portfolio_result_reports_llm_call_counts` |

### EC6: Failures remain isolated from dashboard state

| Task | Description | Depends on | Test |
| --- | --- | --- | --- |
| I3 | Propagate compiler, validation, execution, evaluator, and budget failures as terminal subagent errors with route context. | D through H | `test_portfolio_failures_propagate_with_route_context` |
| I4 | Ensure no Portfolio failure writes a degraded analytical report over the last valid dashboard. | I3 | `test_portfolio_failure_preserves_last_valid_dashboard` |
| I5 | Preserve partial evidence only when contracts mark it safe and limitations are explicit. | F, I3 | `test_partial_portfolio_evidence_requires_explicit_limitations` |

## Tests To Add Or Update

- `tests/test_portfolio_planner.py`
- `tests/test_portfolio_agent.py`
- `tests/test_investment_agent.py`
- `tests/test_agent_trace.py`
- `tests/test_chat_app.py`
- `tests/test_portfolio_data_service.py`

## Required Test Commands

```bash
.venv/bin/python -m pytest tests/test_portfolio_planner.py tests/test_portfolio_agent.py -q
.venv/bin/python -m pytest tests/test_investment_agent.py tests/test_agent_trace.py -q
.venv/bin/python -m pytest tests/test_chat_app.py tests/test_portfolio_data_service.py -q
git diff --check
```

## Verification

Run on 2026-08-05:

```text
.venv/bin/python -m pytest tests/test_portfolio_planner.py tests/test_portfolio_agent.py -q
77 passed

.venv/bin/python -m pytest tests/test_investment_agent.py tests/test_agent_trace.py -q
46 passed, 1 warning

.venv/bin/python -m pytest tests/test_chat_app.py tests/test_portfolio_data_service.py -q
24 passed, 1 warning

.venv/bin/python -m pytest tests --ignore=tests/live -q
357 passed, 1 warning

.venv/bin/python -m py_compile src/moomail_finance_ai/agent_schemas.py src/moomail_finance_ai/asset_resolver.py src/moomail_finance_ai/portfolio_evidence_planner.py src/moomail_finance_ai/portfolio_agent.py src/moomail_finance_ai/investment_planner.py src/moomail_finance_ai/investment_agent.py src/moomail_finance_ai/agent_trace.py
passed

git diff --check
passed
```

The warning is the existing LangGraph dependency deprecation warning.

Not run:

- `tests/live`: deterministic compiler/call-budget completion does not require
  live OpenD or hosted model calls.
- Ruff: the project virtual environment does not contain a Ruff executable.

## Remaining

No remaining V1.5.3 exit criteria. V1.5.4 still owns complete provider token
telemetry, LangSmith spans, full MooMail trace propagation, and optional graph
checkpointing. V1.5.5 owns frontend trace presentation and iteration closeout.

## Notes And Risks

- This compiler is deterministic evidence policy, not a return to deterministic
  user-query interpretation. Investment Agent has already supplied the bounded
  semantic request.
- Mapping tables must be exhaustive and fail closed on new enum values.
- Removing one LLM call should not widen tool authority. Existing MCP allowlists
  and consumer identities remain mandatory.
- Do not retain both active LLM and deterministic evidence planners behind a
  silent fallback switch.
- `LLMPortfolioEvidencePlanner` remains importable only for V1.4 compatibility
  parsing/live-test fixtures. Remove it when those callers migrate; the default
  Portfolio constructor has no switch or fallback that can activate it.
