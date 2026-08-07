from __future__ import annotations

from datetime import UTC, datetime, timedelta

from pydantic import Field

from moomail_finance_ai.agent_schemas import (
    BaselineCapability,
    FreshnessRequirement,
    InvestmentTurnDecision,
    PortfolioBaselinePacket,
    PortfolioRequest,
)
from moomail_finance_ai.schemas import StrictModel


WINDOWED_CAPABILITIES = {
    "portfolio_value_trend_7d",
    "portfolio_value_trend_30d",
    "top_allocation_changes_7d",
    "top_position_changes_7d",
    "history_freshness",
}


class DirectAnswerCoverageError(ValueError):
    """Raised when a direct Investment answer is not supported by baseline evidence."""


class DirectAnswerCoverageResult(StrictModel):
    is_valid: bool
    missing_capabilities: list[BaselineCapability] = Field(default_factory=list)
    invalid_evidence_refs: list[str] = Field(default_factory=list)
    stale_evidence_refs: list[str] = Field(default_factory=list)
    window_mismatches: list[BaselineCapability] = Field(default_factory=list)
    fallback_portfolio_request: PortfolioRequest | None = None
    limitation: str | None = None


def validate_direct_answer_coverage(
    decision: InvestmentTurnDecision,
    baseline: PortfolioBaselinePacket,
    *,
    freshness_requirement: FreshnessRequirement = "cached_ok",
    requested_window: str | None = None,
    now: datetime | None = None,
    latest_max_age: timedelta = timedelta(minutes=15),
    cached_max_age: timedelta = timedelta(hours=24),
) -> DirectAnswerCoverageResult:
    """Check whether a direct answer is fully supported by the bounded baseline packet."""

    if decision.route != "direct_context":
        return DirectAnswerCoverageResult(
            is_valid=False,
            fallback_portfolio_request=decision.portfolio_request,
            limitation="Evidence coverage validation applies only to direct_context routes.",
        )

    available = set(baseline.capabilities)
    missing_capabilities = [
        capability
        for capability in decision.required_evidence
        if capability not in available
    ]

    refs_by_id = {ref.ref_id: ref for ref in baseline.evidence_refs}
    invalid_refs = [
        ref_id for ref_id in decision.cited_evidence_refs if ref_id not in refs_by_id
    ]

    capability_refs: dict[BaselineCapability, set[str]] = {}
    for summary in baseline.summaries:
        capability_refs.setdefault(summary.capability, set()).update(summary.evidence_refs)
    for capability in decision.required_evidence:
        if not capability_refs.get(capability) and capability not in missing_capabilities:
            missing_capabilities.append(capability)

    cited_ref_ids = set(decision.cited_evidence_refs)
    for capability in decision.required_evidence:
        if capability in missing_capabilities:
            continue
        if not capability_refs.get(capability, set()) & cited_ref_ids:
            missing_capabilities.append(capability)

    current_time = _as_utc(now or datetime.now(UTC))
    max_age = (
        latest_max_age
        if freshness_requirement == "latest_required"
        else cached_max_age if freshness_requirement == "cached_ok" else None
    )
    stale_refs: list[str] = []
    for ref_id in decision.cited_evidence_refs:
        ref = refs_by_id.get(ref_id)
        if ref is None:
            continue
        ref_time = _as_utc(ref.as_of)
        if ref.quality != "complete" or (
            max_age is not None and current_time - ref_time > max_age
        ):
            stale_refs.append(ref_id)

    window_mismatches: list[BaselineCapability] = []
    requested_days = _window_days(requested_window)
    if requested_days is not None:
        for capability in decision.required_evidence:
            if capability not in WINDOWED_CAPABILITIES or capability in missing_capabilities:
                continue
            ref_windows = [
                _window_days(refs_by_id[ref_id].window)
                for ref_id in capability_refs.get(capability, set())
                if ref_id in refs_by_id
            ]
            covered_days = [days for days in ref_windows if days is not None]
            if not covered_days or max(covered_days) < requested_days:
                window_mismatches.append(capability)

    is_valid = not (
        missing_capabilities or invalid_refs or stale_refs or window_mismatches
    )
    limitation = None
    if not is_valid:
        limitation = _coverage_limitation(
            missing_capabilities,
            invalid_refs,
            stale_refs,
            window_mismatches,
        )
    return DirectAnswerCoverageResult(
        is_valid=is_valid,
        missing_capabilities=_dedupe(missing_capabilities),
        invalid_evidence_refs=_dedupe(invalid_refs),
        stale_evidence_refs=_dedupe(stale_refs),
        window_mismatches=_dedupe(window_mismatches),
        fallback_portfolio_request=(
            decision.fallback_portfolio_request if not is_valid else None
        ),
        limitation=limitation,
    )


def enforce_direct_answer_coverage(
    decision: InvestmentTurnDecision,
    baseline: PortfolioBaselinePacket,
    **kwargs,
) -> DirectAnswerCoverageResult:
    result = validate_direct_answer_coverage(decision, baseline, **kwargs)
    if not result.is_valid:
        raise DirectAnswerCoverageError(
            result.limitation or "Direct answer lacks sufficient baseline evidence."
        )
    return result


def _coverage_limitation(
    missing_capabilities: list[BaselineCapability],
    invalid_refs: list[str],
    stale_refs: list[str],
    window_mismatches: list[BaselineCapability],
) -> str:
    reasons: list[str] = []
    if missing_capabilities:
        reasons.append("missing capabilities: " + ", ".join(missing_capabilities))
    if invalid_refs:
        reasons.append("unknown evidence refs: " + ", ".join(invalid_refs))
    if stale_refs:
        reasons.append("stale or incomplete evidence refs: " + ", ".join(stale_refs))
    if window_mismatches:
        reasons.append("insufficient history window: " + ", ".join(window_mismatches))
    return "Direct answer requires Portfolio escalation or an explicit limitation (" + "; ".join(
        reasons
    ) + ")."


def _window_days(window: str | None) -> int | None:
    if window is None:
        return None
    normalized = window.strip().lower()
    if len(normalized) < 2 or not normalized[:-1].isdigit():
        return None
    quantity = int(normalized[:-1])
    multiplier = {"d": 1, "w": 7, "m": 30, "y": 365}.get(normalized[-1])
    return quantity * multiplier if multiplier is not None else None


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _dedupe(values: list) -> list:
    result = []
    seen = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
