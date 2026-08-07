# Task V1.5.0: Routing And Observability Contracts

## Goal

Define the typed contracts and validators required for one-call Investment
answers, strict Portfolio delegation, LLM call accounting, and useful
user/developer traces.

This task is additive contract and safety work. It must not switch runtime
routing or add LangSmith network calls yet; later V1.5 tasks adopt the contracts.

## Status

Complete as of 2026-08-03.

## Implemented In

- `src/moomail_finance_ai/agent_schemas.py`
  - Added bounded `EvidenceRef`, `BaselineSummary`, and
    `PortfolioBaselinePacket` contracts with capability, row, reference, and
    serialized-size limits.
  - Added `InvestmentTurnDecision` direct/delegate route invariants, allowlisted
    route reasons, required/missing evidence, cited refs, and bounded fallback
    request fields.
  - Added provider-neutral `LLMCallTrace` and `UserProgressEvent` contracts and
    optional trace grouping/child-run fields.
- `src/moomail_finance_ai/investment_routing.py`
  - Added deterministic direct-answer coverage validation for capability,
    evidence-ref, quality/freshness, requested-window, and fallback-request
    checks.
- `src/moomail_finance_ai/investment_planner.py` and
  `src/moomail_finance_ai/investment_agent.py`
  - Planner and pre-subagent validation now inspect the original user query,
    enforce normalized `PortfolioRequest.source_query` integrity, and block a
    planner from rewriting away trade/order intent.
  - Investment structured output now accepts one recognized envelope with
    allowlisted provider metadata and rejects unknown-only/ambiguous payloads.
- `src/moomail_finance_ai/portfolio_evidence_planner.py`
  - Structured plan normalization rejects empty/unknown-only output, accepts
    one recognized envelope with provider metadata, and rejects ambiguous
    multiple envelopes.
- `src/moomail_finance_ai/config.py`
  - An explicitly supplied missing OpenD env-file path now raises an actionable
    `FileNotFoundError`; omission still uses documented defaults.
- `src/moomail_finance_ai/agent_trace.py`
  - Added allowlisted route, evidence coverage, LLM call, token, duration, and
    grouping metadata while denying raw broker payload/account fields.
- Tests and fixtures
  - Added covered/stale baseline, direct/delegated route, rewritten-source, and
    unknown-only planner fixtures plus schema, coverage, safety, normalization,
    configuration, and trace tests.

## Scope And Boundaries

Owns:

- Baseline portfolio capability and evidence-reference schemas.
- Investment direct/delegate route decision and reason codes.
- Direct-answer evidence coverage validation.
- LLM call telemetry and user progress event schemas.
- Original-query/`source_query` integrity enforcement.
- Empty/unknown-only structured planner rejection.
- Explicit missing OpenD env-file error semantics.

Does not own:

- Baseline SQL/dashboard reads; V1.5.1 owns them.
- Investment graph adoption; V1.5.2 owns it.
- Portfolio execution changes; V1.5.3 owns them.
- LangSmith or frontend rendering; V1.5.4/V1.5.5 own them.

## Exit Criteria

1. Typed contracts represent baseline evidence capabilities, coverage, freshness,
   evidence references, and limitations without embedding raw broker payloads.
2. Investment output explicitly selects `direct_context`,
   `delegate_portfolio`, `delegate_sentiment`, `delegate_both`, or `unsupported`
   and supplies structured route/delegation reasons.
3. Direct answers are rejected unless deterministic policy proves complete,
   fresh, window-compatible evidence coverage and valid evidence references.
4. LLM calls and user progress have separate sanitized contracts suitable for
   MooMail trace and optional external observability.
5. Original-query trade/order intent and `PortfolioRequest.source_query`
   integrity are validated before any subagent call.
6. Empty/unknown-only planner payloads and ambiguous envelopes fail closed, and
   explicitly supplied missing OpenD env-file paths fail clearly.

## Dependency Graph

