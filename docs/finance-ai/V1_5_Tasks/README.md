# V1.5 Task Notes

Status: complete as of 2026-08-05. V1.5.0 through V1.5.5 are implemented and
the deterministic release gates pass.

## Implementation Progress

Completed through 2026-08-05:

- V1.5.0 added bounded baseline/evidence contracts, strict Investment route
  contracts, deterministic direct-answer coverage validation, provider-neutral
  LLM/user-progress trace contracts, and trace grouping fields.
- Investment validation now inspects the original query, enforces
  `PortfolioRequest.source_query` integrity, and blocks rewritten-away
  trade/order intent before subagent calls.
- Investment and Portfolio structured planner normalization now rejects
  unknown-only/ambiguous payloads while accepting one recognized envelope with
  allowlisted provider metadata.
- Explicitly supplied missing OpenD env-file paths now fail clearly; omitted
  paths retain documented defaults.
- V1.5.1 added the bounded, read-only `PortfolioBaselineService`, a dedicated
  least-privilege gateway profile, deterministic 7-day/30-day trend and change
  summaries, stable evidence refs, explicit limitations, and lazy ChatService
  access without changing Investment routing.
- V1.5.2 made Investment Agent the only public web-chat entrypoint, loaded the
  bounded baseline before one structured Investment LLM turn, adopted
  `InvestmentTurnDecision` plus deterministic coverage/safety validation in the
  live graph, and added guarded one-call direct answers with strict bounded
  Portfolio fallback.
- V1.5.3 replaced the normal Portfolio evidence-planner model request with an
  exhaustive deterministic compiler, added explicit deterministic-only versus
  interpretation-required handoffs, assembled evidence before interpretation,
  and enforced one Portfolio analysis call / two total calls for detailed
  delegated runs.
- V1.5.4 added provider usage/lifecycle instrumentation, live nested Portfolio
  trace propagation, opt-in sanitized LangSmith root/node/LLM spans, stable
  run/thread correlation, and opt-in redacted diagnostic checkpoint summaries.
- V1.5.5 replaced raw status spam with ordered plain-language progress, added
  grouped expandable sanitized run details, guarded dashboard replacement,
  nonfatal observability warnings, and final golden/privacy/ownership gates.

## V1.5 Goal

Make Investment Agent the single public chat entrypoint, give it a compact
deterministic portfolio baseline before its first LLM call, and require an
explicit evidence-based decision before it delegates to Portfolio Agent.

V1.5 should reduce ordinary portfolio questions to one LLM call while preserving
deeper Portfolio Agent analysis for requests that truly need evidence outside
the baseline packet. It should also make both developer traces and user-facing
progress understandable enough to audit which agent, model, graph node, and
data lane ran.

## Target Runtime

```text
User query
  -> deterministic baseline portfolio packet (cached snapshot + compact trends)
  -> Investment Agent structured LLM turn
  -> deterministic validation of safety, source integrity, and evidence coverage
       ├── direct_context: answer from cited baseline evidence (one LLM call total)
       └── delegate_portfolio: bounded PortfolioRequest with missing-evidence reason
             -> deterministic asset resolution and evidence-plan compilation
             -> deterministic MCP/tool execution
             -> one Portfolio analysis LLM call when interpretation is needed
  -> deterministic final composition and guardrail review
  -> user progress + sanitized audit trace
```

The first Investment LLM response is both a mission decision and, on the
`direct_context` path, the user-facing answer. A direct answer is valid only when
deterministic coverage checks prove that every required evidence capability is
present and sufficiently fresh in the baseline packet.

## Confirmed Product Decisions

- Investment Agent is the only public and user-selectable chat entrypoint.
- Remove the Portfolio Agent selector from the webapp. Legacy backend aliases
  may remain temporarily, but they must resolve to Investment Agent.
- A fixed, bounded baseline context is loaded deterministically before the first
  LLM call. It may include the latest stored portfolio snapshot, allocation and
  effective-cash summaries, data freshness, and compact 7-day/30-day value,
  allocation, and position-change summaries when SQL history supports them.
- General breakdown, rough trend, and common recent-change questions should use
  `direct_context` when the requested window and evidence are present. They must
  not call Portfolio Agent merely because the subject is the user's portfolio.
- Requests requiring unsupported time windows, asset-level history, cost-basis
  inference, deeper risk metrics, anomaly investigation, current OpenD data, or
  other missing evidence must delegate to Portfolio Agent with explicit reason
  codes and a bounded `PortfolioRequest`.
- Investment Agent remains the semantic mission planner. Deterministic policy
  verifies whether the selected route is supportable; it does not infer intent
  with hidden keyword or regex routing.
- Portfolio evidence planning becomes deterministic compilation from the
  validated bounded request, resolved assets, freshness policy, and output
  goals. Portfolio Agent gets at most one LLM analysis call per delegation.
- Sentiment Agent remains a stub in V1.5. Real research retrieval is out of
  scope.
- LangSmith is the developer observability layer. MooMail's sanitized trace is
  the product/audit layer and remains available without LangSmith.
