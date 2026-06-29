# Task V1.4.5: Trace, Evaluation, And Closeout

## Goal

Close V1.4 by making planner decisions visible, adding golden prompt/evaluation
coverage, updating docs, and proving the new structured planning path does not
regress the working V1.3 runtime.

This task is the release gate for V1.4, not a new feature bucket.

## Status

Complete as of 2026-06-29.

## Implemented In

- `src/moomail_finance_ai/investment_agent.py`
  - Investment Agent runtime now passes the structured `PortfolioRequest` into
    Portfolio Agent calls instead of relying only on the legacy task adapter.
  - Sanitized trace includes `portfolio_evidence_plan_ready`,
    `portfolio_evidence_packet_ready`, and deterministic tool execution phases.
- `src/moomail_finance_ai/chat_api.py`
  - Portfolio Agent chat payloads expose the separated evidence packet under
    `final_report.portfolio_analysis.evidence_packet`.
- Tests
  - Added golden runtime coverage for recent-purchase queries sending logical
    asset hints and `history_only` bounded requests.
  - Added chat trace assertions for evidence-planner and deterministic
    execution phases.
  - Added deterministic Portfolio Agent execution, stale cache, no-OpenD
    history-only, evidence packet, LLM-boundary, dashboard independence, and
    full-suite regressions.
- Documentation
  - Updated V1.4 task closeout, current-truth architecture/agent/protocol docs,
    testing map, action plan, and decision log to reflect implemented V1.4.4
    and V1.4.5 reality.

## Exit Criteria

1. Frontend/terminal trace shows Investment planning, validation, asset
   resolution, Portfolio evidence planning, deterministic policy, tool
   execution, and final guardrail phases.
2. Golden prompt tests prove the correct agent owns each decision.
3. Regression tests prove no trade execution, no hidden broker-id assumptions,
   and no direct Investment Agent OpenD access.
4. Docs reflect implemented reality, remaining stubs, and future work.
5. Full non-live deterministic test suite passes.

## Dependency Graph

```text
V1.4.0 contracts
  ├── V1.4.1 asset resolution and validation
  ├── V1.4.2 Investment planner
  ├── V1.4.3 Portfolio evidence planner
  └── V1.4.4 deterministic execution and evidence packet
      ├── A. Trace/status surface updates
      ├── B. Golden prompt evaluation suite
      ├── C. Safety/regression tests
      ├── D. Docs and decision log closeout
      └── E. Final test gates
```

## Task Breakdown By Exit Criteria

### EC1: Trace shows planner and policy decisions

| Task | Description | Depends on | Test |
| --- | --- | --- | --- |
| A | Extend sanitized trace rendering for Investment planner output summary. | V1.4.2 | `test_chat_trace_shows_investment_plan_summary` |
| A1 | Extend trace rendering for asset resolution status. | V1.4.1 | `test_chat_trace_shows_asset_resolution_status` |
| A2 | Extend trace rendering for Portfolio evidence plan summary. | V1.4.3 | `test_chat_trace_shows_portfolio_evidence_plan` |
| A3 | Extend trace rendering for freshness policy choice and actual/skipped tools. | V1.4.4 | `test_chat_trace_shows_freshness_policy_and_tool_execution` |
| A4 | Ensure trace excludes hidden chain-of-thought, prompts, secrets, raw account numbers, and raw broker payloads. | A through A3 | `test_planner_trace_is_sanitized` |

### EC2: Golden prompts prove ownership boundaries

| Task | Description | Depends on | Test |
| --- | --- | --- | --- |
| B | Add golden prompt: “How much cash/effective cash do I have?” Investment requests portfolio fact, Portfolio uses cash/effective-cash evidence. | V1.4.2, V1.4.3 | `test_golden_cash_query_uses_portfolio_fact_request` |
| B1 | Add golden prompt: “What price did I buy recent AMZN shares at?” Investment sends logical `AMZN`, Portfolio resolves and scopes position-state changes. | V1.4.1 through V1.4.4 | `test_golden_recent_purchase_query_uses_asset_resolution_and_position_changes` |
| B2 | Add golden prompt: broad portfolio review requests Portfolio Agent and Sentiment stub, with Investment deciding sentiment need. | V1.4.2 | `test_golden_full_review_routes_sentiment_from_investment_agent` |
| B3 | Add golden prompt: invalid/unheld ticker returns explicit unresolved/not-in-portfolio warning. | V1.4.1 | `test_golden_unheld_ticker_returns_resolution_warning` |
| B4 | Add golden prompt: history-only query avoids OpenD. | V1.4.4 | `test_golden_history_only_query_skips_opend` |

### EC3: Safety and runtime regressions are covered

