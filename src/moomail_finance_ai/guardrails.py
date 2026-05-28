from __future__ import annotations

import re

from moomail_finance_ai.schemas import FinalReport, GuardrailCheck, GuardrailResult


EXECUTION_PHRASES = (
    "place an order",
    "execute the trade",
    "submit the order",
    "send the order",
    "market order",
    "limit order",
)

EXACT_TRADE_PATTERN = re.compile(
    r"\b(buy|sell|short|purchase)\s+\d+(\.\d+)?\s+(share|shares|contract|contracts)\b",
    re.IGNORECASE,
)


def review_report(report: FinalReport) -> GuardrailResult:
    checks = [
        _check_no_trading(report),
        _check_no_exact_share_counts(report),
        _check_source_coverage(report),
        _check_missing_data_visibility(report),
    ]
    passed = all(check.passed for check in checks)
    required_revisions = [check.message for check in checks if not check.passed]
    return GuardrailResult(
        passed=passed,
        checks=checks,
        required_revisions=required_revisions,
        blocked_reason=None if passed else "Guardrail review failed.",
    )


def _report_text(report: FinalReport) -> str:
    parts = [report.title, report.summary]
    for recommendation in report.recommendations:
        parts.extend([recommendation.title, recommendation.rationale])
        parts.extend(recommendation.constraints)
    return "\n".join(parts)


def _check_no_trading(report: FinalReport) -> GuardrailCheck:
    text = _report_text(report).lower()
    blocked_phrase = next((phrase for phrase in EXECUTION_PHRASES if phrase in text), None)
    passed = blocked_phrase is None
    return GuardrailCheck(
        check="no_trading",
        passed=passed,
        message=(
            "No trade execution language detected."
            if passed
            else f"Trade execution language detected: {blocked_phrase}."
        ),
    )


def _check_no_exact_share_counts(report: FinalReport) -> GuardrailCheck:
    text = _report_text(report)
    match = EXACT_TRADE_PATTERN.search(text)
    passed = match is None
    return GuardrailCheck(
        check="no_exact_share_counts",
        passed=passed,
        message=(
            "No exact share-count trading instruction detected."
            if passed
            else f"Exact share-count trading instruction detected: {match.group(0)}."
        ),
    )


def _check_source_coverage(report: FinalReport) -> GuardrailCheck:
    report_citation_ids = {citation.citation_id for citation in report.citations}
    recommendation_evidence = {
        evidence_id
        for recommendation in report.recommendations
        for evidence_id in recommendation.supporting_evidence
    }
    missing_evidence = sorted(recommendation_evidence - report_citation_ids)
    passed = bool(report.citations) and not missing_evidence
    return GuardrailCheck(
        check="source_coverage",
        passed=passed,
        message=(
            "Citations are present and recommendation evidence IDs resolve."
            if passed
            else f"Missing or unresolved citations: {missing_evidence or 'no citations present'}."
        ),
    )


def _check_missing_data_visibility(report: FinalReport) -> GuardrailCheck:
    mentions_missing_data = bool(report.missing_data) or any(
        recommendation.missing_data for recommendation in report.recommendations
    )
    return GuardrailCheck(
        check="missing_data_visibility",
        passed=mentions_missing_data,
        message=(
            "Missing data is visible in the report."
            if mentions_missing_data
            else "Report does not expose missing data or limitations."
        ),
    )

