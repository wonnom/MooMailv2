# Task 4: Add Sentiment Agent Stub

Status: complete as of 2026-06-15.

## Goal

Build a Sentiment Agent stub that accepts the future GraphRAG task shape and
returns a structured missing-research response. This lets the Investment Agent
exercise routing, synthesis, limitations, and guardrails before Neo4j ingestion
exists.

The stub must not fabricate sentiment, citations, documents, or company facts.

## Implementation Notes

Implemented in `src/moomail_finance_ai/sentiment_agent_stub.py` as
`SentimentAgentStub`.

The stub:

- accepts `SentimentTask` or a strict task payload dictionary
- validates and normalizes tickers through the V1.2 Pydantic contract
- preserves requested tickers, entities, themes, key questions, evidence types,
  and time window on the returned packet
- returns `retrieval_status: not_implemented`
- expands requested evidence types into `missing_documents`
- returns no holdings, citations, contradictions, source metadata, or sentiment
  stance while GraphRAG is unavailable
- requires no Neo4j, Pinecone, vector DB, or external research credentials

The future Neo4j GraphRAG implementation should satisfy the same
`SentimentTask -> SentimentPacket` contract and replace the stub without
changing the Investment Agent graph boundary.

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
| A | Complete Task 1 `SentimentTask` and `SentimentPacket`. | None | Done |
| B | Create stub module, likely `src/moomail_finance_ai/sentiment_agent_stub.py` or `src/moomail_finance_ai/v2/sentiment_agent.py`. | A | Done |
| C | Validate incoming `SentimentTask` and normalize scope into tickers/entities/questions. | A, B | Done |
| C1 | Reject malformed task payloads instead of silently dropping fields. | C | Done |
| G | Add adapter callable for Investment Agent graph. | B, Task 2 | Done |
| G1 | Ensure stub does not require Neo4j config, vector DB config, or external credentials. | B | Done |

### EC2: Final synthesis can say research is unavailable

| Task | Description | Depends on | Test |
| --- | --- | --- | --- |
| D | Return `retrieval_status: not_implemented` by default. | B | Done |
| D1 | Include `missing_documents` for requested evidence types when available in task. | D | Done |
| D2 | Include clear warnings such as `Neo4j GraphRAG is not implemented in V1.2`. | D | Done |
| E | Preserve requested tickers, companies, themes, and questions in output scope. | C, D | Done |
| H | Ensure Investment Agent synthesis consumes stub status and writes a limitation in final output. | G, Task 2 | Done |
| H1 | Synthesis should not treat stub as a failure when portfolio-only answer can proceed. | H | Done |

### EC3: Future Neo4j work has a concrete contract

| Task | Description | Depends on | Test |
| --- | --- | --- | --- |
| F | Return empty citations and no stance when retrieval is not implemented. | D | Done |
| F1 | Include placeholders for future fields: holdings, portfolio-level sentiment, contradictions, open questions, source metadata. | A, D | Done |
| F2 | Add a fixture showing a future non-stub successful packet shape for schema compatibility only. | A | Done |
| I | Document how Neo4j GraphRAG must satisfy the stub contract later. | F1 | Done |

## Tests To Add

- `tests/test_sentiment_agent_stub.py`
- `tests/fixtures/agent/sentiment_task_full_review.json`
- `tests/fixtures/agent/sentiment_packet_stub.json`
- Optional `tests/fixtures/agent/sentiment_packet_future_success.json`

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
- Do not leak future Neo4j schema complexity into V1.2 beyond the task/packet
  shape.
- Keep stub deterministic.
