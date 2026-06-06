# V2 Task Maps

These files break down the active V2 plan from
[`ACTION_PLAN.md`](../ACTION_PLAN.md). V1 task maps remain historical under
`../V1_TASKS/`.

V2 goal:

```text
V1 Portfolio Agent POC
  -> thin LangGraph Investment Agent supervisor
  -> bounded-planning Portfolio Agent subgraph
  -> Sentiment Agent stub
  -> synthesis, guardrails, trace, and deterministic tests
```

## Task Files

| Task | File | Purpose |
| --- | --- | --- |
| 1 | [TASK_1_DEFINE_V2_CONTRACTS.md](TASK_1_DEFINE_V2_CONTRACTS.md) | Create Pydantic contracts for Investment Agent state, query plans, Portfolio Agent tasks/plans, Sentiment Agent stub tasks, synthesis, and guardrails. |
| 2 | [TASK_2_THIN_LANGGRAPH_INVESTMENT_AGENT.md](TASK_2_THIN_LANGGRAPH_INVESTMENT_AGENT.md) | Build the thin LangGraph Investment Agent supervisor and route to portfolio and sentiment stub paths. |
| 3 | [TASK_3_PORTFOLIO_AGENT_BOUNDED_PLANNING.md](TASK_3_PORTFOLIO_AGENT_BOUNDED_PLANNING.md) | Convert the current deterministic Portfolio Agent into a bounded-planning subgraph while preserving V1 behavior as the broad-review default. |
| 4 | [TASK_4_SENTIMENT_AGENT_STUB.md](TASK_4_SENTIMENT_AGENT_STUB.md) | Add a structured Sentiment Agent stub that cements the future GraphRAG task and response contracts. |
| 5 | [TASK_5_GUARDRAILS_AND_TRACE.md](TASK_5_GUARDRAILS_AND_TRACE.md) | Move guardrails and trace into the V2 Investment Agent path. |
| 6 | [TASK_6_DOCUMENTATION_AND_TESTS.md](TASK_6_DOCUMENTATION_AND_TESTS.md) | Add the test strategy and documentation updates needed to close V2. |

## Cross-Task Dependency Map

```text
T1. Contracts
  ├── T2. Thin Investment Agent graph
  │   ├── T4. Sentiment Agent stub
  │   ├── T5. Guardrails and trace
  │   └── T6. Documentation and tests
  └── T3. Portfolio Agent bounded-planning subgraph
      ├── T2. Investment Agent integration
      ├── T5. Tool-call trace
      └── T6. Planner tests

T4. Sentiment Agent stub
  ├── T2. Investment Agent portfolio-plus-sentiment route
  ├── T5. Missing-research guardrails
  └── T6. Contract tests
```

## Free Tasks

These can begin before code implementation:

- T1-A: Audit existing schemas and output contracts.
- T1-B: Decide V2 model module locations and naming.
- T1-C: Draft Pydantic models and fixture JSON.
- T4-A: Define Sentiment Agent stub fixture shape.
- T5-A: Define guardrail result schema extensions.
- T6-A: Define deterministic test matrix.

Implementation tasks should begin with Task 1. Do not start Neo4j ingestion in
V2. GraphRAG should be designed against the Sentiment Agent contract after the
stub is accepted.
