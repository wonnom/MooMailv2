# Task 3: Convert Portfolio Agent To Bounded Planning Path

Status: complete as of 2026-06-13.

## Goal

Refactor the current deterministic `MCPPortfolioAgent.run()` workflow into a
bounded-planning Portfolio Agent path.

The key change is not "make it fully autonomous." The key change is:

```text
portfolio task -> structured context plan -> deterministic tool execution
```

V1.1 broad-review behavior must remain available as the safe default.

Implemented shape:

- `interpret_portfolio_task(query)` maps direct Portfolio Agent queries into a
  bounded `PortfolioTask`.
- `plan_portfolio_context(task)` maps that task into a schema-validated
  `PortfolioContextPlan`.
- `MCPPortfolioAgent.run(..., portfolio_task=...)` can now accept the
  Investment Agent's planned task or interpret a direct query itself.
- Full review and deep-dive tasks preserve broad V1.1 context: OpenD snapshot,
  deterministic metrics, SQL history status, latest state, growth history,
  allocation history, and persistence.
- Narrow portfolio-fact tasks such as cash-weight/effective-cash questions use
  current OpenD plus selected metrics and skip broad SQL history/persistence by
  default.
- `PortfolioAgentResult.tool_calls` now includes planned, actual, and skipped
  tool entries. The V1.2 portfolio packet also carries this trace.

Reality note: this is implemented inside the existing Python Portfolio Agent,
not as a separate compiled LangGraph subgraph.

## Exit Criteria

1. A cash-weight query can avoid unnecessary broad history reads.
2. A "what changed" query can request portfolio growth/allocation history.
3. A full review can preserve the existing V1.1 broad context behavior.
4. Tool calls are visible in trace output.

## Dependency Graph

```text
A. Task 1 PortfolioTask and PortfolioContextPlan
   ├── B. Split current MCPPortfolioAgent.run into reusable tool-execution steps
   │   ├── C. Build deterministic portfolio task interpreter
   │   │   └── D. Build bounded context planner
   │   ├── E. Current snapshot node
   │   ├── F. SQL write/persistence node
   │   ├── G. SQL history read node
   │   ├── H. Metrics node
   │   ├── I. Portfolio packet assembly node
   │   └── J. Portfolio evaluator node
   ├── K. Trace/tool-call summary
   └── L. Tests
```

## Task Breakdown By Exit Criteria

### EC1: Cash-weight query avoids unnecessary broad history reads

| Task | Description | Depends on | Test |
| --- | --- | --- | --- |
| A | Complete Task 1 portfolio contracts. | None | Covered by Task 1 |
| B | Extract current V1.1 operations into smaller functions/nodes without changing behavior: initialize SQL, OpenD context, metrics, writes, reads, evaluator. | A | Existing `tests/test_portfolio_agent.py` still pass |
| C | Implement deterministic `interpret_portfolio_task(query)` or adapter from Investment Agent `PortfolioTask`. | A, B | `test_portfolio_task_interpreter_cash_weight` |
| D | Implement `plan_portfolio_context(task)` returning `PortfolioContextPlan`. | C | `test_cash_weight_plan_minimal_context` |
| D1 | Cash/current allocation facts should set `needs_current_snapshot=true`, `needs_sql_history=false`, metric groups limited to needed groups. | D | Assert no growth/allocation history queries |
| E | Execute OpenD current snapshot only when plan says current snapshot is needed. | D | Fake OpenD call count |
| G | Skip SQL broad history reads when `needs_sql_history=false`. | D, B | Fake SQL history call count zero |
| H | Calculate only required metric groups where supported; until granular metric tools exist, call snapshot metrics but record that broad metrics were used. | D, B | Metric call trace records selected groups |

### EC2: "What changed" query requests history

| Task | Description | Depends on | Test |
| --- | --- | --- | --- |
| D2 | History/change queries should set `needs_sql_history=true`. | D | `test_what_changed_plan_requests_history` |
| D3 | Plan should request `portfolio_growth` and `allocation_history`; optionally `latest_state`. | D2 | Assert history query list |
| G1 | SQL history node maps requested history queries to MCP tools. | D3 | Fake SQL calls expected tools |
| G2 | History read limits should be plan-controlled, for example 30 days or task-specified limit. | D3 | Limit propagated test |
| I1 | Portfolio packet includes history context relevant to the plan. | G1 | Packet includes growth/allocation rows |

### EC3: Full review preserves V1.1 broad behavior

| Task | Description | Depends on | Test |
| --- | --- | --- | --- |
| D4 | Full review default plan mirrors V1.1: current snapshot, persistence, all key metrics, history status, latest state, growth, allocation history. | D | `test_full_review_plan_matches_v1_broad_context` |
| F | Persistence node writes portfolio/account/assets/position states/daily value/weights/data-quality events only when plan says `persist_observation=true`. | D4, B | Existing idempotency tests plus persist false test |
| F1 | Non-review queries may choose `persist_observation=false` to avoid writing history for purely historical reads. | F | `test_non_review_can_skip_persistence` |
| I | Assemble V1.2-compatible packet from snapshot, metrics, storage result, history context, effective cash, and candidate issues. | E, F, G, H | Packet validation test |
| J | LLM portfolio evaluator receives only plan-selected context and still answers query directly. | I | Fake evaluator prompt/context test |
| J1 | Preserve malformed JSON recovery tests for evaluator. | J | Existing evaluator tests |

### EC4: Tool calls visible in trace output

| Task | Description | Depends on | Test |
| --- | --- | --- | --- |
| K | Record planned tools before execution and actual MCP calls after execution. | D, E, F, G, H | `test_portfolio_trace_includes_planned_and_actual_tools` |
| K1 | Include skipped tool reasons, such as `sql_history_skipped: not_needed_for_cash_query`. | K | Trace skipped reason test |
| K2 | Expose trace through `PortfolioAgentResult.tool_calls` or a V1.2 trace field. | K | Chat trace contains planned/actual calls |
| L | Update tests to assert fewer calls for narrow queries and broad calls for full review. | K | `tests/test_portfolio_planner.py` |

## Tests To Add

- `tests/test_portfolio_planner.py`
- Updates to `tests/test_portfolio_agent.py` for backward compatibility.

Minimum cases:

- Cash-weight plan avoids SQL history tools.
- Current holding weight plan avoids SQL history tools.
- What-changed plan requests growth and allocation history.
- Full review plan mirrors V1.1 broad behavior.
- Persist false does not write a daily value snapshot.
- Tool trace includes planned, actual, and skipped tools.

## Free Tasks

- B: Split current workflow into helper functions without changing behavior.
- C/D: Deterministic planner can be implemented before LangGraph wiring.
- K: Trace field design can be drafted alongside Task 5.

## Risks

- Planner autonomy can creep too far. Keep outputs bounded and schema-validated.
- Skipping persistence by default would lose useful history. Full review should
  keep V1.1 persistence behavior.
- Query-specific metrics may require new finance metric MCP tools later. V1.2 can
  record broad metric execution as a temporary implementation detail.
