from __future__ import annotations

import re
from typing import Any

from moomail_finance_ai.schemas import FinalReport, GuardrailCheck, InvestmentPolicy
from moomail_finance_ai.agent_schemas import GuardrailReview, InvestmentAgentState


INVESTMENT_GUARDRAIL_CHECKS = (
    "no_trading",
    "no_exact_share_count_trading",
    "unsupported_research_claims",
    "unsupported_price_or_portfolio_facts",
    "missing_ips_for_optimization",
    "missing_sentiment_visibility",
)

INVESTMENT_GUARDRAIL_SEVERITY = {
    "no_trading": "high",
    "no_exact_share_count_trading": "high",
    "unsupported_research_claims": "high",
    "unsupported_price_or_portfolio_facts": "medium",
    "missing_ips_for_optimization": "high",
    "missing_sentiment_visibility": "medium",
}

EXECUTABLE_TRADE_PHRASES = (
    "place order",
    "place an order",
    "place a trade",
    "execute trade",
    "execute the trade",
    "submit order",
    "submit the order",
    "send order",
    "send the order",
    "market order",
    "limit order",
)

EXACT_TRADE_PATTERN = re.compile(
    r"\b(?:buy|sell|short|purchase)\s+(?:exactly\s+)?\d+(?:\.\d+)?\s+"
    r"(?:share|shares|contract|contracts)\b",
    re.IGNORECASE,
)

RESEARCH_CLAIM_PATTERN = re.compile(
    r"\b(?:research shows|source-backed research says|earnings transcript shows|"
    r"shareholder letter says|management tone is|sentiment is "
    r"(?:positive|mixed|negative))\b",
    re.IGNORECASE,
)

OPTIMIZATION_TERMS = (
    "optimize",
    "optimization",
    "rebalance",
    "rebalancing",
    "target allocation",
    "increase exposure",
    "reduce exposure",
    "risk tolerance",
)


def review_investment_report(state: InvestmentAgentState) -> GuardrailReview:
    if state.final_report is None:
        raise ValueError("Investment guardrail review requires a final report.")

    checks = [
        _check_no_trading(state.final_report),
        _check_no_exact_share_counts(state.final_report),
        _check_unsupported_research_claims(state),
        _check_unsupported_price_or_portfolio_facts(state),
        _check_missing_ips_for_optimization(state.final_report, state.ips),
        _check_missing_sentiment_visibility(state),
    ]
    passed = all(check.passed for check in checks)
    failed_checks = [check for check in checks if not check.passed]
    return GuardrailReview(
        passed=passed,
        output_status="approved" if passed else "blocked",
        checks=checks,
        required_revisions=[check.message for check in failed_checks],
        blocked_reason=None if passed else "Investment guardrail review failed.",
        metadata={
            "check_severity": INVESTMENT_GUARDRAIL_SEVERITY,
            "failed_checks": [check.check for check in failed_checks],
        },
    )


def _check_no_trading(report: FinalReport) -> GuardrailCheck:
    text = _report_text(report).lower()
    blocked_phrase = next(
        (phrase for phrase in EXECUTABLE_TRADE_PHRASES if phrase in text),
        None,
    )
    return GuardrailCheck(
        check="no_trading",
        passed=blocked_phrase is None,
        message=(
            "No trade execution language detected."
            if blocked_phrase is None
            else f"Trade execution language detected: {blocked_phrase}."
        ),
    )


def _check_no_exact_share_counts(report: FinalReport) -> GuardrailCheck:
    match = EXACT_TRADE_PATTERN.search(_report_text(report))
    return GuardrailCheck(
        check="no_exact_share_count_trading",
        passed=match is None,
        message=(
            "No exact share-count trading instruction detected."
            if match is None
            else f"Exact share-count trading instruction detected: {match.group(0)}."
        ),
    )


