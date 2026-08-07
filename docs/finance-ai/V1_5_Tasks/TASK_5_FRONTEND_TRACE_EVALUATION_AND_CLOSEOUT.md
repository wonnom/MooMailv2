# Task V1.5.5: Frontend Trace, Evaluation, And Closeout

## Goal

Close V1.5 by replacing raw internal status spam with useful user progress and
expandable audit detail, preserving the deterministic dashboard across all agent
and observability failures, proving route/call budgets with golden evaluations,
and updating current-truth documentation.

This task is the V1.5 release gate. It should not introduce new agent domains.

## Status

Complete as of 2026-08-05.

## Scope And Boundaries

Owns:

- Plain-language grouped progress timeline.
- Expandable sanitized detailed trace.
- Dashboard-preservation behavior for all terminal failures.
- Golden routing, LLM call-count, privacy, and trace usability evaluations.
- Current-truth docs, decision log, testing map, and closeout gates.

Does not own:

- Route, baseline, Portfolio, or observability implementation internals from
  V1.5.1 through V1.5.4.
- A general visual redesign unrelated to progress/trace/dashboard behavior.
- Real Sentiment Agent, memory, or trading features.

## Exit Criteria

1. The chat timeline shows no raw snake_case status prefixes and presents a
   small, ordered set of plain-language progress stages.
2. Repeated planned/actual/skipped tools are grouped for users while full
   sanitized detail remains available in the trace panel.
3. Detailed trace shows route, evidence coverage, delegation reasons, graph
   nodes/subagents, LLM purpose/model/timing/usage, tools, warnings, errors, and
   call totals without sensitive content.
4. Investment planner, Portfolio compiler/executor/evaluator, stream,
   LangSmith, and checkpoint failures preserve the last valid dashboard and
   surface actionable chat/trace errors.
5. Golden tests prove one-call direct routes, strict evidence escalation,
   delegated call budgets, safety, privacy, and agent ownership.
6. Documentation reflects implemented reality and the full non-live suite,
   whitespace gate, and targeted frontend/backend tests pass.

## Dependency Graph

```text
V1.5.1 baseline context
V1.5.2 Investment default and strict routing
V1.5.3 Portfolio escalation and call budget
V1.5.4 LangSmith and MooMail trace
  ├── A. Map internal events to user progress stages
  ├── B. Group repeated tool/subagent events
  ├── C. Render expandable detailed trace
  ├── D. Preserve dashboard on every terminal failure
  ├── E. Golden route and LLM call-count evaluations
  ├── F. Trace privacy and usability regressions
  ├── G. Current-truth docs and decision log
  └── H. Final deterministic release gates
```

## Task Breakdown By Exit Criteria

### EC1: User progress is plain-language and concise

| Task | Description | Depends on | Test |
| --- | --- | --- | --- |
| A | Map internal trace events into stable user stages such as reviewing request, loading saved data, checking coverage, retrieving details, analyzing evidence, safety review, and complete. | V1.5.4 | `test_progress_mapper_returns_plain_language_stages` |
| A1 | Remove raw `event.status + ":"` rendering from chat bubbles. | A | `test_chat_does_not_render_raw_status_prefixes` |
| A2 | Include useful context such as cached `as_of`, direct versus delegated path, and why deeper evidence is being retrieved. | A, V1.5.2 | `test_progress_explains_data_source_and_delegation_reason` |
| A3 | Do not expose hidden reasoning, prompt text, internal exception detail, or broker identifiers in progress messages. | A | `test_progress_messages_are_sanitized` |

### EC2: Repetitive events are grouped without losing audit detail

| Task | Description | Depends on | Test |
| --- | --- | --- | --- |
| B | Group repeated planned/actual/skipped tool events into one phase summary with counts and outcome. | A, V1.5.4 | `test_progress_groups_repeated_portfolio_tool_events` |
| B1 | Collapse repeated asset-resolution and validation statuses unless a warning/error requires an individual message. | B | `test_progress_collapses_success_noise_but_keeps_warnings` |
| B2 | Preserve every sanitized source event in the detailed trace payload. | B | `test_grouping_does_not_drop_detailed_trace_events` |
| B3 | Prevent duplicate Portfolio events caused by live forwarding plus final-result adaptation. | B, V1.5.4 | `test_frontend_receives_each_trace_event_once` |

### EC3: Detailed trace supports real auditing

