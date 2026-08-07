from __future__ import annotations

import re
from typing import Any

from moomail_finance_ai.agent_schemas import TraceEvent


TRACE_METADATA_ALLOWLIST = {
    "phase",
    "result",
    "mode",
    "needs_portfolio_agent",
    "needs_sentiment_agent",
    "portfolio_task_intent",
    "asset_hint_count",
    "answer_constraint_count",
    "guardrail_status",
    "check_count",
    "tool_call_kind",
    "retrieval_status",
    "missing_documents_count",
    "warning_count",
    "passed",
    "output_status",
    "error_location",
    "route",
    "route_reason",
    "route_reasons",
    "required_evidence",
    "missing_evidence",
    "coverage_result",
    "baseline_version",
    "as_of",
    "capability_count",
    "llm_purpose",
    "provider",
    "model",
    "duration_ms",
    "input_tokens",
    "output_tokens",
    "total_tokens",
    "attempt",
    "error_category",
    "expected_call_count",
    "actual_call_count",
    "analysis_requirement",
    "budget_limit",
    "fallback_used",
    "group_count",
    "planner_type",
    "requested_window",
    "retry_reason",
}

TRACE_METADATA_DENYLIST = {
    "api_key",
    "account_id",
    "authorization",
    "broker_account_id",
    "chain_of_thought",
    "developer_prompt",
    "hidden_reasoning",
    "password",
    "prompt",
    "raw_broker_account_id",
    "raw_broker_payload",
    "raw_prompt",
    "reasoning",
    "scratchpad",
    "secret",
    "system_prompt",
    "token",
}

SENSITIVE_TEXT_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"\b(?:api[_-]?key|password|secret|token)=\S+", re.IGNORECASE),
)


def sanitize_trace_events(events: list[TraceEvent]) -> list[TraceEvent]:
    return [sanitize_trace_event(event) for event in events]


def trace_event_to_public_dict(event: TraceEvent) -> dict[str, Any]:
    return sanitize_trace_event(event).model_dump(mode="json")


def sanitize_trace_event(event: TraceEvent) -> TraceEvent:
    return event.model_copy(
        update={
            "status": _sanitize_text(event.status),
            "message": _sanitize_text(event.message),
            "input_summary": _sanitize_optional_text(event.input_summary),
            "output_summary": _sanitize_optional_text(event.output_summary),
            "metadata": sanitize_trace_metadata(event.metadata),
            "error_message": _sanitize_optional_text(event.error_message),
        }
    )


def sanitize_trace_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    sanitized: dict[str, Any] = {}
    for key, value in metadata.items():
        normalized_key = key.lower()
        if normalized_key in TRACE_METADATA_DENYLIST:
            continue
        if normalized_key not in TRACE_METADATA_ALLOWLIST:
            continue
        sanitized[key] = _sanitize_metadata_value(value)
    return sanitized


def _sanitize_metadata_value(value: Any) -> Any:
    if isinstance(value, str):
        return _sanitize_text(value)
    if isinstance(value, bool | int | float) or value is None:
        return value
    if isinstance(value, list):
        return [_sanitize_metadata_value(item) for item in value]
    if isinstance(value, dict):
        return sanitize_trace_metadata(value)
    return _sanitize_text(str(value))


def _sanitize_optional_text(text: str | None) -> str | None:
    if text is None:
        return None
    return _sanitize_text(text)


def _sanitize_text(text: str) -> str:
    sanitized = text
    for pattern in SENSITIVE_TEXT_PATTERNS:
        sanitized = pattern.sub("[redacted]", sanitized)
    return sanitized


def sanitize_public_text(text: str) -> str:
    return _sanitize_text(text)
