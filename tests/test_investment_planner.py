from __future__ import annotations

import json
from pathlib import Path

from moomail_finance_ai.agent_schemas import InvestmentPlan
from moomail_finance_ai.investment_planner import (
    DeterministicInvestmentPlanner,
    InvestmentPlanner,
    investment_plan_to_query_plan,
    validate_investment_plan,
)
from moomail_finance_ai.mocks import mock_investment_policy


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "agent"


def test_investment_planner_protocol_returns_plan():
    planner: InvestmentPlanner = DeterministicInvestmentPlanner()

    plan = planner.plan("Review my portfolio.", mock_investment_policy())

    assert isinstance(plan, InvestmentPlan)
    assert plan.mode == "review"
    assert plan.needs_portfolio_agent is True


def test_fallback_planner_returns_portfolio_request_for_portfolio_query():
    plan = DeterministicInvestmentPlanner().plan(
        "How much effective cash do I have?",
        mock_investment_policy(),
    )

    assert plan.portfolio_request is not None
    assert plan.portfolio_request.task_intent == "portfolio_fact"
    assert "effective_cash" in plan.portfolio_request.output_goals


def test_planner_maps_cash_query_to_portfolio_fact_request():
    plan = DeterministicInvestmentPlanner().plan(
        "How much effective cash do I have?",
        mock_investment_policy(),
    )
    query_plan = investment_plan_to_query_plan(plan)

    assert plan.mode == "portfolio_fact"
    assert plan.portfolio_request is not None
    assert plan.portfolio_request.task_intent == "portfolio_fact"
    assert plan.needs_sentiment_agent is False
    assert query_plan.portfolio_task is not None
    assert query_plan.portfolio_task.task_type == "portfolio_fact"


def test_planner_maps_recent_purchase_query_to_position_change_request():
    plan = DeterministicInvestmentPlanner().plan(
        "What price did I buy my recent AMZN shares at?",
        mock_investment_policy(),
    )

    assert plan.mode == "what_changed"
    assert plan.portfolio_request is not None
    assert plan.portfolio_request.task_intent == "what_changed"
    assert "position_changes" in plan.portfolio_request.output_goals


def test_planner_keeps_asset_hints_logical():
    plan = DeterministicInvestmentPlanner().plan(
        "What price did I buy my recent AMZN shares at?",
        mock_investment_policy(),
    )

    assert plan.logical_asset_hints[0].raw_input == "AMZN"
    assert plan.logical_asset_hints[0].raw_input != "US.AMZN"
    assert plan.portfolio_request is not None
    assert plan.portfolio_request.asset_hints[0].raw_input == "AMZN"


def test_planner_sets_freshness_requirement():
    planner = DeterministicInvestmentPlanner()

    history_plan = planner.plan(
        "What price did I buy my recent AMZN shares at?",
        mock_investment_policy(),
    )
    cash_plan = planner.plan("How much cash do I have now?", mock_investment_policy())

    assert history_plan.freshness_requirement == "history_only"
    assert history_plan.portfolio_request is not None
    assert history_plan.portfolio_request.freshness_requirement == "history_only"
    assert cash_plan.freshness_requirement == "latest_required"


def test_portfolio_request_carries_source_query():
    query = "What price did I buy my recent AMZN shares at?"

    plan = DeterministicInvestmentPlanner().plan(query, mock_investment_policy())

    assert plan.portfolio_request is not None
    assert plan.portfolio_request.source_query == query


def test_planner_emits_sentiment_task_for_broad_review():
    plan = DeterministicInvestmentPlanner().plan(
        "Review my portfolio and market sentiment.",
        mock_investment_policy(),
    )

    assert plan.needs_sentiment_agent is True
    assert plan.sentiment_task is not None
    assert plan.sentiment_task.key_questions == ["Review my portfolio and market sentiment."]


def test_planner_skips_sentiment_for_mechanical_portfolio_fact():
    plan = DeterministicInvestmentPlanner().plan(
        "How much effective cash do I have?",
        mock_investment_policy(),
    )

    assert plan.needs_sentiment_agent is False
    assert plan.sentiment_task is None


def test_investment_planner_golden_prompts():
    planner = DeterministicInvestmentPlanner()
    cases = [
        ("How much cash/effective cash do I have?", "portfolio_fact", False),
        ("What price did I buy my recent AMZN shares at?", "what_changed", False),
        ("Review my portfolio.", "review", True),
        ("Check my portfolio concentration risk.", "risk_check", True),
        ("What does recent research say about GOOG?", "deep_dive", True),
    ]

    for query, mode, needs_sentiment in cases:
        plan = planner.plan(query, mock_investment_policy())
        validate_investment_plan(plan)
        assert plan.mode == mode
        assert plan.needs_sentiment_agent is needs_sentiment
        assert plan.needs_portfolio_agent is True


def test_investment_plan_fixtures_validate():
    for fixture_name in [
        "investment_plan_cash_query.json",
        "investment_plan_recent_purchase.json",
        "investment_plan_portfolio_request.json",
    ]:
        payload = json.loads((FIXTURE_DIR / fixture_name).read_text(encoding="utf-8"))
        plan = InvestmentPlan.model_validate(payload)
        assert plan.model_dump(mode="json")
