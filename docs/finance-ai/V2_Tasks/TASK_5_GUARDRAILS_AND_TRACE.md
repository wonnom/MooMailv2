# Task 5: Guardrails And Trace

## Goal

Move guardrail review and trace into the V2 Investment Agent path.

V2 should make graph progress, subagent calls, selected/skipped tools, failures,
missing data, and guardrail outcomes visible without exposing hidden reasoning.

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
| A | Complete Task 1 `GuardrailReview` and status/trace contracts. | None | Covered by Task 1 |
| B | Define V2 guardrail check names and severities. | A | `test_v2_guardrail_check_names_are_stable` |
| C | Implement deterministic no-trading phrase checks for final output and recommendations. | B | `test_guardrail_blocks_order_instruction` |
| C1 | Check for exact share-count/executable order style suggestions. | C | Exact share count recommendation test |
| D | Check unsupported research claims when Sentiment Agent status is missing/not implemented. | B, Task 4 | `test_guardrail_flags_research_claim_without_sentiment` |
| E | Check missing IPS when output frames optimization/rebalancing as recommendation. | B | Missing IPS recommendation test |
| G | Add guardrail node to Investment Agent graph after synthesis and before final output. | Task 2, B through E | `test_v2_graph_runs_guardrail_before_final` |
| I | Add terminal rendering for guardrail summary and blocked status. | G | CLI output smoke |
| J | Ensure chat response includes guardrail result in final payload. | G | Chat response shape test |

### EC2: Streamed trace shows high-level progress and errors

| Task | Description | Depends on | Test |
| --- | --- | --- | --- |
| H | Define V2 trace entries for graph node start/end, subagent call, MCP tool call, skipped tool, and error. | A | Trace schema test |
| H1 | Emit graph statuses: classify, plan, portfolio, sentiment_stub, synthesize, guardrails, complete. | Task 2, H | Stream contains expected statuses |
| H2 | Include Portfolio Agent planned/actual/skipped tool summary from Task 3. | Task 3, H | Trace includes planned vs actual tools |
| H3 | Include Sentiment Agent stub status and missing research status from Task 4. | Task 4, H | Trace includes sentiment status |
| J1 | Extend existing frontend technical trace to show V2 graph trace without breaking V1 portfolio trace. | H, J | Static frontend test |
| J2 | Preserve existing structured stream error behavior. | H | Existing chat error tests still pass |

### EC3: Hidden reasoning is never stored or exposed

| Task | Description | Depends on | Test |
| --- | --- | --- | --- |
| B1 | Define trace allowlist: statuses, node names, tool names, arguments summaries, data timestamps, warnings, and errors. | A, B | Trace allowlist test |
| B2 | Define trace denylist: hidden chain-of-thought, raw prompts, secrets, API keys, raw broker account IDs, raw LLM scratch text. | B1 | Redaction test |
| H4 | Add trace sanitizer before terminal/chat output. | B1, B2, H | `test_trace_sanitizer_removes_sensitive_fields` |
| H5 | Ensure audit/run summaries store output summary and tool/source refs only. | H4 | SQL/audit shape test |
| K | Add regression tests with fake hidden fields to ensure they do not appear in final trace. | H4 | Hidden field regression test |

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
