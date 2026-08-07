# Requirements

## Product Requirements

### PR-1: Investment Branch First

The system must implement the Investment Agent branch before any budgeting, expenses, savings, or main finance orchestrator work.

### PR-2: Personal Portfolio Focus

The system must optimize for one user's own portfolio, preferences, and long-term investment policy.

### PR-3: No Trading

The system must never place trades, prepare executable orders, or expose hidden trade execution paths.

### PR-4: Source-Backed Analysis

Portfolio facts, market prices, research claims, and recommendations must be grounded in cited data sources.

### PR-5: Adaptive Query Handling

The system must adapt to the user's query and select suitable analysis modes, tools, and subagent calls.

### PR-6: Portfolio Review Workflow

The completed V1.1 workflow is a portfolio-only `review my portfolio` path.

It includes:

- Current holdings
- Cash
- Allocation
- Concentration
- Risk diagnostics
- Performance analysis where history exists
- Missing data
- Portfolio-data source context

The V1.2 Investment Agent workflow adds:

- Query-aware routing
- Portfolio Agent bounded-planning calls
- Sentiment Agent stub calls when research context would be useful
- Investment Agent synthesis
- Guardrail review

The V1.3 deterministic dashboard lane adds:

- Backend OpenD connection status
- Latest SQL-backed portfolio dashboard snapshot
- Manual refresh of OpenD context, metrics, and SQL history
- Frontend dashboard update without invoking Portfolio Agent, Investment Agent,
  a sentiment agent, or an LLM

### PR-7: Investment Policy Statement

Optimization recommendations require an IPS. Factual portfolio queries may proceed without one.

### PR-8: No Chat-Based IPS Edits

The IPS must not be directly edited through chat.

### PR-9: No Confidence Scores

The system must not produce numeric or label-based confidence scores. It should express uncertainty through missing data, limitations, assumptions, and evidence quality.

### PR-10: Backend Contracts Before Frontend Expansion

The backend should finalize agents, tooling, memory, orchestration, output formats, and requirements before expanding the frontend. Terminal output remains acceptable for backend validation.

Current exception: a minimal local chatbot exists to exercise backend contracts.
It should remain contract-driven rather than becoming the source of truth.

## Functional Requirements

### FR-1: OpenD Read-Only Integration

The system must connect to local OpenD through `moomail-opend-mcp` and retrieve read-only current portfolio data.

### FR-2: OpenD Field Exploration

OpenD capabilities and fields must be explored before final SQL schema design.

### FR-3: Portfolio History Store

The system must persist portfolio snapshots and portfolio history in SQL once schema design is complete.

### FR-4: Deterministic Metrics

Financial metrics must be computed by deterministic Python functions exposed through MCP.

Cash metrics must distinguish literal cash, explicit cash-equivalent holdings,
and any configured auto-invested fund-assets assumption.

### FR-5: Portfolio Agent

The Portfolio Agent must return structured portfolio diagnostics and performance analysis.

### FR-6: Sentiment Agent

V1.2 must include a Sentiment Agent stub with the same task and response shape
expected from the future GraphRAG-backed Sentiment Agent. It must not fabricate
research.

### FR-7: Curated Research Corpus

The first real research retrieval implementation must use manually populated
documents only. Daily checks and event-triggered ingestion are future features.

### FR-8: GraphRAG

The future research system must use Neo4j for entity and relationship metadata,
plus vector retrieval for semantic document chunks. Neo4j GraphRAG is deferred
until after the V1.2 Investment Agent and Sentiment Agent contracts are stable.

### FR-9: Separate Memory and Research Stores

Pinecone long-term memory must remain separate from Neo4j GraphRAG research retrieval.

### FR-10: Long-Term Memory

The future Investment Agent must use long-term memory for durable context such
as preferences, theses, prior recommendations, review summaries, risk concerns,
and agent observations. V1.2 may keep local/file-backed memory placeholders.

### FR-11: Memory Scope

Portfolio Agent and Sentiment Agent must not directly access Pinecone.

### FR-12: Audit Logs

Every run must produce an audit record with tool calls, timestamps, source IDs, assumptions, guardrail result, and a simple output summary.

### FR-13: Structured Outputs

All MCP tools and subagents must return structured JSON-compatible objects.

### FR-14: Citations

Citations must reference chunk-level evidence and parent document metadata where applicable.

### FR-15: Missing Data Handling

The system must explicitly report missing or stale data. Critical missing data must block recommendations.

Unsupported quote rows, such as OpenD rejecting an OTC market snapshot while the
position row is available, are non-critical warnings.

### FR-16: Guardrail Node

The V1.2 Investment Agent must run a final guardrail/review node before producing
the final response.

### FR-17: V1.2 Investment Agent Routing

The V1.2 Investment Agent must decide whether to call Portfolio Agent, Sentiment
Agent stub, or both. Portfolio Agent must not directly call Sentiment Agent.

