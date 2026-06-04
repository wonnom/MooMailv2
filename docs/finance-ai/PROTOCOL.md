# Protocol

## Runtime Flow

The Investment Agent should run as a LangGraph state machine. Each run receives a user query and produces a structured final report.

```text
1. receive_user_query
2. classify_query
3. load_investment_policy
4. retrieve_memory
5. retrieve_portfolio_context
6. decide_sentiment_scope
7. run_portfolio_agent
8. run_sentiment_agent when needed
9. synthesize_report
10. run_guardrail_review
11. emit_final_output
12. write_audit_summary
13. handle_memory_updates
```

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

- `classifying_query`
- `loading_policy`
- `retrieving_memory`
- `checking_opend_connection`
- `retrieving_portfolio`
- `retrieving_quotes`
- `analyzing_allocation`
- `calculating_risk`
- `selecting_research_scope`
- `retrieving_research`
- `checking_contradictions`
- `synthesizing_report`
- `checking_guardrails`
- `saving_audit_summary`
- `complete`
- `failed`

Status events must not reveal private chain-of-thought. They may reveal tool names, high-level steps, and operational progress.

## Stream Payloads

The local chat server streams newline-delimited JSON payloads. Each line is one
of:

- `status`: high-level operational progress.
- `final`: completed structured agent state.
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

## Agent State

High-level state shape:

```json
{
  "run_id": "run_123",
  "user_query": "Review my portfolio",
  "mode": "review",
  "portfolio_id": "portfolio_default",
  "ips": {},
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

Currency should be stored on every balance, quote, position, transaction, and snapshot, even if v1 analysis defaults to USD.

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

```json
{
  "scope": [
    {
      "ticker": "AAPL",
      "reason": "Material holding above threshold."
    }
  ],
  "holdings": [
    {
      "ticker": "AAPL",
      "company": "Apple Inc.",
      "stance": "mixed",
      "thesis_summary": "Summary grounded in retrieved documents.",
      "recent_developments": [],
      "management_tone": "Measured but constructive.",
      "risks": [],
      "catalysts": [],
      "contradictions": [],
      "open_questions": [],
      "citations": []
    }
  ],
  "portfolio_level_sentiment": {
    "summary": "Portfolio-level qualitative exposure summary.",
    "themes": [],
    "risks": [],
    "citations": []
  },
  "data_quality": {
    "retrieval_status": "sufficient",
    "missing_documents": [],
    "warnings": []
  }
}
```

Sentiment stance is qualitative: `positive`, `mixed`, `negative`, or `unclear`.

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

- No trading
- No executable order instructions
- No unsupported portfolio facts
- No unsupported market prices
- Research claims have citations
- IPS compliance
- Stale data warnings
- Missing critical data
- No over-specific position sizing
- Scope compliance

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