- The deterministic dashboard/status/refresh lane remains independent from
  analytical agent execution and failures.

## LLM Call Budget

| Route | Expected LLM calls | Notes |
| --- | ---: | --- |
| Unsupported or non-portfolio request | 1 | Investment structured turn; no Portfolio Agent. |
| General breakdown from fresh baseline | 1 | Investment returns a baseline-cited direct answer. |
| Rough 7-day/30-day trend covered by baseline | 1 | No Portfolio Agent or Portfolio evaluator. |
| Common recent changes covered by baseline | 1 | Direct only when history coverage is complete enough. |
| Deterministic-only Portfolio escalation | 1 | Investment decision plus deterministic Portfolio evidence; evaluator is skipped. |
| Detailed portfolio escalation | 2 | Investment decision plus one Portfolio analysis call after deterministic evidence execution. |
| Planner unavailable or invalid | 0 or 1 attempted | Fail closed; do not execute a hidden deterministic planner. |

The budget counts outbound model endpoint requests, not deterministic OpenD,
SQL, finance-metric, dashboard, validation, or guardrail calls. No automatic LLM
retry may exceed the budget without a separately traced retry policy.

## Direct-Context Coverage Rules

The Investment planner declares required evidence capabilities. Deterministic
policy compares them with the baseline packet before subagent calls.

Examples of baseline capabilities:

- `latest_snapshot`
- `allocation_breakdown`
- `effective_cash`
- `portfolio_value_trend_7d`
- `portfolio_value_trend_30d`
- `top_allocation_changes_7d`
- `top_position_changes_7d`
- `history_freshness`

Direct response is allowed only when:

1. all required capabilities are present;
2. their `as_of` timestamps satisfy the requested freshness;
3. the requested time window is covered;
4. the answer cites baseline evidence references rather than inventing values;
5. the original-query safety and `source_query` integrity checks pass; and
6. the planner supplies a bounded fallback request when deterministic coverage
   could require escalation.

If any condition fails, policy uses the planner-supplied bounded request to
delegate or returns an explicit limitation. It must not silently fabricate a
direct answer or infer a new mission.

## User-Facing Trace Direction

The current frontend exposes internal event names such as
`planning_investment`, `planned_portfolio_tool`, and
`portfolio_evidence_packet_ready` as repetitive chat bubbles. V1.5 should split
observability into two surfaces:

- Progress timeline: a small number of plain-language stages, for example
  “Reviewing your request,” “Using your saved portfolio snapshot from 3 Aug,”
  “Looking up detailed weekly changes,” “Analyzing the evidence,” and
  “Safety review complete.”
- Trace details: an expandable sanitized record with route decision, delegation
  reason, graph node, subagent, deterministic data source, LLM purpose/model,
  duration, token usage when available, actual/skipped tools, warnings, and
  errors.

Repeated planned/actual/skipped tool events should be grouped by phase and
count. Raw prompts, chain-of-thought, secrets, broker account identifiers, and
raw broker payloads must never be exposed.

## LangSmith Boundary

LangSmith tracing is opt-in by environment and intended for development,
staging, performance analysis, and evaluation. V1.5 should:

- trace the LangGraph root and node hierarchy with the MooMail `run_id` and
  conversation `thread_id`;
- manually trace the custom `urllib` LLM calls as `llm` child spans because
  they are not LangChain model wrappers;
- attach purpose, provider, model, latency, usage, route, and error metadata;
- use redaction/processors so portfolio values, holdings, IPS content, prompts,
  account identifiers, and secrets are not sent unintentionally;
- support local tests with a no-network fake trace sink; and
- keep user-visible MooMail trace behavior correct when LangSmith is disabled.

Checkpointed LangGraph state is separate from tracing. Development/diagnostic
state persistence should be opt-in, correlated by `thread_id`, and use a
documented retention/cleanup policy.

## Required V1.5 Hardening

The earlier V1.5 review findings remain required:

1. Unknown-only or empty planner payloads must fail closed after envelope
   normalization; provider metadata must not turn an empty plan into an
   executable plan through Pydantic defaults.
2. Original user query and `PortfolioRequest.source_query` integrity must be
   validated before subagent calls, including deterministic blocking of
   trade/order intent that planner output rewrites or omits.
3. Explicitly supplied missing OpenD env-file paths must fail with an actionable
   configuration error; omission may still use documented defaults.
4. Investment, Portfolio, stream, and observability failures must preserve the
   last valid deterministic dashboard while surfacing the failure in chat and
   trace.

## Scope

In scope:

- Baseline portfolio context and coverage contracts.
- One-call direct Investment path for sufficiently covered simple questions.
- Strict delegation reasons and bounded escalation requests.
- Deterministic Portfolio evidence-plan compilation.
- Conditional Portfolio analysis and enforced LLM call budgets.
- Investment-only web chat entrypoint.
- LangSmith graph/custom-LLM instrumentation and optional diagnostic state
  checkpointing.
- MooMail trace propagation, sanitization, user progress summaries, and detailed
  trace rendering.
