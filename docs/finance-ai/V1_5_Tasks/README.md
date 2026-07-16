# V1.5 Task Notes

Status: planning placeholder.

## Problem

V1.4 introduces typed planner contracts, a deterministic Investment planner, and
a deterministic Portfolio evidence planner, but the current runtime boundary is
still ambiguous: deterministic planning is described as fallback/offline support
while also being wired into default or bounded runtime paths.

That creates product and maintenance risk:

- The webapp can silently use regex/keyword routing as normal behavior.
- Bounded Portfolio evidence planning can inherit fallback behavior unless
  planner provenance is explicit.
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

## Confirmed Product Decisions

The following decisions are fixed for the V1.5 implementation:

- Investment Agent is the only user-selectable and user-facing agent entrypoint.
- Remove the Portfolio Agent selection from the webapp. Users should not choose
  which analytical agent receives a request.
- Route every chat request through Investment Agent. Investment Agent owns
  mission planning and decides whether to call Portfolio Agent or Sentiment
  Agent internally.
- Keep Portfolio Agent as an internal bounded evidence subagent. It must not be
  exposed as a parallel public chat mode.
- Legacy backend agent-name aliases may remain temporarily for compatibility,
  but they must resolve to Investment Agent and must not reintroduce a frontend
  routing choice.
- Keep the deterministic portfolio dashboard lane independent from analytical
  agent execution and failures.

## Review Follow-Ups For V1.5

The 2026-07-16 planner/dashboard and main-branch comparison identified four
required follow-ups:

1. Structured planner normalization must remain fail-closed. If envelope
   unwrapping and schema-field filtering leave no planner-controlled fields, the
   response must be rejected as unavailable rather than allowing Pydantic
   defaults to create an executable Portfolio evidence plan. Envelope handling
   should also define behavior when a recognized plan envelope is accompanied
   by provider metadata.
2. Dashboard preservation must cover failures below the Investment planner.
   In particular, `portfolio_evidence_planner_unavailable` and other terminal
   agent/subagent planning failures must remain in chat/trace and must not
   replace the last valid dashboard with a degraded final report.
3. Deterministic safety validation must inspect the original user query, not
   only the LLM-produced `InvestmentPlan`. The validator must enforce
   `PortfolioRequest.source_query` integrity and block trade/order intent even
   when planner output rewrites or omits the original request.
4. Explicit OpenD configuration paths must fail clearly when missing. Omitting
   an optional env file may use documented defaults, but a caller-provided typo
   or deleted path must not silently select the default host or account index.

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
- Original-query and source-query integrity checks run before subagent calls so
  an LLM cannot rewrite away blocked trade/order intent.
- Tests continue to run without hosted LLM calls by using fakes, fixtures, or an
  explicitly named deterministic test planner.
- The frontend exposes no Portfolio Agent selector; all chat submissions enter
  through Investment Agent.
- Portfolio Agent remains callable only as an Investment Agent-managed bounded
  subagent in the normal webapp flow.
- Invalid or unknown-only structured planner payloads fail closed and cannot
  become executable plans through model defaults.
- Investment planner, Portfolio evidence planner, and stream failures preserve
  the last valid deterministic dashboard while surfacing errors in chat/trace.
- Explicitly supplied missing OpenD env-file paths fail with an actionable
  configuration error instead of silently using default connection settings.