| Task | Description | Depends on | Test |
| --- | --- | --- | --- |
| C | Render a structured trace summary with run/thread ids, route, coverage, delegation reasons, node/subagent sequence, data source/freshness, and guardrail outcome. | V1.5.4 | `test_trace_panel_shows_route_and_graph_sequence` |
| C1 | Render LLM call rows with purpose, provider/model, duration, usage if available, attempt, and status. | C | `test_trace_panel_shows_every_llm_call` |
| C2 | Render grouped and expandable planned/actual/skipped deterministic tools. | C, B | `test_trace_panel_shows_tool_outcomes` |
| C3 | Make warnings/errors actionable while keeping traceback and sensitive detail out of normal user view. | C | `test_trace_panel_shows_safe_actionable_errors` |
| C4 | Add accessibility coverage for progress and trace controls. | C | `test_trace_progress_controls_are_accessible` |

### EC4: Failures preserve the deterministic dashboard

| Task | Description | Depends on | Test |
| --- | --- | --- | --- |
| D | Define terminal analytical failure statuses across Investment planning/validation, baseline coverage, Portfolio compilation/execution/evaluation, call budget, stream, LangSmith, and checkpointing. | V1.5.1 through V1.5.4 | `test_terminal_agent_failure_statuses_are_complete` |
| D1 | Do not pass a degraded/limitation-only analytical `final_report` to dashboard rendering as a valid replacement. | D | `test_terminal_agent_failure_does_not_render_over_dashboard` |
| D2 | Keep the last valid dashboard title, holdings, allocation, and evaluation while adding a chat/trace error. | D1 | `test_all_terminal_failures_preserve_last_valid_dashboard` |
| D3 | Allow a valid direct or delegated report to replace the dashboard only after final guardrails pass. | D1 | `test_only_guarded_successful_report_replaces_dashboard` |

### EC5: Golden evaluations prove routing and call budgets

| Task | Description | Depends on | Test |
| --- | --- | --- | --- |
| E | Add golden one-call prompts for current breakdown, allocation, effective cash, covered last-week trend/change, and covered last-month trend. | V1.5.2 | `test_golden_direct_routes_make_one_llm_call` |
| E1 | Add golden delegation prompts for custom windows, missing history, asset purchase/cost detail, deeper risk decomposition, anomaly root cause, and latest-live requirements. | V1.5.2, V1.5.3 | `test_golden_missing_evidence_routes_portfolio` |
| E2 | Assert detailed delegated runs make at most two total model calls and no Portfolio planner LLM call. | V1.5.3 | `test_golden_delegated_route_respects_two_call_budget` |
| E3 | Assert deterministic-only escalation can skip Portfolio analysis when its structured evidence is sufficient. | V1.5.3 | `test_golden_deterministic_escalation_skips_second_analysis_call` |
| E4 | Add failure fixtures for stale/partial baseline, invalid planner envelope, rewritten source query, Portfolio failure, and observability failure. | V1.5.0 through V1.5.4 | `test_v1_5_failure_fixtures_follow_safe_routes` |

### EC6: Privacy, ownership, and docs close the iteration

| Task | Description | Depends on | Test |
| --- | --- | --- | --- |
| F | Prove user progress, detailed MooMail trace, and fake LangSmith export contain no raw prompts, secrets, account ids, broker payloads, or hidden reasoning. | V1.5.4, A through C | `test_v1_5_trace_surfaces_pass_privacy_gate` |
| F1 | Prove Investment Agent owns mission/sentiment routing and Portfolio Agent remains internal and portfolio-only. | V1.5.2, V1.5.3 | `test_v1_5_agent_ownership_boundaries` |
| F2 | Prove dashboard refresh/status/latest never call agents or LLMs. | V1.5.1 | Existing dashboard independence tests |
| G | Update `AGENTS.md`, `ARCHITECTURE.md`, `PROTOCOL.md`, `ACTION_PLAN.md`, `TESTING.md`, `ENVIRONMENT.md`, and `MCP_SERVERS.md` with implemented V1.5 truth. | A through F | Docs review and docs regression tests |
| G1 | Add a decision-log entry with designed versus actual call budgets, routing outcomes, privacy choices, verification, and remaining limitations. | H | Docs review |
| G2 | Mark task statuses complete only after their actual targeted verification is recorded. | H | Docs review |

### EC7: Final release gates pass

