# Task 2: Build Thin LangGraph Investment Agent

## Goal

Implement the first real Investment Agent architecture as a thin LangGraph
supervisor. It should route queries, call subagents, synthesize outputs, run
guardrails, and emit structured terminal/frontend responses.

It should not implement GraphRAG, Pinecone memory, or a rich frontend.

## Exit Criteria

1. Portfolio-only queries call only Portfolio Agent.
2. Full review queries call Portfolio Agent and, when appropriate, Sentiment
   Agent stub.
3. Missing sentiment data is shown as a clear limitation, not hallucinated
   research.
4. Existing terminal/frontend paths can call the new Investment Agent path.

## Dependency Graph

```text
A. V2 contracts from Task 1
   ├── B. Add LangGraph/LangChain dependency decision
   │   ├── C. InvestmentAgentGraph module skeleton
   │   │   ├── D. Query classification node
   │   │   ├── E. IPS loading node
   │   │   ├── F. Subagent routing node
   │   │   ├── G. Portfolio Agent adapter node
   │   │   ├── H. Sentiment Agent stub adapter node
   │   │   ├── I. Synthesis node
   │   │   ├── J. Guardrail node
   │   │   └── K. Final output node
   │   ├── L. Terminal script integration
   │   ├── M. Chat service integration
   │   └── N. Tests
```

## Task Breakdown By Exit Criteria

### EC1: Portfolio-only queries call only Portfolio Agent

| Task | Description | Depends on | Test |
| --- | --- | --- | --- |
| A | Complete Task 1 V2 contracts enough for `InvestmentAgentState`, `InvestmentQueryPlan`, and `PortfolioTask`. | None | Covered by Task 1 |
| B | Decide dependency strategy: add `langgraph`/`langchain` extras or isolate behind optional import with fallback skip. | A | Dependency/import smoke test |
| C | Create Investment Agent graph module, likely `src/moomail_finance_ai/v2_investment_agent.py` or `src/moomail_finance_ai/v2/investment_agent.py`. | A, B | Import test |
| D | Implement deterministic query classifier for first pass. It should classify obvious cash/allocation/risk/history/full-review queries without LLM dependency. | C | `test_v2_classifier_cash_query_portfolio_only` |
| D1 | Add optional LLM classifier hook later, but keep deterministic classifier as test default. | D | Fake classifier test |
| F | Implement routing node that sets `needs_portfolio_agent=true`, `needs_sentiment_agent=false` for mechanical portfolio queries. | D | `test_v2_routing_portfolio_only_skips_sentiment` |
| G | Add Portfolio Agent adapter node that can call current V1 Portfolio Agent while Task 3 is still pending. | F | Fake Portfolio Agent called once |
| G1 | Adapter should accept `PortfolioTask` and return a V2-compatible portfolio packet wrapper. | G | Packet adapter test |

### EC2: Full review can call Portfolio Agent plus Sentiment Agent stub

| Task | Description | Depends on | Test |
| --- | --- | --- | --- |
| H | Add Sentiment Agent stub adapter node using Task 4 stub once available. Before Task 4, use a minimal fake in tests. | F, Task 4 | `test_v2_full_review_calls_sentiment_stub` |
| F1 | Route broad review/risk/deep-dive questions to portfolio first, then decide sentiment from user intent and portfolio sentiment candidates. | D, G | `test_v2_full_review_routes_portfolio_then_sentiment` |
| F2 | Ensure Portfolio Agent suggestions do not force sentiment if the user asked a narrow mechanical question. | F1 | Narrow query with candidates skips sentiment |
| F3 | Ensure user-named thesis/news/sentiment questions can request Sentiment Agent even if portfolio packet has no candidates. | F1 | Named ticker sentiment route test |
| H1 | Pass scoped `SentimentTask` into stub: tickers, reasons, evidence types, time window, and questions. | F1, H | Stub receives expected task |

### EC3: Missing sentiment is shown as limitation

| Task | Description | Depends on | Test |
| --- | --- | --- | --- |
| I | Implement synthesis node that combines portfolio packet and sentiment stub packet. | G, H | `test_v2_synthesis_includes_missing_research_warning` |
| I1 | If sentiment status is `not_implemented` or `missing_corpus`, final report must include limitation text and missing data entries. | I | Missing-research test |
| I2 | Synthesis must not invent sentiment stance, documents, or citations when stub is missing. | I | Assert no fake citations/stance |
| I3 | Portfolio-only synthesis should not mention absent sentiment unless the query asked for it. | I | Cash query output test |

### EC4: Terminal/frontend paths can call new Investment Agent

| Task | Description | Depends on | Test |
| --- | --- | --- | --- |
| L | Add terminal script or flag for V2 Investment Agent path, for example `scripts/investment_agent_v2_review.py` or `--agent investment_v2`. | C, I, J | CLI smoke with fake agents |
| M | Update `ChatService` to optionally select V2 Investment Agent path without breaking existing portfolio path. | C, I, J | `test_chat_service_can_call_v2_investment_agent_with_fakes` |
| M1 | Stream graph node status events through existing frontend stream event contract. | M | Stream contains graph statuses |
| K | Convert graph result into existing `chat_response`/final report shape or a V2-compatible extension. | I, J | Frontend response shape test |
| N | Add deterministic tests with fake Portfolio Agent and fake Sentiment Agent stub. | L, M | `tests/test_v2_investment_agent.py` |

## Tests To Add

- `tests/test_v2_investment_agent.py`
- `tests/test_chat_app.py` additions for V2 agent selection if frontend path is wired.

Minimum cases:

- Cash-weight query calls Portfolio Agent once and Sentiment Agent zero times.
- Full review calls Portfolio Agent and Sentiment Agent stub when planner says
  research is useful.
- Sentiment missing data appears in final report.
- No fabricated citations appear when Sentiment Agent stub has no documents.
- Streamed status events include graph-level steps.

## Free Tasks

- B: Decide LangGraph/LangChain dependency strategy.
- D: Deterministic classifier design.
- G: Portfolio Agent adapter can start before full Task 3 if it wraps V1 output.

## Risks

- Adding LangGraph before contracts are stable can create churn.
- If the classifier is too LLM-dependent, deterministic tests become brittle.
- The first graph should stay thin. Do not add GraphRAG or Pinecone in this task.
