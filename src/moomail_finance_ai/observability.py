from __future__ import annotations

import hashlib
import os
import time
from collections import defaultdict
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping, Protocol
from uuid import NAMESPACE_URL, uuid4, uuid5

from langgraph.checkpoint.memory import InMemorySaver
from pydantic import Field

from moomail_finance_ai.agent_schemas import LLMCallPurpose, LLMCallTrace, SubagentName
from moomail_finance_ai.config import load_env_file
from moomail_finance_ai.schemas import StrictModel


EXTERNAL_TRACE_METADATA_ALLOWLIST = {
    "actual_call_count",
    "app_version",
    "attempt",
    "budget_limit",
    "capability_count",
    "duration_ms",
    "environment",
    "error_category",
    "expected_call_count",
    "input_tokens",
    "model",
    "node",
    "output_tokens",
    "provider",
    "purpose",
    "route",
    "route_reason",
    "route_reasons",
    "run_id",
    "status",
    "subagent",
    "thread_id",
    "tool_name",
    "total_tokens",
}

EXTERNAL_TRACE_DENIED_KEYS = {
    "account_id",
    "api_key",
    "authorization",
    "broker_account_id",
    "chain_of_thought",
    "developer_prompt",
    "hidden_reasoning",
    "holdings",
    "ips",
    "password",
    "portfolio_snapshot",
    "prompt",
    "raw_broker_payload",
    "raw_prompt",
    "reasoning",
    "secret",
    "system_prompt",
    "token",
    "user_query",
}


class ObservabilitySettings(StrictModel):
    langsmith_enabled: bool = False
    langsmith_project: str = Field(default="moomail-finance-ai", min_length=1, max_length=120)
    environment: str = Field(default="development", min_length=1, max_length=40)
    sampling_rate: float = Field(default=1.0, ge=0.0, le=1.0)
    checkpoint_enabled: bool = False
    checkpoint_retention_threads: int = Field(default=20, ge=1, le=1000)


class TraceSpan(Protocol):
    def end(
        self,
        *,
        outputs: Mapping[str, Any] | None = None,
        error: str | None = None,
    ) -> None: ...


class TraceSink(Protocol):
    @contextmanager
    def span(
        self,
        name: str,
        *,
        run_type: str,
        metadata: Mapping[str, Any],
        inputs: Mapping[str, Any] | None = None,
    ) -> Iterator[TraceSpan]: ...


@dataclass
class _NullSpan:
    ended: bool = False

    def end(self, *, outputs: Mapping[str, Any] | None = None, error: str | None = None) -> None:
        del outputs, error
        self.ended = True


class NullTraceSink:
    @contextmanager
    def span(
        self,
        name: str,
        *,
        run_type: str,
        metadata: Mapping[str, Any],
        inputs: Mapping[str, Any] | None = None,
    ) -> Iterator[TraceSpan]:
        del name, run_type, metadata, inputs
        yield _NullSpan()


class TraceSpanRecord(StrictModel):
    span_id: str
    parent_span_id: str | None = None
    name: str
    run_type: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    inputs: dict[str, Any] = Field(default_factory=dict)
    outputs: dict[str, Any] = Field(default_factory=dict)
    status: str = "started"
    error: str | None = None


_IN_MEMORY_SPAN_STACK: ContextVar[tuple[str, ...]] = ContextVar(
    "moomail_in_memory_span_stack",
    default=(),
)


@dataclass
class _RecordedSpan:
    record: TraceSpanRecord

    def end(self, *, outputs: Mapping[str, Any] | None = None, error: str | None = None) -> None:
        self.record.outputs = sanitize_external_trace_payload(dict(outputs or {}))
        self.record.error = error
        self.record.status = "failed" if error else "completed"

    @property
    def ended(self) -> bool:
        return self.record.status != "started"


