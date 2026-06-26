# Protocol

## Runtime Flow

The Investment Agent runs as a thin LangGraph state machine. Each run
receives a user query and produces a structured final report.

```text
1. receive_user_query
2. load_investment_policy
3. plan_investment as a typed InvestmentPlan
4. validate_investment_plan before subagent calls
5. run_portfolio_agent when the plan requests portfolio context
6. route_sentiment from the InvestmentPlan
7. run_sentiment_agent_stub when the plan requests research context
8. synthesize_report
9. run_guardrail_review
10. emit_final_output
11. write_audit_summary
```

Memory retrieval and writes remain part of the long-term design. The current
runtime does not connect Pinecone or another long-term memory store.

## Status Events

The backend should stream operational status events. These are for user experience and debugging, not hidden reasoning.

Example events:

```json
{
  "event_type": "status",
  "run_id": "run_123",
  "status": "retrieving_portfolio",
  "message": "Retrieving current holdings and cash balances.",
  "timestamp": "2026-05-23T00:00:00Z"
}
```

Recommended statuses:

- `loading_policy`
- `retrieving_memory`
- `planning_investment`
- `investment_plan_ready`
- `validating_investment_plan`
- `investment_plan_validated`
- `checking_opend_connection`
- `retrieving_portfolio`
- `retrieving_quotes`
- `planning_portfolio_context`
- `planning_portfolio_evidence`
- `portfolio_evidence_plan_validated`
- `asset_resolution_resolved`
- `asset_resolution_ambiguous`
- `asset_resolution_not_in_portfolio`
- `analyzing_allocation`
- `calculating_risk`
- `selecting_research_scope`
- `calling_sentiment_stub`
- `checking_contradictions`
- `synthesizing_report`
- `checking_guardrails`
- `saving_audit_summary`
- `complete`
- `failed`

Status events must not reveal private chain-of-thought. They may reveal tool
names, high-level steps, bounded input/output summaries, skipped-tool reasons,
warnings, errors, and operational progress.

Public trace metadata is allowlisted. Allowed metadata includes phase,
planner mode, subagent need booleans, portfolio task intent, bounded planner
summary counts, result, guardrail status, check count, tool call kind,
retrieval status, missing document count, warning count, pass/fail status,
output status, and error location. Denied metadata includes hidden
chain-of-thought, raw prompts, developer/system prompts, API keys, secrets,
tokens, passwords, raw broker account IDs, and scratchpad fields.

## Stream Payloads

The local chat server streams newline-delimited JSON payloads. Each line is one
of:

- `status`: high-level operational progress.
- `final`: completed structured agent state, including `investment_plan` for
  Investment Agent runs.
- `error`: failed run details for the chat rail and technical trace.

Example error payload:

```json
{
  "type": "error",
  "error": {
    "error_type": "OpenDConnectionError",
    "message": "positions query failed: Network interruption",
    "timestamp": "2026-06-03T00:00:00Z",
    "traceback": ["Traceback lines for local debugging"]
  }
}
```

The frontend must stop the loading state when it receives `error`, show a failed
chat status, and render the error details in the trace panel. Traceback lines are
local operational diagnostics; they must not include hidden model reasoning.

## Chat Agent Names

The chat API accepts canonical agent values `portfolio` and `investment`.
For frontend compatibility it also accepts `portfolio_agent` and
`investment_agent`, normalizing those aliases before routing the request.

## Portfolio Data Lane Protocol

The deterministic portfolio data lane supports dashboard status, page load, and
manual refresh. This lane is not an agent query and must not call an LLM.

The frontend calls backend APIs only. The backend calls MCP through the
gateway.

Implemented backend routes:

- `GET /api/portfolio/status`
- `GET /api/portfolio/dashboard`
- `POST /api/portfolio/refresh`

### `PortfolioConnectionStatus`

Purpose: show whether OpenD and the backend data lane are ready.

Required fields:

- `ok`
- `status`: `connected`, `degraded`, or `disconnected`
- `checked_at`
- `message`
- `source`
- `warnings`
- `error`

The response must be frontend-safe: no API keys, passwords, raw account secrets,
broker login material, or hidden backend config.

### `PortfolioDashboardSnapshot`

Purpose: render current portfolio state without asking an agent to decide
whether current OpenD data is needed.