### FR-18: V1.2 Bounded Portfolio Planning

The V1.2 Portfolio Agent must produce a bounded context plan before executing
portfolio tools. Execution of OpenD, SQL, and metric tools remains deterministic
after the plan is selected.

### FR-19: Deterministic Portfolio Data Lane

The web app must be able to load portfolio status, latest dashboard state, and
manual refresh results through backend APIs without starting an agent run. The
backend owns MCP access through the gateway; the frontend must never call MCP
directly.

### FR-20: V1.4 Structured Evidence Packets

The Investment Agent must send a bounded `PortfolioRequest` when portfolio
evidence is needed. The Portfolio Agent must resolve logical asset hints,
produce a validated `PortfolioEvidencePlan`, execute deterministic freshness
and tool policy, and return a `PortfolioEvidencePacket` that separates facts,
derived metrics, position changes, detected patterns, portfolio-only
interpretation, limitations, sentiment-context needs, warnings, and tool refs.

### FR-21: V1.5 Evidence-Gated Investment Routing

Investment-first routing must use a bounded deterministic portfolio baseline
and an explicit typed route decision. A direct answer is permitted only when
deterministic validation proves complete capability coverage, compatible
freshness and time windows, and valid cited evidence references. Otherwise the
Investment Agent may delegate only through its bounded planner-supplied
Portfolio request or return an explicit limitation.

The original user query and `PortfolioRequest.source_query` must be checked
before subagent calls so planner rewriting cannot remove trade/order intent or
change the assigned mission.

V1.5.1 satisfies bounded deterministic baseline construction. V1.5.2 satisfies
Investment-only public web routing, baseline-before-planner graph consumption,
one-call covered direct answers, deterministic evidence-gated direct versus
delegated routing, bounded fallback, and pre-subagent original-query/source
integrity enforcement. V1.5.3 satisfies deterministic Portfolio evidence-plan
compilation, explicit deterministic-only versus interpretation-required
handoffs, one-call Portfolio analysis, and the normal two-call delegated budget.
V1.5.4 satisfies provider/token lifecycle instrumentation, live nested
Portfolio trace propagation, sanitized opt-in LangSmith spans, stable
run/thread correlation, and controlled diagnostic checkpoint summaries.

## Non-Functional Requirements

### NFR-1: Local-First

Development and local execution should be local-first.

Python execution must use the project-local `.venv` to avoid interpreter and package drift.

### NFR-2: Privacy

Brokerage credentials, database credentials, and MCP secrets must remain backend-only.

### NFR-3: Auditability

The system must be inspectable through structured logs, source IDs, tool calls, and generated summaries.

### NFR-4: Determinism for Math

Financial calculations must be reproducible and unit-tested.

### NFR-5: Graceful Degradation

If the Sentiment Agent fails, quantitative-only analysis may proceed if appropriate. If portfolio retrieval fails, portfolio recommendations must be blocked.

### NFR-6: Source Quality

Research retrieval must rank source quality. Filings and company reports outrank transcripts, shareholder letters, reputable research, and commentary.

### NFR-7: Data Freshness

Every tool response should include `as_of`, `freshness_status`, and warnings where relevant.

### NFR-8: Schema Validation

Agent and tool outputs must be validated with Pydantic models or equivalent schema validation.

### NFR-9: Separated Observability Surfaces

Every outbound LLM call must be representable by sanitized provider-neutral
telemetry covering purpose, model, timing, usage when available, status, retry,
and safe error category. User progress must use a smaller plain-language event
vocabulary than internal developer/audit traces. Neither surface may expose raw
prompts, hidden reasoning, credentials, account identifiers, or raw broker
payloads.

LangSmith export is explicitly enabled and sampled independently from MooMail
trace. External spans accept only allowlisted correlation, route, model, usage,
timing, status, capability, tool, and error-category metadata. Export or
checkpoint failures must not fail chat or mutate deterministic dashboard state.

## Security and Guardrail Requirements

### SG-1: No Trade Tools

No MCP server may expose trade placement, order modification, order cancellation, or executable order preparation.

### SG-2: No Unsupported Claims

The final response must not contain unsupported portfolio facts, prices, or research claims.

### SG-3: IPS Compliance

Recommendations must be checked against the canonical IPS.

### SG-4: Memory Precedence

IPS, current portfolio data, and cited source data outrank Pinecone memory.

### SG-5: No Hidden Reasoning Storage

Audit logs must not store hidden model reasoning.

### SG-6: Over-Specific Sizing Check

The guardrail node must flag exact share-count or executable trade-style recommendations.

### SG-7: Scope Control

The first real research scope is held portfolio stocks and Investment
Agent-selected tickers/themes, unless a later requirement expands the scope.

## Data Requirements

### DR-1: Portfolio Identity

Use `portfolio_id` as the canonical portfolio unit, even with one portfolio in v1.

### DR-2: Account Identity

