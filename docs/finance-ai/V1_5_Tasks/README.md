# V1.5 Task Notes

Status: planning placeholder.

## Problem

V1.4 introduces typed planner contracts and a deterministic investment planner,
but the current runtime boundary is still ambiguous: the deterministic planner is
described as a fallback/offline path while also being wired as the default
Investment Agent planner.

That creates product and maintenance risk:

- The webapp can silently use regex/keyword routing as normal behavior.
- The user cannot clearly tell whether an LLM planner, deterministic fallback,
  or fixed backend route produced a decision.
- Broad keyword matching can accumulate in the codebase as hidden product logic.
- The project may confuse deterministic validation and guardrails, which should
  remain, with deterministic query interpretation, which should not be the
  default agent behavior.

## Desired Direction

V1.5 should make the planner boundary explicit:

```text
User query
  -> LLM structured planner for dynamic agent intent
  -> deterministic schema validation and safety checks
  -> deterministic MCP/tool execution
  -> LLM synthesis where useful
  -> deterministic guardrail review
```

Deterministic code should remain first-class for:

- portfolio dashboard/status/refresh endpoints
- finance metric calculations
- asset resolution and plan validation
- no-trading safety checks
- test fakes and offline deterministic tests
- explicit degraded mode, if intentionally enabled

Deterministic keyword planning should not be silently used as the normal webapp
planner.

## Questions To Resolve

1. Should missing/unavailable LLM planner fail closed instead of falling back?
2. If fallback remains, what exact UI and trace fields should expose it?
3. Should the current deterministic planner move into a test fake, a degraded
   mode module, or be replaced by fixture-based planner tests?
4. Which hardcoded rules are true safety guardrails and should stay in runtime?
5. Which hardcoded rules are product intent inference and should be removed from
   normal runtime?

## Candidate Acceptance Criteria

- The default webapp Investment Agent path uses an explicit structured planner
  implementation, not silent regex/keyword routing.
- Planner responses include planner provenance, for example `planner_type`,
  `planner_mode`, and `fallback_reason`.
- The frontend trace clearly shows when a deterministic fallback or degraded
  mode is active.
- Deterministic fallback behavior, if kept, is opt-in or only triggered by a
  documented degraded-mode policy.
- Safety checks for trade/order requests remain deterministic and cannot be
  bypassed by planner output.
- Tests continue to run without hosted LLM calls by using fakes, fixtures, or an
  explicitly named deterministic test planner.