- Existing V1.5 safety, planner normalization, dashboard preservation, and
  explicit OpenD config follow-ups.
- Golden-route, call-count, trace, privacy, failure, and regression tests.

Out of scope:

- Real Sentiment Agent retrieval or GraphRAG.
- Pinecone memory.
- Trade placement, order preparation, or exact-share execution guidance.
- LLM-calculated portfolio math.
- Sending unredacted portfolio/account data to LangSmith.
- Replacing the deterministic dashboard lane with an agent.
- A general frontend redesign unrelated to agent selection, progress, trace, or
  dashboard failure preservation.

## Task Files

| Task | Status | File | Purpose |
| --- | --- | --- | --- |
| V1.5.0 | complete as of 2026-08-03 | [TASK_0_ROUTING_OBSERVABILITY_CONTRACTS.md](TASK_0_ROUTING_OBSERVABILITY_CONTRACTS.md) | Define baseline coverage, strict route, call telemetry, user progress, safety-integrity, and fail-closed contracts. |
| V1.5.1 | complete as of 2026-08-03 | [TASK_1_BASELINE_PORTFOLIO_CONTEXT.md](TASK_1_BASELINE_PORTFOLIO_CONTEXT.md) | Build the deterministic baseline packet for current snapshot, allocation, cash, compact trends, changes, and freshness. |
| V1.5.2 | complete as of 2026-08-03 | [TASK_2_INVESTMENT_DEFAULT_AND_STRICT_ROUTING.md](TASK_2_INVESTMENT_DEFAULT_AND_STRICT_ROUTING.md) | Make Investment Agent the only web entrypoint and implement evidence-covered one-call direct routing with strict escalation. |
| V1.5.3 | complete as of 2026-08-05 | [TASK_3_PORTFOLIO_ESCALATION_AND_CALL_BUDGET.md](TASK_3_PORTFOLIO_ESCALATION_AND_CALL_BUDGET.md) | Compile Portfolio evidence plans deterministically and limit delegated runs to one Portfolio analysis LLM call. |
| V1.5.4 | complete as of 2026-08-05 | [TASK_4_LANGSMITH_AND_MOOMAIL_TRACE.md](TASK_4_LANGSMITH_AND_MOOMAIL_TRACE.md) | Add opt-in LangSmith spans, graph/run correlation, optional checkpointing, and complete sanitized MooMail trace propagation. |
| V1.5.5 | complete as of 2026-08-05 | [TASK_5_FRONTEND_TRACE_EVALUATION_AND_CLOSEOUT.md](TASK_5_FRONTEND_TRACE_EVALUATION_AND_CLOSEOUT.md) | Replace raw status spam with useful progress/detail views, preserve dashboards on failure, evaluate call budgets, update docs, and close V1.5. |

## Cross-Task Dependency Map

```text
V1.5.0. Routing, observability, and safety contracts [complete]
  ├── V1.5.1. Deterministic baseline portfolio context [complete]
  │   └── V1.5.2. Investment default and strict evidence routing [complete]
  │       └── V1.5.3. Portfolio escalation and LLM call budget [complete]
  ├── V1.5.4. LangSmith and MooMail trace instrumentation [complete]
  │       depends on route/telemetry contracts and instruments V1.5.2/V1.5.3
  └── V1.5.5. Frontend trace, evaluations, docs, and closeout [complete]
          depends on V1.5.1 through V1.5.4
```

## Release Gate

V1.5 is complete only when:

- the webapp has no Portfolio Agent selector and every chat enters Investment
  Agent;
- golden general-breakdown, 7-day/30-day trend, and covered recent-change
  prompts make exactly one outbound LLM call;
- missing or stale baseline evidence causes a traced, reasoned Portfolio
  escalation rather than an unsupported direct answer;
- a delegated portfolio run makes no more than two total LLM calls under the
  normal policy;
- every LLM call is visible in the sanitized MooMail trace and, when enabled,
  as a correlated LangSmith child span;
- the user timeline contains grouped plain-language progress rather than raw
  snake_case status spam;
- trace privacy tests prove prompts, secrets, raw account ids, and raw broker
  payloads are absent;
- original-query safety, planner fail-closed behavior, explicit OpenD config
  errors, and dashboard preservation tests pass; and
- the full non-live deterministic suite and documentation gates pass.

This gate was met on 2026-08-05: all targeted commands passed, the full
non-live suite passed with 375 tests, the interactive local browser check
confirmed ordered progress and expandable detail, and the whitespace gate
passed.

## Risks And Guardrails

- Supplying more baseline data can increase prompt size. Keep the packet compact,
  typed, capped, and evidence-referenced.
- “Simple” is not a keyword classification. The LLM declares evidence needs and
  deterministic coverage policy validates them.
- One-call direct answers can hide stale data unless `as_of`, history coverage,
  and freshness limitations are visible in both answer and trace.
- LangSmith improves debugging but is not the system of record for user-facing
  audit. MooMail trace contracts and tests remain mandatory.
- Checkpointed states contain sensitive financial context. Diagnostic
  checkpointing must be opt-in with explicit storage and retention policy.
