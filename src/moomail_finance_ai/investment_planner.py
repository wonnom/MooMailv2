from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from pydantic import Field

from moomail_finance_ai.agent_schemas import (
    InvestmentPlan,
    InvestmentQueryPlan,
    PortfolioRequest,
    PortfolioTask,
)
from moomail_finance_ai.asset_resolver import validate_portfolio_request
from moomail_finance_ai.llm import TextLLMClient, build_llm_client_from_env
from moomail_finance_ai.schemas import InvestmentPolicy, StrictModel


class InvestmentPlanner(Protocol):
    def plan(self, query: str, ips: InvestmentPolicy) -> InvestmentPlan: ...


class InvestmentPlanningUnavailableError(RuntimeError):
    """Raised when the required LLM planner cannot produce a usable plan."""

    def __init__(self, message: str, *, cause: BaseException | None = None):
        super().__init__(message)
        self.__cause__ = cause


class InvestmentPlanValidationError(ValueError):
    """Raised when a planner emits an unsafe or inconsistent investment plan."""


class InvestmentPlanValidationResult(StrictModel):
    is_valid: bool
    warnings: list[str] = Field(default_factory=list)


@dataclass
class UnavailableInvestmentPlanner:
    """Planner used only when the configured LLM client cannot be constructed."""

    reason: str

    def plan(self, query: str, ips: InvestmentPolicy) -> InvestmentPlan:
        del query, ips
        raise InvestmentPlanningUnavailableError(self.reason)


@dataclass
class LLMInvestmentPlanner:
    """Structured-output Investment planner backed by the configured LLM."""

    llm: TextLLMClient

    @classmethod
    def from_env(
        cls,
        *,
        provider: str | None = None,
        env_file: str | Path | None = "config/local.env",
    ) -> LLMInvestmentPlanner:
        return cls(build_llm_client_from_env(provider=provider, env_file=env_file))

    def plan(self, query: str, ips: InvestmentPolicy) -> InvestmentPlan:
        try:
            text = self.llm.generate_text(
                _investment_planner_prompt(query=query, ips=ips),
                system_instruction=INVESTMENT_PLANNER_SYSTEM_PROMPT,
                max_output_tokens=4096,
                temperature=0.0,
            )
            payload = _extract_json_object(text)
            plan = InvestmentPlan.model_validate(payload)
            validation = validate_investment_plan(plan)
            warnings = _dedupe([*plan.warnings, *validation.warnings])
            return plan.model_copy(update={"warnings": warnings})
        except InvestmentPlanValidationError:
            raise
        except Exception as exc:
            raise InvestmentPlanningUnavailableError(
                "Investment planning is unavailable because the LLM planner did not "
                "return a valid structured InvestmentPlan. No deterministic fallback "
                "planner is configured.",
                cause=exc,
            ) from exc


INVESTMENT_PLANNER_SYSTEM_PROMPT = """
You are the Investment Agent planner for a personal finance AI.
Return only one JSON object matching the InvestmentPlan schema. Do not use
markdown, comments, prose, or code fences.

Plan the user's mission and bounded subagent requests. You may choose:
- mode: review, portfolio_fact, risk_check, what_changed, deep_dive, compare, unsupported
- needs_portfolio_agent and needs_sentiment_agent
- portfolio_request when needs_portfolio_agent is true
- sentiment_task when needs_sentiment_agent is true
- logical_asset_hints, themes, time_horizon, freshness_requirement, answer_constraints, warnings

Rules:
- Do not choose OpenD symbols, broker identifiers, SQL asset ids, SQL queries, or tool names.
- Use logical asset hints exactly as the user wrote them, such as AMZN or Berkshire Class B.
- time_horizon and portfolio_request.time_range must be null or a compact duration made
  from a positive integer plus d, w, m, or y (examples: 30d, 12w, 6m, 1y). Use 1y for
  a general long-term review; never return phrases such as "Long-term".
- Block trade execution, order preparation, exact share-count instructions, and order placement
  by returning mode unsupported with no subagent calls and an explanatory warning.
- For portfolio-only mechanical facts, skip sentiment unless the user explicitly asks for
  market, news, research, outlook, earnings, transcript, thesis, or management context.
- Portfolio requests must preserve source_query.
- Answer constraints must include no_trade_execution, no_order_preparation, no_exact_share_count,
  and source_backed unless the request is unsupported.
""".strip()