Required fields:

- `portfolio_id`
- `as_of`
- `last_updated_at`
- `freshness_status`
- `connection`
- `portfolio_snapshot`
- `metrics`
- `history_status`
- `latest_state`
- `storage_result`
- `warnings`
- `errors`
- `source_summary`

Balances should make configured cash sweep treatment explicit. Unsupported
quotes, stale data, missing data, and cash-sweep assumptions should be surfaced
as displayable warnings or data-quality events.

The dashboard endpoint reads SQL and calculates metrics from the stored
snapshot. It does not call OpenD. Explicit refresh is the boundary that performs
OpenD retrieval.

### `PortfolioRefreshResult`

Purpose: represent a manual or backend-triggered refresh.

Required fields:

- `status`: `refreshed` or `failed`
- `dashboard`
- `connection`
- `storage_result`
- `warnings`
- `errors`

Refresh sequence:

```text
1. Check OpenD connection.
2. Retrieve latest funds, positions, and normalized portfolio context.
3. Calculate finance metrics.
4. Update SQL portfolio history.
5. Return a dashboard snapshot and refresh metadata.
```

If refresh fails, return a structured sanitized error and the last-known
dashboard snapshot when one exists. Mark that snapshot stale rather than hiding
the failure.

## Agent State

High-level state shape:

```json
{
  "run_id": "run_123",
  "user_query": "Review my portfolio",
  "mode": "review",
  "portfolio_id": "portfolio_default",
  "ips": {},
  "investment_plan": {},
  "query_plan": {},
  "memory_context": [],
  "portfolio_packet": {},
  "sentiment_scope": [],
  "sentiment_packet": {},
  "synthesis": {},
  "guardrail_result": {},
  "final_report": {},
  "warnings": [],
  "audit": {}
}
```

## Investment Plan

The Investment Agent routes from a typed `InvestmentPlan` before subagent calls:

```json
{
  "mode": "review",
  "needs_portfolio_agent": true,
  "needs_sentiment_agent": true,
  "freshness_requirement": "latest_required",
  "portfolio_request": {
    "task_intent": "full_review",
    "asset_hints": [],
    "output_goals": [
      "snapshot",
      "allocation_context",
      "risk_context",
      "portfolio_patterns"
    ],
    "freshness_requirement": "latest_required",
    "source_query": "Review my portfolio"
  },
  "sentiment_task": {
    "tickers": [],
    "themes": [],
    "key_questions": []
  },
  "logical_asset_hints": [],
  "answer_constraints": ["No trade execution."]
}
```

The Investment Agent owns this plan. The current runtime adapts
`portfolio_request` to the older `query_plan`/`PortfolioTask` path for the
default chat route. The Portfolio Agent can also accept bounded
`PortfolioRequest` input directly and plan portfolio evidence from it. Portfolio
Agent may suggest sentiment candidates in its response, but it must not call
Sentiment Agent directly.

## Portfolio Evidence Plan

Portfolio Agent plans bounded portfolio evidence from `PortfolioRequest` into
`PortfolioEvidencePlan` before selecting tool scope:

```json
{
  "task_intent": "what_changed",
  "resolved_assets": [
    {
      "input": "AMZN",
      "canonical_symbol": "US.AMZN",
      "sql_asset_id": "asset_amzn",
      "display_name": "Amazon.com Inc.",
      "resolution_status": "resolved",
      "warnings": [],
      "source": "fixture"
    }
  ],
  "history_queries": [
    "history_status",
    "latest_state",
    "portfolio_growth",
    "allocation_history",
    "position_state_changes"
  ],
  "metric_groups": ["performance"],
  "needs_current_values": false,
  "history_window": "90d",
  "freshness_requirement": "history_only",
  "position_change_scope": "asset_scoped",
  "persistence_mode": "skip",
  "pattern_detectors": ["large_position_changes", "average_cost_shifts"],
  "warnings": []
}
```

The Portfolio Agent planner must not emit sentiment routing or final-thesis
fields. The current runtime adapts this evidence plan into `PortfolioContextPlan`
for deterministic execution; direct `PortfolioEvidencePacket` assembly remains
V1.4.4 work.

## Portfolio Context Plan

Portfolio Agent still uses a bounded context plan as the current execution
adapter:

```json
{
  "needs_current_snapshot": true,
  "needs_sql_history": true,
  "history_queries": ["history_status", "position_state_changes"],
  "asset_ids": ["asset_amzn"],
  "canonical_symbols": ["US.AMZN"],
  "tickers": ["AMZN"],
  "metric_groups": ["performance"],
  "persist_observation": true
}
```

Tool execution remains deterministic after this plan is selected.

## Portfolio Snapshot Schema

Illustrative high-level schema:

```json
{
  "portfolio_id": "portfolio_default",
  "as_of": "2026-05-23T00:00:00Z",
  "base_currency": "USD",
  "total_value": {
    "amount": 100000.0,
    "currency": "USD",
    "source": "moomoo",
    "as_of": "2026-05-23T00:00:00Z"
  },
  "cash": [
    {
      "account_id": "moomoo_primary",
      "amount": 5000.0,
      "currency": "USD",
      "weight": 0.05
    }
  ],
  "holdings": [
    {
      "asset_id": "asset_aapl_us",
      "ticker": "AAPL",
      "name": "Apple Inc.",
      "asset_type": "equity",
      "exchange": "NASDAQ",
      "currency": "USD",
      "quantity": 10,
      "market_price": 190.0,
      "market_value": 1900.0,
      "portfolio_weight": 0.019,
      "unrealized_pnl": 100.0,
      "sector": "Information Technology",
      "source": "moomoo",
      "as_of": "2026-05-23T00:00:00Z"
    }
  ],
  "data_quality": {
    "freshness_status": "fresh",
    "warnings": []
  }
}
```

Currency should be stored on every balance, quote, position, transaction, and snapshot, even if current analysis defaults to USD.

## Portfolio Agent Packet

```json
{
  "portfolio_id": "portfolio_default",
  "snapshot": {},
  "allocation": {
    "by_asset": [],
    "by_sector": [],
    "by_currency": []
  },
  "performance": {
    "summary": "Portfolio performance summary from available data.",
    "periods": [],
    "benchmark": "SPY",
    "warnings": []
  },
  "risk": {
    "concentration": [],
    "volatility": null,
    "drawdown": null,
    "beta": null,
    "correlation": [],
    "warnings": []
  },
  "candidate_issues": [
    {
      "issue_type": "concentration",
      "description": "Single-position concentration exceeds IPS target.",
      "evidence": [],
      "severity": "medium"
    }
  ],
  "data_quality": {
    "freshness_status": "fresh",
    "missing_fields": [],
    "warnings": []
  }
}
```

Severity labels are operational triage, not confidence scores.

## Sentiment Packet

Current stub response:

```json
{
  "retrieval_status": "not_implemented",
  "task": {
    "tickers": ["AAPL"],
    "companies_entities": [],
    "themes": ["portfolio thesis"],
    "time_window": "1y",
    "requested_evidence_types": ["earnings_transcript", "annual_report"],
    "key_questions": ["What does recent source-backed research say about AAPL?"],
    "reason": "Investment Agent requested sentiment/research context.",
    "candidate_refs": [],
    "warnings": []
  },
  "scope": [
    {
      "ticker": "AAPL",
      "reason": "Material holding above threshold."
    }
  ],
  "holdings": [],
  "portfolio_level_sentiment": {
    "summary": "GraphRAG sentiment retrieval is not implemented. No sentiment stance, company claims, or citations were produced.",
    "themes": [],
    "risks": [],
    "citations": []
  },
  "contradictions": [],
  "open_questions": [],
  "source_metadata": {},
  "missing_documents": [
    {
      "ticker": "AAPL",
      "entity": null,
      "document_type": "earnings_transcript",
      "reason": "Neo4j GraphRAG is not implemented. The sentiment stub cannot retrieve earnings transcript evidence."
    }
  ],
  "citations": [],
  "data_quality": {
    "freshness_status": "unknown",
    "missing_fields": ["graph_rag_corpus", "neo4j_research_store"],
    "warnings": [
      "Sentiment Agent is a stub; no research retrieval was performed.",
      "Neo4j GraphRAG is not implemented."
    ]
  },
  "warnings": ["Sentiment Agent is a stub.", "Neo4j GraphRAG is not implemented."]
}
```

Sentiment stance is qualitative: `positive`, `mixed`, `negative`, or `unclear`.

