from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

from pydantic import Field

from moomail_finance_ai.agent_schemas import (
    AssetHint,
    InvestmentPlan,
    InvestmentQueryPlan,
    PortfolioOutputGoal,
    PortfolioRequest,
    PortfolioTask,
    SentimentTask,
)
from moomail_finance_ai.asset_resolver import validate_portfolio_request
from moomail_finance_ai.schemas import InvestmentPolicy, StrictModel


TRADE_EXECUTION_TERMS = (
    "place order",
    "place a trade",
    "execute trade",
    "execute the trade",
    "submit order",
    "submit the order",
    "market order",
    "limit order",
)
PORTFOLIO_FACT_TERMS = (
    "cash",
    "effective cash",
    "allocation",
    "allocations",
    "holding",
    "holdings",
    "position",
    "positions",
    "weight",
    "weights",
    "value",
)
HISTORY_TERMS = (
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
    "recent purchase",
    "recently purchased",
    "buy my recent",
    "did i buy",
    "what price did i buy",
)
SENTIMENT_TERMS = (
    "sentiment",
    "research",
    "news",
    "outlook",
    "thesis",
    "earnings",
    "transcript",
    "shareholder letter",
    "management",
)
RISK_TERMS = ("risk", "concentration", "drawdown", "downside")
COMPARE_TERMS = ("compare", "versus", "vs ")
LATEST_TERMS = ("latest", "current", "now", "today", "live")


class InvestmentPlanner(Protocol):
    def plan(self, query: str, ips: InvestmentPolicy) -> InvestmentPlan: ...


class InvestmentPlanValidationError(ValueError):
    """Raised when a planner emits an unsafe or inconsistent investment plan."""


class InvestmentPlanValidationResult(StrictModel):
    is_valid: bool
    warnings: list[str] = Field(default_factory=list)


@dataclass
class DeterministicInvestmentPlanner:
    """Offline-safe fallback planner used by tests and local deterministic runs."""

    def plan(self, query: str, ips: InvestmentPolicy) -> InvestmentPlan:
        del ips
        lowered = query.lower()
        asset_hints = _asset_hints_from_query(query)
        explicit_sentiment = _contains_any(lowered, SENTIMENT_TERMS)

        if _contains_any(lowered, TRADE_EXECUTION_TERMS):
            return InvestmentPlan(
                mode="unsupported",
                needs_portfolio_agent=False,
                needs_sentiment_agent=False,
                logical_asset_hints=asset_hints,
                time_horizon=None,
                freshness_requirement="cached_ok",
                warnings=[
                    "Trade execution requests are outside the allowed investment-analysis scope."
                ],
            )

        mode = _mode_for_query(lowered, explicit_sentiment)
        needs_sentiment = _needs_sentiment(mode, explicit_sentiment)
        freshness_requirement = _freshness_requirement(lowered, mode)
        portfolio_request = PortfolioRequest(
            task_intent=_portfolio_task_intent_for_mode(mode),
            asset_hints=asset_hints,
            time_range="90d" if mode == "what_changed" else "30d",
            freshness_requirement=freshness_requirement,
            output_goals=_portfolio_output_goals(mode, lowered, needs_sentiment),
            source_query=query,
        )
        sentiment_task = (
            SentimentTask(
                tickers=[_ticker_from_hint(hint) for hint in asset_hints if _ticker_from_hint(hint)],
                companies_entities=[],
                themes=_sentiment_themes_for_query(lowered),
                key_questions=[query],
                reason=_sentiment_reason(mode, explicit_sentiment),
            )
            if needs_sentiment
            else None
        )
        return InvestmentPlan(
            mode=mode,
            needs_portfolio_agent=True,
            needs_sentiment_agent=needs_sentiment,
            portfolio_request=portfolio_request,
            sentiment_task=sentiment_task,
            logical_asset_hints=asset_hints,
            themes=_themes_for_query(lowered, mode),
            time_horizon=portfolio_request.time_range,
            freshness_requirement=freshness_requirement,
            answer_constraints=_answer_constraints(mode, needs_sentiment),
        )


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


def extract_logical_tickers(query: str) -> list[str]:
    return [_ticker_from_hint(hint) for hint in _asset_hints_from_query(query)]


def _portfolio_task_from_request(request: PortfolioRequest) -> PortfolioTask:
    return PortfolioTask(
        task_type=_legacy_portfolio_task_type(request.task_intent),
        source_query=request.source_query,
        requested_tickers=[
            ticker for hint in request.asset_hints if (ticker := _ticker_from_hint(hint))
        ],
        history_window=request.time_range,
        required_outputs=_legacy_required_outputs(request.output_goals),
        persistence_mode="auto",
        focus_areas=[request.task_intent, *request.output_goals],
        warnings=list(request.warnings),
    )