def _check_unsupported_research_claims(state: InvestmentAgentState) -> GuardrailCheck:
    report = state.final_report
    assert report is not None
    sentiment_unavailable = (
        state.sentiment_packet is None
        or state.sentiment_packet.retrieval_status in {"not_implemented", "missing_corpus"}
    )
    if not sentiment_unavailable:
        return GuardrailCheck(
            check="unsupported_research_claims",
            passed=True,
            message="Sentiment/research packet is available for research claims.",
        )

    sentiment_analysis = report.sentiment_analysis or {}
    has_research_artifacts = bool(report.citations)
    has_research_artifacts = has_research_artifacts or bool(sentiment_analysis.get("citations"))
    has_research_artifacts = has_research_artifacts or bool(sentiment_analysis.get("holdings"))
    has_research_artifacts = has_research_artifacts or _sentiment_summary_claims_research(
        sentiment_analysis
    )
    has_claim_text = RESEARCH_CLAIM_PATTERN.search(_report_text(report)) is not None
    passed = not has_research_artifacts and not has_claim_text
    return GuardrailCheck(
        check="unsupported_research_claims",
        passed=passed,
        message=(
            "No unsupported research claims detected while sentiment retrieval is unavailable."
            if passed
            else "Research or sentiment claims appear without retrieved sentiment evidence."
        ),
    )


def _check_unsupported_price_or_portfolio_facts(
    state: InvestmentAgentState,
) -> GuardrailCheck:
    report = state.final_report
    assert report is not None
    portfolio_missing = state.portfolio_packet is None
    has_portfolio_payload = bool(report.portfolio_snapshot) or bool(report.portfolio_analysis)
    has_portfolio_claim = "portfolio value is" in _report_text(report).lower()
    passed = not (portfolio_missing and (has_portfolio_payload or has_portfolio_claim))
    return GuardrailCheck(
        check="unsupported_price_or_portfolio_facts",
        passed=passed,
        message=(
            "Portfolio facts are backed by a Portfolio Agent packet or are absent."
            if passed
            else "Portfolio facts appear without a Portfolio Agent packet."
        ),
    )


def _check_missing_ips_for_optimization(
    report: FinalReport,
    ips: InvestmentPolicy | None,
) -> GuardrailCheck:
    needs_ips = any(term in _report_text(report).lower() for term in OPTIMIZATION_TERMS)
    passed = bool(ips) or not needs_ips
    return GuardrailCheck(
        check="missing_ips_for_optimization",
        passed=passed,
        message=(
            "IPS is available or the output does not frame optimization/rebalancing advice."
            if passed
            else "Optimization or rebalancing recommendation appears without an IPS."
        ),
    )


def _check_missing_sentiment_visibility(state: InvestmentAgentState) -> GuardrailCheck:
    report = state.final_report
    assert report is not None
    sentiment_missing = (
        state.sentiment_packet is not None
        and state.sentiment_packet.retrieval_status in {"not_implemented", "missing_corpus"}
    )
    visible = bool(report.missing_data) or any(
        recommendation.missing_data for recommendation in report.recommendations
    )
    passed = not sentiment_missing or visible
    return GuardrailCheck(
        check="missing_sentiment_visibility",
        passed=passed,
        message=(
            "Missing sentiment data is visible when research retrieval is unavailable."
            if passed
            else "Missing sentiment data is not visible in the final report."
        ),
    )


def _sentiment_summary_claims_research(sentiment_analysis: dict[str, Any]) -> bool:
    portfolio_sentiment = sentiment_analysis.get("portfolio_level_sentiment")
    if not isinstance(portfolio_sentiment, dict):
        return False
    summary = str(portfolio_sentiment.get("summary") or "").lower()
    if not summary:
        return False
    limitation_terms = ("not implemented", "not connected", "no sentiment stance", "stub")
    return not any(term in summary for term in limitation_terms)


def _report_text(report: FinalReport) -> str:
    parts = [
        report.title,
        report.summary,
        " ".join(report.missing_data),
        " ".join(report.assumptions),
    ]
    for recommendation in report.recommendations:
        parts.extend(
            [
                recommendation.title,
                recommendation.rationale,
                " ".join(recommendation.supporting_evidence),
                " ".join(recommendation.constraints),
                " ".join(recommendation.missing_data),
            ]
        )
    return "\n".join(parts)