The current Sentiment Agent returns this shape as a stub. It should use
`retrieval_status: "not_implemented"` or `retrieval_status: "missing_corpus"`
and must not invent research claims, citations, source metadata, or sentiment.
When GraphRAG is implemented, the same packet can include populated holdings,
portfolio-level sentiment, contradictions, open questions, source metadata, and
citations grounded in retrieved documents.

## Citation Schema

```json
{
  "citation_id": "cite_123",
  "source_type": "earnings_transcript",
  "title": "Q4 2025 Earnings Call",
  "publisher": "Company",
  "document_date": "2026-02-01",
  "ingestion_date": "2026-05-23",
  "ticker": "AAPL",
  "company": "Apple Inc.",
  "chunk_id": "chunk_abc",
  "document_id": "doc_xyz",
  "location": {
    "page": null,
    "section": "Prepared remarks"
  },
  "snippet": "Short evidence snippet or summary.",
  "source_quality": "primary"
}
```

Final answers should cite chunk-level evidence and expose parent document metadata.

## Memory Record

```json
{
  "memory_id": "mem_123",
  "memory_type": "portfolio_review_summary",
  "scope": {
    "portfolio_id": "portfolio_default",
    "tickers": ["AAPL", "MSFT"]
  },
  "content": "Concise durable summary.",
  "created_at": "2026-05-23T00:00:00Z",
  "expires_at": null,
  "status": "active",
  "source_run_id": "run_123",
  "requires_user_approval": false
}
```

Memory types:

- `user_preference`
- `investment_thesis`
- `past_recommendation`
- `decision_record`
- `portfolio_review_summary`
- `risk_concern`
- `watchlist_interest`
- `agent_observation`

User preference and thesis changes require explicit approval. Routine agent-generated review summaries may be written without approval if clearly labeled.

## Guardrail Result

```json
{
  "passed": true,
  "checks": [
    {
      "check": "no_trading",
      "passed": true,
      "message": "No trade execution or executable order instructions detected."
    },
    {
      "check": "source_coverage",
      "passed": true,
      "message": "Portfolio facts and research claims include source references."
    }
  ],
  "required_revisions": [],
  "blocked_reason": null
}
```

Required checks:

- `no_trading`: no executable order-placement language.
- `no_exact_share_count_trading`: no exact share/contract count trading instruction.
- `unsupported_research_claims`: no research/sentiment claims when Sentiment
  Agent retrieval is missing or `not_implemented`.
- `unsupported_price_or_portfolio_facts`: portfolio facts require a Portfolio
  Agent packet.
- `missing_ips_for_optimization`: optimization or rebalancing recommendations
  require an IPS.
- `missing_sentiment_visibility`: missing GraphRAG/sentiment limitations must
  be visible in final output.

## Final Report Shape

```json
{
  "run_id": "run_123",
  "mode": "review",
  "title": "Portfolio Review",
  "as_of": "2026-05-23T00:00:00Z",
  "summary": "Short source-backed investment summary.",
  "portfolio_snapshot": {},
  "portfolio_analysis": {},
  "sentiment_analysis": {},
  "recommendations": [
    {
      "title": "Reduce concentration risk over time",
      "rationale": "Reasoning tied to portfolio metrics and research evidence.",
      "supporting_evidence": [],
      "constraints": [],
      "missing_data": []
    }
  ],
  "missing_data": [],
  "assumptions": [],
  "citations": [],
  "disclaimer": "This is investment analysis for personal decision support, not licensed financial advice."
}
```

Recommendations should avoid exact share counts or executable orders. Allocation ranges and risk constraints are preferred.

## Audit Record

```json
{
  "run_id": "run_123",
  "timestamp": "2026-05-23T00:00:00Z",
  "user_query": "Review my portfolio",
  "mode": "review",
  "tools_called": [],
  "data_timestamps": [],
  "source_ids": [],
  "assumptions": [],
  "guardrail_result": {},
  "output_summary": "Concise summary of the final output.",
  "memory_updates": []
}
```

Audit records should store:

- User query
- Mode
- Tool calls
- Tool inputs and outputs where safe
- Data timestamps
- Source IDs
- Assumptions
- Guardrail result
- Simple output summary
- Proposed or completed memory updates

Audit records should not store hidden model reasoning. Full final responses do not need to be stored.