| Task | Description | Depends on | Test |
| --- | --- | --- | --- |
| C | Prove trade/order requests are blocked before tool execution. | V1.4.1, V1.4.2 | `test_trade_execution_request_blocked_before_subagent_calls` |
| C1 | Prove Investment Agent does not call OpenD directly by default. | V1.4.2, V1.4.4 | `test_investment_agent_cannot_call_opend_directly` |
| C2 | Prove Portfolio Agent does not invoke Sentiment Agent or decide sentiment routing. | V1.4.3 | `test_portfolio_agent_does_not_route_sentiment` |
| C3 | Prove finance math and position-change inference are deterministic and not LLM-generated. | V1.4.4 | Existing SQL/metrics tests plus `test_portfolio_llm_not_used_for_math` |
| C4 | Keep deterministic dashboard lane independent from agent path. | V1.4.4 | Existing `tests/test_portfolio_data_service.py` plus no-agent assertions |

### EC4: Documentation reflects implemented reality

| Task | Description | Depends on | Test |
| --- | --- | --- | --- |
| D | Update `ACTION_PLAN.md` with V1.4 implementation status and remaining future work. | V1.4.0 through V1.4.4 | Docs review |
| D1 | Update `AGENTS.md` with actual implemented planner boundaries. | V1.4.0 through V1.4.4 | Docs review |
| D2 | Update `ARCHITECTURE.md` and `PROTOCOL.md` with final request/plan/evidence packet contracts. | V1.4.0 through V1.4.4 | Docs review |
| D3 | Update `TESTING.md` with new planner/asset/evidence test ownership map. | V1.4.0 through V1.4.4 | Docs review |
| D4 | Add decision-log closeout with designed versus actual, verification, limitations, and next work. | E | Docs review |
| D5 | Add/update docs regression tests if the project keeps doc tests for task status. | D through D4 | `tests/test_historical_docs.py` or new docs test |

### EC5: Final test gates pass

| Task | Description | Depends on | Test |
| --- | --- | --- | --- |
| E | Run targeted planner and asset-resolution tests. | A through C | Targeted commands below |
| E1 | Run Portfolio Agent and Investment Agent tests. | A through C | Targeted commands below |
| E2 | Run dashboard/data-lane tests. | C4 | Targeted commands below |
| E3 | Run full deterministic suite excluding live tests. | D | `.venv/bin/python -m pytest tests --ignore=tests/live -q` |
| E4 | Run `git diff --check`. | D | Whitespace gate |

## Tests To Add Or Update

- `tests/test_chat_app.py`
- `tests/test_investment_planner.py`
- `tests/test_asset_resolver.py`
- `tests/test_portfolio_planner.py`
- `tests/test_portfolio_agent.py`
- `tests/test_investment_agent.py`
- `tests/test_portfolio_data_service.py`
- docs regression tests as needed

## Required Test Commands

```bash
.venv/bin/python -m pytest tests/test_investment_planner.py tests/test_asset_resolver.py -q
.venv/bin/python -m pytest tests/test_portfolio_planner.py tests/test_portfolio_agent.py -q
.venv/bin/python -m pytest tests/test_investment_agent.py tests/test_chat_app.py -q
.venv/bin/python -m pytest tests/test_portfolio_data_service.py -q
.venv/bin/python -m pytest tests --ignore=tests/live -q
git diff --check
```

## Verification

Run on 2026-06-29:

```text
.venv/bin/python -m pytest tests/test_investment_planner.py tests/test_asset_resolver.py -q
23 passed in 0.05s

.venv/bin/python -m pytest tests/test_portfolio_planner.py tests/test_portfolio_agent.py -q
51 passed in 0.83s

.venv/bin/python -m pytest tests/test_investment_agent.py tests/test_chat_app.py -q
22 passed, 1 warning in 5.69s

.venv/bin/python -m pytest tests/test_portfolio_data_service.py -q
7 passed, 1 warning in 0.51s

.venv/bin/python -m pytest tests --ignore=tests/live -q
251 passed, 1 warning in 8.77s

git diff --check
passed
```

The warnings are the existing LangGraph dependency deprecation warning.

Not run:

- `tests/live`: opt-in live connector/OpenD tests are outside the deterministic
  V1.4 closeout gate.

## Remaining

No remaining exit criteria for V1.4.5. Future work remains V1.5+ scope:
structured-output LLM planners, richer Investment Agent synthesis, real
Sentiment Agent GraphRAG retrieval, Pinecone memory, and frontend redesign.

## Notes

- Do not mark V1.4 complete if the planner path is only documented but not wired
  into Investment Agent and Portfolio Agent runtime behavior.
- Keep Sentiment Agent as a stub unless a separate later version explicitly
  starts GraphRAG implementation.
