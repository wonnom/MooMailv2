from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from moomail_finance_ai.metrics import calculate_snapshot_metrics
from moomail_finance_ai.mocks import mock_investment_policy, mock_portfolio_packet
from moomail_finance_ai.portfolio_agent import (
    EffectiveCashSummary,
    PortfolioAgentResult,
    PortfolioEvaluation,
    PortfolioHistoryContext,
    build_effective_cash_summary,
    plan_portfolio_context,
)
from moomail_finance_ai.sentiment_agent_stub import SentimentAgentStub
from moomail_finance_ai.investment_agent import (
    InvestmentAgent,
    classify_investment_query,
)
from moomail_finance_ai.agent_schemas import PortfolioTask, SentimentPacket, SentimentTask


def test_dependency_strategy_uses_real_langgraph_runtime():
    agent = InvestmentAgent(
        portfolio_agent=FakePortfolioAgent(),
        sentiment_agent=FakeSentimentAgent(),
        ips=mock_investment_policy(),
    )

    assert agent.graph_runtime == "langgraph_state_graph"
    assert hasattr(agent.graph, "invoke")


def test_classifier_cash_query_portfolio_only():
    plan = classify_investment_query("How much effective cash do I have?")

    assert plan.mode == "portfolio_fact"
    assert plan.needs_portfolio_agent is True
    assert plan.needs_sentiment_agent is False
    assert plan.portfolio_task is not None
    assert plan.portfolio_task.required_outputs == ["snapshot", "allocation", "effective_cash"]
    assert plan.sentiment_task is None


def test_routing_portfolio_only_skips_sentiment():
    portfolio_agent = FakePortfolioAgent()
    sentiment_agent = FakeSentimentAgent()
    agent = InvestmentAgent(
        portfolio_agent=portfolio_agent,
        sentiment_agent=sentiment_agent,
        ips=mock_investment_policy(),
    )

    state = agent.run("How much effective cash do I have?")

    assert portfolio_agent.calls == 1
    assert portfolio_agent.last_task is not None
    assert portfolio_agent.last_task.task_type == "portfolio_fact"
    assert sentiment_agent.calls == 0
    assert state.query_plan is not None
    assert state.query_plan.mode == "portfolio_fact"
    assert state.query_plan.needs_sentiment_agent is False
    assert state.final_report is not None
    assert state.final_report.sentiment_analysis == {}
    assert "Sentiment Agent GraphRAG retrieval" not in state.final_report.missing_data


def test_full_review_routes_portfolio_then_sentiment_stub():
    portfolio_agent = FakePortfolioAgent()
    sentiment_agent = FakeSentimentAgent()
    agent = InvestmentAgent(
        portfolio_agent=portfolio_agent,
        sentiment_agent=sentiment_agent,
        ips=mock_investment_policy(),
    )

    state = agent.run("Review my portfolio and market sentiment.")

    assert portfolio_agent.calls == 1
    assert portfolio_agent.last_task is not None
    assert portfolio_agent.last_task.task_type == "deep_dive"
    assert sentiment_agent.calls == 1
    assert sentiment_agent.last_task is not None
    assert sentiment_agent.last_task.tickers == ["MSFT", "AAPL"]
    assert state.portfolio_packet is not None
    assert state.portfolio_packet.context_plan.persist_observation is True
    assert "fake_portfolio_agent" in state.portfolio_packet.tool_calls
    assert [candidate.ticker for candidate in state.portfolio_packet.sentiment_candidates] == [
        "MSFT",
        "AAPL",
    ]
    assert state.sentiment_packet is not None
    assert state.sentiment_packet.retrieval_status == "not_implemented"


def test_full_review_includes_missing_research_without_fake_citations():
    agent = InvestmentAgent(
        portfolio_agent=FakePortfolioAgent(),
        sentiment_agent=SentimentAgentStub(),
        ips=mock_investment_policy(),
    )

    state = agent.run("Review my portfolio.")

    assert state.final_report is not None
    assert "Sentiment Agent GraphRAG retrieval is not implemented." in (
        state.final_report.missing_data
    )
    assert state.final_report.citations == []
    assert state.final_report.sentiment_analysis["retrieval_status"] == "not_implemented"
    assert "GraphRAG is not connected yet" in state.final_report.summary
    assert state.guardrail_review is not None
    assert state.guardrail_review.passed is True