Use `account_id` for brokerage accounts, including provider metadata, base currency, and account type.

### DR-3: Asset Identity

Use internal `asset_id` records. Do not rely on ticker alone.

### DR-4: Currency

Store currency on every portfolio value snapshot, position state, allocation
weight row, and asset record where applicable.

### DR-5: Timestamps

Store system timestamps in UTC and preserve source timestamps separately.

### DR-6: Snapshot Frequency

V1.1 stores snapshots on demand when portfolio reviews run. Scheduled daily snapshots are future work.

### DR-7: Transactions Optional

Transaction-level history is not mandatory for v1.

### DR-8: Metric Versioning

Portfolio-history should store only the derived metric values needed for
historical portfolio reconstruction and display, especially overall portfolio
weights. It does not need to persist metric version, input scope, or full source
input artifacts in V1.

### DR-8A: Position State History

Position state history must stay compact. Insert a new position-state row when
quantity, average cost, side, active status, or asset identity changes. Update
the active row when only market price, market value, unrealized P&L, or
last-observed timestamp changes.

### DR-8B: Portfolio Value and Weight History

Portfolio growth must be stored as daily portfolio value snapshots. Historical
allocation must be stored as child portfolio weight rows rather than a JSON
dictionary or full stock-price history table.

### DR-8C: Raw Source Storage

Portfolio-history must not store broad raw OpenD source-observation blobs in V1.1
when the same information is already parsed into first-class tables. Missing
data and unsupported quote problems should be stored as data-quality events.

### DR-9: Document Metadata

Research documents require:

- Ticker
- Company
- Document type
- Source
- Date
- Author or publisher
- Ingestion date
- Ticker/entity mapping quality

### DR-10: Document Versioning

Source documents should be versioned by content hash or version metadata.

### DR-11: Memory Lifecycle

Memories should be marked active, inactive, or superseded rather than hard-deleted, unless explicit deletion is requested.

## Evaluation Requirements

### ER-1: Correctness

The system must be truthful and source-backed.

### ER-2: Reasoning Quality

The system should provide sound reasoning based on current data, IPS constraints, and long-term memory. It does not need a separate process for learning from prior recommendations based on later news.

### ER-3: Test Set

Create 20 to 30 curated evaluation queries covering:

- Portfolio review
- Risk check
- Holding deep dive
- Allocation
- Missing data
- RAG retrieval
- Guardrail behavior

### ER-4: Tool Tests

Financial metric tools must have unit tests with known inputs and expected outputs.

### ER-5: RAG Golden Tests

Known document queries should retrieve expected companies, claims, risks, and citations.

### ER-6: Hallucination Tests

Use adversarial queries that ask for unsupported prices, nonexistent holdings, exact trade orders, or facts outside the corpus.

### ER-7: No Silent Failures

The following must never fail silently:

- OpenD connection failure
- Stale quotes
- Missing SQL history
- Empty RAG retrieval
- Failed metric calculation
- Missing IPS for optimization
- Guardrail failure
- Backend chat stream failure

The local chat frontend must surface backend stream failures in the chat rail and
technical trace so the user does not need to inspect the terminal traceback to
understand that a run failed.

## V1.1 Acceptance Criteria

V1.1 is complete when the system can run a local portfolio-only
review that uses:

- Live read-only MooMoo/OpenD securities account data
- Current holdings, literal cash, optional configured auto-invested fund assets,
  and quote warnings
- SQLite portfolio value snapshots, allocation weight history, compact position
  states, data-quality events, audit summaries, and run summaries
- Deterministic finance metrics
- Portfolio-only LLM evaluation with structured output recovery
- Canonical IPS checks where recommendations or optimization framing are used
- Guardrail review
- Clear missing-data warnings
- Terminal output and the local TypeScript/static chatbot frontend

V1.1 intentionally does not require a LangGraph Investment Agent, Pinecone, Neo4j
GraphRAG, real research document ingestion, crypto account ingestion, scheduled
checks, or OTC quote fallback.

See [V1_1_FINALIZATION_PLAN.md](V1_1_Tasks/V1_1_FINALIZATION_PLAN.md) for the V1.1 closeout.

## V1.2 Acceptance Criteria

V1.2 is complete when the system can run a local Investment Agent flow that:

- Uses a thin LangGraph supervisor.
- Routes portfolio-only questions to Portfolio Agent.
- Routes full review or research-sensitive questions to Portfolio Agent plus
  Sentiment Agent stub.
- Converts Portfolio Agent from a fixed pipeline into a bounded-planning path
  while preserving V1.1 behavior as the broad-review default.
- Synthesizes Portfolio Agent output and Sentiment Agent stub output without
  fabricating research.
- Runs guardrails before final output.
- Streams high-level graph status and errors to the local frontend.
- Keeps deterministic tests passing without live OpenD, Neo4j, Pinecone, or
  hosted LLM calls.
