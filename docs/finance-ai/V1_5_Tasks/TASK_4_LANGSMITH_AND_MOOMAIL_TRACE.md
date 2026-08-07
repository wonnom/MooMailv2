# Task V1.5.4: LangSmith And MooMail Trace Instrumentation

## Goal

Provide complete, correlated observability for LangGraph nodes, custom LLM HTTP
calls, subagents, deterministic tools, route decisions, and failures while
keeping MooMail's sanitized trace independent from optional LangSmith tracing.

LangSmith is for developer diagnosis and evaluation. MooMail trace remains the
product-facing audit surface and source for frontend progress/detail rendering.

## Status

Complete as of 2026-08-05.

## Scope And Boundaries

Owns:

- Provider-neutral LLM instrumentation around the custom `urllib` clients.
- Opt-in LangSmith graph and child-span integration.
- `run_id`/`thread_id`/subagent/call-purpose correlation.
- Forwarding Portfolio Agent statuses into Investment Agent trace/stream.
- Optional diagnostic LangGraph checkpointing and retention policy.
- Redaction, sampling/enablement, no-network tests, and failure isolation.

Does not own:

- User progress wording/layout; V1.5.5 owns presentation.
- Route policy or call budgets; V1.5.2/V1.5.3 own behavior.
- Unredacted financial telemetry.
- Making LangSmith required for the chat runtime.

## Exit Criteria

1. Every outbound LLM call emits MooMail start/completed/failed events with
   purpose, provider, model, duration, usage when available, attempt, and status.
2. Portfolio planning/execution/evaluation statuses are forwarded live and
   nested under the Investment run without losing their Portfolio run id.
3. When enabled, LangSmith displays the graph root/nodes and custom LLM calls as
   correlated child spans; when disabled/unavailable, chat behavior is unchanged.
4. Trace processors prevent prompts, secrets, account ids, raw broker payloads,
   and unapproved portfolio/IPS values from leaving the process.
5. Optional diagnostic checkpointing supports thread-correlated state inspection
   with documented storage, retention, cleanup, and production defaults.
6. Observability failures never fail an agent run or alter dashboard state.

## Dependency Graph

```text
V1.5.0 trace/telemetry contracts
  ├── A. Provider-neutral LLM instrumentation
  │   ├── B. Capture provider usage and timing
  │   └── C. Emit sanitized MooMail LLM events
  ├── D. Forward/nest Portfolio status events
  ├── E. Correlate run_id and thread_id through LangGraph config
  │   ├── F. Opt-in LangSmith graph tracing
  │   ├── G. Manual custom-LLM child spans
  │   └── H. Optional diagnostic checkpointer
  ├── I. Redaction and privacy policy
  └── J. No-network, failure-isolation, and trace-shape tests

V1.5.2/V1.5.3 route and call-budget events are instrumented as they land.
```

## Task Breakdown By Exit Criteria

### EC1: All LLM calls are visible in MooMail trace

| Task | Description | Depends on | Test |
| --- | --- | --- | --- |
| A | Add one instrumentation boundary around `TextLLMClient.generate_text` calls that accepts purpose, run context, and safe metadata. | V1.5.0 | `test_llm_instrumentation_wraps_every_generate_text_call` |
| A1 | Name purposes `investment_planning`, `portfolio_analysis`, and any retained compatibility purpose explicitly. | A | `test_llm_trace_uses_allowlisted_call_purposes` |
| B | Return or extract provider response usage metadata without exposing raw responses; retain compatibility for providers that omit usage. | A | `test_llm_result_captures_usage_when_available` |
| B1 | Record monotonic duration and attempt index for success/failure. | A | `test_llm_trace_records_duration_and_attempt` |
| C | Emit `llm_call_started`, `llm_call_completed`, and `llm_call_failed` through sanitized MooMail trace. | A, B | `test_moomail_trace_emits_llm_call_lifecycle` |
| C1 | Ensure client construction alone emits no call event. | C | `test_llm_client_construction_is_not_counted_as_call` |

### EC2: Nested Portfolio activity is propagated live

| Task | Description | Depends on | Test |
| --- | --- | --- | --- |
| D | Forward a Portfolio status callback from Investment Agent into `PortfolioAgent.run()`. | Existing stream path | `test_investment_agent_forwards_portfolio_status_callback` |
| D1 | Adapt Portfolio `StatusEvent` into nested sanitized `TraceEvent` with parent Investment run id and child Portfolio run id metadata. | D | `test_portfolio_events_are_nested_under_investment_run` |
| D2 | Preserve evidence compilation, actual/skipped tool execution, evaluator lifecycle, warning, and error events. | D1, V1.5.3 | `test_nested_portfolio_trace_contains_all_execution_phases` |
| D3 | Stream events once; prevent duplicate re-emission when final result events are adapted. | D2 | `test_portfolio_trace_events_are_not_duplicated` |

### EC3: LangSmith tracing is opt-in and correlated

| Task | Description | Depends on | Test |
| --- | --- | --- | --- |
| E | Pass stable `run_name`, `run_id`, `thread_id`, route, app version, and environment tags through graph invocation config. | V1.5.2 | `test_langgraph_invocation_has_trace_correlation_config` |
| F | Add documented opt-in LangSmith configuration/project selection and make `langsmith` an explicit dependency if imported directly. | E | `test_langsmith_is_disabled_without_explicit_config` |
| F1 | Ensure the compiled Investment graph appears as a root with named node spans when a fake tracer is enabled. | F | `test_langsmith_graph_trace_contains_named_nodes` |
| G | Manually instrument custom `urllib` model calls as `run_type="llm"` children with provider/model/purpose metadata. | A, F | `test_custom_llm_span_is_child_of_active_graph_run` |
| G1 | Attach token/cost metadata only when provided or deterministically configured; do not invent usage. | G, B | `test_langsmith_span_does_not_invent_missing_usage` |

