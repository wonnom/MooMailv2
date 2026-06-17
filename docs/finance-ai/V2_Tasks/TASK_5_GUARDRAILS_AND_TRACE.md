# Task 5: Guardrails And Trace

Status: complete as of 2026-06-15.

## Goal

Move guardrail review and trace into the V2 Investment Agent path.

V2 should make graph progress, subagent calls, selected/skipped tools, failures,
missing data, and guardrail outcomes visible without exposing hidden reasoning.

## Implementation Notes

Implemented modules:

- `src/moomail_finance_ai/v2_guardrails.py`
- `src/moomail_finance_ai/v2_trace.py`

The V2 Investment Agent emits:

- graph node/status events for classification, planning, IPS loading, Portfolio
  Agent call, Sentiment Agent routing/stub status, synthesis, guardrails, and
  completion
- `tool_call` trace events derived from the Portfolio Agent's planned, actual,
  skipped, and detail tool-call strings
- an `error` trace event if the LangGraph run raises

The public trace sanitizer allowlists operational metadata only and removes
hidden chain-of-thought, raw prompts, secrets, API keys, raw broker account IDs,
tokens, passwords, and scratchpad-like fields before chat or terminal output.

Deterministic V2 guardrail check names:

- `no_trading`
- `no_exact_share_count_trading`
- `unsupported_research_claims`
- `unsupported_price_or_portfolio_facts`
- `missing_ips_for_optimization`
- `missing_sentiment_visibility`

## Exit Criteria

1. Guardrail result is included in terminal and chat outputs.
2. Streamed trace shows high-level graph node progress and errors.
3. Hidden reasoning is never stored or exposed.

## Dependency Graph

```text
A. Task 1 GuardrailReview and trace/status contracts
   ├── B. Define V2 guardrail checks
   │   ├── C. Deterministic no-trading checks
   │   ├── D. Unsupported research/price fact checks
   │   ├── E. Missing IPS recommendation check
   │   └── F. Missing sentiment limitation check
   ├── G. Investment Agent guardrail node
   ├── H. Trace event collection
   │   ├── I. Terminal output integration
   │   └── J. Chat stream integration
   └── K. Tests
```

## Task Breakdown By Exit Criteria

### EC1: Guardrail result included in terminal and chat outputs

| Task | Description | Depends on | Test |
| --- | --- | --- | --- |
| A | Complete Task 1 `GuardrailReview` and status/trace contracts. | None | Done |
| B | Define V2 guardrail check names and severities. | A | Done |
| C | Implement deterministic no-trading phrase checks for final output and recommendations. | B | Done |
| C1 | Check for exact share-count/executable order style suggestions. | C | Done |
| D | Check unsupported research claims when Sentiment Agent status is missing/not implemented. | B, Task 4 | Done |
| E | Check missing IPS when output frames optimization/rebalancing as recommendation. | B | Done |
| G | Add guardrail node to Investment Agent graph after synthesis and before final output. | Task 2, B through E | Done |
| I | Add terminal rendering for guardrail summary and blocked status. | G | Done |
| J | Ensure chat response includes guardrail result in final payload. | G | Done |

### EC2: Streamed trace shows high-level progress and errors

| Task | Description | Depends on | Test |
| --- | --- | --- | --- |
| H | Define V2 trace entries for graph node start/end, subagent call, MCP tool call, skipped tool, and error. | A | Done |
| H1 | Emit graph statuses: classify, plan, portfolio, sentiment_stub, synthesize, guardrails, complete. | Task 2, H | Done |
| H2 | Include Portfolio Agent planned/actual/skipped tool summary from Task 3. | Task 3, H | Done |
| H3 | Include Sentiment Agent stub status and missing research status from Task 4. | Task 4, H | Done |
| J1 | Extend existing frontend technical trace to show V2 graph trace without breaking V1 portfolio trace. | H, J | Done |
| J2 | Preserve existing structured stream error behavior. | H | Done |

### EC3: Hidden reasoning is never stored or exposed

| Task | Description | Depends on | Test |
| --- | --- | --- | --- |
| B1 | Define trace allowlist: statuses, node names, tool names, arguments summaries, data timestamps, warnings, and errors. | A, B | Done |
| B2 | Define trace denylist: hidden chain-of-thought, raw prompts, secrets, API keys, raw broker account IDs, raw LLM scratch text. | B1 | Done |
| H4 | Add trace sanitizer before terminal/chat output. | B1, B2, H | Done |
| H5 | Ensure audit/run summaries store output summary and tool/source refs only. | H4 | Deferred; V2 audit persistence is not active yet |
| K | Add regression tests with fake hidden fields to ensure they do not appear in final trace. | H4 | Done |

## Tests To Add

- `tests/test_v2_guardrails.py`
- `tests/test_v2_trace.py`
- Updates to `tests/test_chat_app.py` for V2 stream trace if frontend is wired.

Minimum cases:

- Trade/order language is blocked.
- Missing research is reported, not hallucinated.
- Missing IPS blocks optimization/rebalancing recommendations.
- Trace includes graph statuses and tool names.
- Trace sanitizer removes hidden/sensitive fields.
- Stream error handling from V1 remains intact.

## Free Tasks

- B: Guardrail check list design.
- B1/B2: Trace allowlist/denylist design.
- C: Deterministic no-trading check can be implemented before full graph.

## Risks

- Guardrails should not become vague LLM-only reviews. Deterministic checks are
  required for no-trading and missing data.
- Trace should be useful but not verbose enough to expose prompts or private
  implementation details.
- Do not store hidden reasoning in SQL audit summaries.