@dataclass
class InMemoryTraceSink:
    """No-network trace sink used by deterministic tests and local inspection."""

    records: list[TraceSpanRecord] = field(default_factory=list)
    fail_on_start: bool = False
    fail_on_end: bool = False

    @contextmanager
    def span(
        self,
        name: str,
        *,
        run_type: str,
        metadata: Mapping[str, Any],
        inputs: Mapping[str, Any] | None = None,
    ) -> Iterator[TraceSpan]:
        if self.fail_on_start:
            raise RuntimeError("fake trace export failed")
        stack = _IN_MEMORY_SPAN_STACK.get()
        record = TraceSpanRecord(
            span_id=uuid4().hex,
            parent_span_id=stack[-1] if stack else None,
            name=name,
            run_type=run_type,
            metadata=sanitize_external_trace_metadata(metadata),
            inputs=sanitize_external_trace_payload(dict(inputs or {})),
        )
        self.records.append(record)
        token = _IN_MEMORY_SPAN_STACK.set((*stack, record.span_id))
        span = _RecordedSpan(record)
        try:
            yield span
            if record.status == "started":
                span.end(outputs={"status": "completed"})
            if self.fail_on_end:
                raise RuntimeError("fake trace export failed")
        except BaseException as exc:
            if record.status == "started":
                span.end(error=exc.__class__.__name__)
            raise
        finally:
            _IN_MEMORY_SPAN_STACK.reset(token)


class _LangSmithSpan:
    def __init__(self, run: Any):
        self._run = run
        self.ended = False

    def end(self, *, outputs: Mapping[str, Any] | None = None, error: str | None = None) -> None:
        self._run.end(
            outputs=sanitize_external_trace_payload(dict(outputs or {})),
            error=error,
        )
        self.ended = True


@dataclass
class LangSmithTraceSink:
    project_name: str

    @contextmanager
    def span(
        self,
        name: str,
        *,
        run_type: str,
        metadata: Mapping[str, Any],
        inputs: Mapping[str, Any] | None = None,
    ) -> Iterator[TraceSpan]:
        from langsmith.run_helpers import trace

        context = trace(
            name,
            run_type=run_type,
            inputs=sanitize_external_trace_payload(dict(inputs or {})),
            metadata=sanitize_external_trace_metadata(metadata),
            project_name=self.project_name,
        )
        run = context.__enter__()
        span = _LangSmithSpan(run)
        try:
            yield span
        except BaseException as exc:
            try:
                if not getattr(span, "ended", False):
                    span.end(error=exc.__class__.__name__)
            finally:
                context.__exit__(None, None, None)
            raise
        else:
            context.__exit__(None, None, None)


class DiagnosticCheckpointSummary(StrictModel):
    thread_id: str
    checkpoint_id: str
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    step: int | None = None
    source: str | None = None
    run_id: str | None = None
    mode: str | None = None
    route: str | None = None
    total_llm_calls: int = 0
    warning_count: int = 0
    status_event_count: int = 0
    has_baseline: bool = False
    has_portfolio_packet: bool = False
    has_final_report: bool = False


class SafeDiagnosticCheckpointer(InMemorySaver):
    """Transient LangGraph saver with retained redacted summaries only.

    LangGraph needs its native checkpoint payload while a run is executing. The
    raw in-memory entries are purged by ``finalize_thread``; only the bounded
    summaries below remain available for diagnostic inspection.
    """

    def __init__(self, *, retention_threads: int = 20):
        super().__init__(serde=None)
        self.retention_threads = retention_threads
        self._summaries: dict[str, list[DiagnosticCheckpointSummary]] = defaultdict(list)
        self._thread_order: list[str] = []

    def put(self, config, checkpoint, metadata, new_versions):
        thread_id = str(config["configurable"]["thread_id"])
        self._summaries[thread_id].append(
            _checkpoint_summary(thread_id, checkpoint, metadata)
        )
        if thread_id not in self._thread_order:
            self._thread_order.append(thread_id)
        self._prune_summaries()
        return super().put(config, checkpoint, metadata, new_versions)

    def inspect(self, thread_id: str) -> list[DiagnosticCheckpointSummary]:
        return [summary.model_copy(deep=True) for summary in self._summaries.get(thread_id, [])]

    def finalize_thread(self, thread_id: str) -> None:
        self.storage.pop(thread_id, None)
        for key in [key for key in self.writes if key[0] == thread_id]:
            self.writes.pop(key, None)
        for key in [key for key in self.blobs if key[0] == thread_id]:
            self.blobs.pop(key, None)

    def cleanup(self, thread_id: str | None = None) -> None:
        if thread_id is None:
            for retained_thread in list(self._summaries):
                self.finalize_thread(retained_thread)
            self._summaries.clear()
            self._thread_order.clear()
            return
        self.finalize_thread(thread_id)
        self._summaries.pop(thread_id, None)
        self._thread_order = [item for item in self._thread_order if item != thread_id]

    def _prune_summaries(self) -> None:
        while len(self._thread_order) > self.retention_threads:
            expired = self._thread_order.pop(0)
            self._summaries.pop(expired, None)
            self.finalize_thread(expired)


