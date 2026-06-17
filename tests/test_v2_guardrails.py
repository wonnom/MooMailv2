from __future__ import annotations

from datetime import UTC, datetime

from moomail_finance_ai.mocks import mock_investment_policy
from moomail_finance_ai.schemas import FinalReport, PortfolioLevelSentiment, Recommendation
from moomail_finance_ai.v2_guardrails import (
    V2_GUARDRAIL_CHECKS,
    V2_GUARDRAIL_SEVERITY,
    review_v2_report,
)
from moomail_finance_ai.v2_schemas import InvestmentAgentState, SentimentPacket


def test_v2_guardrail_check_names_are_stable():
    assert V2_GUARDRAIL_CHECKS == (
        "no_trading",
        "no_exact_share_count_trading",
        "unsupported_research_claims",
        "unsupported_price_or_portfolio_facts",
        "missing_ips_for_optimization",
        "missing_sentiment_visibility",
    )
    assert set(V2_GUARDRAIL_SEVERITY) == set(V2_GUARDRAIL_CHECKS)


def test_guardrail_blocks_order_instruction():
    state = _state_with_report(
        _report(
            summary="Place an order for the portfolio after this review.",
        )
    )

    review = review_v2_report(state)

    assert review.passed is False
    assert review.output_status == "blocked"
    assert _check(review, "no_trading").passed is False


def test_guardrail_blocks_exact_share_count_recommendation():
    state = _state_with_report(
        _report(
            recommendations=[
                Recommendation(
                    title="Unsafe exact instruction",
                    rationale="Buy 42 shares of AAPL.",
                )
            ],
        )
    )

    review = review_v2_report(state)

    assert review.passed is False
    assert _check(review, "no_exact_share_count_trading").passed is False


def test_guardrail_flags_research_claim_without_sentiment():
    report = _report(
        sentiment_analysis={
            "portfolio_level_sentiment": {
                "summary": "Management tone is constructive based on earnings transcripts.",
                "themes": [],
                "risks": [],
                "citations": [],
            }
        }
    )
    state = _state_with_report(
        report,
        sentiment_packet=SentimentPacket(
            retrieval_status="not_implemented",
            portfolio_level_sentiment=PortfolioLevelSentiment(
                summary="GraphRAG sentiment retrieval is not implemented in V2."
            ),
        ),
    )

    review = review_v2_report(state)

    assert review.passed is False
    assert _check(review, "unsupported_research_claims").passed is False


def test_guardrail_blocks_optimization_recommendation_without_ips():
    state = _state_with_report(
        _report(
            recommendations=[
                Recommendation(
                    title="Optimize allocation",
                    rationale="Optimize the portfolio target allocation for risk tolerance.",
                )
            ],
        ),
        ips=None,
    )

    review = review_v2_report(state)

    assert review.passed is False
    assert _check(review, "missing_ips_for_optimization").passed is False


def test_guardrail_requires_missing_sentiment_limitation_visibility():
    state = _state_with_report(
        _report(missing_data=[]),
        sentiment_packet=SentimentPacket(retrieval_status="not_implemented"),
    )

    review = review_v2_report(state)

    assert review.passed is False
    assert _check(review, "missing_sentiment_visibility").passed is False


def _state_with_report(
    report: FinalReport,
    *,
    sentiment_packet: SentimentPacket | None = None,
    ips=mock_investment_policy(),
) -> InvestmentAgentState:
    return InvestmentAgentState(
        run_id="v2_guardrail_test",
        user_query="Review my portfolio.",
        ips=ips,
        sentiment_packet=sentiment_packet,
        final_report=report,
    )


def _report(
    *,
    summary: str = "Portfolio review completed without executable orders.",
    recommendations: list[Recommendation] | None = None,
    missing_data: list[str] | None = None,
    sentiment_analysis: dict | None = None,
) -> FinalReport:
    return FinalReport(
        run_id="v2_guardrail_test",
        mode="review",
        title="V2 Portfolio Review",
        as_of=datetime(2026, 6, 15, tzinfo=UTC),
        summary=summary,
        portfolio_snapshot={},
        portfolio_analysis={},
        sentiment_analysis=sentiment_analysis or {},
        recommendations=recommendations or [],
        missing_data=missing_data if missing_data is not None else [],
        assumptions=[],
        citations=[],
    )


def _check(review, name: str):
    return next(check for check in review.checks if check.check == name)
