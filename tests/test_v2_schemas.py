from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from moomail_finance_ai.mocks import mock_investment_policy
from moomail_finance_ai.schemas import GuardrailCheck
from moomail_finance_ai.v2_schemas import (
    GuardrailReview,
    InvestmentAgentState,
    InvestmentQueryPlan,
    PortfolioContextPlan,
    PortfolioTask,
    SentimentCandidate,
    SentimentPacket,
    SentimentTask,
    SynthesisInput,
    TraceEvent,
    V2PortfolioAgentPacket,
)


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "v2"


def test_v2_investment_state_defaults_and_round_trip():
    plan = InvestmentQueryPlan.model_validate(_fixture("investment_query_plan_portfolio_only.json"))

    state = InvestmentAgentState(
        run_id="run_v2_contract",
        user_query="How much effective cash do I have?",
        mode=plan.mode,
        query_plan=plan,
    )

    payload = state.model_dump(mode="json")
    round_tripped = InvestmentAgentState.model_validate(payload)

    assert payload["portfolio_id"] == "portfolio_default"
    assert payload["status_events"] == []
    assert round_tripped.query_plan is not None
    assert round_tripped.query_plan.portfolio_task is not None
    assert round_tripped.query_plan.portfolio_task.persistence_mode == "skip"


def test_v2_query_plan_validates_required_flags():
    full_review = InvestmentQueryPlan.model_validate(
        _fixture("investment_query_plan_full_review.json")
    )
    assert full_review.needs_portfolio_agent is True
    assert full_review.needs_sentiment_agent is True
    assert full_review.sentiment_task is not None
    assert full_review.sentiment_task.tickers == ["GOOG", "ASML"]

    with pytest.raises(ValidationError, match="portfolio_task is required"):
        InvestmentQueryPlan(
            mode="portfolio_fact",
            needs_portfolio_agent=True,
            needs_sentiment_agent=False,
        )

    with pytest.raises(ValidationError, match="sentiment_task must be omitted"):
        InvestmentQueryPlan(
            mode="portfolio_fact",
            needs_portfolio_agent=True,
            needs_sentiment_agent=False,
            portfolio_task=PortfolioTask(
                task_type="portfolio_fact",
                source_query="Show my cash.",
            ),
            sentiment_task=SentimentTask(tickers=["GOOG"]),
        )


@pytest.mark.parametrize(
    "mode",
    [
        "review",
        "portfolio_fact",
        "risk_check",
        "what_changed",
        "deep_dive",
        "compare",
        "unsupported",
    ],
)
def test_v2_query_plan_accepts_supported_modes(mode: str):
    plan = InvestmentQueryPlan(
        mode=mode,
        needs_portfolio_agent=True,
        needs_sentiment_agent=False,
        portfolio_task=PortfolioTask(source_query="Review my portfolio."),
    )

    assert plan.mode == mode


def test_v2_query_plan_rejects_unsupported_mode():
    with pytest.raises(ValidationError):
        InvestmentQueryPlan(
            mode="rebalance",
            needs_portfolio_agent=True,
            needs_sentiment_agent=False,
            portfolio_task=PortfolioTask(source_query="Rebalance my portfolio."),
        )


def test_portfolio_task_defaults_to_review_safe_mode():
    task = PortfolioTask(source_query="Review my portfolio.")

    assert task.task_type == "full_review"
    assert task.persistence_mode == "auto"
    assert "sentiment_candidates" in task.required_outputs


def test_portfolio_context_plan_limits_allowed_history_queries():
    cash_only = PortfolioContextPlan.model_validate(
        _fixture("portfolio_context_plan_cash_only.json")
    )
    what_changed = PortfolioContextPlan.model_validate(
        _fixture("portfolio_context_plan_what_changed.json")
    )

    assert cash_only.history_queries == ["none"]
    assert cash_only.needs_sql_history is False
    assert what_changed.history_queries[-1] == "allocation_history"
    assert what_changed.tickers == ["GOOG", "ASML"]

    with pytest.raises(ValidationError, match="cannot combine 'none'"):
        PortfolioContextPlan(
            needs_sql_history=True,
            history_queries=["none", "portfolio_growth"],
        )

    with pytest.raises(ValidationError):
        PortfolioContextPlan(history_queries=["raw_sql"])


