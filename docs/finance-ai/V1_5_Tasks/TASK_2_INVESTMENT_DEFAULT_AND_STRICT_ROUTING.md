# Task V1.5.2: Investment Default And Strict Evidence Routing

## Goal

Make Investment Agent the only public chat entrypoint and integrate the
deterministic baseline packet into its first structured LLM turn so covered
general breakdown, rough trend, and recent-change questions finish with one LLM
call.

Portfolio delegation must be a strict evidence decision: the planner declares
what evidence the answer needs, deterministic policy verifies coverage, and any
escalation carries a bounded request plus an explicit missing-evidence reason.

## Status

Complete as of 2026-08-03.

## Implemented In

- `src/moomail_finance_ai/investment_planner.py`
  - Added the baseline-aware `plan_turn()` runtime contract. One structured LLM
    request now receives the original query, IPS, and bounded baseline packet
    and returns an `InvestmentTurnDecision` containing a direct answer or
    bounded delegation.
  - Added deterministic source-integrity, original-query safety, fallback, and
    evidence-coverage validation before graph routing. Failed direct coverage
    delegates only through the supplied fallback request or returns an explicit
    limitation.
  - Retained the V1.4 `plan()` shape only as an injected compatibility adapter;
    it cannot create a baseline-direct answer.
- `src/moomail_finance_ai/investment_agent.py`
  - Added `load_baseline` before the Investment planner, conditional
    direct/Portfolio/Sentiment branches, guarded direct `FinalReport`
    composition, and sanitized route/coverage/LLM-call provenance.
  - Direct baseline routes skip Portfolio and Sentiment agents and record one
    Investment LLM request. Missing, stale, short-window, and detailed requests
    use explicit bounded Portfolio delegation reasons.
- `src/moomail_finance_ai/agent_schemas.py`,
  `src/moomail_finance_ai/investment_guardrails.py`, and
  `src/moomail_finance_ai/chat_api.py`
  - Agent state now carries baseline, planned/validated turn decisions,
    coverage, safe LLM-call records, and call count. Portfolio-fact guardrails
    accept only deterministically validated baseline-direct evidence when no
    Portfolio packet exists.
  - Chat responses expose the new sanitized state. Legacy Portfolio aliases
    resolve to Investment Agent and add deprecation provenance.
- `scripts/serve_chat.py` and `web/`
  - `/api/chat` and `/api/chat/stream` ignore any frontend agent field and
    always enter Investment Agent.
  - Removed the agent selector, DOM binding, function argument, and submission
    payload field from both checked-in TypeScript and browser JavaScript.
- Tests and fixtures
  - Added baseline prompt/privacy, direct/delegate parsing, graph ordering,
    one-call golden routes, missing/stale/short-window/detailed escalation,
    adversarial safety, public entrypoint, frontend, and trace provenance
    coverage plus `v1_5_investment_*.json` fixtures.

## Scope And Boundaries

Owns:

- Removing the frontend agent choice and routing every web chat to Investment
  Agent.
- Loading baseline context before the Investment LLM call.
- Structured direct answer plus fallback request output.
- Coverage-based graph branch before Portfolio Agent.
- One-call direct composition and deterministic guardrails.
- Route provenance and call-count events.

Does not own:

- Baseline data calculations; V1.5.1 owns them.
- Portfolio evidence compilation/execution; V1.5.3 owns it.
- LangSmith transport or final trace presentation; V1.5.4/V1.5.5 own them.
- Hidden deterministic keyword routing.

## Exit Criteria

1. The webapp has no Portfolio Agent selector and all submitted chat requests
   enter Investment Agent; compatibility aliases cannot create a public
   Portfolio chat mode.
2. Investment Agent receives the original query, IPS, and compact baseline packet
   in one structured LLM turn.
3. Covered breakdown, 7-day/30-day rough trend, and recent-change prompts return
   a baseline-cited direct answer with exactly one outbound LLM request.
4. Missing, stale, short-window, or overly detailed evidence causes a bounded
   Portfolio delegation with explicit reason codes, never a guessed direct
   answer.