```text
V1.4 planner/evidence/trace contracts
  ├── A. Baseline capability and evidence-reference contracts
  │   ├── B. Investment route decision contract
  │   └── C. Deterministic evidence-coverage validator
  ├── D. LLM call telemetry contract
  ├── E. User progress event contract
  ├── F. Original-query and source-query integrity validator
  ├── G. Fail-closed planner normalization
  └── H. Explicit OpenD env-file validation
          └── I. Fixtures and schema/safety tests
```

## Task Breakdown By Exit Criteria

### EC1: Baseline evidence is typed and bounded

| Task | Description | Depends on | Test |
| --- | --- | --- | --- |
| A | Add a capability literal for latest snapshot, allocation, effective cash, 7-day/30-day value trends, recent allocation/position changes, and history freshness. | V1.4 contracts | `test_baseline_capability_accepts_expected_values` |
| A1 | Add `EvidenceRef` with source, field/path, `as_of`, period/window, and quality/limitation fields; prohibit secrets and raw payload fields. | A | `test_baseline_evidence_ref_is_bounded_and_sanitized` |
| A2 | Add `PortfolioBaselinePacket` with portfolio scope, capability coverage, compact values/summaries, warnings, and evidence references. | A, A1 | `test_portfolio_baseline_packet_round_trips` |
| A3 | Add explicit caps for holdings/change rows and serialized packet size. | A2 | `test_baseline_packet_enforces_size_and_row_caps` |

### EC2: Route and delegation decisions are explicit

| Task | Description | Depends on | Test |
| --- | --- | --- | --- |
| B | Extend or replace the Investment planner result with a typed route decision and allowlisted reason codes. | A | `test_investment_turn_decision_requires_route_reason` |
| B1 | Add required-evidence capabilities, cited baseline refs, missing-evidence declarations, optional direct answer, and bounded fallback `PortfolioRequest`. | B, A1 | `test_direct_route_carries_evidence_refs_and_fallback_request` |
| B2 | Require direct routes to omit subagent calls; require delegate routes to include the corresponding bounded task. | B1 | `test_route_contract_keeps_direct_and_delegate_fields_consistent` |

### EC3: Direct answers pass deterministic coverage policy

| Task | Description | Depends on | Test |
| --- | --- | --- | --- |
| C | Add a validator that compares required capabilities with baseline coverage before graph routing. | A2, B1 | `test_direct_route_requires_complete_baseline_coverage` |
| C1 | Enforce requested-window and freshness compatibility, including `as_of` and history coverage. | C | `test_direct_route_rejects_stale_or_short_window_evidence` |
| C2 | Validate every factual direct-answer reference against the packet and reject invented/unknown refs. | C, A1 | `test_direct_answer_rejects_unknown_evidence_reference` |
| C3 | When direct coverage fails, allow only the planner-supplied bounded fallback request; otherwise fail with an explicit limitation. | C1, C2, B1 | `test_missing_coverage_uses_only_bounded_fallback_request` |

### EC4: Observability contracts separate audit from presentation

| Task | Description | Depends on | Test |
| --- | --- | --- | --- |
| D | Add `LLMCallTrace` fields for purpose, provider, model, subagent, start/end or duration, usage, status, retry index, and error category. | None | `test_llm_call_trace_captures_safe_call_metadata` |
| D1 | Prohibit prompt text, authorization data, chain-of-thought, raw portfolio payloads, and account ids in public LLM metadata. | D | `test_llm_call_trace_rejects_sensitive_metadata` |
| E | Add a small user-progress stage vocabulary independent from internal trace statuses. | None | `test_user_progress_event_accepts_plain_language_stages` |
| E1 | Preserve internal `TraceEvent` detail while defining grouping keys for repeated planned/actual/skipped tools. | D, E | `test_trace_event_supports_grouping_without_losing_detail` |

### EC5: Original request safety cannot be rewritten away

