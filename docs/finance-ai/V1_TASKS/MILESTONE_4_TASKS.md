# Milestone 4 Task Map

Milestone 4 goal: retrieve curated source-backed research for held portfolio stocks.

## Scope

This milestone implements the research and Sentiment Agent contracts locally. The local store models the eventual Neo4j plus vector retrieval boundary but does not require Neo4j, embeddings, or external services to run tests.

The store is intentionally manual-ingestion first:

- Company filings
- Earnings transcripts
- Shareholder letters
- Annual reports
- Quarterly reports
- Curated research notes

## Exit Criteria

1. For a held ticker, Sentiment Agent returns thesis, developments, risks, catalysts, contradictions, stance, citations, and missing research.
2. Empty retrieval produces an explicit warning instead of invented analysis.
3. Source quality is ranked and visible in structured output.

## Dependency Graph

```text
A. Research document metadata contract
   ├── B. Research chunk contract
   │   ├── C. Manual ingestion into local research store
   │   │   ├── D. Deterministic retrieval by ticker/query/topic
   │   │   ├── E. Source quality ranking
   │   │   └── F. Graph context placeholders
   │   └── G. Citation conversion with chunk and parent document metadata
   └── H. Required metadata validation

I. Local Sentiment Agent
   ├── D. Retrieval
   ├── E. Source quality ranking
   ├── G. Citations
   ├── J. Thesis/development/risk/catalyst/contradiction synthesis
   ├── K. Missing research detection
   └── L. Empty retrieval handling

M. Tests
   ├── EC1 complete held-ticker sentiment packet
   ├── EC2 empty retrieval warning
   └── EC3 source quality ranking visibility
```

## Task Breakdown by Exit Criteria

### EC1: Held ticker returns complete source-backed sentiment packet

| Task | Description | Depends on | Status |
| --- | --- | --- | --- |
| A | Define required document metadata | None | Done |
| B | Define research chunk contract | A | Done |
| C | Add manual ingestion store | A, B | Done |
| D | Add deterministic retrieval | C | Done |
| G | Convert chunks into citations | A, B | Done |
| I | Build Local Sentiment Agent | D, G | Done |
| J | Populate thesis, developments, risks, catalysts, contradictions, stance | I | Done |
| K | Add missing research detection | I | Done |
| M | Add EC1 test | I, J, K | Done |

### EC2: Empty retrieval warns instead of inventing analysis

| Task | Description | Depends on | Status |
| --- | --- | --- | --- |
| L | Return `unclear` stance for empty retrieval | I | Done |
| L1 | Add explicit missing-data warning | L | Done |
| L2 | Return no citations when no evidence exists | L | Done |
| M | Add EC2 test | L | Done |

### EC3: Source quality is ranked and visible

| Task | Description | Depends on | Status |
| --- | --- | --- | --- |
| E | Define source quality ranking | A | Done |
| E1 | Sort retrieval by source quality and text score | D, E | Done |
| E2 | Include rank in citation metadata | G | Done |
| M | Add EC3 test | E1, E2 | Done |

## Current Status

Milestone 4 is implemented as a local deterministic research prototype. It is ready to be backed by `research-rag-mcp` with Neo4j graph lookup and vector chunk retrieval later.

Latest local demo:

```bash
.venv/bin/python scripts/research_demo.py AAPL MSFT ZZZZ \
  --output reports/research/sentiment-demo.json
```

Demo result:

- AAPL returned thesis, developments, risks, catalysts, contradiction, mixed stance, citations, and missing document types.
- MSFT returned thesis, risks, catalysts, mixed stance, citations, missing document types, and a missing disconfirming-evidence note.
- ZZZZ returned `unclear` stance, no citations, and an explicit missing-research warning.
- Citations expose source quality and `source_quality_rank`.

Generated research reports under `reports/research/` are ignored by git.

## Verification

Run:

```bash
.venv/bin/python -m pytest
```

Latest result:

```text
66 passed, 10 skipped
```
