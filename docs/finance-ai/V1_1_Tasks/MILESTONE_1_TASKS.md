# Milestone 1 Task Map

Milestone 1 goal: prove the Investment Agent orchestration and output contracts without real external integrations.

Run Milestone 1 commands with the project venv:

```bash
.venv/bin/python -m pytest
.venv/bin/python scripts/run_prototype.py "Review my portfolio"
```

## Exit Criteria

1. A `review my portfolio` query runs end to end against mocked data.
2. The Investment Agent calls mock Portfolio and Sentiment agents.
3. The final output contains portfolio analysis, research context, missing data, and source references.
4. The guardrail node can block or revise unsafe outputs.

## Dependency Graph

```text
A. Project skeleton
   ├── B. Core schemas
   │   ├── C. Mock data contracts
   │   │   ├── D. Mock Portfolio Agent
   │   │   ├── E. Mock Sentiment Agent
   │   │   └── F. Prototype Investment Agent flow
   │   │       ├── G. Terminal runner
   │   │       └── H. End-to-end output validation tests
   │   └── I. Guardrail schemas
   │       └── J. Guardrail review implementation
   │           └── K. Unsafe output tests
   └── L. Tooling config
```

## Task Breakdown by Exit Criteria

### EC1: End-to-end mocked portfolio review

| Task | Description | Depends on | Status |
| --- | --- | --- | --- |
| A | Create Python package skeleton | None | Done |
| B | Define core Pydantic schemas | A | Done |
| C | Create mock IPS, memory, portfolio, and sentiment payloads | B | Done |
| F | Implement prototype Investment Agent flow | C, D, E, J | Done |
| G | Add terminal runner for `review my portfolio` | F | Done |
| H | Add end-to-end validation test | F | Done |

### EC2: Investment Agent calls mock subagents

| Task | Description | Depends on | Status |
| --- | --- | --- | --- |
| D | Implement mock Portfolio Agent callable | B, C | Done |
| E | Implement mock Sentiment Agent callable | B, C | Done |
| F | Route through subagents from Investment Agent | D, E | Done |
| H | Assert both subagents were called | F | Done |

### EC3: Final output contains required sections

| Task | Description | Depends on | Status |
| --- | --- | --- | --- |
| B | Define final report, citation, missing data, and recommendation schemas | A | Done |
| C | Include source references and missing data in mocks | B | Done |
| F | Synthesize final report from portfolio and sentiment packets | C, D, E | Done |
| H | Validate required sections in tests | F | Done |

### EC4: Guardrail node can block or revise unsafe outputs

| Task | Description | Depends on | Status |
| --- | --- | --- | --- |
| I | Define guardrail result schema | B | Done |
| J | Implement guardrail review function | I | Done |
| K | Add tests for exact trade/share-count blocking | J | Done |
| F | Place guardrail review before final output | J | Done |

## Free Tasks Started First

These tasks have no implementation dependencies and are safe to begin immediately:

- A: Project skeleton
- B: Core schemas
- I: Guardrail schemas
- L: Tooling config

All four free tasks are now implemented.

## Deferred Until Dependencies Exist

- Real LangGraph state machine: after prototype flow and schemas stabilize.
- MCP server wrappers: added after the initial OpenD, SQL, and metrics modules.
- TypeScript/frontend expansion: basic local chat UI exists, but backend contracts remain primary.
