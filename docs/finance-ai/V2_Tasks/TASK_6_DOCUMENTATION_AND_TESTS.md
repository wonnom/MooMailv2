# Task 6: Documentation And Tests

## Goal

Close V2 with deterministic tests and documentation that describe the actual
implemented architecture.

This task should be done throughout V2, not only at the end.

## Exit Criteria

1. Deterministic suite passes without live OpenD, Neo4j, Pinecone, or hosted LLM
   calls.
2. Live OpenD connector tests remain opt-in.
3. Docs describe V1 as complete and V2 as active.

## Dependency Graph

```text
A. Task 1 schema tests
   ├── B. Task 2 Investment Agent graph tests
   ├── C. Task 3 Portfolio planner tests
   ├── D. Task 4 Sentiment stub tests
   ├── E. Task 5 guardrail/trace tests
   ├── F. Update test fixtures and fakes
   ├── G. Update docs after each implementation task
   └── H. Final V2 release gate
```

## Task Breakdown By Exit Criteria

### EC1: Deterministic suite passes without live services

| Task | Description | Depends on | Test |
| --- | --- | --- | --- |
| A | Add `tests/test_v2_schemas.py`. | Task 1 | Schema round-trip tests |
| B | Add `tests/test_v2_investment_agent.py` with fake Portfolio Agent and fake Sentiment Agent. | Task 2 | Routing and synthesis tests |
| C | Add `tests/test_v2_portfolio_planner.py`. | Task 3 | Planner and call-minimization tests |
| D | Add `tests/test_sentiment_agent_stub.py`. | Task 4 | Stub packet tests |
| E | Add `tests/test_v2_guardrails.py` and `tests/test_v2_trace.py`. | Task 5 | Guardrail and trace tests |
| F | Add V2 fixtures under `tests/fixtures/v2/` or local factory functions. | A through E | Fixture validation |
| F1 | Add fake LLM/classifier/evaluator objects so hosted LLM calls are never needed in deterministic tests. | B, C | No env key required tests |
| F2 | Add fake Portfolio Agent and Sentiment Agent call counters for routing tests. | B | Call-count assertions |
| F3 | Add fake MCP modules or existing recorded OpenD fixtures for Portfolio Agent planner tests. | C | No live OpenD call assertions |
| H | Run `.venv/bin/python -m pytest -q` and update doc counts only when final V2 closeout is reached. | A through G | Full suite |

### EC2: Live OpenD connector tests remain opt-in

| Task | Description | Depends on | Test |
| --- | --- | --- | --- |
| H1 | Confirm no new V2 deterministic test requires `MOOMAIL_RUN_LIVE_CONNECTOR_TESTS=1`. | A through E | Run full suite with env unset |
| H2 | Keep live OpenD tests under `tests/live/`. | None | Existing live tests |
| H3 | If V2 adds a live Investment Agent smoke test, mark it live and use recorded OpenD by default. | Task 2, Task 3 | Live marker test |
| H4 | Document any new live command in `CONNECTOR_TESTS.md`. | H3 | Docs search |

### EC3: Docs describe V1 complete and V2 active

| Task | Description | Depends on | Test |
| --- | --- | --- | --- |
| G | Update `ACTION_PLAN.md` after each V2 task status change. | All tasks | Docs search |
| G1 | Update `AGENTS.md` if agent responsibilities change during implementation. | Task 2, Task 3, Task 4 | Docs search |
| G2 | Update `ARCHITECTURE.md` if graph or MCP boundaries change. | Task 2, Task 3 | Docs search |
| G3 | Update `PROTOCOL.md` if state/packet schemas change. | Task 1 through Task 5 | Docs search |
| G4 | Update `MCP_SERVERS.md` if Portfolio Agent planning changes tool usage. | Task 3 | Docs search |
| G5 | Update `TESTING.md` with new V2 test files and retirement plan for legacy prototype tests. | A through E | Docs search |
| G6 | Add a V2 closeout section or new closeout doc only when implementation is complete. | H | Manual review |

## Suggested Test Matrix

| Scenario | Expected route | Required fakes |
| --- | --- | --- |
| "What is my cash weight?" | Portfolio Agent only | Fake Portfolio Agent |
| "Review my portfolio" | Portfolio Agent plus Sentiment Agent stub when candidates exist | Fake Portfolio Agent, fake Sentiment Agent |
| "What changed since last month?" | Portfolio Agent with SQL history plan | Fake SQL/history |
| "What does recent research say about GOOG?" | Portfolio Agent if needed, Sentiment Agent stub | Fake Sentiment Agent |
| Unsupported trade request | Guardrail blocks or refuses | Fake graph result |
| Missing research | Final report lists limitation | Sentiment stub |
| Backend exception | Stream emits structured error | Fake failing service |

## Final V2 Release Gate

Run:

```bash
.venv/bin/python -m pytest -q
```

Optional live OpenD gate:

```bash
MOOMAIL_RUN_LIVE_CONNECTOR_TESTS=1 .venv/bin/python -m pytest tests/live -q -k opend
```

Manual smoke checks:

- Terminal V2 Investment Agent review with fake/stub sentiment.
- Chat V2 Investment Agent review with fake/stub sentiment.
- Portfolio-only query shows no sentiment call.
- Full review shows missing-research limitation from stub.
- No trade tools are exposed.

## Free Tasks

- A/F: Schema tests and fixtures can begin after Task 1.
- G: Docs updates should happen continuously.
- H1/H2: Live test guardrails can be checked before implementation.

## Risks

- Adding tests only at the end will make graph refactors painful.
- Hosted LLM or live OpenD dependency leakage will make the deterministic suite
  unreliable.
- V2 docs should describe what was actually implemented, not the future Neo4j
  system.