| Task | Description | Depends on | Test |
| --- | --- | --- | --- |
| F | Change Investment plan validation to receive the original user query. | V1.4 validator | `test_investment_validation_inspects_original_user_query` |
| F1 | Require exact normalized integrity between original query and `PortfolioRequest.source_query`, or an explicit lossless source representation. | F | `test_portfolio_request_source_query_must_match_original` |
| F2 | Block trade/order intent found in either original query or planner output before subagent/tool calls. | F, F1 | `test_planner_cannot_rewrite_away_trade_order_intent` |

### EC6: Planner and configuration failures are explicit

| Task | Description | Depends on | Test |
| --- | --- | --- | --- |
| G | Reject planner payloads when envelope normalization and schema filtering leave no planner-controlled fields. | Existing structured planners | `test_unknown_only_planner_payload_fails_closed` |
| G1 | Define accepted recognized-envelope plus provider-metadata behavior and reject ambiguous multi-plan envelopes. | G | `test_planner_envelope_with_provider_metadata_is_unambiguous` |
| H | Distinguish omitted optional OpenD env files from explicitly supplied paths. | Existing config loader | `test_explicit_missing_opend_env_file_raises_actionable_error` |
| H1 | Preserve documented defaults only when no explicit path was supplied. | H | `test_omitted_opend_env_file_uses_documented_defaults` |
| I | Add JSON fixtures for covered direct route, delegated route, stale baseline, rewritten source query, and unknown-only payload. | A through H | `test_v1_5_contract_fixtures_validate` |

## Tests To Add Or Update

- `tests/test_agent_schemas.py`
- `tests/test_investment_planner.py`
- `tests/test_portfolio_planner.py`
- `tests/test_opend_config.py`
- `tests/test_agent_trace.py`
- `tests/fixtures/agent/v1_5_*.json`

## Required Test Commands

```bash
.venv/bin/python -m pytest tests/test_agent_schemas.py tests/test_agent_trace.py -q
.venv/bin/python -m pytest tests/test_investment_planner.py tests/test_portfolio_planner.py -q
.venv/bin/python -m pytest tests/test_opend_config.py -q
git diff --check
```

## Verification

Run on 2026-08-03:

```text
.venv/bin/python -m pytest tests/test_agent_schemas.py tests/test_agent_trace.py -q
74 passed, 1 warning

.venv/bin/python -m pytest tests/test_investment_planner.py tests/test_portfolio_planner.py -q
63 passed

.venv/bin/python -m pytest tests/test_opend_config.py -q
6 passed

.venv/bin/python -m pytest tests/test_investment_agent.py tests/test_chat_app.py tests/test_asset_resolver.py -q
36 passed, 1 warning

.venv/bin/python -m pytest tests --ignore=tests/live -q
281 passed, 1 warning

git diff --check
passed
```

The warning is the existing LangGraph dependency deprecation warning.

Not run:

- `tests/live`: V1.5.0 is deterministic contract/safety work and does not
  require live OpenD or hosted LLM calls.
- Ruff: the repository virtual environment does not contain a Ruff executable.

## Remaining

No remaining V1.5.0 exit criteria. V1.5.1 must build real baseline packets from
the deterministic dashboard/SQL lane; V1.5.2 later adopts
`InvestmentTurnDecision` and coverage validation for live graph routing;
V1.5.4 later instruments actual LLM calls and user progress events.

## Notes And Risks

- Avoid using the word “simple” as executable policy. Route eligibility must be
  expressed as evidence capabilities, freshness, and coverage.
- Keep new runtime names version-neutral.
- Do not add LangSmith-specific fields to domain schemas when a provider-neutral
  telemetry contract is sufficient.
- Planner normalization must not let Pydantic defaults manufacture an executable
  plan from provider commentary.
- Grounding used the execute-iteration skill's
  `references/finance-ai-grounding.md`, this task, the sibling README, the
  routed architecture/agent/requirements/protocol/testing/decision docs, the
  relevant V1.4 contract task, and directly affected modules/tests.
