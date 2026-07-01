from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Protocol

from moomail_finance_ai.agent_schemas import (
    AssetResolution,
    HistoryQuery,
    PortfolioContextPlan,
    PortfolioEvidencePlan,
    PortfolioRequest,
    PortfolioTask,
    PositionChangeScopeEntry,
)
from moomail_finance_ai.asset_resolver import (
    PortfolioAssetCandidate,
    resolve_asset_hints,
    validate_portfolio_request,
)
from moomail_finance_ai.llm import TextLLMClient, build_llm_client_from_env
from moomail_finance_ai.schemas import InvestmentPolicy


class PortfolioEvidencePlanner(Protocol):
    def plan(
        self,
        request: PortfolioRequest,
        ips: InvestmentPolicy,
        candidates: Iterable[PortfolioAssetCandidate | dict],
    ) -> PortfolioEvidencePlan: ...


class PortfolioEvidencePlanningUnavailableError(RuntimeError):
    """Raised when the required LLM planner cannot produce a usable evidence plan."""

    def __init__(self, message: str, *, cause: BaseException | None = None):
        super().__init__(message)
        self.__cause__ = cause


class PortfolioEvidencePlanValidationError(ValueError):
    """Raised when a portfolio evidence request is unsafe or inconsistent."""


@dataclass
class UnavailablePortfolioEvidencePlanner:
    """Planner used only when the configured LLM client cannot be constructed."""

    reason: str

    def plan(
        self,
        request: PortfolioRequest,
        ips: InvestmentPolicy,
        candidates: Iterable[PortfolioAssetCandidate | dict],
    ) -> PortfolioEvidencePlan:
        del request, ips, candidates
        raise PortfolioEvidencePlanningUnavailableError(self.reason)


@dataclass
class LLMPortfolioEvidencePlanner:
    """Structured-output Portfolio evidence planner backed by the configured LLM."""

    llm: TextLLMClient

    @classmethod
    def from_env(
        cls,
        *,
        provider: str | None = None,
        env_file: str | Path | None = "config/local.env",
    ) -> LLMPortfolioEvidencePlanner:
        return cls(build_llm_client_from_env(provider=provider, env_file=env_file))

    def plan(
        self,
        request: PortfolioRequest,
        ips: InvestmentPolicy,
        candidates: Iterable[PortfolioAssetCandidate | dict],
    ) -> PortfolioEvidencePlan:
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

        try:
            text = self.llm.generate_text(
                _portfolio_planner_prompt(
                    request=request,
                    ips=ips,
                    resolutions=resolutions,
                    validation_warnings=[
                        issue.message for issue in validation.warnings
                    ],
                ),
                system_instruction=PORTFOLIO_EVIDENCE_PLANNER_SYSTEM_PROMPT,
                max_output_tokens=4096,
                temperature=0.0,
            )
            payload = _extract_json_object(text)
            payload.update(
                {
                    "task_intent": request.task_intent,
                    "resolved_assets": [
                        resolution.model_dump(mode="json") for resolution in resolutions
                    ],
                    "history_window": request.time_range,
                    "freshness_requirement": request.freshness_requirement,
                    "warnings": _dedupe(
                        [
                            *request.warnings,
                            *(issue.message for issue in validation.warnings),
                            *payload.get("warnings", []),
                        ]
                    ),
                }
            )
            plan = PortfolioEvidencePlan.model_validate(payload)
            validate_portfolio_evidence_plan(request, plan)
            return plan
        except PortfolioEvidencePlanValidationError:
            raise
        except Exception as exc:
            raise PortfolioEvidencePlanningUnavailableError(
                "Portfolio evidence planning is unavailable because the LLM planner "
                "did not return a valid structured PortfolioEvidencePlan. No "
                "deterministic fallback planner is configured.",
                cause=exc,
            ) from exc