def test_user_named_sentiment_query_scopes_requested_ticker():
    sentiment_agent = FakeSentimentAgent()
    agent = InvestmentAgent(
        portfolio_agent=FakePortfolioAgent(candidate_weights=False),
        sentiment_agent=sentiment_agent,
        ips=mock_investment_policy(),
    )

    state = agent.run("What does recent research say about GOOG?")

    assert state.query_plan is not None
    assert state.query_plan.mode == "deep_dive"
    assert sentiment_agent.calls == 1
    assert sentiment_agent.last_task is not None
    assert sentiment_agent.last_task.tickers == ["GOOG"]


def test_streamed_status_events_include_graph_steps():
    emitted = []
    agent = InvestmentAgent(
        portfolio_agent=FakePortfolioAgent(),
        sentiment_agent=FakeSentimentAgent(),
        ips=mock_investment_policy(),
    )

    state = agent.run("Review my portfolio.", status_callback=emitted.append)

    statuses = [event.status for event in emitted]
    assert statuses[0] == "classifying_query"
    assert "planning_subagent_calls" in statuses
    assert "loading_policy" in statuses
    assert "calling_portfolio_agent" in statuses
    assert "calling_sentiment_agent" in statuses
    assert "checking_guardrails" in statuses
    assert "guardrails_passed" in statuses
    assert statuses[-1] == "complete"
    assert len(emitted) == len(state.status_events)


class FakePortfolioAgent:
    def __init__(self, *, candidate_weights: bool = True):
        self.calls = 0
        self.queries: list[str] = []
        self.last_task: PortfolioTask | None = None
        self.candidate_weights = candidate_weights

    def run(
        self,
        query: str,
        ips,
        *,
        status_callback=None,
        portfolio_task: PortfolioTask | None = None,
    ) -> PortfolioAgentResult:
        del status_callback
        self.calls += 1
        self.queries.append(query)
        self.last_task = portfolio_task
        packet = mock_portfolio_packet()
        if not self.candidate_weights:
            holdings = [
                holding.model_copy(update={"portfolio_weight": 0.01})
                for holding in packet.snapshot.holdings
            ]
            snapshot = packet.snapshot.model_copy(update={"holdings": holdings})
            packet = packet.model_copy(update={"snapshot": snapshot})
        metrics = calculate_snapshot_metrics(packet.snapshot, ips)
        effective_cash: EffectiveCashSummary = build_effective_cash_summary(packet.snapshot)
        history_context = PortfolioHistoryContext(
            history_status={"snapshot_count": 1, "data_quality": {"warnings": []}},
            latest_portfolio_state=None,
            portfolio_growth=[],
            allocation_history=[],
        )
        return PortfolioAgentResult(
            run_id=f"fake_portfolio_{self.calls}",
            portfolio_id=packet.portfolio_id,
            context_plan=plan_portfolio_context(
                portfolio_task
                or PortfolioTask(task_type="full_review", source_query=query)
            ),
            snapshot=packet.snapshot,
            portfolio_packet=packet,
            metrics=metrics,
            storage_result={"status": "inserted"},
            metrics_storage_result={"metrics_stored": 0, "weight_rows_stored": 0},
            effective_cash=effective_cash,
            history_status=history_context.history_status,
            history_context=history_context,
            evaluation=PortfolioEvaluation(summary="Fake portfolio evaluation complete."),
            tool_calls=["planned:fake_portfolio_agent", "fake_portfolio_agent"],
            status_events=[],
            warnings=[],
        )


class FakeSentimentAgent:
    def __init__(self):
        self.calls = 0
        self.last_task: SentimentTask | None = None

    def run(self, task: SentimentTask) -> SentimentPacket:
        self.calls += 1
        self.last_task = task
        return SentimentPacket(
            retrieval_status="not_implemented",
            task=task,
            warnings=["Fake sentiment stub called."],
        )