| Task | Description | Depends on | Test |
| --- | --- | --- | --- |
| H | Run schema, planner, baseline, agent, observability, frontend, safety, and dashboard targeted suites. | A through G | Commands below |
| H1 | Run the full deterministic suite excluding live tests. | H | `.venv/bin/python -m pytest tests --ignore=tests/live -q` |
| H2 | Run `git diff --check`. | G | Whitespace gate |
| H3 | Record opt-in live tests separately; do not require hosted LLM/OpenD calls for deterministic closeout. | H1 | Verification note |

## Tests To Add Or Update

- `tests/test_chat_app.py`
- `tests/test_agent_trace.py`
- `tests/test_llm_observability.py`
- `tests/test_investment_planner.py`
- `tests/test_investment_agent.py`
- `tests/test_portfolio_baseline.py`
- `tests/test_portfolio_planner.py`
- `tests/test_portfolio_agent.py`
- `tests/test_portfolio_data_service.py`
- `tests/test_investment_guardrails.py`
- docs regression tests as needed

## Required Test Commands

```bash
.venv/bin/python -m pytest tests/test_agent_schemas.py tests/test_agent_trace.py -q
.venv/bin/python -m pytest tests/test_portfolio_baseline.py tests/test_portfolio_data_service.py -q
.venv/bin/python -m pytest tests/test_investment_planner.py tests/test_investment_agent.py -q
.venv/bin/python -m pytest tests/test_portfolio_planner.py tests/test_portfolio_agent.py -q
.venv/bin/python -m pytest tests/test_llm.py tests/test_llm_observability.py -q
.venv/bin/python -m pytest tests/test_chat_app.py tests/test_investment_guardrails.py -q
.venv/bin/python -m pytest tests --ignore=tests/live -q
git diff --check
```

## Verification

Implemented and verified on 2026-08-05.

Actual implementation:

- Added a deterministic `TraceEvent` to `UserProgressEvent` mapper with a
  fixed, ordered presentation vocabulary. The browser merges repeated stages
  and never renders `event.status + ":"` in chat.
- Added a sanitized `trace_summary` response projection with route/coverage,
  data context, graph/subagent sequence, model-call totals and lifecycle rows,
  grouped planned/actual/skipped tools, warnings/errors, guardrails, and every
  sanitized source event.
- Replaced the raw trace JSON block with accessible expandable sections and a
  concise run overview. Normal chat receives only progress plus one bounded run
  summary.
- Added an explicit terminal analytical failure set and a guarded-success gate.
  Stream and agent errors now update chat/trace only; they never overwrite the
  last valid dashboard. LangSmith export and checkpoint finalization failures
  are nonfatal `observability_degraded` warnings.
- Reused and strengthened the V1.5 golden route/call-budget, planner-integrity,
  ownership, privacy, and dashboard-independence evaluations; added progress,
  grouping, source-detail, observability-failure, and frontend regression
  coverage.

Required command results:

```text
tests/test_agent_schemas.py tests/test_agent_trace.py: 77 passed, 1 warning
tests/test_portfolio_baseline.py tests/test_portfolio_data_service.py: 27 passed, 1 warning
tests/test_investment_planner.py tests/test_investment_agent.py: 60 passed, 1 warning
tests/test_portfolio_planner.py tests/test_portfolio_agent.py: 77 passed, 1 warning
tests/test_llm.py tests/test_llm_observability.py: 16 passed, 1 warning
tests/test_chat_app.py tests/test_investment_guardrails.py: 23 passed, 1 warning
tests --ignore=tests/live: 375 passed, 1 warning
node --check for changed browser JavaScript: passed
interactive local browser progress/trace/accessibility check: passed
git diff --check: passed
```

The warning is the existing LangGraph serializer deprecation warning. Hosted
LangSmith/model and live OpenD tests were intentionally not run; they remain
opt-in and are not required for deterministic V1.5 closeout. Ruff remains
unavailable in the project virtual environment.

## Notes And Risks

- The screenshot motivating this task shows implementation statuses rather than
  useful progress. The release gate is user comprehension, not merely the
  presence of more trace fields.
- Keep chat progress concise even when detailed trace volume grows.
- Do not mark V1.5 complete if call counts are inferred from route labels rather
  than measured at the model client boundary.
- Live LangSmith/LLM/OpenD checks remain opt-in and must use non-sensitive test
  data or approved redaction settings.