PORTFOLIO_EVIDENCE_PLANNER_SYSTEM_PROMPT = """
You are the Portfolio Agent evidence planner for a personal finance AI.
Return only one JSON object matching the PortfolioEvidencePlan schema. Do not use
markdown, comments, prose, or code fences.

You receive a bounded PortfolioRequest plus deterministic asset-resolution
results. Choose only portfolio evidence subtasks, history queries, metric
groups, freshness/current-value dependency, position-change scope, persistence
mode, pattern detectors, and warnings. Stay inside the request's task intent and
output goals.

Rules:
- Do not route the Sentiment Agent.
- Do not produce final recommendations, thesis, order guidance, trade execution,
  exact share counts, or external market claims.
- Do not invent SQL asset ids, broker symbols, or holdings. Use only the provided
  resolved assets.
- Use only the allowed enum values provided in the prompt.
- If a requested output is incoherent, preserve the bounded request and add a
  warning rather than changing the mission.
""".strip()


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
        position_change_scopes=_position_change_scope_entries(history_queries, resolved),
        metric_groups=plan.metric_groups,
        persist_observation=plan.persistence_mode in {"auto", "persist"},
        history_window=plan.history_window,
        row_limit=100 if needs_sql_history else 30,
        warnings=list(plan.warnings),
    )


def _portfolio_planner_prompt(
    *,
    request: PortfolioRequest,
    ips: InvestmentPolicy,
    resolutions: list[AssetResolution],
    validation_warnings: list[str],
) -> str:
    context = {
        "portfolio_request": request.model_dump(mode="json"),
        "investment_policy": ips.model_dump(mode="json"),
        "resolved_assets": [resolution.model_dump(mode="json") for resolution in resolutions],
        "validation_warnings": validation_warnings,
        "allowed_values": {
            "history_queries": [
                "none",
                "history_status",
                "latest_state",
                "portfolio_growth",
                "allocation_history",
                "position_state_changes",
            ],
            "metric_groups": [
                "allocation",
                "concentration",
                "effective_cash",
                "risk",
                "performance",
            ],
            "position_change_scope": [
                "none",
                "portfolio_wide",
                "ticker_scoped",
                "asset_scoped",
            ],
            "persistence_mode": ["auto", "persist", "skip"],
            "pattern_detectors": [
                "stale_data",
                "unsupported_quote_warnings",
                "concentration",
                "allocation_drift",
                "cash_effective_cash",
                "large_position_changes",
                "average_cost_shifts",
                "portfolio_outliers",
                "sentiment_context_needed",
            ],
        },
        "output_shape": {
            "task_intent": request.task_intent,
            "resolved_assets": [],
            "history_queries": ["history_status"],
            "metric_groups": ["allocation"],
            "needs_current_values": True,
            "history_window": request.time_range,
            "freshness_requirement": request.freshness_requirement,
            "position_change_scope": "none",
            "persistence_mode": "auto",
            "pattern_detectors": ["stale_data"],
            "warnings": [],
        },
    }
    return json.dumps(context, sort_keys=True)


def validate_portfolio_evidence_plan(
    request: PortfolioRequest,
    plan: PortfolioEvidencePlan,
) -> None:
    problems: list[str] = []
    goals = set(request.output_goals)
    history_queries = set(plan.history_queries)
    metric_groups = set(plan.metric_groups)

    if plan.task_intent != request.task_intent:
        problems.append("task_intent must match the PortfolioRequest.")
    if plan.history_window != request.time_range:
        problems.append("history_window must match the PortfolioRequest time_range.")
    if plan.freshness_requirement != request.freshness_requirement:
        problems.append("freshness_requirement must match the PortfolioRequest.")

    if request.freshness_requirement == "latest_required" and not plan.needs_current_values:
        problems.append("latest_required requests require needs_current_values=true.")
    if request.freshness_requirement == "history_only":
        if plan.needs_current_values:
            problems.append("history_only requests require needs_current_values=false.")
        if plan.persistence_mode != "skip":
            problems.append("history_only requests cannot persist a current observation.")
    if (
        request.freshness_requirement == "cached_ok"
        and _goals_require_snapshot_values(goals)
        and not plan.needs_current_values
    ):
        problems.append("cached_ok snapshot-valued requests require needs_current_values=true.")

    if _request_requires_history(request, goals) and history_queries == {"none"}:
        problems.append("requested historical outputs require SQL history queries.")

    if "position_changes" in goals:
        if "position_state_changes" not in history_queries:
            problems.append("position_changes requires position_state_changes history.")
        if plan.position_change_scope == "none":
            problems.append("position_changes requires a non-none position_change_scope.")
        expected_scope = _expected_position_change_scope(request, plan)
        if expected_scope and plan.position_change_scope != expected_scope:
            problems.append(
                "position_change_scope must match deterministic asset-resolution scope."
            )
    elif (
        plan.position_change_scope != "none"
        and "position_state_changes" not in history_queries
    ):
        problems.append(
            "position_change_scope must be none unless position_state_changes is planned."
        )

    missing_metrics = [
        metric
        for metric in _required_metric_groups(request, goals)
        if metric not in metric_groups and "all" not in metric_groups
    ]
    if missing_metrics:
        problems.append(
            "metric_groups missing required groups: " + ", ".join(missing_metrics) + "."
        )

    if "portfolio_patterns" in goals and not plan.pattern_detectors:
        problems.append("portfolio_patterns requires at least one pattern detector.")
    if (
        "sentiment_context_needs" in goals
        and "sentiment_context_needed" not in plan.pattern_detectors
    ):
        problems.append(
            "sentiment_context_needs requires the sentiment_context_needed pattern detector."
        )

    if problems:
        raise PortfolioEvidencePlanValidationError("; ".join(problems))


