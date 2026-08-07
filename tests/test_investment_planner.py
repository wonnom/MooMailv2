from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from moomail_finance_ai.agent_schemas import (
    InvestmentPlan,
    InvestmentTurnDecision,
    PortfolioBaselinePacket,
)
from moomail_finance_ai.investment_routing import validate_direct_answer_coverage
from moomail_finance_ai.investment_planner import (
    InvestmentPlanValidationError,
    InvestmentPlanner,
    InvestmentPlanningUnavailableError,
    LLMInvestmentPlanner,
    UnavailableInvestmentPlanner,
    _investment_planner_prompt,
    _investment_turn_prompt,
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


def test_investment_llm_returns_direct_or_delegate_decision():
    baseline = PortfolioBaselinePacket.model_validate(
        _fixture("v1_5_baseline_covered.json")
    )
    planner = LLMInvestmentPlanner(
        FakeLLM(json.dumps(_fixture("v1_5_route_direct.json")))
    )

    decision = planner.plan_turn(
        "How has my portfolio changed since last week?",
        mock_investment_policy(),
        baseline,
    )

    assert isinstance(decision, InvestmentTurnDecision)
    assert decision.route == "direct_context"
    assert decision.direct_answer


def test_investment_prompt_contains_compact_baseline_capabilities():
    baseline = PortfolioBaselinePacket.model_validate(
        _fixture("v1_5_baseline_covered.json")
    )

    prompt = _investment_turn_prompt(
        query="How has my portfolio changed since last week?",
        ips=mock_investment_policy(),
        baseline=baseline,
    )

    assert '"portfolio_baseline"' in prompt
    assert '"portfolio_value_trend_7d"' in prompt
    assert '"sql.trend.7d"' in prompt
    assert '"as_of"' in prompt
    assert '"limitations"' in prompt
    assert '"portfolio_analysis_requirement"' in prompt
    assert '"deterministic_only"' in prompt
    assert '"interpretation_required"' in prompt


def test_investment_prompt_excludes_raw_baseline_payloads():
    baseline = PortfolioBaselinePacket.model_validate(
        _fixture("v1_5_baseline_covered.json")
    )

    prompt = _investment_turn_prompt(
        query="Review the saved portfolio breakdown.",
        ips=mock_investment_policy(),
        baseline=baseline,
    )

    assert "raw_broker_payload" not in prompt
    assert "broker_account_id" not in prompt
    assert '"account_id"' not in prompt
    assert len(prompt.encode("utf-8")) < 70_000


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


def test_v1_5_investment_turn_fixtures_validate():
    for fixture_name in [
        "v1_5_investment_direct_breakdown.json",
        "v1_5_investment_delegate_detail.json",
        "v1_5_investment_absent_evidence.json",
    ]:
        decision = InvestmentTurnDecision.model_validate(_fixture(fixture_name))
        assert decision.model_dump(mode="json")


def test_direct_route_requires_complete_baseline_coverage():
    baseline = PortfolioBaselinePacket.model_validate(
        _fixture("v1_5_baseline_covered.json")
    )
    decision = InvestmentTurnDecision.model_validate(
        _fixture("v1_5_route_direct.json")
    ).model_copy(
        update={
            "required_evidence": ["allocation_breakdown"],
            "cited_evidence_refs": ["dashboard.total"],
        }
    )

    result = validate_direct_answer_coverage(
        decision,
        baseline,
        now=datetime(2026, 8, 3, 14, 0, tzinfo=UTC),
    )

    assert result.is_valid is False
    assert result.missing_capabilities == ["allocation_breakdown"]


def test_direct_route_rejects_stale_or_short_window_evidence():
    covered = PortfolioBaselinePacket.model_validate(
        _fixture("v1_5_baseline_covered.json")
    )
    direct = InvestmentTurnDecision.model_validate(_fixture("v1_5_route_direct.json"))

    short_window = validate_direct_answer_coverage(
        direct,
        covered,
        requested_window="30d",
        now=datetime(2026, 8, 3, 14, 0, tzinfo=UTC),
    )

    stale_baseline = PortfolioBaselinePacket.model_validate(
        _fixture("v1_5_baseline_stale.json")
    )
    stale_decision = direct.model_copy(
        update={
            "required_evidence": ["latest_snapshot"],
            "cited_evidence_refs": ["dashboard.stale.total"],
        }
    )
    stale = validate_direct_answer_coverage(
        stale_decision,
        stale_baseline,
        now=datetime(2026, 8, 3, 14, 0, tzinfo=UTC),
    )

    assert short_window.is_valid is False
    assert short_window.window_mismatches == ["portfolio_value_trend_7d"]
    assert stale.is_valid is False
    assert stale.stale_evidence_refs == ["dashboard.stale.total"]


def test_direct_answer_rejects_unknown_evidence_reference():
    baseline = PortfolioBaselinePacket.model_validate(
        _fixture("v1_5_baseline_covered.json")
    )
    decision = InvestmentTurnDecision.model_validate(
        _fixture("v1_5_route_direct.json")
    ).model_copy(update={"cited_evidence_refs": ["invented.ref"]})

    result = validate_direct_answer_coverage(
        decision,
        baseline,
        now=datetime(2026, 8, 3, 14, 0, tzinfo=UTC),
    )

    assert result.is_valid is False
    assert result.invalid_evidence_refs == ["invented.ref"]


def test_missing_coverage_uses_only_bounded_fallback_request():
    baseline = PortfolioBaselinePacket.model_validate(
        _fixture("v1_5_baseline_stale.json")
    )
    decision = InvestmentTurnDecision.model_validate(
        _fixture("v1_5_route_direct.json")
    ).model_copy(
        update={
            "required_evidence": ["latest_snapshot"],
            "cited_evidence_refs": ["dashboard.stale.total"],
        }
    )

    result = validate_direct_answer_coverage(
        decision,
        baseline,
        now=datetime(2026, 8, 3, 14, 0, tzinfo=UTC),
    )

    assert result.is_valid is False
    assert result.fallback_portfolio_request == decision.fallback_portfolio_request
    assert result.fallback_portfolio_request is not None


def test_portfolio_request_source_query_must_match_original():
    plan = InvestmentPlan.model_validate(
        _fixture("v1_5_rewritten_source_query.json")
    )

    with pytest.raises(InvestmentPlanValidationError, match="preserve the original"):
        validate_investment_plan(
            plan,
            original_query="Show my portfolio and explain the recent changes.",
        )


def test_investment_validation_inspects_original_user_query():
    plan = InvestmentPlan.model_validate(_cash_plan_payload())

    with pytest.raises(InvestmentPlanValidationError, match="cannot be blank"):
        validate_investment_plan(plan, original_query=" \n\t ")


def test_planner_cannot_rewrite_away_trade_order_intent():
    plan = InvestmentPlan.model_validate(_cash_plan_payload())

    with pytest.raises(InvestmentPlanValidationError, match="Original user query"):
        validate_investment_plan(
            plan,
            original_query="Place an order for 10 shares of AMZN.",
        )


def test_unknown_only_investment_planner_payload_fails_closed():
    payload = (FIXTURE_DIR / "v1_5_unknown_only_planner.json").read_text(
        encoding="utf-8"
    )
    planner = LLMInvestmentPlanner(FakeLLM(payload))

    with pytest.raises(InvestmentPlanningUnavailableError):
        planner.plan("Review my portfolio.", mock_investment_policy())


def test_unknown_only_investment_turn_stops_before_graph_routing():
    planner = LLMInvestmentPlanner(
        FakeLLM((FIXTURE_DIR / "v1_5_unknown_only_planner.json").read_text())
    )

    with pytest.raises(InvestmentPlanningUnavailableError):
        planner.plan_turn(
            "Review my portfolio.",
            mock_investment_policy(),
            PortfolioBaselinePacket.model_validate(
                _fixture("v1_5_baseline_covered.json")
            ),
        )


def test_investment_planner_accepts_envelope_with_provider_metadata():
    planner = LLMInvestmentPlanner(
        FakeLLM(
            json.dumps(
                {
                    "investment_plan": _cash_plan_payload(),
                    "provider": "test-provider",
                    "model": "test-model",
                    "usage": {"input_tokens": 10, "output_tokens": 10},
                }
            )
        )
    )

    plan = planner.plan("How much effective cash do I have?", mock_investment_policy())

    assert plan.mode == "portfolio_fact"


def _fixture(name: str) -> dict:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


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