5. Safety, source integrity, planner normalization, and evidence-coverage
   validation run before any subagent call.
6. Route decision, evidence coverage, delegation reason, and total LLM call count
   are present in sanitized trace state.

## Dependency Graph

```text
V1.5.0 routing/safety contracts
  └── V1.5.1 baseline context
      ├── A. Remove public Portfolio selection
      ├── B. Load baseline before Investment planning
      ├── C. Extend structured Investment turn prompt/output
      ├── D. Validate safety and evidence coverage
      │   ├── E. Direct-context graph branch
      │   └── F. Bounded Portfolio delegation branch
      ├── G. Direct final report and guardrails
      └── H. Route/call-count golden tests
```

## Task Breakdown By Exit Criteria

### EC1: Investment Agent is the only public entrypoint

| Task | Description | Depends on | Test |
| --- | --- | --- | --- |
| A | Remove `agentSelect` and the Portfolio option from `web/index.html`, DOM bindings, frontend types, and chat submission payload. | V1.5.0 | `test_frontend_has_no_agent_selector` |
| A1 | Make `/api/chat` and `/api/chat/stream` select Investment Agent without trusting a frontend agent field. | A | `test_chat_api_always_uses_investment_agent` |
| A2 | Keep legacy backend names only as compatibility aliases that resolve to Investment Agent and emit deprecation provenance where appropriate. | A1 | `test_legacy_portfolio_alias_routes_to_investment_agent` |
| A3 | Reject any new direct free-text Portfolio public route. | A1 | `test_direct_portfolio_chat_mode_is_not_exposed` |

### EC2: First Investment call receives bounded baseline context

| Task | Description | Depends on | Test |
| --- | --- | --- | --- |
| B | Add a graph node that loads `PortfolioBaselinePacket` before `plan_investment`. | V1.5.1 | `test_investment_graph_loads_baseline_before_planner` |
| B1 | Pass the compact packet, capability list, evidence refs, freshness, and limitations into the structured planner prompt. | B | `test_investment_prompt_contains_compact_baseline_capabilities` |
| B2 | Ensure prompt construction excludes raw broker/account payloads and obeys the packet size cap. | B1 | `test_investment_prompt_excludes_raw_baseline_payloads` |
| C | Update the LLM output contract/prompt to declare required evidence, route decision, route reasons, cited refs, optional direct answer, and bounded fallback request. | B1, V1.5.0 | `test_investment_llm_returns_direct_or_delegate_decision` |

### EC3: Covered questions use one LLM call

| Task | Description | Depends on | Test |
| --- | --- | --- | --- |
| D | Run original-query safety, source integrity, planner normalization, and coverage validation before routing. | C | `test_investment_route_validation_runs_before_subagents` |
| E | Add a `direct_context` graph branch that skips Portfolio and Sentiment agents. | D | `test_direct_context_route_skips_all_subagents` |
| G | Convert the structured direct answer into `FinalReport`, include `as_of`/limitations/evidence refs, then run deterministic guardrails. | E | `test_direct_context_answer_becomes_guarded_final_report` |
| H | Count outbound LLM calls by purpose and assert one-call behavior for golden current breakdown, 7-day trend, 30-day trend, and covered recent changes. | G | `test_golden_baseline_queries_make_exactly_one_llm_call` |

### EC4: Insufficient evidence escalates explicitly

| Task | Description | Depends on | Test |
| --- | --- | --- | --- |
| F | Route to Portfolio Agent only when the validated decision is a Portfolio delegate or direct coverage fails and a valid fallback request exists. | D | `test_missing_baseline_evidence_routes_bounded_portfolio_request` |
| F1 | Add allowlisted reason codes for unsupported window, stale baseline, missing history, asset detail, cost basis, deeper risk, anomaly investigation, and latest OpenD requirement. | F | `test_portfolio_delegation_has_specific_reason_code` |
| F2 | Preserve required evidence and missing capabilities in the bounded handoff and trace. | F1 | `test_delegation_preserves_missing_evidence_scope` |
| F3 | If coverage fails and no valid fallback request exists, return an explicit limitation instead of inventing a request. | D, F | `test_missing_fallback_request_fails_closed` |
| F4 | Keep Sentiment routing owned by Investment Agent and unchanged as a stub. | C | `test_investment_agent_still_owns_sentiment_routing` |