@dataclass
class ObservabilityRuntime:
    settings: ObservabilitySettings = field(default_factory=ObservabilitySettings)
    sink: TraceSink = field(default_factory=NullTraceSink)
    checkpointer: SafeDiagnosticCheckpointer | None = None
    failures: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.settings.checkpoint_enabled and self.checkpointer is None:
            self.checkpointer = SafeDiagnosticCheckpointer(
                retention_threads=self.settings.checkpoint_retention_threads
            )

    def enabled_for_run(self, run_id: str) -> bool:
        if not self.settings.langsmith_enabled:
            return False
        if self.settings.sampling_rate >= 1.0:
            return True
        digest = hashlib.sha256(run_id.encode("utf-8")).digest()
        sample = int.from_bytes(digest[:8], "big") / float(2**64 - 1)
        return sample < self.settings.sampling_rate

    @contextmanager
    def span(
        self,
        name: str,
        *,
        run_type: str,
        metadata: Mapping[str, Any],
        inputs: Mapping[str, Any] | None = None,
    ) -> Iterator[TraceSpan]:
        run_id = str(metadata.get("run_id") or "")
        if not run_id or not self.enabled_for_run(run_id):
            yield _NullSpan()
            return
        context = None
        span: TraceSpan = _NullSpan()
        try:
            context = self.sink.span(
                name,
                run_type=run_type,
                metadata=sanitize_external_trace_metadata(metadata),
                inputs=sanitize_external_trace_payload(dict(inputs or {})),
            )
            span = context.__enter__()
        except Exception as exc:
            self._record_failure(exc)
            context = None
        try:
            yield span
        except BaseException as exc:
            try:
                if not getattr(span, "ended", False):
                    span.end(error=exc.__class__.__name__)
            except Exception as export_exc:
                self._record_failure(export_exc)
            raise
        else:
            try:
                if not getattr(span, "ended", False):
                    span.end(outputs={"status": "completed"})
            except Exception as exc:
                self._record_failure(exc)
        finally:
            if context is not None:
                try:
                    context.__exit__(None, None, None)
                except Exception as exc:
                    self._record_failure(exc)

    def graph_config(self, *, run_id: str, thread_id: str) -> dict[str, Any]:
        return {
            "run_name": "moomail.investment_agent",
            "run_id": uuid5(NAMESPACE_URL, run_id),
            "tags": ["moomail", "investment-agent", f"env:{self.settings.environment}"],
            "metadata": sanitize_external_trace_metadata(
                {
                    "run_id": run_id,
                    "thread_id": thread_id,
                    "app_version": "1.5",
                    "environment": self.settings.environment,
                    "subagent": "investment_agent",
                }
            ),
            "configurable": {"thread_id": thread_id},
        }

    def _record_failure(self, exc: BaseException) -> None:
        self.failures.append(exc.__class__.__name__)


@dataclass(frozen=True)
class LLMObservationContext:
    run_id: str
    thread_id: str
    subagent: SubagentName
    runtime: ObservabilityRuntime
    callback: Callable[[LLMCallTrace], None] | None = None
    route: str | None = None
    attempt: int = 1
    retry_reason: str | None = None
    budget_limit: int | None = None
    expected_call_count: int | None = None