def validate_investment_plan(plan: InvestmentPlan) -> InvestmentPlanValidationResult:
    warnings = list(plan.warnings)
    if plan.portfolio_request is not None:
        request_validation = validate_portfolio_request(plan.portfolio_request, [])
        if not request_validation.is_valid:
            messages = [
                issue.message
                for issue in request_validation.blocking_issues
                if issue.severity == "blocking"
            ]
            raise InvestmentPlanValidationError("; ".join(messages) or "Invalid portfolio request.")
        warnings.extend(issue.message for issue in request_validation.warnings)
    return InvestmentPlanValidationResult(is_valid=True, warnings=_dedupe(warnings))


def investment_plan_to_query_plan(plan: InvestmentPlan) -> InvestmentQueryPlan:
    portfolio_task = (
        _portfolio_task_from_request(plan.portfolio_request)
        if plan.portfolio_request is not None
        else None
    )
    return InvestmentQueryPlan(
        mode=plan.mode,
        needs_portfolio_agent=plan.needs_portfolio_agent,
        needs_sentiment_agent=plan.needs_sentiment_agent,
        portfolio_task=portfolio_task,
        sentiment_task=plan.sentiment_task,
        plan_warnings=list(plan.warnings),
        route_reason=_route_reason(plan),
    )


def _portfolio_task_from_request(request: PortfolioRequest) -> PortfolioTask:
    return PortfolioTask(
        task_type="full_review" if request.task_intent == "full_review" else request.task_intent,
        source_query=request.source_query,
        requested_tickers=[hint.raw_input for hint in request.asset_hints],
        history_window=request.time_range,
        required_outputs=_legacy_required_outputs(request.output_goals),
        persistence_mode="auto",
        focus_areas=[request.task_intent, *request.output_goals],
        warnings=list(request.warnings),
    )


def _legacy_required_outputs(output_goals: list[str]) -> list[str]:
    output_map = {
        "snapshot": "snapshot",
        "allocation_context": "allocation",
        "performance_context": "performance",
        "risk_context": "risk",
        "effective_cash": "effective_cash",
        "position_changes": "history_context",
        "portfolio_patterns": "candidate_issues",
        "sentiment_context_needs": "sentiment_candidates",
        "derived_metrics": "performance",
    }
    return _dedupe([output_map[goal] for goal in output_goals if goal in output_map])


def _route_reason(plan: InvestmentPlan) -> str:
    if plan.mode == "unsupported":
        return "The LLM planner rejected the query as outside investment-analysis scope."
    if plan.needs_sentiment_agent:
        return f"LLM planner routed as {plan.mode}; Portfolio Agent and Sentiment Agent are needed."
    if plan.needs_portfolio_agent:
        return f"LLM planner routed as {plan.mode}; portfolio evidence is needed."
    return f"LLM planner routed as {plan.mode}; no subagent evidence is needed."


def _investment_planner_prompt(*, query: str, ips: InvestmentPolicy) -> str:
    context = {
        "user_query": query,
        "investment_policy": ips.model_dump(mode="json"),
        "allowed_values": {
            "mode": [
                "review",
                "portfolio_fact",
                "risk_check",
                "what_changed",
                "deep_dive",
                "compare",
                "unsupported",
            ],
            "freshness_requirement": ["latest_required", "cached_ok", "history_only"],
            "time_window_format": "positive integer plus d, w, m, or y; examples: 30d, 12w, 6m, 1y",
            "portfolio_task_intent": [
                "full_review",
                "portfolio_fact",
                "risk_check",
                "what_changed",
                "deep_dive",
                "compare",
            ],
            "portfolio_output_goals": [
                "snapshot",
                "allocation_context",
                "performance_context",
                "risk_context",
                "effective_cash",
                "position_changes",
                "portfolio_patterns",
                "sentiment_context_needs",
                "derived_metrics",
            ],
            "answer_constraints": [
                "no_trade_execution",
                "no_order_preparation",
                "no_exact_share_count",
                "source_backed",
                "portfolio_only",
            ],
        },
        "example_shape": {
            "mode": "portfolio_fact",
            "needs_portfolio_agent": True,
            "needs_sentiment_agent": False,
            "portfolio_request": {
                "task_intent": "portfolio_fact",
                "asset_hints": [],
                "time_range": "30d",
                "freshness_requirement": "latest_required",
                "output_goals": ["snapshot", "effective_cash"],
                "source_query": query,
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
        },
    }
    return json.dumps(context, sort_keys=True)


def _extract_json_object(text: str) -> dict[str, Any]:
    stripped = _strip_markdown_fence(text)
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("no JSON object found")
    payload = json.loads(stripped[start : end + 1])
    if not isinstance(payload, dict):
        raise ValueError("JSON output is not an object")
    return payload


def _strip_markdown_fence(text: str) -> str:
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _dedupe(values: list[str]) -> list[str]:
    seen = set()
    result = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
