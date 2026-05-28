from moomail_finance_ai.agents import (
    InvestmentAgentPrototype,
    MockPortfolioAgent,
    MockSentimentAgent,
)
from moomail_finance_ai.guardrails import review_report
from moomail_finance_ai.schemas import Recommendation


def test_review_my_portfolio_runs_end_to_end_against_mock_data():
    state = InvestmentAgentPrototype().run("Review my portfolio")

    assert state.final_report is not None
    assert state.guardrail_result is not None
    assert state.audit_record is not None
    assert state.guardrail_result.passed is True
    assert state.final_report.portfolio_analysis
    assert state.final_report.sentiment_analysis
    assert state.final_report.missing_data
    assert state.final_report.citations


def test_investment_agent_calls_mock_portfolio_and_sentiment_agents():
    portfolio_agent = MockPortfolioAgent()
    sentiment_agent = MockSentimentAgent()
    agent = InvestmentAgentPrototype(
        portfolio_agent=portfolio_agent,
        sentiment_agent=sentiment_agent,
    )

    agent.run("Review my portfolio")

    assert portfolio_agent.calls == 1
    assert sentiment_agent.calls == 1


def test_mechanical_query_skips_sentiment_agent():
    sentiment_agent = MockSentimentAgent()
    agent = InvestmentAgentPrototype(sentiment_agent=sentiment_agent)

    state = agent.run("Show my cash balance")

    assert sentiment_agent.calls == 0
    assert state.sentiment_packet is None


def test_guardrail_blocks_exact_share_count_order():
    state = InvestmentAgentPrototype().run("Review my portfolio")
    assert state.final_report is not None

    unsafe_report = state.final_report.model_copy(
        update={
            "recommendations": [
                Recommendation(
                    title="Sell 12 shares of AAPL",
                    rationale="Sell 12 shares of AAPL tomorrow using a market order.",
                    supporting_evidence=[
                        citation.citation_id for citation in state.final_report.citations
                    ],
                    constraints=[],
                    missing_data=state.final_report.missing_data,
                )
            ]
        }
    )

    guardrail_result = review_report(unsafe_report)

    assert guardrail_result.passed is False
    assert any(check.check == "no_trading" and not check.passed for check in guardrail_result.checks)
    assert any(
        check.check == "no_exact_share_counts" and not check.passed
        for check in guardrail_result.checks
    )