_LLM_CONTEXT: ContextVar[LLMObservationContext | None] = ContextVar(
    "moomail_llm_observation_context",
    default=None,
)


@contextmanager
def llm_observation_scope(
    *,
    run_id: str | None = None,
    thread_id: str | None = None,
    subagent: SubagentName | None = None,
    runtime: ObservabilityRuntime | None = None,
    callback: Callable[[LLMCallTrace], None] | None = None,
    route: str | None = None,
    attempt: int | None = None,
    retry_reason: str | None = None,
    budget_limit: int | None = None,
    expected_call_count: int | None = None,
) -> Iterator[LLMObservationContext]:
    parent = _LLM_CONTEXT.get()
    context = LLMObservationContext(
        run_id=run_id or (parent.run_id if parent else f"llm_run_{uuid4().hex[:12]}"),
        thread_id=thread_id or (parent.thread_id if parent else f"thread_{uuid4().hex[:12]}"),
        subagent=subagent or (parent.subagent if parent else "investment_agent"),
        runtime=runtime or (parent.runtime if parent else ObservabilityRuntime()),
        callback=callback if callback is not None else (parent.callback if parent else None),
        route=route if route is not None else (parent.route if parent else None),
        attempt=attempt if attempt is not None else (parent.attempt if parent else 1),
        retry_reason=(
            retry_reason if retry_reason is not None else (parent.retry_reason if parent else None)
        ),
        budget_limit=(
            budget_limit if budget_limit is not None else (parent.budget_limit if parent else None)
        ),
        expected_call_count=(
            expected_call_count
            if expected_call_count is not None
            else (parent.expected_call_count if parent else None)
        ),
    )
    token = _LLM_CONTEXT.set(context)
    try:
        yield context
    finally:
        _LLM_CONTEXT.reset(token)


def current_llm_observation_context() -> LLMObservationContext | None:
    return _LLM_CONTEXT.get()


def generate_text_with_observability(
    llm: Any,
    prompt: str,
    *,
    purpose: LLMCallPurpose,
    system_instruction: str | None = None,
    max_output_tokens: int = 2048,
    temperature: float = 0.1,
    timeout: int = 60,
) -> str:
    context = _LLM_CONTEXT.get()
    if context is None:
        context = LLMObservationContext(
            run_id=f"llm_run_{uuid4().hex[:12]}",
            thread_id=f"thread_{uuid4().hex[:12]}",
            subagent=_subagent_for_purpose(purpose),
            runtime=ObservabilityRuntime(),
        )
    provider, model = _llm_identity(llm)
    started_at = datetime.now(UTC)
    started_clock = time.perf_counter()
    metadata = _llm_metadata(context, purpose, provider, model)
    started = LLMCallTrace(
        run_id=context.run_id,
        purpose=purpose,
        provider=provider,
        model=model,
        subagent=context.subagent,
        status="started",
        started_at=started_at,
        attempt=context.attempt,
        retry_reason=context.retry_reason,
        metadata=_llm_call_metadata(context),
    )
    _safe_callback(context.callback, started)
    with context.runtime.span(
        f"llm.{purpose}",
        run_type="llm",
        metadata=metadata,
        inputs={"status": "started"},
    ) as span:
        try:
            result_method = getattr(llm, "generate_text_result", None)
            if callable(result_method):
                result = result_method(
                    prompt,
                    system_instruction=system_instruction,
                    max_output_tokens=max_output_tokens,
                    temperature=temperature,
                    timeout=timeout,
                )
                text = result.text
                input_tokens = getattr(result, "input_tokens", None)
                output_tokens = getattr(result, "output_tokens", None)
                total_tokens = getattr(result, "total_tokens", None)
            else:
                text = llm.generate_text(
                    prompt,
                    system_instruction=system_instruction,
                    max_output_tokens=max_output_tokens,
                    temperature=temperature,
                    timeout=timeout,
                )
                input_tokens = output_tokens = total_tokens = None
        except Exception as exc:
            ended_at = datetime.now(UTC)
            failed = LLMCallTrace(
                run_id=context.run_id,
                purpose=purpose,
                provider=provider,
                model=model,
                subagent=context.subagent,
                status="failed",
                started_at=started_at,
                ended_at=ended_at,
                duration_ms=max(0.0, (time.perf_counter() - started_clock) * 1000),
                attempt=context.attempt,
                retry_reason=context.retry_reason,
                error_category=exc.__class__.__name__,
                metadata=_llm_call_metadata(context),
            )
            _safe_callback(context.callback, failed)
            span.end(
                outputs={"status": "failed", "error_category": exc.__class__.__name__},
                error=exc.__class__.__name__,
            )
            raise
        completed = LLMCallTrace(
            run_id=context.run_id,
            purpose=purpose,
            provider=provider,
            model=model,
            subagent=context.subagent,
            status="completed",
            started_at=started_at,
            ended_at=datetime.now(UTC),
            duration_ms=max(0.0, (time.perf_counter() - started_clock) * 1000),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            attempt=context.attempt,
            retry_reason=context.retry_reason,
            metadata=_llm_call_metadata(context),
        )
        _safe_callback(context.callback, completed)
        span.end(
            outputs={
                "status": "completed",
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": total_tokens,
            }
        )
        return text