def _required_outputs_from_goals(goals: list[str]) -> list[str]:
    output_map = {
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


def _goals_require_snapshot_values(goals: set[str]) -> bool:
    return bool(
        goals
        & {
            "snapshot",
            "allocation_context",
            "performance_context",
            "risk_context",
            "effective_cash",
            "portfolio_patterns",
            "derived_metrics",
            "sentiment_context_needs",
        }
    )


def _request_requires_history(request: PortfolioRequest, goals: set[str]) -> bool:
    return (
        request.task_intent in {"full_review", "deep_dive", "compare", "what_changed"}
        or bool(goals & {"position_changes", "performance_context", "derived_metrics"})
    )


def _expected_position_change_scope(
    request: PortfolioRequest,
    plan: PortfolioEvidencePlan,
) -> str | None:
    if not request.asset_hints:
        return "portfolio_wide"
    resolved = [
        asset for asset in plan.resolved_assets if asset.resolution_status == "resolved"
    ]
    if any(asset.sql_asset_id for asset in resolved):
        return "asset_scoped"
    if any(_ticker_from_resolution(asset) for asset in resolved):
        return "ticker_scoped"
    return None


def _required_metric_groups(request: PortfolioRequest, goals: set[str]) -> list[str]:
    required: list[str] = []
    if request.task_intent in {"full_review", "deep_dive", "compare"}:
        required.extend(["allocation", "concentration", "effective_cash", "risk", "performance"])
    if "allocation_context" in goals:
        required.append("allocation")
    if "risk_context" in goals:
        required.append("risk")
    if "effective_cash" in goals:
        required.append("effective_cash")
    if goals & {"performance_context", "derived_metrics", "position_changes"}:
        required.append("performance")
    return _dedupe(required)


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
    return _dedupe([hint.raw_input.strip().upper() for hint in request.asset_hints])


def _position_change_scope_entries(
    history_queries: list[HistoryQuery],
    resolutions: list[AssetResolution],
) -> list[PositionChangeScopeEntry]:
    if "position_state_changes" not in history_queries:
        return []
    scopes = []
    for asset in resolutions:
        ticker = _ticker_from_resolution(asset)
        if asset.sql_asset_id:
            scopes.append(PositionChangeScopeEntry(asset_id=asset.sql_asset_id, ticker=ticker))
        elif ticker:
            scopes.append(PositionChangeScopeEntry(ticker=ticker))
    return scopes


def _ticker_from_resolution(asset: AssetResolution) -> str:
    symbol = asset.canonical_symbol or asset.input
    return _ticker_from_symbol(symbol)


def _ticker_from_symbol(symbol: str) -> str:
    normalized = symbol.strip().upper()
    prefix, separator, ticker = normalized.partition(".")
    if separator and prefix in {"US", "HK", "CN", "SG", "JP", "UK", "EU", "AU", "CA", "CRYPTO"}:
        return ticker
    return normalized


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
