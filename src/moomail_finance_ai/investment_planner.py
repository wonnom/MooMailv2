from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from pydantic import Field

from moomail_finance_ai.agent_schemas import (
    BaselineCapability,
    InvestmentPlan,
    InvestmentQueryPlan,
    InvestmentTurnDecision,
    PortfolioBaselinePacket,
    PortfolioRequest,
    PortfolioTask,
)
from moomail_finance_ai.asset_resolver import (
    contains_trade_execution_intent,
    validate_portfolio_request,
)
from moomail_finance_ai.llm import TextLLMClient, build_llm_client_from_env
from moomail_finance_ai.observability import generate_text_with_observability
from moomail_finance_ai.investment_routing import (
    DirectAnswerCoverageResult,
    validate_direct_answer_coverage,
)
from moomail_finance_ai.schemas import InvestmentPolicy, StrictModel


class InvestmentPlanner(Protocol):
    def plan(self, query: str, ips: InvestmentPolicy) -> InvestmentPlan: ...


class InvestmentTurnPlanner(Protocol):
    def plan_turn(
        self,
        query: str,
        ips: InvestmentPolicy,
        baseline: PortfolioBaselinePacket,
    ) -> InvestmentTurnDecision: ...


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


@dataclass(frozen=True)
class InvestmentTurnValidationResult:
    decision: InvestmentTurnDecision
    coverage: DirectAnswerCoverageResult | None
    fallback_used: bool
    warnings: list[str]


@dataclass
class UnavailableInvestmentPlanner:
    """Planner used only when the configured LLM client cannot be constructed."""

    reason: str
    outbound_llm: bool = False

    def plan(self, query: str, ips: InvestmentPolicy) -> InvestmentPlan:
        del query, ips
        raise InvestmentPlanningUnavailableError(self.reason)

    def plan_turn(
        self,
        query: str,
        ips: InvestmentPolicy,
        baseline: PortfolioBaselinePacket,
    ) -> InvestmentTurnDecision:
        del query, ips, baseline
        raise InvestmentPlanningUnavailableError(self.reason)


@dataclass
class LLMInvestmentPlanner:
    """Structured-output Investment planner backed by the configured LLM."""

    llm: TextLLMClient
    outbound_llm: bool = True

    @classmethod
    def from_env(
        cls,
        *,
        provider: str | None = None,
        env_file: str | Path | None = "config/local.env",
    ) -> LLMInvestmentPlanner:
        return cls(build_llm_client_from_env(provider=provider, env_file=env_file))

    def plan(self, query: str, ips: InvestmentPolicy) -> InvestmentPlan:
        """Compatibility V1.4 planner entrypoint; live chat uses ``plan_turn``."""

        try:
            text = generate_text_with_observability(
                self.llm,
                _investment_planner_prompt(query=query, ips=ips),
                purpose="investment_planning",
                system_instruction=INVESTMENT_PLANNER_SYSTEM_PROMPT,
                max_output_tokens=4096,
                temperature=0.0,
            )
            payload = _extract_json_object(text)
            payload = _normalize_investment_plan_payload(payload)
            plan = InvestmentPlan.model_validate(payload)
            validation = validate_investment_plan(plan, original_query=query)
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

    def plan_turn(
        self,
        query: str,
        ips: InvestmentPolicy,
        baseline: PortfolioBaselinePacket,
    ) -> InvestmentTurnDecision:
        """Produce one baseline-aware direct/delegate decision in one LLM request."""

        try:
            text = generate_text_with_observability(
                self.llm,
                _investment_turn_prompt(query=query, ips=ips, baseline=baseline),
                purpose="investment_planning",
                system_instruction=INVESTMENT_TURN_SYSTEM_PROMPT,
                max_output_tokens=4096,
                temperature=0.0,
            )
            payload = _extract_json_object(text)
            payload = _normalize_investment_turn_payload(payload)
            return InvestmentTurnDecision.model_validate(payload)
        except InvestmentPlanValidationError:
            raise
        except Exception as exc:
            raise InvestmentPlanningUnavailableError(
                "Investment planning is unavailable because the LLM planner did not "
                "return a valid structured InvestmentTurnDecision. No deterministic "
                "fallback planner is configured.",
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
- Set portfolio_request.analysis_requirement to deterministic_only for structured fact,
  metric, or change retrieval. Use interpretation_required only for deeper explanation,
  comparison, ranking, risk interpretation, or anomaly analysis.
- Portfolio requests must preserve source_query.
- Answer constraints must include no_trade_execution, no_order_preparation, no_exact_share_count,
  and source_backed unless the request is unsupported.
""".strip()


INVESTMENT_TURN_SYSTEM_PROMPT = """
You are the Investment Agent's single structured planning and direct-answer turn.
Return only one JSON object matching the InvestmentTurnDecision schema. Do not
use markdown, comments, prose outside the JSON object, or code fences.

Choose exactly one route: direct_context, delegate_portfolio,
delegate_sentiment, delegate_both, or unsupported.

Rules:
- Use direct_context only when the supplied compact baseline appears to contain
  every capability needed for the answer. Deterministic policy will verify this.
- A direct answer must cite exact evidence ref ids from the baseline, state the
  stored data as_of, and make relevant baseline limitations visible.
- Never invent values, evidence refs, capabilities, holdings, prices, or research.
- General breakdown, allocation, effective-cash, rough 7-day/30-day trend, and
  covered recent-change requests should use direct_context when evidence exists.
- Use delegate_portfolio for unsupported windows, asset-level history, cost basis,
  deeper risk, anomaly investigation, or a request that explicitly requires the
  latest OpenD state. Include one bounded PortfolioRequest and a specific reason.
- Every PortfolioRequest must declare analysis_requirement. Use deterministic_only
  when deterministic facts, metrics, or scoped changes are sufficient; use
  interpretation_required only for deeper explanation, comparison, ranking, risk
  interpretation, or anomaly analysis.
- For direct_context, include a bounded fallback_portfolio_request whenever a
  coverage failure could require Portfolio escalation.
- PortfolioRequest.source_query must preserve the original user query exactly.
- Do not choose OpenD symbols, broker identifiers, SQL asset ids, SQL queries, or
  tool names. Use logical asset hints exactly as the user wrote them.
- Investment Agent owns sentiment routing. Portfolio Agent must never be asked to
  call Sentiment Agent.
- Block trade execution, order preparation, exact share-count instructions, and
  order placement with route unsupported and reason safety_blocked.
""".strip()


def validate_investment_plan(
    plan: InvestmentPlan,
    *,
    original_query: str | None = None,
) -> InvestmentPlanValidationResult:
    warnings = list(plan.warnings)
    if original_query is not None:
        normalized_original = normalize_source_query(original_query)
        if not normalized_original:
            raise InvestmentPlanValidationError("Original user query cannot be blank.")
        if contains_trade_execution_intent(original_query) and (
            plan.mode != "unsupported"
            or plan.needs_portfolio_agent
            or plan.needs_sentiment_agent
        ):
            raise InvestmentPlanValidationError(
                "Original user query contains trade execution or order-preparation intent."
            )
        if plan.portfolio_request is not None and (
            normalize_source_query(plan.portfolio_request.source_query)
            != normalized_original
        ):
            raise InvestmentPlanValidationError(
                "PortfolioRequest.source_query must preserve the original user query."
            )
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


def validate_investment_turn_decision(
    decision: InvestmentTurnDecision,
    baseline: PortfolioBaselinePacket,
    *,
    original_query: str,
) -> InvestmentTurnValidationResult:
    """Validate safety, request integrity, and baseline coverage before routing."""

    compatibility_plan = investment_turn_to_plan(decision)
    plan_validation = validate_investment_plan(
        compatibility_plan,
        original_query=original_query,
    )
    _validate_optional_portfolio_request(
        decision.fallback_portfolio_request,
        original_query=original_query,
        label="fallback_portfolio_request",
    )

    if decision.route != "direct_context":
        return InvestmentTurnValidationResult(
            decision=decision,
            coverage=None,
            fallback_used=False,
            warnings=_dedupe([*decision.warnings, *plan_validation.warnings]),
        )

    fallback = decision.fallback_portfolio_request
    coverage = validate_direct_answer_coverage(
        decision,
        baseline,
        freshness_requirement=(
            fallback.freshness_requirement if fallback is not None else "cached_ok"
        ),
        requested_window=fallback.time_range if fallback is not None else None,
        now=baseline.generated_at,
    )
    if coverage.is_valid:
        return InvestmentTurnValidationResult(
            decision=decision,
            coverage=coverage,
            fallback_used=False,
            warnings=_dedupe([*decision.warnings, *plan_validation.warnings]),
        )

    limitation = coverage.limitation or (
        "Direct baseline evidence is insufficient for this request."
    )
    if coverage.fallback_portfolio_request is None:
        unsupported = InvestmentTurnDecision(
            route="unsupported",
            route_reasons=["unsupported_request"],
            required_evidence=list(decision.required_evidence),
            cited_evidence_refs=[],
            missing_evidence=_coverage_missing_capabilities(decision, coverage),
            warnings=_dedupe([*decision.warnings, limitation]),
        )
        return InvestmentTurnValidationResult(
            decision=unsupported,
            coverage=coverage,
            fallback_used=False,
            warnings=unsupported.warnings,
        )

    delegated = InvestmentTurnDecision(
        route="delegate_portfolio",
        route_reasons=[_coverage_route_reason(coverage)],
        required_evidence=list(decision.required_evidence),
        cited_evidence_refs=[],
        missing_evidence=_coverage_missing_capabilities(decision, coverage),
        portfolio_request=coverage.fallback_portfolio_request,
        warnings=_dedupe([*decision.warnings, limitation]),
    )
    return InvestmentTurnValidationResult(
        decision=delegated,
        coverage=coverage,
        fallback_used=True,
        warnings=delegated.warnings,
    )


def investment_turn_to_plan(decision: InvestmentTurnDecision) -> InvestmentPlan:
    """Build the existing compatibility plan from an explicit route decision."""

    portfolio_request = decision.portfolio_request
    needs_portfolio = decision.route in {"delegate_portfolio", "delegate_both"}
    needs_sentiment = decision.route in {"delegate_sentiment", "delegate_both"}
    return InvestmentPlan(
        mode=_decision_mode(decision),
        needs_portfolio_agent=needs_portfolio,
        needs_sentiment_agent=needs_sentiment,
        portfolio_request=portfolio_request if needs_portfolio else None,
        sentiment_task=decision.sentiment_task if needs_sentiment else None,
        logical_asset_hints=(
            list(portfolio_request.asset_hints) if portfolio_request is not None else []
        ),
        themes=list(decision.route_reasons),
        time_horizon=(portfolio_request.time_range if portfolio_request is not None else None),
        freshness_requirement=(
            portfolio_request.freshness_requirement
            if portfolio_request is not None
            else "cached_ok"
        ),
        answer_constraints=[
            "no_trade_execution",
            "no_order_preparation",
            "no_exact_share_count",
            "source_backed",
        ],
        warnings=list(decision.warnings),
    )


def legacy_plan_to_turn_decision(plan: InvestmentPlan) -> InvestmentTurnDecision:
    """Adapt injected V1.4 planners without making them eligible for direct answers."""

    if plan.mode == "unsupported":
        return InvestmentTurnDecision(
            route="unsupported",
            route_reasons=["unsupported_request"],
            warnings=list(plan.warnings),
        )
    if plan.needs_portfolio_agent and plan.needs_sentiment_agent:
        route = "delegate_both"
        reasons = ["combined_evidence_required"]
    elif plan.needs_portfolio_agent:
        route = "delegate_portfolio"
        reasons = [_legacy_portfolio_route_reason(plan.portfolio_request)]
    elif plan.needs_sentiment_agent:
        route = "delegate_sentiment"
        reasons = ["sentiment_requested"]
    else:
        return InvestmentTurnDecision(
            route="unsupported",
            route_reasons=["unsupported_request"],
            warnings=_dedupe(
                [
                    *plan.warnings,
                    "A legacy InvestmentPlan without subagents cannot produce a "
                    "baseline-cited direct answer.",
                ]
            ),
        )
    return InvestmentTurnDecision(
        route=route,
        route_reasons=reasons,
        required_evidence=_required_evidence_from_request(plan.portfolio_request),
        missing_evidence=_required_evidence_from_request(plan.portfolio_request),
        portfolio_request=plan.portfolio_request,
        sentiment_task=plan.sentiment_task,
        warnings=list(plan.warnings),
    )


def _validate_optional_portfolio_request(
    request: PortfolioRequest | None,
    *,
    original_query: str,
    label: str,
) -> None:
    if request is None:
        return
    if normalize_source_query(request.source_query) != normalize_source_query(original_query):
        raise InvestmentPlanValidationError(
            f"{label}.source_query must preserve the original user query."
        )
    validation = validate_portfolio_request(request, [])
    if not validation.is_valid:
        messages = [issue.message for issue in validation.blocking_issues]
        raise InvestmentPlanValidationError(
            "; ".join(messages) or f"Invalid {label}."
        )


def _coverage_missing_capabilities(
    decision: InvestmentTurnDecision,
    coverage: DirectAnswerCoverageResult,
) -> list[BaselineCapability]:
    missing = [*coverage.missing_capabilities, *coverage.window_mismatches]
    if coverage.stale_evidence_refs or coverage.invalid_evidence_refs:
        missing.extend(decision.required_evidence)
    return _dedupe(missing)


def _coverage_route_reason(coverage: DirectAnswerCoverageResult) -> str:
    if coverage.stale_evidence_refs:
        return "stale_baseline"
    if coverage.window_mismatches:
        return "unsupported_time_window"
    return "missing_baseline_capability"


def _decision_mode(decision: InvestmentTurnDecision) -> str:
    if decision.route == "unsupported":
        return "unsupported"
    if decision.portfolio_request is not None:
        return {
            "full_review": "review",
            "portfolio_fact": "portfolio_fact",
            "risk_check": "risk_check",
            "what_changed": "what_changed",
            "deep_dive": "deep_dive",
            "compare": "compare",
        }[decision.portfolio_request.task_intent]
    if any(
        capability.startswith("portfolio_value_trend_")
        or capability.startswith("top_")
        for capability in decision.required_evidence
    ):
        return "what_changed"
    if decision.route == "delegate_sentiment":
        return "deep_dive"
    return "portfolio_fact"


def _legacy_portfolio_route_reason(request: PortfolioRequest | None) -> str:
    if request is None:
        return "missing_baseline_capability"
    if request.freshness_requirement == "latest_required":
        return "latest_opend_required"
    if request.task_intent == "risk_check":
        return "deeper_risk_required"
    if request.asset_hints:
        return "asset_detail_required"
    return "missing_baseline_capability"


def _required_evidence_from_request(
    request: PortfolioRequest | None,
) -> list[BaselineCapability]:
    if request is None:
        return []
    mapping: dict[str, BaselineCapability] = {
        "snapshot": "latest_snapshot",
        "allocation_context": "allocation_breakdown",
        "effective_cash": "effective_cash",
        "performance_context": "portfolio_value_trend_30d",
        "position_changes": "top_position_changes_7d",
    }
    return _dedupe([mapping[goal] for goal in request.output_goals if goal in mapping])


def normalize_source_query(query: str) -> str:
    """Normalize representation-only differences without rewriting user intent."""

    normalized = unicodedata.normalize("NFKC", query)
    return re.sub(r"\s+", " ", normalized).strip()


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
            "portfolio_analysis_requirement": [
                "deterministic_only",
                "interpretation_required",
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
                "analysis_requirement": "deterministic_only",
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


def _investment_turn_prompt(
    *,
    query: str,
    ips: InvestmentPolicy,
    baseline: PortfolioBaselinePacket,
) -> str:
    context = {
        "user_query": query,
        "investment_policy": ips.model_dump(mode="json"),
        "portfolio_baseline": _baseline_prompt_payload(baseline),
        "allowed_values": {
            "route": [
                "direct_context",
                "delegate_portfolio",
                "delegate_sentiment",
                "delegate_both",
                "unsupported",
            ],
            "route_reason": [
                "baseline_sufficient",
                "portfolio_not_required",
                "missing_baseline_capability",
                "stale_baseline",
                "unsupported_time_window",
                "asset_detail_required",
                "cost_basis_required",
                "deeper_risk_required",
                "anomaly_investigation_required",
                "latest_opend_required",
                "sentiment_requested",
                "combined_evidence_required",
                "unsupported_request",
                "safety_blocked",
            ],
            "baseline_capability": [
                "latest_snapshot",
                "allocation_breakdown",
                "effective_cash",
                "portfolio_value_trend_7d",
                "portfolio_value_trend_30d",
                "top_allocation_changes_7d",
                "top_position_changes_7d",
                "history_freshness",
            ],
            "freshness_requirement": ["latest_required", "cached_ok", "history_only"],
            "portfolio_task_intent": [
                "full_review",
                "portfolio_fact",
                "risk_check",
                "what_changed",
                "deep_dive",
                "compare",
            ],
            "portfolio_output_goal": [
                "snapshot",
                "allocation_context",
                "performance_context",
                "risk_context",
                "effective_cash",
                "position_changes",
                "portfolio_patterns",
                "derived_metrics",
                "sentiment_context_needs",
            ],
            "portfolio_analysis_requirement": [
                "deterministic_only",
                "interpretation_required",
            ],
            "time_window_format": (
                "positive integer plus d, w, m, or y; examples: 7d, 30d, 12w, 1y"
            ),
        },
        "output_requirements": {
            "direct_context": (
                "direct_answer plus exact cited_evidence_refs and required_evidence; "
                "no subagent task"
            ),
            "delegate_portfolio": (
                "one bounded portfolio_request with an explicit missing-evidence reason and "
                "analysis_requirement; use deterministic_only for structured fact/metric "
                "retrieval and interpretation_required only for deeper explanation, ranking, "
                "or anomaly analysis"
            ),
            "delegate_sentiment": "one bounded sentiment_task",
            "delegate_both": "one bounded portfolio_request and one sentiment_task",
            "unsupported": "no subagent tasks and an explicit reason/warning",
        },
        "direct_example": {
            "route": "direct_context",
            "route_reasons": ["baseline_sufficient"],
            "required_evidence": ["latest_snapshot"],
            "cited_evidence_refs": ["an exact ref_id from portfolio_baseline"],
            "missing_evidence": [],
            "direct_answer": "A concise answer with stored as_of and limitations.",
            "portfolio_request": None,
            "fallback_portfolio_request": {
                "task_intent": "portfolio_fact",
                "asset_hints": [],
                "time_range": None,
                "freshness_requirement": "cached_ok",
                "output_goals": ["snapshot"],
                "analysis_requirement": "deterministic_only",
                "source_query": query,
                "warnings": [],
            },
            "sentiment_task": None,
            "warnings": [],
        },
    }
    return json.dumps(context, sort_keys=True)


def _baseline_prompt_payload(baseline: PortfolioBaselinePacket) -> dict[str, Any]:
    """Keep the LLM input limited to the already bounded public baseline contract."""

    return {
        "schema_version": baseline.schema_version,
        "generated_at": baseline.generated_at.isoformat(),
        "as_of": baseline.as_of.isoformat() if baseline.as_of else None,
        "capabilities": list(baseline.capabilities),
        "summaries": [summary.model_dump(mode="json") for summary in baseline.summaries],
        "evidence_refs": [ref.model_dump(mode="json") for ref in baseline.evidence_refs],
        "warnings": list(baseline.warnings),
        "limitations": list(baseline.limitations),
    }


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


_INVESTMENT_PLAN_ENVELOPES = ("investment_plan", "plan", "result", "response", "data")
_INVESTMENT_TURN_ENVELOPES = (
    "investment_turn",
    "turn_decision",
    "decision",
    "result",
    "response",
    "data",
)
_PROVIDER_METADATA_FIELDS = {
    "id",
    "model",
    "provider",
    "request_id",
    "usage",
}
_INVESTMENT_PLANNER_CONTROLLED_FIELDS = {
    "mode",
    "needs_portfolio_agent",
    "needs_sentiment_agent",
}
_INVESTMENT_TURN_CONTROLLED_FIELDS = {"route", "route_reasons"}


def _normalize_investment_plan_payload(payload: dict[str, Any]) -> dict[str, Any]:
    envelope_keys = [
        key for key in _INVESTMENT_PLAN_ENVELOPES if isinstance(payload.get(key), dict)
    ]
    if len(envelope_keys) > 1:
        raise ValueError("Investment planner returned multiple recognized plan envelopes.")
    if envelope_keys:
        envelope_key = envelope_keys[0]
        siblings = set(payload) - {envelope_key}
        if not siblings <= _PROVIDER_METADATA_FIELDS:
            raise ValueError(
                "Investment planner envelope contains ambiguous non-metadata fields."
            )
        payload = payload[envelope_key]

    allowed = InvestmentPlan.model_fields.keys()
    selected = {key: value for key, value in payload.items() if key in allowed}
    if not (_INVESTMENT_PLANNER_CONTROLLED_FIELDS & selected.keys()):
        raise ValueError("Investment planner returned no planner-controlled fields.")
    return selected


def _normalize_investment_turn_payload(payload: dict[str, Any]) -> dict[str, Any]:
    envelope_keys = [
        key for key in _INVESTMENT_TURN_ENVELOPES if isinstance(payload.get(key), dict)
    ]
    if len(envelope_keys) > 1:
        raise ValueError("Investment planner returned multiple recognized turn envelopes.")
    if envelope_keys:
        envelope_key = envelope_keys[0]
        siblings = set(payload) - {envelope_key}
        if not siblings <= _PROVIDER_METADATA_FIELDS:
            raise ValueError(
                "Investment turn envelope contains ambiguous non-metadata fields."
            )
        payload = payload[envelope_key]

    allowed = InvestmentTurnDecision.model_fields.keys()
    selected = {key: value for key, value in payload.items() if key in allowed}
    if not _INVESTMENT_TURN_CONTROLLED_FIELDS <= selected.keys():
        raise ValueError("Investment planner returned no complete route decision.")
    return selected


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