### EC4: Trace data is private by construction

| Task | Description | Depends on | Test |
| --- | --- | --- | --- |
| I | Add input/output/metadata processors or anonymizers for LangSmith and reuse MooMail sanitization rules where appropriate. | F, G | `test_langsmith_processors_redact_financial_and_secret_fields` |
| I1 | Deny raw prompts, API keys, auth headers, account ids, raw broker payloads, chain-of-thought, and unrestricted IPS/snapshot dumps. | I | `test_external_trace_contains_no_denied_fields` |
| I2 | Define an explicit safe allowlist: run/thread ids, route/reasons, capability names, counts, provider/model, duration, usage, tool names, status, and errors. | I | `test_external_trace_metadata_is_allowlisted` |
| I3 | Document dev/staging default, production opt-in/sampling, region/retention review, and incident disable switch. | I | Docs review |

### EC5: Diagnostic state inspection is optional and controlled

| Task | Description | Depends on | Test |
| --- | --- | --- | --- |
| H | Add an opt-in LangGraph checkpointer for development/diagnostics and invoke the graph with stable `thread_id`. | E | `test_diagnostic_checkpointer_persists_node_state_by_thread` |
| H1 | Keep production default off unless an explicit storage and retention configuration exists. | H | `test_checkpointing_is_opt_in` |
| H2 | Document checkpoint location, encryption expectation, retention, cleanup, and difference from LangSmith tracing. | H | Docs review |
| H3 | Provide a safe state summary/redaction path for inspection rather than relying on raw broker payload state. | H, I | `test_checkpoint_state_excludes_raw_sensitive_payloads` |

### EC6: Observability cannot break the product

| Task | Description | Depends on | Test |
| --- | --- | --- | --- |
| J | Add a fake/no-network trace sink for deterministic tests. | A through I | `test_observability_tests_make_no_network_calls` |
| J1 | Swallow/report LangSmith export failures without failing the graph, subagent, final answer, or dashboard. | F | `test_langsmith_export_failure_does_not_fail_chat` |
| J2 | Prove MooMail trace remains complete when LangSmith is disabled. | C, D, F | `test_moomail_trace_is_independent_from_langsmith` |
| J3 | Prove tracing/checkpoint failure does not mutate the last valid dashboard. | H, J1 | `test_observability_failure_preserves_dashboard` |

## Tests To Add Or Update

- new `tests/test_llm_observability.py`
- `tests/test_llm.py`
- `tests/test_agent_trace.py`
- `tests/test_investment_agent.py`
- `tests/test_portfolio_agent.py`
- `tests/test_chat_app.py`
- optional checkpointer-specific tests

## Required Test Commands

```bash
.venv/bin/python -m pytest tests/test_llm.py tests/test_llm_observability.py -q
.venv/bin/python -m pytest tests/test_agent_trace.py tests/test_investment_agent.py tests/test_portfolio_agent.py -q
.venv/bin/python -m pytest tests/test_chat_app.py -q
git diff --check
```

## Implemented In

- `src/moomail_finance_ai/observability.py` now owns explicit observability
  configuration, external-trace allowlisting, opt-in LangSmith root/node/custom
  LLM spans, a no-network in-memory sink, graph correlation config, and bounded
  diagnostic checkpoint summaries.
- `src/moomail_finance_ai/llm.py` returns provider usage when Gemini/OpenAI
  supplies it while preserving the text-only client API. Investment planning,
  Portfolio analysis, and the isolated compatibility planner all use one
  observed generation boundary.
- `InvestmentAgent` passes stable `run_id`/`thread_id` config to LangGraph,
  emits every LLM start/completed/failed event into MooMail trace, and forwards
  live Portfolio statuses with the Portfolio child run id. `PortfolioAgent`
  emits planned/actual/skipped tool activity when it occurs instead of relying
  on final-result replay.
- Diagnostic checkpointing is disabled by default. When explicitly enabled it
  uses LangGraph's in-memory checkpointer during execution, retains only safe
  thread-correlated summaries for inspection, and purges raw transient entries
  at run completion.
- `langsmith` is now an explicit runtime dependency because the opt-in sink
  imports its tracing API directly.

## Verification

Run on 2026-08-05:

```text
tests/test_llm.py tests/test_llm_observability.py: 15 passed, 1 warning
tests/test_agent_trace.py tests/test_investment_agent.py tests/test_portfolio_agent.py: 61 passed, 1 warning
tests/test_chat_app.py: 15 passed, 1 warning
tests --ignore=tests/live: 369 passed, 1 warning
py_compile (V1.5.4 touched runtime modules): passed
git diff --check: passed
```

The warning is the existing LangGraph serializer deprecation warning. Hosted
LangSmith, hosted model, and live OpenD tests were not run because this gate
uses fake providers and a no-network trace sink. V1.5.5 still owns frontend
progress/detail presentation and final route/UX evaluation.

## Notes And Risks

- Automatic LangSmith environment tracing is intentionally not used because it
  could receive raw graph state. Explicit MooMail enablement creates sanitized
  manual root, node, and custom-LLM spans instead.
- Do not store raw prompts merely to make debugging convenient.
- LangSmith is not a compliance archive or a replacement for local audit
  records.
- `langsmith` is pinned explicitly rather than relying on LangGraph's transitive
  dependency.