def load_observability_settings(
    *,
    env_file: str | Path | None = None,
    env: Mapping[str, str] | None = None,
) -> ObservabilitySettings:
    merged = dict(os.environ if env is None else env)
    if env_file is not None and Path(env_file).expanduser().exists():
        merged.update(load_env_file(env_file))
    environment = (merged.get("MOOMAIL_ENVIRONMENT") or "development").strip().lower()
    enabled = _parse_bool(merged.get("MOOMAIL_LANGSMITH_ENABLED"), default=False)
    sampling_default = 0.0 if environment == "production" else 1.0
    return ObservabilitySettings(
        langsmith_enabled=enabled,
        langsmith_project=(
            merged.get("MOOMAIL_LANGSMITH_PROJECT")
            or merged.get("LANGSMITH_PROJECT")
            or "moomail-finance-ai"
        ),
        environment=environment,
        sampling_rate=_parse_float(
            merged.get("MOOMAIL_LANGSMITH_SAMPLING_RATE"),
            default=sampling_default,
        ),
        checkpoint_enabled=_parse_bool(
            merged.get("MOOMAIL_DIAGNOSTIC_CHECKPOINT_ENABLED"),
            default=False,
        ),
        checkpoint_retention_threads=_parse_int(
            merged.get("MOOMAIL_DIAGNOSTIC_CHECKPOINT_RETENTION_THREADS"),
            default=20,
        ),
    )


def build_observability_runtime(
    *,
    env_file: str | Path | None = None,
    env: Mapping[str, str] | None = None,
    sink: TraceSink | None = None,
) -> ObservabilityRuntime:
    settings = load_observability_settings(env_file=env_file, env=env)
    selected_sink = sink
    if selected_sink is None:
        selected_sink = (
            LangSmithTraceSink(settings.langsmith_project)
            if settings.langsmith_enabled
            else NullTraceSink()
        )
    return ObservabilityRuntime(settings=settings, sink=selected_sink)


def sanitize_external_trace_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: _sanitize_external_value(value)
        for key, value in metadata.items()
        if key.casefold() in EXTERNAL_TRACE_METADATA_ALLOWLIST
        and key.casefold() not in EXTERNAL_TRACE_DENIED_KEYS
        and value is not None
    }


def sanitize_external_trace_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    return sanitize_external_trace_metadata(payload)


def _sanitize_external_value(value: Any) -> Any:
    if value is None or isinstance(value, bool | int | float):
        return value
    if isinstance(value, str):
        return value[:240]
    if isinstance(value, list | tuple):
        return [_sanitize_external_value(item) for item in value[:32]]
    return str(value)[:240]


