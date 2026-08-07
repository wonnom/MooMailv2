from __future__ import annotations

from collections import Counter
from typing import Any, Iterable

from moomail_finance_ai.agent_schemas import (
    InvestmentAgentState,
    TraceEvent,
    UserProgressEvent,
)
from moomail_finance_ai.agent_trace import sanitize_public_text, trace_event_to_public_dict


PROGRESS_STAGE_ORDER = (
    "reviewing_request",
    "loading_saved_portfolio",
    "checking_evidence_coverage",
    "retrieving_portfolio_details",
    "analyzing_evidence",
    "checking_safety",
    "complete",
    "failed",
)

TERMINAL_ANALYTICAL_FAILURE_STATUSES = frozenset(
    {
        "investment_agent_error",
        "investment_planner_unavailable",
        "investment_route_rejected",
        "complete_with_planning_failure",
        "portfolio_evidence_planner_unavailable",
        "portfolio_evidence_compilation_failed",
        "portfolio_execution_failed",
        "portfolio_analysis_failed",
        "portfolio_llm_call_failed",
        "portfolio_llm_budget_exceeded",
        "delegated_llm_budget_exceeded",
        "llm_call_failed",
        "stream_error",
    }
)

_REVIEWING_STATUSES = frozenset(
    {
        "loading_policy",
        "planning_investment",
        "investment_plan_ready",
        "llm_call_started",
        "llm_call_completed",
    }
)
_BASELINE_STATUSES = frozenset(
    {
        "loading_portfolio_baseline",
        "portfolio_baseline_ready",
        "portfolio_baseline_unavailable",
    }
)
_COVERAGE_STATUSES = frozenset(
    {
        "validating_investment_plan",
        "investment_route_validated",
        "investment_plan_validated",
        "skipping_portfolio_agent",
    }
)
_ANALYSIS_STATUSES = frozenset(
    {
        "portfolio_llm_call_started",
        "portfolio_llm_call_completed",
        "portfolio_evidence_packet_ready",
        "calling_sentiment_agent",
        "sentiment_stub_status",
        "synthesizing_report",
    }
)
_SAFETY_STATUSES = frozenset({"checking_guardrails", "guardrails_passed"})


def progress_event_for_trace(event: TraceEvent) -> UserProgressEvent | None:
    """Map one sanitized internal event to a bounded user-facing stage."""

    event = TraceEvent.model_validate(trace_event_to_public_dict(event))
    stage: str | None = None
    status = "completed"
    message: str | None = None

    if _is_terminal_failure(event):
        stage = "failed"
        status = "failed"
        message = _failure_message(event.status)
    elif event.status == "observability_degraded":
        stage = "complete"
        message = (
            "Response ready, but developer tracing is degraded. "
            "The answer and saved dashboard are unaffected."
        )
    elif event.status == "complete":
        stage = "complete"
        message = "Response ready."
    elif event.status in _REVIEWING_STATUSES:
        stage = "reviewing_request"
        status = "started" if event.status in {"planning_investment", "llm_call_started"} else "completed"
        message = "Reviewing your request and choosing the smallest safe plan."
    elif event.status in _BASELINE_STATUSES:
        stage = "loading_saved_portfolio"
        as_of = event.metadata.get("as_of")
        message = (
            "Saved portfolio data is unavailable; checking whether a bounded detail lookup can help."
            if event.status == "portfolio_baseline_unavailable"
            else (
                f"Using your saved portfolio dashboard data as of {as_of}."
                if as_of
                else "Using your saved portfolio dashboard data."
            )
        )
    elif event.status in _COVERAGE_STATUSES:
        stage = "checking_evidence_coverage"
        message = _coverage_message(event)
    elif _is_portfolio_detail_event(event):
        stage = "retrieving_portfolio_details"
        message = _portfolio_detail_message(event)
    elif event.status in _ANALYSIS_STATUSES or event.phase in {"synthesis"}:
        stage = "analyzing_evidence"
        message = "Analyzing the available evidence for your answer."
    elif event.status in _SAFETY_STATUSES or event.phase == "guardrail":
        stage = "checking_safety"
        message = "Checking the answer against investment safety rules."

    if stage is None or message is None:
        return None
    return UserProgressEvent(
        run_id=event.run_id,
        stage=stage,
        status=status,
        message=sanitize_public_text(message),
        timestamp=event.timestamp,
        group_key=f"progress.{stage}",
    )


def build_user_progress(events: Iterable[TraceEvent]) -> list[UserProgressEvent]:
    """Collapse noisy source events into one latest event per ordered stage."""

    by_stage: dict[str, UserProgressEvent] = {}
    for event in events:
        progress = progress_event_for_trace(event)
        if progress is None:
            continue
        existing = by_stage.get(progress.stage)
        if existing is None or _progress_priority(progress) >= _progress_priority(existing):
            by_stage[progress.stage] = progress
    return [by_stage[stage] for stage in PROGRESS_STAGE_ORDER if stage in by_stage]


