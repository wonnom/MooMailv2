from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable, Protocol

from moomail_finance_ai.agent_schemas import (
    AssetHint,
    AssetResolution,
    HistoryQuery,
    MetricGroup,
    PortfolioContextPlan,
    PortfolioEvidencePlan,
    PortfolioOutputGoal,
    PortfolioOutputKind,
    PortfolioRequest,
    PortfolioTask,
)
from moomail_finance_ai.asset_resolver import (
    PortfolioAssetCandidate,
    resolve_asset_hints,
    validate_portfolio_request,
)
from moomail_finance_ai.schemas import InvestmentPolicy


PORTFOLIO_REVIEW_TERMS = ("review", "analyze", "analyse", "breakdown", "overview")
PORTFOLIO_CASH_TERMS = ("cash", "effective cash", "buying power", "purchase power")
PORTFOLIO_ALLOCATION_TERMS = ("allocation", "allocations", "weight", "weights")
PORTFOLIO_POSITION_TERMS = ("holding", "holdings", "position", "positions", "value")
PORTFOLIO_HISTORY_TERMS = (
    "what changed",
    "changed",
    "history",
    "growth",
    "performance",
    "bought",
    "purchased",
    "sold",
    "added",
    "reduced",
    "increased",
    "decreased",
    "average cost",
    "cost basis",
)
PORTFOLIO_RISK_TERMS = ("risk", "concentration", "downside", "drawdown")


class PortfolioEvidencePlanner(Protocol):
    def plan(
        self,
        request: PortfolioRequest,
        ips: InvestmentPolicy,
        candidates: Iterable[PortfolioAssetCandidate | dict],
    ) -> PortfolioEvidencePlan: ...


class PortfolioEvidencePlanValidationError(ValueError):
    """Raised when a portfolio evidence request is unsafe or inconsistent."""


@dataclass
class DeterministicPortfolioEvidencePlanner:
    """Offline-safe PortfolioRequest-to-PortfolioEvidencePlan planner."""

    def plan(
        self,
        request: PortfolioRequest,
        ips: InvestmentPolicy,
        candidates: Iterable[PortfolioAssetCandidate | dict],
    ) -> PortfolioEvidencePlan:
        del ips
        resolutions = resolve_asset_hints(request.asset_hints, candidates)
        validation = validate_portfolio_request(request, resolutions)
        if not validation.is_valid:
            messages = [
                issue.message
                for issue in validation.blocking_issues
                if issue.severity == "blocking"
            ]
            raise PortfolioEvidencePlanValidationError(
                "; ".join(messages) or "Invalid portfolio evidence request."
            )

        warnings = list(request.warnings)
        warnings.extend(issue.message for issue in validation.warnings)
        warnings.extend(_incoherent_goal_warnings(request))
        if "sentiment_context_needs" in request.output_goals:
            warnings.append(
                "Portfolio Evidence Planner records sentiment context needs but does not "
                "route the Sentiment Agent."
            )

        history_queries = _history_queries_for_request(request)
        return PortfolioEvidencePlan(
            task_intent=request.task_intent,
            resolved_assets=resolutions,
            history_queries=history_queries,
            metric_groups=_metric_groups_for_request(request),
            needs_current_values=_needs_current_values(request),
            history_window=request.time_range,
            freshness_requirement=request.freshness_requirement,
            position_change_scope=_position_change_scope(history_queries, resolutions),
            persistence_mode=_persistence_mode_for_request(request),
            pattern_detectors=_pattern_detectors_for_request(request),
            warnings=_dedupe(warnings),
        )


@dataclass
class FallbackPortfolioEvidencePlanner:
    """Explicit keyword fallback matching the pre-V1.4 PortfolioTask behavior."""

    evidence_planner: PortfolioEvidencePlanner = field(
        default_factory=DeterministicPortfolioEvidencePlanner
    )

    def request_from_query(self, query: str) -> PortfolioRequest:
        return portfolio_task_to_request(fallback_portfolio_task_from_query(query))

    def task_from_query(self, query: str) -> PortfolioTask:
        return fallback_portfolio_task_from_query(query)

    def plan_from_query(
        self,
        query: str,
        ips: InvestmentPolicy,
        candidates: Iterable[PortfolioAssetCandidate | dict],
    ) -> PortfolioEvidencePlan:
        return self.evidence_planner.plan(self.request_from_query(query), ips, candidates)


def fallback_portfolio_task_from_query(query: str) -> PortfolioTask:
    lowered = query.lower()
    if _contains_any(lowered, PORTFOLIO_REVIEW_TERMS):
        task_type = "full_review"
    elif _contains_any(lowered, PORTFOLIO_HISTORY_TERMS):
        task_type = "what_changed"
    elif _contains_any(lowered, PORTFOLIO_RISK_TERMS):
        task_type = "risk_check"
    elif _contains_any(
        lowered,
        (*PORTFOLIO_CASH_TERMS, *PORTFOLIO_ALLOCATION_TERMS, *PORTFOLIO_POSITION_TERMS),
    ):
        task_type = "portfolio_fact"
    else:
        task_type = "full_review"

    return PortfolioTask(
        task_type=task_type,
        source_query=query,
        requested_tickers=extract_portfolio_tickers(query),
        history_window="90d" if task_type == "what_changed" else "30d",
        required_outputs=_portfolio_required_outputs(task_type, lowered),
        persistence_mode="auto",
        focus_areas=_portfolio_focus_areas(task_type, lowered),
    )


def portfolio_task_to_request(task: PortfolioTask) -> PortfolioRequest:
    task_intent = "full_review" if task.task_type == "unsupported" else task.task_type
    return PortfolioRequest(
        task_intent=task_intent,
        asset_hints=[
            AssetHint(raw_input=ticker, source_field="portfolio_task.requested_tickers")
            for ticker in task.requested_tickers
        ],
        time_range=task.history_window,
        freshness_requirement=_freshness_for_task(task),
        output_goals=_output_goals_from_required_outputs(task),
        source_query=task.source_query,
        warnings=list(task.warnings),
    )


def portfolio_request_to_task(
    request: PortfolioRequest,
    plan: PortfolioEvidencePlan | None = None,
) -> PortfolioTask:
    return PortfolioTask(
        task_type=request.task_intent,
        source_query=request.source_query,
        requested_tickers=_tickers_from_request_or_plan(request, plan),
        history_window=request.time_range,
        required_outputs=_required_outputs_from_goals(request.output_goals),
        persistence_mode=plan.persistence_mode if plan is not None else "auto",
        focus_areas=[request.task_intent, *request.output_goals],
        warnings=list(request.warnings) + (list(plan.warnings) if plan is not None else []),
    )


def portfolio_evidence_plan_to_context_plan(
    plan: PortfolioEvidencePlan,
    *,
    runtime_requires_current_snapshot: bool = True,
) -> PortfolioContextPlan:
    history_queries = plan.history_queries
    needs_sql_history = history_queries != ["none"]
    resolved = [asset for asset in plan.resolved_assets if asset.resolution_status == "resolved"]
    return PortfolioContextPlan(
        needs_current_snapshot=plan.needs_current_values or runtime_requires_current_snapshot,
        needs_sql_history=needs_sql_history,
        history_queries=history_queries,
        asset_ids=[asset.sql_asset_id for asset in resolved if asset.sql_asset_id],
        canonical_symbols=[asset.canonical_symbol for asset in resolved if asset.canonical_symbol],
        tickers=[_ticker_from_resolution(asset) for asset in resolved],
        metric_groups=plan.metric_groups,
        persist_observation=plan.persistence_mode in {"auto", "persist"},
        history_window=plan.history_window,
        row_limit=100 if needs_sql_history else 30,
        warnings=list(plan.warnings),
    )


def extract_portfolio_tickers(query: str) -> list[str]:
    tickers = re.findall(r"\b(?:US\.)?[A-Z]{1,5}\b", query)
    stopwords = {"I", "A", "US", "USD", "ETF", "LLM", "AI"}
    normalized = []
    for ticker in tickers:
        ticker = ticker.removeprefix("US.").upper()
        if ticker not in stopwords:
            normalized.append(ticker)
    return _dedupe(normalized)


def _history_queries_for_request(request: PortfolioRequest) -> list[HistoryQuery]:
    goals = set(request.output_goals)
    if request.task_intent in {"full_review", "deep_dive", "compare"}:
        return [
            "history_status",
            "latest_state",
            "portfolio_growth",
            "allocation_history",
            "position_state_changes",
        ]
    if request.task_intent == "what_changed" or "position_changes" in goals:
        return [
            "history_status",
            "latest_state",
            "portfolio_growth",
            "allocation_history",
            "position_state_changes",
        ]
    if "performance_context" in goals:
        return ["history_status", "latest_state", "portfolio_growth"]
    return ["none"]


def _metric_groups_for_request(request: PortfolioRequest) -> list[MetricGroup]:
    goals = set(request.output_goals)
    if request.task_intent in {"full_review", "deep_dive", "compare"}:
        return ["allocation", "concentration", "effective_cash", "risk", "performance"]
    groups: list[MetricGroup] = []
    if "allocation_context" in goals or goals == {"snapshot"}:
        groups.append("allocation")
    if "effective_cash" in goals:
        groups.append("effective_cash")
    if request.task_intent == "risk_check" or "risk_context" in goals:
        groups.extend(["allocation", "concentration", "effective_cash", "risk"])
    if "performance_context" in goals or "position_changes" in goals:
        groups.append("performance")
    return _dedupe(groups or ["allocation"])


def _needs_current_values(request: PortfolioRequest) -> bool:
    if request.freshness_requirement == "history_only":
        return False
    return True


def _persistence_mode_for_request(request: PortfolioRequest) -> str:
    if request.freshness_requirement == "history_only":
        return "skip"
    if request.task_intent in {"full_review", "what_changed", "deep_dive", "compare"}:
        return "persist"
    return "skip"


def _position_change_scope(
    history_queries: list[HistoryQuery],
    resolutions: list[AssetResolution],
) -> str:
    if "position_state_changes" not in history_queries:
        return "none"
    resolved = [asset for asset in resolutions if asset.resolution_status == "resolved"]
    if not resolved:
        return "portfolio_wide"
    if any(asset.sql_asset_id for asset in resolved):
        return "asset_scoped"
    return "ticker_scoped"


def _pattern_detectors_for_request(request: PortfolioRequest) -> list[str]:
    goals = set(request.output_goals)
    detectors = ["stale_data", "unsupported_quote_warnings"]
    if request.task_intent in {"full_review", "risk_check", "deep_dive", "compare"}:
        detectors.append("concentration")
    if request.task_intent in {"full_review", "compare"} or "allocation_context" in goals:
        detectors.append("allocation_drift")
    if "effective_cash" in goals:
        detectors.append("cash_effective_cash")
    if request.task_intent == "what_changed" or "position_changes" in goals:
        detectors.extend(["large_position_changes", "average_cost_shifts"])
    if "portfolio_patterns" in goals:
        detectors.append("portfolio_outliers")
    if "sentiment_context_needs" in goals:
        detectors.append("sentiment_context_needed")
    return _dedupe(detectors)


def _incoherent_goal_warnings(request: PortfolioRequest) -> list[str]:
    warnings = []
    if request.task_intent == "portfolio_fact" and "position_changes" in request.output_goals:
        warnings.append(
            "position_changes was requested for a portfolio_fact task; planning bounded "
            "history evidence without changing the task intent."
        )
    if request.freshness_requirement == "history_only" and "effective_cash" in request.output_goals:
        warnings.append(
            "effective_cash normally depends on current values; history_only freshness may "
            "return cached or historical evidence only."
        )
    return warnings


def _freshness_for_task(task: PortfolioTask) -> str:
    if task.task_type == "what_changed":
        return "history_only"
    return "latest_required"