### EC5: Safety and provenance remain enforceable

| Task | Description | Depends on | Test |
| --- | --- | --- | --- |
| D1 | Prove trade/order intent in the original query cannot be erased by a safe-looking planner result. | D | `test_original_trade_intent_blocks_direct_and_delegate_routes` |
| D2 | Prove unknown-only/empty planner output stops before graph routing. | D | `test_empty_investment_plan_stops_before_subagent_calls` |
| D3 | Emit planner type/mode, route, baseline version, coverage result, direct/delegate reason, and fallback use without raw prompts. | D | `test_investment_route_trace_has_sanitized_provenance` |

### EC6: Route behavior is evaluated, not inferred from implementation

| Task | Description | Depends on | Test |
| --- | --- | --- | --- |
| H1 | Add golden covered prompts for general breakdown, allocation overview, effective cash, last-week rough trend, and last-month rough trend. | H | `test_golden_covered_prompts_use_direct_context` |
| H2 | Add golden delegated prompts for asset-level purchase history, custom unsupported window, detailed risk decomposition, stale latest-value request, and anomaly root cause. | F | `test_golden_detailed_prompts_delegate_portfolio` |
| H3 | Add adversarial prompts that ask the planner to skip validation, rewrite source query, or claim absent evidence. | D | `test_adversarial_routes_fail_closed` |

## Tests To Add Or Update

- `tests/test_chat_app.py`
- `tests/test_investment_agent.py`
- `tests/test_investment_planner.py`
- `tests/test_agent_trace.py`
- `tests/fixtures/agent/v1_5_investment_*.json`

## Required Test Commands

```bash
.venv/bin/python -m pytest tests/test_investment_planner.py tests/test_investment_agent.py -q
.venv/bin/python -m pytest tests/test_chat_app.py tests/test_agent_trace.py -q
.venv/bin/python -m pytest tests/test_investment_guardrails.py -q
git diff --check
```

## Verification

Run on 2026-08-03:

```text
.venv/bin/python -m pytest tests/test_investment_planner.py tests/test_investment_agent.py -q
54 passed, 1 warning

.venv/bin/python -m pytest tests/test_chat_app.py tests/test_agent_trace.py -q
22 passed, 1 warning

.venv/bin/python -m pytest tests/test_investment_guardrails.py -q
6 passed

.venv/bin/python -m pytest tests --ignore=tests/live -q
331 passed, 1 warning

git diff --check
passed
```

The warning is the existing LangGraph dependency deprecation warning.

Not run:

- `tests/live`: V1.5.2 route validation is deterministic and the task does not
  require live OpenD or hosted model calls.
- Ruff: the project virtual environment does not contain a Ruff executable.

## Remaining

No remaining V1.5.2 exit criteria. V1.5.3 still owns delegated Portfolio
evidence-plan compilation changes and enforcement/instrumentation of the full
two-call delegated-run budget. V1.5.4/V1.5.5 still own LangSmith, complete
cross-agent LLM telemetry, and grouped user-facing trace presentation.

## Notes And Risks

- A one-call route is not “no planning.” The single Investment call must produce
  a validated structured decision and direct answer.
- Never always attach a full snapshot/history packet. Keep baseline context
  compact so saved endpoint calls do not become excessive prompt cost.
- The direct answer must state when it uses stored/cached data and show its
  actual `as_of`.
- Backend aliases are compatibility only. Tests should prevent them from
  reappearing as a user choice.
- Grounding used the execute-iteration skill reference, this task, the sibling
  README, V1.5.0/V1.5.1 contracts, and the routed architecture, agent,
  requirements, protocol, testing, and decision documents.
