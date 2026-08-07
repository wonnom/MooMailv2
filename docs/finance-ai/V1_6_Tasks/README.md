# V1.6 Task Notes

Status: planned as of 2026-08-07.

## V1.6 Goal

Make direct-context portfolio answers preserve one validated evidence-coverage
decision from route validation through synthesis and final guardrails. A report
that uses a valid saved dashboard baseline must not be rejected merely because
Portfolio Agent was correctly skipped.

## Observed Failure

The prompt `Review my portfolio` completed one Gemini Investment planning call,
selected a path with no Portfolio tool activity, and then failed the
`unsupported_price_or_portfolio_facts` guardrail:

```text
Investment planning call: completed
Portfolio tools: 0 planned / 0 actual / 0 skipped
Guardrail: unsupported_price_or_portfolio_facts failed
Reason: Portfolio facts appear without a Portfolio Agent packet.
Frontend result: AnalyticalRunUnavailable
```

This is an internal routing/coverage inconsistency. A direct-context response is
allowed to use validated baseline facts without a Portfolio Agent packet, but
the guardrail did not recognize the baseline coverage as valid at the final
review stage.

## V1.6.0 Todo: Direct-Context Coverage And Guardrail Consistency

### Dependencies

- V1.5.1 deterministic baseline packet and evidence references.
- V1.5.2 direct-context routing, deterministic coverage validation, and bounded
  Portfolio fallback.
- V1.5.5 guarded dashboard replacement and frontend run details.

### Subtasks

| ID | Subtask | Depends on | Success criteria |
| --- | --- | --- | --- |
| A | Reproduce the failure with a deterministic fixture matching `Review my portfolio`, including the planner decision, baseline packet, coverage result, final report, and guardrail review. | V1.5.1, V1.5.2 | A regression test fails because a direct-context report with baseline-backed portfolio facts is blocked by `unsupported_price_or_portfolio_facts`. |
| B | Trace where `evidence_coverage.is_valid` is lost, renamed, recomputed, or left unset between direct-route validation and the guardrail node. | A | The test and trace identify one authoritative coverage object and the exact state transition that causes the mismatch. |
| C | Preserve the validated direct-context coverage decision and evidence references through LangGraph state transitions and final synthesis. | B | The guardrail receives the same validated coverage result used to approve `direct_context`; no duplicate or contradictory coverage calculation exists. |
| D | Enforce fail-closed escalation before synthesis whenever direct coverage is invalid, stale, or incomplete. | B | Invalid direct coverage uses the planner-supplied bounded Portfolio fallback, or returns an explicit limitation when no valid fallback exists; unsupported portfolio facts never reach final composition. |
| E | Keep `unsupported_price_or_portfolio_facts` evidence-based and independent of whether Portfolio Agent ran. | C, D | The check passes for baseline-backed direct facts, passes for Portfolio-packet-backed delegated facts, and fails for facts backed by neither source. |
| F | Surface guardrail blocks as actionable user-visible failures. Include failed check names, revision messages, route, and coverage failure reason under Warnings and errors. | C, D, E | A blocked report no longer produces an empty Warnings and errors section or only the generic `AnalyticalRunUnavailable` message. |
| G | Correct terminal progress semantics for blocked reports. | F | The frontend does not show `Complete ✓` or `Response ready` when guardrails block dashboard replacement; it shows a clear blocked/needs-attention terminal state. |
| H | Add direct, delegated, invalid-coverage, stale-baseline, and frontend regression tests. | C, D, E, F, G | Targeted guardrail, Investment Agent, trace, and chat tests pass and prove the one-call direct path remains intact. |

### Dependency Map

```text
A. Reproduce direct-context guardrail failure
  -> B. Locate coverage-state inconsistency
       -> C. Preserve authoritative validated coverage
       -> D. Escalate before synthesis when coverage is invalid
            -> E. Align portfolio-fact guardrail with evidence source
                 -> F. Expose actionable guardrail failure details
                      -> G. Correct blocked terminal progress
                           -> H. Complete regression matrix
```

## Acceptance Criteria

- `Review my portfolio` uses one Investment LLM call when the saved baseline
  validly covers the answer and does not call Portfolio Agent solely to satisfy
  the final guardrail.
- A baseline-backed direct report passes
  `unsupported_price_or_portfolio_facts` without a Portfolio Agent packet.
- Missing, stale, or incomplete baseline evidence cannot silently pass as a
  direct-context answer; it escalates before synthesis or returns an explicit
  limitation.
- The guardrail still blocks portfolio facts that have neither validated
  baseline evidence nor a Portfolio Agent packet.
- Route validation, synthesis, guardrails, MooMail trace, and frontend details
  expose one consistent coverage status and reason.
- Guardrail-blocked runs appear as blocked/needs-attention, not successful
  completion, and their failed checks are visible without opening raw source
  events.
- The deterministic saved dashboard remains unchanged after any blocked run.
- Existing one-call direct and two-call delegated LLM budgets remain enforced.

## Expected Test Coverage

```text
tests/test_investment_agent.py
  - covered direct_context preserves validated evidence coverage
  - invalid direct_context escalates before synthesis

tests/test_investment_guardrails.py
  - baseline-backed direct portfolio facts pass
  - delegated Portfolio-packet-backed facts pass
  - unsupported facts without either evidence source fail

tests/test_agent_trace.py
  - coverage and failed guardrail reasons remain visible and correlated

tests/test_chat_app.py
  - blocked guardrails render actionable details
  - blocked runs do not render Complete / Response ready
  - blocked runs do not replace the saved dashboard
```

## Non-Goals

- Weakening or removing the `unsupported_price_or_portfolio_facts` guardrail.
- Calling Portfolio Agent for every portfolio question.
- Adding keyword-based routing to compensate for missing coverage state.
- Allowing LLM-generated portfolio facts without deterministic evidence.
- Changing the existing no-trading, exact-share-count, research, IPS, or
  sentiment guardrails except where shared terminal presentation is affected.
