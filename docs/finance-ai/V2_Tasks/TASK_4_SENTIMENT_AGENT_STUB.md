# Task 4: Add Sentiment Agent Stub

## Goal

Build a Sentiment Agent stub that accepts the future GraphRAG task shape and
returns a structured missing-research response. This lets the Investment Agent
exercise routing, synthesis, limitations, and guardrails before Neo4j ingestion
exists.

The stub must not fabricate sentiment, citations, documents, or company facts.

## Exit Criteria

1. Investment Agent can call Sentiment Agent without Neo4j.
2. Final synthesis can say when research is unavailable.
3. Future Neo4j work has a concrete input/output contract to satisfy.

## Dependency Graph

```text
A. Task 1 SentimentTask and SentimentPacket contracts
   ├── B. Sentiment Agent stub module
   │   ├── C. Validate incoming task
   │   ├── D. Build missing-research packet
   │   ├── E. Preserve requested scope
   │   └── F. Return no fabricated citations
   ├── G. Investment Agent adapter integration
   ├── H. Synthesis limitation handling
   └── I. Tests
```

## Task Breakdown By Exit Criteria

### EC1: Investment Agent can call Sentiment Agent without Neo4j

| Task | Description | Depends on | Test |
| --- | --- | --- | --- |
| A | Complete Task 1 `SentimentTask` and `SentimentPacket`. | None | Covered by Task 1 |
| B | Create stub module, likely `src/moomail_finance_ai/sentiment_agent_stub.py` or `src/moomail_finance_ai/v2/sentiment_agent.py`. | A | Import smoke test |
| C | Validate incoming `SentimentTask` and normalize scope into tickers/entities/questions. | A, B | `test_sentiment_stub_accepts_scoped_task` |
| C1 | Reject malformed task payloads instead of silently dropping fields. | C | Invalid task raises validation error |
| G | Add adapter callable for Investment Agent graph. | B, Task 2 | Fake graph calls stub |
| G1 | Ensure stub does not require Neo4j config, vector DB config, or external credentials. | B | Env-independent test |

### EC2: Final synthesis can say research is unavailable

| Task | Description | Depends on | Test |
| --- | --- | --- | --- |
| D | Return `retrieval_status: not_implemented` by default. | B | `test_sentiment_stub_status_not_implemented` |
| D1 | Include `missing_documents` for requested evidence types when available in task. | D | Missing docs test |
| D2 | Include clear warnings such as `Neo4j GraphRAG is not implemented in V2`. | D | Warning test |
| E | Preserve requested tickers, companies, themes, and questions in output scope. | C, D | Scope preservation test |
| H | Ensure Investment Agent synthesis consumes stub status and writes a limitation in final output. | G, Task 2 | Final output missing-research test |
| H1 | Synthesis should not treat stub as a failure when portfolio-only answer can proceed. | H | Quantitative-only path still completes |

### EC3: Future Neo4j work has a concrete contract

| Task | Description | Depends on | Test |
| --- | --- | --- | --- |
| F | Return empty citations and no stance when retrieval is not implemented. | D | Assert citations empty and stance absent/unclear |
| F1 | Include placeholders for future fields: holdings, portfolio-level sentiment, contradictions, open questions, source metadata. | A, D | Packet shape test |
| F2 | Add a fixture showing a future non-stub successful packet shape for schema compatibility only. | A | Fixture validation test |
| I | Document how Neo4j GraphRAG must satisfy the stub contract later. | F1 | Documentation check/search |

## Tests To Add

- `tests/test_sentiment_agent_stub.py`
- `tests/fixtures/v2/sentiment_task_full_review.json`
- `tests/fixtures/v2/sentiment_packet_stub.json`
- Optional `tests/fixtures/v2/sentiment_packet_future_success.json`

Minimum cases:

- Stub accepts a task with tickers and evidence types.
- Stub returns `not_implemented`, warnings, missing documents, and no citations.
- Stub requires no Neo4j/Pinecone/vector config.
- Investment Agent synthesis reports unavailable research without hallucination.

## Free Tasks

- A: Contract completion.
- B/D/F: Stub implementation can be built before real Investment Agent graph if
  tests call it directly.

## Risks

- Stub language must be honest. Avoid fake positive/mixed/negative stance.
- Do not leak future Neo4j schema complexity into V2 beyond the task/packet
  shape.
- Keep stub deterministic.