def _checkpoint_summary(
    thread_id: str,
    checkpoint: Mapping[str, Any],
    metadata,
) -> DiagnosticCheckpointSummary:
    values = checkpoint.get("channel_values", {})
    state: Any = None
    if isinstance(values, Mapping):
        state = values if "run_id" in values else values.get("__root__")
        if state is None:
            for value in values.values():
                if hasattr(value, "run_id") or isinstance(value, Mapping) and "run_id" in value:
                    state = value
                    break
    get = (
        (lambda key, default=None: getattr(state, key, default))
        if state is not None and not isinstance(state, Mapping)
        else (
            lambda key, default=None: (
                state.get(key, default) if isinstance(state, Mapping) else default
            )
        )
    )
    decision = get("validated_turn_decision") or get("turn_decision")
    route = (
        getattr(decision, "route", None)
        if decision is not None and not isinstance(decision, Mapping)
        else decision.get("route") if isinstance(decision, Mapping) else None
    )
    return DiagnosticCheckpointSummary(
        thread_id=thread_id,
        checkpoint_id=str(checkpoint.get("id") or "unknown"),
        step=metadata.get("step") if isinstance(metadata, Mapping) else None,
        source=metadata.get("source") if isinstance(metadata, Mapping) else None,
        run_id=get("run_id"),
        mode=get("mode"),
        route=route,
        total_llm_calls=int(get("total_llm_calls", 0) or 0),
        warning_count=len(get("warnings", []) or []),
        status_event_count=len(get("status_events", []) or []),
        has_baseline=get("portfolio_baseline") is not None,
        has_portfolio_packet=get("portfolio_packet") is not None,
        has_final_report=get("final_report") is not None,
    )


def _llm_identity(llm: Any) -> tuple[str, str]:
    config = getattr(llm, "config", None)
    provider = str(getattr(config, "provider", None) or llm.__class__.__name__)
    model = str(getattr(config, "model", None) or llm.__class__.__name__)
    return provider[:80], model[:160]


def _llm_metadata(
    context: LLMObservationContext,
    purpose: LLMCallPurpose,
    provider: str,
    model: str,
) -> dict[str, Any]:
    return sanitize_external_trace_metadata(
        {
            "run_id": context.run_id,
            "thread_id": context.thread_id,
            "subagent": context.subagent,
            "purpose": purpose,
            "provider": provider,
            "model": model,
            "route": context.route,
            "attempt": context.attempt,
            "budget_limit": context.budget_limit,
            "expected_call_count": context.expected_call_count,
            "environment": context.runtime.settings.environment,
            "app_version": "1.5",
        }
    )


def _llm_call_metadata(context: LLMObservationContext) -> dict[str, Any]:
    metadata: dict[str, Any] = {"environment": context.runtime.settings.environment}
    if context.route in {
        "direct_context",
        "delegate_portfolio",
        "delegate_sentiment",
        "delegate_both",
        "unsupported",
    }:
        metadata["route"] = context.route
    if context.budget_limit is not None:
        metadata["budget_limit"] = context.budget_limit
    if context.expected_call_count is not None:
        metadata["expected_call_count"] = context.expected_call_count
    return metadata


def _safe_callback(
    callback: Callable[[LLMCallTrace], None] | None,
    event: LLMCallTrace,
) -> None:
    if callback is None:
        return
    try:
        callback(event)
    except Exception:
        return


def _subagent_for_purpose(purpose: LLMCallPurpose) -> SubagentName:
    return "portfolio_agent" if purpose.startswith("portfolio_") else "investment_agent"


def _parse_bool(value: str | None, *, default: bool) -> bool:
    if value is None or not value.strip():
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"Invalid boolean value: {value}")


def _parse_float(value: str | None, *, default: float) -> float:
    return default if value is None or not value.strip() else float(value)


def _parse_int(value: str | None, *, default: int) -> int:
    return default if value is None or not value.strip() else int(value)
