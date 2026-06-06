# Action Plan

## Status

V1 is complete as of 2026-06-06.

V1 is a Portfolio Agent proof of concept with:

- Read-only OpenD/MooMoo securities-account retrieval.
- OpenD portfolio normalization for funds, positions, supported quotes, and
  non-blocking unsupported quote warnings.
- One canonical local portfolio-history database:
  `data/portfolio-history.sqlite`.
- Lean SQL history through `moomail-portfolio-sql-mcp`: portfolio/account/asset
  identities, compact position states, daily value snapshots, allocation weight
  snapshots, data-quality events, and run summaries.
- Deterministic finance metric tools through `moomail-finance-metrics-mcp`.
- MCP-backed Portfolio Agent using OpenD, SQL history, finance metrics, and a
  provider-neutral portfolio-only LLM evaluator.
- Local terminal and static chat frontend paths over the same backend contracts.
- No trading tools, no trade unlock, no order placement, and no executable
  order-preparation path.

The old milestone task files under `docs/finance-ai/V1_TASKS/` are
historical implementation tracking. They are not the active plan for V2.

## Current Truth

Implemented and useful today:

- `moomail-opend-mcp`: local read-only OpenD tool surface.
- `moomail-portfolio-sql-mcp`: local SQLite portfolio-history tool surface.
- `moomail-finance-metrics-mcp`: deterministic calculation tool surface.
- `MCPPortfolioAgent`: deterministic Python workflow that calls the three MCP
  modules in a fixed order, then asks an LLM evaluator to answer portfolio-only
  questions from the collected packet.
- `scripts/portfolio_agent_review.py`: terminal Portfolio Agent review.
- `scripts/serve_chat.py`: local chat frontend server.
- `data/portfolio-history.sqlite`: canonical local portfolio-history DB.
- Deterministic tests and live OpenD connector smoke tests.

Important limitations:

- The Portfolio Agent is MCP-backed but not yet MCP-autonomous. It does not let
  the LLM decide which OpenD, SQL, or metrics tools to call.
- The current Investment Agent is a prototype, not the target LangGraph
  supervisor.
- The Sentiment Agent and Neo4j GraphRAG path are not implemented for real V1
  use. Existing research fixtures/stubs are contract placeholders.
- Pinecone memory is not connected.
- The MCP modules can run through local stdio servers, but the agent currently
  uses in-process MCP modules rather than an official MCP client/host runtime.
- Crypto holdings and OTC quote fallback are deferred.

## V2 Goal

V2 should turn the V1 Portfolio Agent POC into the first real Investment Agent
architecture.

The target is not to finish GraphRAG or memory yet. The target is to establish
the orchestration shape:

```text
User query
  -> Thin LangGraph Investment Agent supervisor
      -> decide whether portfolio context is needed
      -> decide whether sentiment/research is needed
      -> call Portfolio Agent subgraph
      -> call Sentiment Agent stub when needed
      -> synthesize final answer
      -> run guardrails
```

The Portfolio Agent should become a bounded-planning subgraph:

```text
Portfolio Agent subgraph
  -> interpret portfolio task
  -> produce bounded context plan
  -> retrieve current OpenD snapshot when needed
  -> read SQL history slices when needed
  -> calculate required deterministic metrics
  -> return structured portfolio packet and candidate sentiment scope
```

The Sentiment Agent should be a stub in V2:

```text
Sentiment Agent stub
  -> accept requested tickers/themes/questions
  -> return structured placeholder response
  -> expose missing GraphRAG fields clearly
```

This lets the project cement agent routing, subagent contracts, trace events,
guardrail behavior, and output schemas before committing to the Neo4j ingestion
and GraphRAG retrieval design.

## V2 Principles

- Use LangGraph for orchestration, routing, state, streaming, and future
  checkpointing.
- Use LangChain model/tool abstractions inside nodes only where they add value.
- Keep finance math, OpenD normalization, SQL persistence, and guardrails
  deterministic and testable.
- Add autonomy only where it is bounded by schemas and allowed tools.
- Keep the Investment Agent as the only cross-agent orchestrator.
- Do not let Portfolio Agent call Sentiment Agent directly.
- Let Portfolio Agent suggest sentiment candidates, but let Investment Agent
  decide whether to invoke Sentiment Agent.
