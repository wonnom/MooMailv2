# Milestone 5 Task Map

Milestone 5 goal: combine portfolio diagnostics, research retrieval, long-term memory, policy checks, deterministic metrics, SQL history, guardrails, citations, and audit summaries into a complete Investment Agent review.

## Scope

This milestone implements a local full Investment Agent that preserves the planned MCP boundaries:

- `memory-mcp`: implemented locally as file-backed memory.
- `moomail-portfolio-sql-mcp`: implemented locally through SQLite.
- `moomail-finance-metrics-mcp`: implemented locally through deterministic Python metric functions.
- `research-rag-mcp`: implemented locally through the deterministic research store from Milestone 4.
- `moomail-opend-mcp`: supported through the recorded OpenD client for repeatable tests, and the live OpenD client when requested.

Pinecone remains the intended long-term backend, but local file-backed memory is used for this milestone so tests do not require external secrets or network access.

## Exit Criteria

1. `review my portfolio` runs end to end with OpenD data, SQL history, curated research, deterministic metrics, memory retrieval, guardrail review, citations, and saved audit summaries.
2. No trading tools or executable order paths exist.
3. Missing critical data blocks recommendations when necessary.
4. Non-critical missing data appears in a clear missing-data section.

## Dependency Graph

```text
A. Milestone 2 recorded/live OpenD client
B. Milestone 3 SQL store and metrics
C. Milestone 4 research store and Sentiment Agent
D. Canonical IPS fixture
E. Local memory store
   ├── F. Retrieve relevant memories
   └── G. Write routine portfolio review summaries
H. Full Investment Agent
   ├── A. Portfolio packet from recorded/live OpenD
   ├── B. Persist snapshot and metrics
   ├── C. Sentiment packet and citations
   ├── D. IPS checks
   ├── E/F. Memory retrieval
   ├── I. Synthesis
   ├── J. Guardrail review
   ├── K. Audit storage
   └── G. Memory summary write
L. Tests
```

## Task Breakdown by Exit Criteria

### EC1: End-to-end full portfolio review

| Task | Description | Depends on | Status |
| --- | --- | --- | --- |
| A | Use recorded OpenD field report as repeatable data input | None | Done |
| B | Use SQLite history and deterministic metrics | Milestone 3 | Done |
| C | Use local research retrieval and Sentiment Agent | Milestone 4 | Done |
| E | Add local memory store | None | Done |
| H | Add `FullInvestmentAgent` orchestration | A, B, C, D, E | Done |
| K | Persist audit summary to SQL | H | Done |
| G | Write routine review summary memory | H | Done |
| L | Add full-agent test | H | Done |

### EC2: No trading paths

| Task | Description | Depends on | Status |
| --- | --- | --- | --- |
| H1 | Keep full agent read-only | H | Done |
| J | Reuse guardrail no-trading checks | H | Done |
| L | Add no-trade-surface test | H, J | Done |

### EC3: Critical missing data blocks recommendations

| Task | Description | Depends on | Status |
| --- | --- | --- | --- |
| H2 | Detect missing portfolio packet | H | Done |
| I1 | Produce blocked report without recommendations | H2 | Done |
| J1 | Store guardrail/audit outcome | I1 | Done |
| L | Add blocking test | H2 | Done |

### EC4: Non-critical missing data is visible

| Task | Description | Depends on | Status |
| --- | --- | --- | --- |
| I2 | Preserve missing research/history/quote warnings | H | Done |
| I3 | Include missing-data section in final report | I2 | Done |
| L | Add missing-data visibility test | I2 | Done |

## Verification

Run:

```bash
.venv/bin/python -m pytest
```

Latest focused tests:

```text
tests/test_full_agent.py .... 4 passed
```

Latest full suite:

```text
53 passed, 4 skipped
```

Local terminal review:

```bash
.venv/bin/python scripts/full_review.py --output reports/full-review.json
```

Latest run summary:

- Guardrails passed
- Citations returned
- Missing data surfaced
- SQL snapshot, metrics, audit summary, and memory summary written