def _output_goals_from_required_outputs(task: PortfolioTask) -> list[PortfolioOutputGoal]:
    outputs = set(task.required_outputs)
    goals: list[PortfolioOutputGoal] = []
    output_map: dict[PortfolioOutputKind, PortfolioOutputGoal] = {
        "snapshot": "snapshot",
        "allocation": "allocation_context",
        "performance": "performance_context",
        "risk": "risk_context",
        "effective_cash": "effective_cash",
        "candidate_issues": "portfolio_patterns",
        "sentiment_candidates": "sentiment_context_needs",
    }
    for output in task.required_outputs:
        if output == "history_context":
            if task.task_type == "what_changed":
                goals.append("position_changes")
            else:
                goals.append("performance_context")
            continue
        mapped = output_map.get(output)
        if mapped:
            goals.append(mapped)
    if task.task_type == "what_changed":
        goals.append("position_changes")
    if task.task_type in {"full_review", "deep_dive", "compare"}:
        goals.append("portfolio_patterns")
    if "snapshot" in outputs and "snapshot" not in goals:
        goals.insert(0, "snapshot")
    return _dedupe(goals or ["snapshot"])


def _required_outputs_from_goals(goals: list[PortfolioOutputGoal]) -> list[PortfolioOutputKind]:
    output_map: dict[PortfolioOutputGoal, PortfolioOutputKind] = {
        "snapshot": "snapshot",
        "allocation_context": "allocation",
        "performance_context": "performance",
        "risk_context": "risk",
        "effective_cash": "effective_cash",
        "position_changes": "history_context",
        "portfolio_patterns": "candidate_issues",
        "derived_metrics": "performance",
        "sentiment_context_needs": "sentiment_candidates",
    }
    return _dedupe([output_map[goal] for goal in goals if goal in output_map])


def _tickers_from_request_or_plan(
    request: PortfolioRequest,
    plan: PortfolioEvidencePlan | None,
) -> list[str]:
    if plan is not None:
        resolved_tickers = [
            _ticker_from_resolution(asset)
            for asset in plan.resolved_assets
            if asset.resolution_status == "resolved"
        ]
        if resolved_tickers:
            return _dedupe(resolved_tickers)
    return _dedupe(
        [hint.raw_input.strip().upper().removeprefix("US.") for hint in request.asset_hints]
    )


def _portfolio_required_outputs(task_type: str, lowered_query: str) -> list[str]:
    if task_type == "what_changed":
        return ["snapshot", "performance", "history_context", "sentiment_candidates"]
    if task_type == "risk_check":
        return ["snapshot", "allocation", "risk", "candidate_issues", "sentiment_candidates"]
    if task_type == "portfolio_fact":
        outputs = ["snapshot"]
        if _contains_any(lowered_query, PORTFOLIO_ALLOCATION_TERMS):
            outputs.append("allocation")
        if _contains_any(lowered_query, PORTFOLIO_CASH_TERMS):
            outputs.append("effective_cash")
        if _contains_any(lowered_query, PORTFOLIO_POSITION_TERMS):
            outputs.append("allocation")
        return _dedupe(outputs or ["snapshot"])
    return [
        "snapshot",
        "allocation",
        "performance",
        "risk",
        "effective_cash",
        "candidate_issues",
        "sentiment_candidates",
        "history_context",
    ]


def _portfolio_focus_areas(task_type: str, lowered_query: str) -> list[str]:
    focus = [task_type]
    if _contains_any(lowered_query, PORTFOLIO_CASH_TERMS):
        focus.append("cash")
    if _contains_any(lowered_query, PORTFOLIO_ALLOCATION_TERMS):
        focus.append("allocation")
    if _contains_any(lowered_query, PORTFOLIO_RISK_TERMS):
        focus.append("risk")
    return _dedupe(focus)


def _ticker_from_resolution(asset: AssetResolution) -> str:
    symbol = asset.canonical_symbol or asset.input
    return symbol.upper().removeprefix("US.").split(".", 1)[-1]


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in text for term in terms)


def _dedupe(values: list[str]) -> list[str]:
    seen = set()
    result = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