- Keep all tools read-only or analysis-only. No trade execution path.

## V2 Work Plan

Detailed dependency maps for each work-plan item live under
[`docs/finance-ai/V2_Tasks/`](V2_Tasks/).

### 1. Define V2 Contracts

Create stable Pydantic models for:

- `InvestmentAgentState`
- `InvestmentQueryPlan`
- `PortfolioTask`
- `PortfolioContextPlan`
- `PortfolioAgentPacket`
- `SentimentTask`
- `SentimentPacket`
- `SynthesisInput`
- `GuardrailReview`

Exit criteria:

- Investment Agent can route using structured fields rather than parsing prose.
- Portfolio Agent can tell the Investment Agent which tickers/history changes
  may deserve sentiment review.
- Sentiment Agent stub can return the same shape the future GraphRAG agent will
  fill.

### 2. Build Thin LangGraph Investment Agent

Implement a small LangGraph supervisor with nodes for:

- receive/query classification
- load IPS
- route portfolio need
- route sentiment need
- call Portfolio Agent
- call Sentiment Agent stub
- synthesize final response
- guardrail review
- emit structured output

Exit criteria:

- Portfolio-only queries call only Portfolio Agent.
- Full review queries call Portfolio Agent and, when appropriate, Sentiment
  Agent stub.
- Missing sentiment data is shown as a clear limitation, not hallucinated
  research.
- Existing terminal/frontend paths can call the new Investment Agent path.

### 3. Convert Portfolio Agent To Bounded Planning Subgraph

Refactor the current deterministic Portfolio Agent into graph nodes while
preserving V1 behavior as the safe default.

Initial planner output should decide:

- whether current OpenD is required
- whether SQL history is required
- history window or row limits
- relevant tickers/assets
- required metric groups
- whether persistence should occur for this run

Execution remains deterministic once the plan is produced.

Exit criteria:

- A cash-weight query can avoid unnecessary broad history reads.
- A “what changed” query can request portfolio growth/allocation history.
- A full review can preserve the existing V1 broad context behavior.
- Tool calls are visible in trace output.

### 4. Add Sentiment Agent Stub

Build a stub that receives the real future task shape:

- tickers
- companies/entities
- reasons for research
- time window
- requested evidence types
- key questions

It returns:

- empty or placeholder holdings
- explicit `retrieval_status: not_implemented`
- missing document/research fields
- no fabricated sentiment

Exit criteria:

- Investment Agent can call Sentiment Agent without Neo4j.
- Final synthesis can say when research is unavailable.
- Future Neo4j work has a concrete input/output contract to satisfy.

### 5. Guardrails And Trace

Move guardrail review into the V2 Investment Agent path.

Guardrails should check:

- no trade placement or executable order instructions
- no unsupported research claims
- no unsupported price/portfolio facts
- no exact share-count recommendations
- missing IPS where optimization/rebalancing is framed as recommendation

Exit criteria:

- Guardrail result is included in terminal and chat outputs.
- Streamed trace shows high-level graph node progress and errors.
- Hidden reasoning is never stored or exposed.

### 6. Documentation And Tests

Keep tests deterministic by default.

Add tests for:

- query routing
- portfolio-only path
- portfolio-plus-sentiment-stub path
- Portfolio Agent bounded planner outputs
- no-trading guardrails
- missing research behavior
- schema validation

Exit criteria:

- Deterministic suite passes without live OpenD, Neo4j, Pinecone, or hosted LLM
  calls.
- Live OpenD connector tests remain opt-in.
- Docs describe V1 as complete and V2 as active.

## Deferred Until After V2 Skeleton

- Real Neo4j GraphRAG ingestion.
- Real GraphRAG retrieval.
- Pinecone memory.
- Official MCP SDK/client runtime migration.
- Crypto account ingestion.
- OTC quote fallback provider.
- Scheduled daily checks.
- Rich React frontend migration.

These are still part of the long-term architecture. They should be built after
the V2 Investment Agent and subagent contracts are stable.

## Next Prompt Session

The next implementation-focused session should start with:

1. `InvestmentAgentState` and V2 contract models.
2. Minimal LangGraph supervisor.
3. Sentiment Agent stub contract.
4. Portfolio Agent bounded planning design.

Do not start with Neo4j ingestion. GraphRAG should be designed against the
Sentiment Agent contract, not before it.