@pytest.mark.parametrize(
    "metric_group",
    ["allocation", "concentration", "effective_cash", "risk", "performance", "all"],
)
def test_portfolio_context_plan_accepts_supported_metric_groups(metric_group: str):
    plan = PortfolioContextPlan(metric_groups=[metric_group])

    assert plan.metric_groups == [metric_group]


def test_portfolio_context_plan_rejects_unsupported_metric_group():
    with pytest.raises(ValidationError):
        PortfolioContextPlan(metric_groups=["alpha_model"])


def test_sentiment_candidate_requires_reason_and_asset_context():
    candidate = SentimentCandidate(
        ticker="goog",
        reason="Material holding with thesis-sensitive regulatory exposure.",
        evidence_type="holding_weight",
        rank=1,
        source_portfolio_facts={"portfolio_weight": 0.12},
    )

    assert candidate.ticker == "GOOG"

    with pytest.raises(ValidationError):
        SentimentCandidate(
            reason="No asset context.",
            evidence_type="portfolio_fact",
            rank=1,
        )

    with pytest.raises(ValidationError):
        SentimentCandidate(
            ticker="GOOG",
            reason="",
            evidence_type="portfolio_fact",
            rank=1,
        )


def test_portfolio_packet_contains_sentiment_candidates():
    packet = V2PortfolioAgentPacket(
        portfolio_id="portfolio_default",
        context_plan=PortfolioContextPlan.model_validate(
            _fixture("portfolio_context_plan_what_changed.json")
        ),
        sentiment_candidates=[
            SentimentCandidate(
                ticker="GOOG",
                asset_id="asset_goog_us",
                reason="Largest holding and material source of portfolio concentration.",
                evidence_type="holding_weight",
                rank=1,
                source_portfolio_facts={"portfolio_weight": 0.1179},
            )
        ],
        effective_cash={"effective_cash_weight": 0.02},
    )

    payload = packet.model_dump(mode="json")

    assert payload["sentiment_candidates"][0]["ticker"] == "GOOG"
    assert payload["effective_cash"]["effective_cash_weight"] == 0.02


def test_sentiment_task_accepts_candidate_tickers():
    candidates = [
        SentimentCandidate(
            ticker="goog",
            reason="Material holding.",
            evidence_type="holding_weight",
            rank=1,
        ),
        SentimentCandidate(
            ticker="asml",
            reason="Material holding.",
            evidence_type="holding_weight",
            rank=2,
        ),
    ]

    task = SentimentTask.from_candidates(candidates)

    assert task.tickers == ["GOOG", "ASML"]
    assert [candidate.ticker for candidate in task.candidate_refs] == ["GOOG", "ASML"]


@pytest.mark.parametrize(
    "evidence_type",
    [
        "filing",
        "earnings_transcript",
        "shareholder_letter",
        "annual_report",
        "quarterly_report",
        "research_note",
        "management_commentary",
        "unknown",
    ],
)
def test_sentiment_task_accepts_supported_evidence_types(evidence_type: str):
    task = SentimentTask(tickers=["GOOG"], requested_evidence_types=[evidence_type])

    assert task.requested_evidence_types == [evidence_type]


def test_sentiment_task_rejects_unsupported_evidence_type():
    with pytest.raises(ValidationError):
        SentimentTask(tickers=["GOOG"], requested_evidence_types=["message_board"])


@pytest.mark.parametrize(
    "retrieval_status",
    ["not_implemented", "missing_corpus", "empty_result", "partial", "sufficient"],
)
def test_sentiment_packet_accepts_supported_retrieval_statuses(retrieval_status: str):
    packet = SentimentPacket(retrieval_status=retrieval_status)

    assert packet.retrieval_status == retrieval_status


def test_sentiment_packet_stub_shape():
    packet = SentimentPacket.model_validate(_fixture("sentiment_packet_stub.json"))

    payload = packet.model_dump(mode="json")

    assert payload["retrieval_status"] == "not_implemented"
    assert payload["holdings"] == []
    assert payload["citations"] == []
    assert payload["missing_documents"][0]["document_type"] == "earnings_transcript"


def test_sentiment_packet_not_implemented_rejects_fake_research():
    with pytest.raises(ValidationError, match="cannot include holdings or citations"):
        SentimentPacket(
            retrieval_status="not_implemented",
            citations=[_citation()],
        )