def _mode_for_query(lowered_query: str, explicit_sentiment: bool) -> str:
    if _contains_any(lowered_query, COMPARE_TERMS):
        return "compare"
    if _contains_any(lowered_query, HISTORY_TERMS):
        return "what_changed"
    if _contains_any(lowered_query, RISK_TERMS):
        return "risk_check"
    if explicit_sentiment:
        return "deep_dive"
    if _contains_any(lowered_query, PORTFOLIO_FACT_TERMS):
        return "portfolio_fact"
    return "review"


def _needs_sentiment(mode: str, explicit_sentiment: bool) -> bool:
    return explicit_sentiment or mode in {"review", "deep_dive", "compare", "risk_check"}


def _freshness_requirement(lowered_query: str, mode: str) -> str:
    if mode == "what_changed":
        return "history_only"
    if _contains_any(lowered_query, LATEST_TERMS):
        return "latest_required"
    if mode in {"portfolio_fact", "review", "risk_check", "deep_dive", "compare"}:
        return "latest_required"
    return "cached_ok"


def _portfolio_task_intent_for_mode(mode: str) -> str:
    if mode == "review":
        return "full_review"
    if mode in {"portfolio_fact", "risk_check", "what_changed", "deep_dive", "compare"}:
        return mode
    return "portfolio_fact"


def _portfolio_output_goals(
    mode: str,
    lowered_query: str,
    needs_sentiment: bool,
) -> list[PortfolioOutputGoal]:
    if mode == "portfolio_fact":
        goals: list[PortfolioOutputGoal] = ["snapshot"]
        if _contains_any(lowered_query, ("cash", "effective cash", "buying power")):
            goals.append("effective_cash")
        if _contains_any(lowered_query, ("allocation", "weight", "holding", "position")):
            goals.append("allocation_context")
        return _dedupe(goals)
    if mode == "what_changed":
        return ["snapshot", "position_changes", "performance_context", "portfolio_patterns"]
    if mode == "risk_check":
        goals = ["snapshot", "risk_context", "allocation_context", "portfolio_patterns"]
    elif mode == "compare":
        goals = ["snapshot", "allocation_context", "performance_context", "portfolio_patterns"]
    elif mode == "deep_dive":
        goals = ["snapshot", "allocation_context", "performance_context", "portfolio_patterns"]
    else:
        goals = [
            "snapshot",
            "allocation_context",
            "performance_context",
            "risk_context",
            "effective_cash",
            "portfolio_patterns",
        ]
    if needs_sentiment:
        goals.append("sentiment_context_needs")
    return _dedupe(goals)


def _legacy_portfolio_task_type(task_intent: str) -> str:
    return "full_review" if task_intent == "full_review" else task_intent


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


def _asset_hints_from_query(query: str) -> list[AssetHint]:
    hints = []
    for ticker in extract_ticker_strings(query):
        hints.append(AssetHint(raw_input=ticker, source_field="user_query"))
    return hints


def extract_ticker_strings(query: str) -> list[str]:
    tickers = []
    for match in re.finditer(r"\b(?:US\.)?([A-Z]{1,5})(?:\.[A-Z]{1,4})?\b", query):
        ticker = match.group(1)
        if ticker in {"I", "A", "USD", "ETF", "LLM", "AI", "CEO", "CFO", "IPO", "US"}:
            continue
        tickers.append(ticker)
    return _dedupe(tickers)


def _ticker_from_hint(hint: AssetHint) -> str:
    raw = hint.raw_input.strip().upper()
    if raw.startswith("US."):
        raw = raw.removeprefix("US.")
    if not re.fullmatch(r"[A-Z]{1,5}(?:\.[A-Z]{1,4})?", raw):
        return ""
    return raw.split(".", 1)[0]


def _sentiment_themes_for_query(lowered_query: str) -> list[str]:
    themes = []
    if "earnings" in lowered_query:
        themes.append("earnings")
    if "management" in lowered_query:
        themes.append("management commentary")
    if "risk" in lowered_query:
        themes.append("risk")
    if "thesis" in lowered_query:
        themes.append("investment thesis")
    return themes


def _themes_for_query(lowered_query: str, mode: str) -> list[str]:
    themes = [mode]
    themes.extend(_sentiment_themes_for_query(lowered_query))
    return _dedupe(themes)


def _sentiment_reason(mode: str, explicit_sentiment: bool) -> str:
    if explicit_sentiment:
        return "User asked for sentiment, research, news, outlook, or thesis context."
    return f"Mode {mode} benefits from material-holding sentiment context."


def _answer_constraints(mode: str, needs_sentiment: bool) -> list[str]:
    constraints = [
        "no_trade_execution",
        "no_order_preparation",
        "no_exact_share_count",
        "source_backed",
    ]
    if mode == "portfolio_fact" and not needs_sentiment:
        constraints.append("portfolio_only")
    return constraints


def _route_reason(plan: InvestmentPlan) -> str:
    if plan.mode == "unsupported":
        return "Trade execution requests are outside the allowed investment-analysis scope."
    if plan.needs_sentiment_agent:
        return f"Routed as {plan.mode}; Portfolio Agent plus Sentiment Agent stub are needed."
    return f"Routed as {plan.mode}; portfolio-only evidence is enough."


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
