# Task 1: Define V1.2 Contracts

## Goal

Create stable Pydantic contracts for the V1.2 Investment Agent supervisor,
Portfolio Agent bounded planner, Sentiment Agent stub, synthesis, guardrails,
and trace output.

These contracts are the foundation for the rest of V1.2. They should be small,
JSON-compatible, and strict enough that the Investment Agent can route using
structured fields instead of parsing prose.

## Status

Complete as of 2026-06-08.

Implemented in:

- `src/moomail_finance_ai/agent_schemas.py`
- `tests/test_agent_schemas.py`
- `tests/fixtures/agent/`

Verification:

- `python3 -m pytest tests/test_agent_schemas.py -q`
- `PYTHONPATH=src python3 -m pytest tests --ignore=tests/live -q`

## Exit Criteria

1. Investment Agent can route using structured fields rather than parsing prose.
2. Portfolio Agent can tell the Investment Agent which tickers/history changes
   may deserve sentiment review.
3. Sentiment Agent stub can return the same shape the future GraphRAG agent will
   fill.

## Dependency Graph

```text
A. Audit current V1.1 schemas and outputs
   ├── B. Decide V1.2 model module layout
   │   ├── C. Define InvestmentAgentState
   │   │   ├── D. Define InvestmentQueryPlan
   │   │   ├── E. Define PortfolioTask
   │   │   │   └── F. Define PortfolioContextPlan
   │   │   ├── G. Define SentimentTask
   │   │   │   └── H. Define SentimentPacket
   │   │   ├── I. Define SynthesisInput
   │   │   └── J. Define GuardrailReview
   │   └── K. Define trace/status event extensions
   ├── L. Add representative fixtures
   └── M. Add schema validation tests
```

## Task Breakdown By Exit Criteria

### EC1: Investment Agent routes using structured fields

| Task | Description | Depends on | Test |
| --- | --- | --- | --- |
| A | Inventory current `AgentState`, `FinalReport`, `PortfolioAgentResult`, `PortfolioAgentPacket`, `GuardrailResult`, and citation schemas. | None | None, documentation/audit task |
| B | Decide module layout, likely `src/moomail_finance_ai/agent_schemas.py` or a `v2/` package. | A | Import smoke test |
| C | Define `InvestmentAgentState` with run id, query, mode, IPS, query plan, portfolio packet, sentiment packet, synthesis, guardrail result, status events, warnings, and audit refs. | B | `test_agent_investment_state_defaults_and_round_trip` |
| D | Define `InvestmentQueryPlan` with mode, needs flags, routed tasks, missing data, and plan warnings. | C | `test_agent_query_plan_validates_required_flags` |
| D1 | Add enums/literals for mode: `review`, `portfolio_fact`, `risk_check`, `what_changed`, `deep_dive`, `compare`, `unsupported`. | D | Parametrized enum validation test |
| D2 | Add routing invariants: if `needs_sentiment_agent=true`, a `SentimentTask` must be present; if `needs_portfolio_agent=true`, a `PortfolioTask` must be present. | D | Invalid fixture raises validation error |

### EC2: Portfolio Agent can suggest sentiment scope

| Task | Description | Depends on | Test |
| --- | --- | --- | --- |
| E | Define `PortfolioTask`: task type, requested tickers, history window, required outputs, persistence mode, and source query. | B | `test_portfolio_task_defaults_to_review_safe_mode` |
| F | Define `PortfolioContextPlan`: `needs_current_snapshot`, `needs_sql_history`, `history_queries`, `tickers`, `metric_groups`, `persist_observation`, and warnings. | E | `test_portfolio_context_plan_limits_allowed_history_queries` |
| F1 | Add allowed `history_queries`: `history_status`, `latest_state`, `portfolio_growth`, `allocation_history`, possibly `none`. | F | Parametrized valid/invalid query names |
| F2 | Add allowed `metric_groups`: `allocation`, `concentration`, `effective_cash`, `risk`, `performance`, `all`. | F | Parametrized valid/invalid metric groups |
| F3 | Define `SentimentCandidate`: ticker, asset id, reason, evidence type, rank/order, and source portfolio facts. | E, F | `test_sentiment_candidate_requires_reason` |
| F4 | Extend/compose `PortfolioAgentPacket` with `context_plan`, `history_context`, `effective_cash`, and `sentiment_candidates`. | F, F3 | `test_portfolio_packet_contains_sentiment_candidates` |

### EC3: Sentiment Agent stub returns future GraphRAG shape

| Task | Description | Depends on | Test |
| --- | --- | --- | --- |
| G | Define `SentimentTask`: tickers, companies/entities, themes, time window, requested evidence types, key questions, and reason. | D, F3 | `test_sentiment_task_accepts_candidate_tickers` |
| G1 | Add allowed evidence types: `filing`, `earnings_transcript`, `shareholder_letter`, `annual_report`, `quarterly_report`, `research_note`, `management_commentary`, `unknown`. | G | Evidence type validation |
| H | Define `SentimentPacket`: retrieval status, scope, holdings, portfolio-level sentiment, missing documents, warnings, and citations. | G | `test_sentiment_packet_stub_shape` |
| H1 | Add retrieval statuses: `not_implemented`, `missing_corpus`, `empty_result`, `partial`, `sufficient`. | H | Status validation |
| H2 | Ensure stub packets can be empty without becoming an error when status is `not_implemented`. | H | Empty stub packet validation |
| I | Define `SynthesisInput` combining query plan, portfolio packet, sentiment packet, IPS, memory context placeholder, and warnings. | C, F4, H | `test_synthesis_input_round_trip` |
| J | Define/extend `GuardrailReview` for V1.2 final checks and blocked/revised output metadata. | C, I | `test_guardrail_review_requires_checks` |
| K | Define trace/status event extensions for graph nodes, subagent calls, and tool-call summary. | C | `test_agent_status_event_is_json_compatible` |
| L | Add JSON fixtures for portfolio-only route, portfolio-plus-sentiment route, and missing-research route. | C through K | Fixture validation test |
| M | Add schema tests that validate all fixtures and reject invalid nested states. | L | `tests/test_agent_schemas.py` |

## Tests To Add

- `tests/test_agent_schemas.py`
- Fixture files under `tests/fixtures/agent/` if useful:
  - `investment_query_plan_portfolio_only.json`
  - `investment_query_plan_full_review.json`
  - `portfolio_context_plan_cash_only.json`
  - `portfolio_context_plan_what_changed.json`
  - `sentiment_packet_stub.json`

Minimum assertions:

- All V1.2 models serialize with `model_dump(mode="json")`.
- Invalid plan combinations fail validation.
- Sentiment stub can represent missing GraphRAG without fake citations.
- Portfolio sentiment candidates require ticker/asset context and reason.

## Free Tasks

- A: Audit existing schemas.
- B: Decide model module layout.
- G1/H1: Decide allowed evidence/retrieval status literals.
- L: Draft fixture JSON after model names are selected.

## Risks

- Over-modeling too early can slow implementation. Keep V1.2 contracts useful,
  not exhaustive.
- Reusing V1.1 model names without clear V1.2 suffixes may blur current and future
  behavior.
- Contracts should avoid raw SQL or raw OpenD payload fields.