def build_trace_summary(state: InvestmentAgentState) -> dict[str, Any]:
    """Build a sanitized, grouped audit projection while retaining source events."""

    public_events = [trace_event_to_public_dict(event) for event in state.status_events]
    decision = state.validated_turn_decision or state.turn_decision
    route = decision.route if decision else None
    route_reasons = list(decision.route_reasons) if decision else []
    tool_groups = {
        "planned": _tool_group(public_events, "planned_portfolio_tool"),
        "actual": _tool_group(public_events, "called_portfolio_tool"),
        "skipped": _tool_group(public_events, "skipped_portfolio_tool"),
    }
    node_sequence = [
        {
            "node": event.get("node"),
            "status": event["status"],
            "subagent": event.get("subagent"),
            "child_run_id": event.get("child_run_id"),
            "timestamp": event["timestamp"],
        }
        for event in public_events
        if event.get("event_type") == "graph_node"
    ]
    subagent_sequence = _unique_dicts(
        {
            "subagent": event.get("subagent"),
            "child_run_id": event.get("child_run_id"),
            "status": event["status"],
        }
        for event in public_events
        if event.get("subagent") and event.get("subagent") != "investment_agent"
    )
    warnings = [
        _event_issue(event)
        for event in public_events
        if event.get("event_type") == "warning" or "warning" in event["status"]
    ]
    errors = [
        _event_issue(event)
        for event in public_events
        if event.get("event_type") == "error"
        or event["status"] in TERMINAL_ANALYTICAL_FAILURE_STATUSES
    ]
    purpose_counts = Counter(call.purpose for call in state.llm_calls)
    baseline = state.portfolio_baseline
    return {
        "run_id": state.run_id,
        "thread_id": state.thread_id,
        "route": {
            "decision": route,
            "reasons": route_reasons,
            "required_evidence": list(decision.required_evidence) if decision else [],
            "missing_evidence": list(decision.missing_evidence) if decision else [],
            "coverage": dict(state.evidence_coverage),
            "delegated": bool(route and route.startswith("delegate_")),
        },
        "data_context": {
            "baseline_version": baseline.schema_version if baseline else None,
            "as_of": baseline.as_of.isoformat() if baseline and baseline.as_of else None,
            "capabilities": list(baseline.capabilities) if baseline else [],
        },
        "graph": {
            "nodes": node_sequence,
            "subagents": subagent_sequence,
        },
        "llm": {
            "total_calls": state.total_llm_calls,
            "calls_by_purpose": dict(sorted(purpose_counts.items())),
            "calls": [call.model_dump(mode="json") for call in state.llm_calls],
        },
        "tools": tool_groups,
        "warnings": warnings,
        "errors": errors,
        "guardrails": (
            state.guardrail_review.model_dump(mode="json")
            if state.guardrail_review
            else None
        ),
        "source_events": public_events,
    }


def has_terminal_analytical_failure(events: Iterable[TraceEvent]) -> bool:
    return any(_is_terminal_failure(event) for event in events)


def _is_terminal_failure(event: TraceEvent) -> bool:
    return event.event_type == "error" or event.status in TERMINAL_ANALYTICAL_FAILURE_STATUSES


def _is_portfolio_detail_event(event: TraceEvent) -> bool:
    return (
        event.status == "calling_portfolio_agent"
        or event.event_type == "tool_call"
        or event.subagent == "portfolio_agent"
        and event.phase
        in {
            "portfolio_evidence_planner",
            "portfolio_policy",
            "deterministic_tool_execution",
        }
    )


def _coverage_message(event: TraceEvent) -> str:
    route = event.metadata.get("route")
    reasons = event.metadata.get("route_reasons") or []
    if route == "direct_context":
        return "Saved portfolio data covers this request; no Portfolio Agent call is needed."
    if isinstance(route, str) and route.startswith("delegate_"):
        reason_text = _reason_text(reasons)
        return f"More detail is needed{reason_text}; preparing a bounded lookup."
    return "Checking whether saved portfolio data fully covers your request."


def _portfolio_detail_message(event: TraceEvent) -> str:
    reasons = event.metadata.get("route_reasons") or []
    reason_text = _reason_text(reasons)
    return f"Retrieving only the additional portfolio details needed{reason_text}."


def _reason_text(reasons: Any) -> str:
    if not isinstance(reasons, list) or not reasons:
        return ""
    labels = [str(reason).replace("_", " ") for reason in reasons[:2]]
    return f" for {' and '.join(labels)}"


def _failure_message(status: str) -> str:
    if "planner" in status or "planning" in status:
        return (
            "Investment planning is unavailable. Check the configured LLM provider and try again; "
            "your saved dashboard is unchanged."
        )
    if "budget" in status:
        return "The run exceeded its model-call budget and stopped; your saved dashboard is unchanged."
    if "portfolio" in status:
        return "The requested portfolio detail could not be completed; your saved dashboard is unchanged."
    return "The analysis could not be completed; your saved dashboard is unchanged."


def _progress_priority(event: UserProgressEvent) -> tuple[int, str]:
    status_priority = {"started": 0, "completed": 1, "failed": 2}[event.status]
    return status_priority, event.timestamp.isoformat()


def _tool_group(events: list[dict[str, Any]], status: str) -> dict[str, Any]:
    items = [
        {
            "server_name": event.get("server_name"),
            "tool_name": event.get("tool_name"),
            "message": event.get("message"),
            "input_summary": event.get("input_summary"),
            "output_summary": event.get("output_summary"),
            "child_run_id": event.get("child_run_id"),
            "timestamp": event.get("timestamp"),
        }
        for event in events
        if event.get("status") == status
    ]
    return {"count": len(items), "items": items}


def _event_issue(event: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": event["status"],
        "message": event.get("error_message") or event["message"],
        "error_type": event.get("error_type"),
        "phase": event.get("phase"),
        "timestamp": event["timestamp"],
    }


def _unique_dicts(items: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    unique: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for item in items:
        key = tuple(item.values())
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique
