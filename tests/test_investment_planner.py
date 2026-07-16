from __future__ import annotations

import json
from pathlib import Path

import pytest

from moomail_finance_ai.agent_schemas import InvestmentPlan
from moomail_finance_ai.investment_planner import (
    InvestmentPlanner,
    InvestmentPlanningUnavailableError,
    LLMInvestmentPlanner,
    UnavailableInvestmentPlanner,
    _investment_planner_prompt,
    investment_plan_to_query_plan,
    validate_investment_plan,
)
from moomail_finance_ai.mocks import mock_investment_policy


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "agent"


def test_llm_investment_planner_protocol_returns_plan():
    planner: InvestmentPlanner = LLMInvestmentPlanner(
        FakeLLM(json.dumps(_cash_plan_payload()))
    )

    plan = planner.plan("How much effective cash do I have?", mock_investment_policy())

    assert isinstance(plan, InvestmentPlan)
    assert plan.mode == "portfolio_fact"
    assert plan.needs_portfolio_agent is True
    assert plan.needs_sentiment_agent is False
    assert plan.portfolio_request is not None
    assert plan.portfolio_request.output_goals == ["snapshot", "effective_cash"]


def test_llm_planner_maps_plan_to_query_plan_without_keyword_classifier():
    planner = LLMInvestmentPlanner(FakeLLM(json.dumps(_cash_plan_payload())))

    plan = planner.plan("How much effective cash do I have?", mock_investment_policy())
    query_plan = investment_plan_to_query_plan(plan)

    assert query_plan.mode == "portfolio_fact"
    assert query_plan.portfolio_task is not None
    assert query_plan.portfolio_task.task_type == "portfolio_fact"
    assert query_plan.portfolio_task.required_outputs == ["snapshot", "effective_cash"]


def test_llm_planner_keeps_asset_hints_logical():
    planner = LLMInvestmentPlanner(FakeLLM(json.dumps(_recent_purchase_payload())))

    plan = planner.plan(
        "What price did I buy my recent AMZN shares at?",
        mock_investment_policy(),
    )

    assert plan.logical_asset_hints[0].raw_input == "AMZN"
    assert plan.logical_asset_hints[0].raw_input != "US.AMZN"
    assert plan.portfolio_request is not None
    assert plan.portfolio_request.asset_hints[0].raw_input == "AMZN"
    assert plan.portfolio_request.freshness_requirement == "history_only"


def test_llm_planner_invalid_output_fails_without_deterministic_fallback():
    planner = LLMInvestmentPlanner(FakeLLM("not json"))

    with pytest.raises(InvestmentPlanningUnavailableError) as exc_info:
        planner.plan("Review my portfolio.", mock_investment_policy())

    assert "No deterministic fallback planner" in str(exc_info.value)


def test_unavailable_planner_raises_graceful_failure_message():
    planner = UnavailableInvestmentPlanner("LLM planner is not configured.")

    with pytest.raises(InvestmentPlanningUnavailableError) as exc_info:
        planner.plan("Review my portfolio.", mock_investment_policy())

    assert str(exc_info.value) == "LLM planner is not configured."


def test_investment_planner_prompt_constrains_schema_time_windows():
    prompt = _investment_planner_prompt(
        query="Review my portfolio.",
        ips=mock_investment_policy(),
    )

    assert "positive integer plus d, w, m, or y" in prompt
    assert '"time_horizon": "30d"' in prompt
    assert '"time_range": "30d"' in prompt


def test_investment_plan_fixtures_validate():
    for fixture_name in [
        "investment_plan_cash_query.json",
        "investment_plan_recent_purchase.json",
        "investment_plan_portfolio_request.json",
    ]:
        payload = json.loads((FIXTURE_DIR / fixture_name).read_text(encoding="utf-8"))
        plan = InvestmentPlan.model_validate(payload)
        validate_investment_plan(plan)
        assert plan.model_dump(mode="json")


def _cash_plan_payload() -> dict:
    return {
        "mode": "portfolio_fact",
        "needs_portfolio_agent": True,
        "needs_sentiment_agent": False,
        "portfolio_request": {
            "task_intent": "portfolio_fact",
            "asset_hints": [],
            "time_range": "30d",
            "freshness_requirement": "latest_required",
            "output_goals": ["snapshot", "effective_cash"],
            "source_query": "How much effective cash do I have?",
            "warnings": [],
        },
        "sentiment_task": None,
        "logical_asset_hints": [],
        "themes": ["portfolio_fact"],
        "time_horizon": "30d",
        "freshness_requirement": "latest_required",
        "answer_constraints": [
            "no_trade_execution",
            "no_order_preparation",
            "no_exact_share_count",
            "source_backed",
            "portfolio_only",
        ],
        "warnings": [],
    }


def _recent_purchase_payload() -> dict:
    return {
        "mode": "what_changed",
        "needs_portfolio_agent": True,
        "needs_sentiment_agent": False,
        "portfolio_request": {
            "task_intent": "what_changed",
            "asset_hints": [{"raw_input": "AMZN"}],
            "time_range": "90d",
            "freshness_requirement": "history_only",
            "output_goals": ["snapshot", "position_changes"],
            "source_query": "What price did I buy my recent AMZN shares at?",
            "warnings": [],
        },
        "sentiment_task": None,
        "logical_asset_hints": [{"raw_input": "AMZN"}],
        "themes": ["position_changes"],
        "time_horizon": "90d",
        "freshness_requirement": "history_only",
        "answer_constraints": [
            "no_trade_execution",
            "no_order_preparation",
            "no_exact_share_count",
            "source_backed",
        ],
        "warnings": [],
    }


class FakeLLM:
    config = None

    def __init__(self, text: str):
        self.text = text

    def generate_text(self, *args, **kwargs) -> str:
        return self.text
