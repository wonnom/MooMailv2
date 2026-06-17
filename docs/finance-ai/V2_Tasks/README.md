# V2 Task Maps

These files break down the V2 implementation plan from
[`ACTION_PLAN.md`](../ACTION_PLAN.md). V1 task maps remain historical under
`../V1_TASKS/`.

Status: V2 skeleton complete as of 2026-06-15.

V2 implemented goal:

```text
V1 Portfolio Agent POC
  -> thin LangGraph Investment Agent supervisor
  -> bounded-planning Portfolio Agent path
  -> Sentiment Agent stub
  -> synthesis, guardrails, trace, and deterministic tests
```

## What Changed From V1

V1 proved the Portfolio Agent POC:

- read-only OpenD/MooMoo portfolio retrieval
- canonical SQLite portfolio-history persistence
- deterministic finance metrics
- MCP-facing OpenD, SQL, and metrics modules
- portfolio-only LLM evaluation
- terminal and local static chat paths

V2 adds the first Investment Agent skeleton:

- real LangGraph `StateGraph` supervisor in `V2InvestmentAgent`
- structured query plan, Portfolio Agent task, Sentiment Agent task, synthesis,
  guardrail, and trace contracts
- Investment Agent routing between portfolio-only and portfolio-plus-sentiment
  flows
- bounded Portfolio Agent context planning for broad review, cash/fact queries,
  what-changed/history queries, and risk checks
- structured Sentiment Agent stub that returns missing-research packets without
  Neo4j
- deterministic guardrails and sanitized operational trace
- deterministic tests for V2 contracts, graph routing, portfolio planning,
  sentiment stubbing, guardrails, trace, chat integration, and fixtures

## Current Reality

Implemented:

- `src/moomail_finance_ai/v2_investment_agent.py`
- `src/moomail_finance_ai/v2_schemas.py`
- `src/moomail_finance_ai/sentiment_agent_stub.py`
- `src/moomail_finance_ai/v2_guardrails.py`
- `src/moomail_finance_ai/v2_trace.py`
- V2 chat route through `investment_v2`
- terminal V2 review script at `scripts/investment_agent_v2_review.py`

Still mock/stub/not fully developed:

- Sentiment Agent is a stub only. It does not retrieve Neo4j/GraphRAG evidence,
  does not return citations, and does not produce real sentiment.
- V2 synthesis is deterministic/template-style. It is not yet a rich LLM
  Investment Agent synthesis step over all subagent packets.
- Query classification and Portfolio Agent context planning are deterministic
  rule/keyword based. They are not yet guided structured-output LLM planners.
- Portfolio Agent bounded planning is implemented inside the existing Python
  Portfolio Agent path, not as a separate compiled LangGraph subgraph.
- MCP modules have stdio JSON-RPC server wrappers, but the agent still calls
  in-process MCP modules rather than an official MCP client/host runtime.
- Pinecone memory is not connected.
- Neo4j GraphRAG and `research-rag-mcp` are not implemented.
- Crypto account ingestion, OTC quote fallback, scheduled checks, and a richer
  React/TypeScript frontend are deferred.

## Closeout Gate

Final deterministic gate for V2 closeout:

```bash
.venv/bin/python -m pytest tests --ignore=tests/live -q
```

Latest closeout result on 2026-06-15:

```text
156 passed, 1 warning
```

The warning is a LangGraph dependency deprecation warning. Live connector tests
remain opt-in under `tests/live/`.

## Task Files

| Task | File | Purpose |
| --- | --- | --- |
| 1 | [TASK_1_DEFINE_V2_CONTRACTS.md](TASK_1_DEFINE_V2_CONTRACTS.md) | Complete. Create Pydantic contracts for Investment Agent state, query plans, Portfolio Agent tasks/plans, Sentiment Agent stub tasks, synthesis, and guardrails. |
| 2 | [TASK_2_THIN_LANGGRAPH_INVESTMENT_AGENT.md](TASK_2_THIN_LANGGRAPH_INVESTMENT_AGENT.md) | Complete. Build the thin Investment Agent supervisor as a real LangGraph `StateGraph`. |
| 3 | [TASK_3_PORTFOLIO_AGENT_BOUNDED_PLANNING.md](TASK_3_PORTFOLIO_AGENT_BOUNDED_PLANNING.md) | Complete. Convert the current deterministic Portfolio Agent into a bounded-planning path while preserving V1 behavior as the broad-review default. |
| 4 | [TASK_4_SENTIMENT_AGENT_STUB.md](TASK_4_SENTIMENT_AGENT_STUB.md) | Complete. Add a structured Sentiment Agent stub that cements the future GraphRAG task and response contracts. |
| 5 | [TASK_5_GUARDRAILS_AND_TRACE.md](TASK_5_GUARDRAILS_AND_TRACE.md) | Complete. Move deterministic guardrails and sanitized trace into the V2 Investment Agent path. |
| 6 | [TASK_6_DOCUMENTATION_AND_TESTS.md](TASK_6_DOCUMENTATION_AND_TESTS.md) | Complete. Add the test strategy and documentation updates needed to close V2. |

## Cross-Task Dependency Map

```text
T1. Contracts
  ├── T2. Thin Investment Agent graph
  │   ├── T4. Sentiment Agent stub
  │   ├── T5. Guardrails and trace
  │   └── T6. Documentation and tests
  └── T3. Portfolio Agent bounded-planning path
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

Implementation tasks are complete for the V2 skeleton. Do not treat V2 as a
finished research assistant: the next work should choose one deferred track,
most likely real Neo4j GraphRAG, an LLM-guided planning layer, official MCP
client/host runtime migration, or Pinecone memory.