def test_synthesis_input_round_trip():
    query_plan = InvestmentQueryPlan.model_validate(
        _fixture("investment_query_plan_full_review.json")
    )
    sentiment_packet = SentimentPacket.model_validate(_fixture("sentiment_packet_stub.json"))
    portfolio_packet = V2PortfolioAgentPacket(
        portfolio_id="portfolio_default",
        context_plan=PortfolioContextPlan.model_validate(
            _fixture("portfolio_context_plan_what_changed.json")
        ),
    )
    synthesis_input = SynthesisInput(
        run_id="run_v2_contract",
        user_query="Review my portfolio and market sentiment.",
        query_plan=query_plan,
        ips=mock_investment_policy(),
        portfolio_packet=portfolio_packet,
        sentiment_packet=sentiment_packet,
        warnings=["Sentiment Agent is a stub."],
    )

    payload = synthesis_input.model_dump(mode="json")
    round_tripped = SynthesisInput.model_validate(payload)

    assert round_tripped.query_plan.needs_sentiment_agent is True
    assert round_tripped.sentiment_packet is not None
    assert round_tripped.sentiment_packet.retrieval_status == "not_implemented"


def test_guardrail_review_requires_checks():
    review = GuardrailReview(
        passed=True,
        output_status="approved",
        checks=[
            GuardrailCheck(
                check="no_trading",
                passed=True,
                message="No trade execution language detected.",
            )
        ],
    )

    assert review.model_dump(mode="json")["output_status"] == "approved"

    with pytest.raises(ValidationError):
        GuardrailReview(
            passed=True,
            output_status="approved",
            checks=[],
        )

    with pytest.raises(ValidationError, match="blocked_reason"):
        GuardrailReview(
            passed=False,
            output_status="blocked",
            checks=[
                GuardrailCheck(
                    check="no_trading",
                    passed=False,
                    message="Trade execution language detected.",
                )
            ],
        )


def test_v2_status_event_is_json_compatible():
    event = TraceEvent(
        event_type="tool_call",
        run_id="run_v2_contract",
        status="calling_tool",
        message="Calling finance metrics.",
        subagent="portfolio_agent",
        server_name="moomail-finance-metrics-mcp",
        tool_name="calculate_snapshot_metrics",
        input_summary="snapshot and IPS",
        output_summary="5 metric rows",
    )

    payload = event.model_dump(mode="json")

    assert payload["event_type"] == "tool_call"
    assert payload["timestamp"].endswith(("Z", "+00:00"))

    with pytest.raises(ValidationError, match="tool_name"):
        TraceEvent(
            event_type="tool_call",
            run_id="run_v2_contract",
            status="calling_tool",
            message="Missing tool name.",
        )


def test_all_v2_fixtures_validate_and_serialize():
    model_by_fixture = {
        "investment_query_plan_portfolio_only.json": InvestmentQueryPlan,
        "investment_query_plan_full_review.json": InvestmentQueryPlan,
        "portfolio_context_plan_cash_only.json": PortfolioContextPlan,
        "portfolio_context_plan_what_changed.json": PortfolioContextPlan,
        "sentiment_packet_stub.json": SentimentPacket,
    }

    for fixture_name, model in model_by_fixture.items():
        instance = model.model_validate(_fixture(fixture_name))
        payload = instance.model_dump(mode="json")
        assert json.loads(json.dumps(payload)) == payload


def test_investment_agent_state_rejects_plan_mode_mismatch():
    plan = InvestmentQueryPlan.model_validate(_fixture("investment_query_plan_portfolio_only.json"))

    with pytest.raises(ValidationError, match="mode must match query_plan"):
        InvestmentAgentState(
            run_id="run_v2_contract",
            user_query="How much cash do I have?",
            mode="review",
            query_plan=plan,
        )


def _fixture(name: str):
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def _citation() -> dict[str, object]:
    return {
        "citation_id": "cite_fake",
        "source_type": "earnings_transcript",
        "title": "Fake Transcript",
        "publisher": "Company",
        "document_id": "doc_fake",
        "location": {},
        "snippet": "Fake evidence should not appear in a not_implemented stub.",
        "source_quality": "primary",
    }
