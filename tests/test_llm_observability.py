from __future__ import annotations

import json

import pytest

from moomail_finance_ai.investment_agent import InvestmentAgent
from moomail_finance_ai.investment_planner import LLMInvestmentPlanner
from moomail_finance_ai.llm import (
    GeminiConfig,
    GeminiLLMClient,
    OpenAIConfig,
    OpenAILLMClient,
)
from moomail_finance_ai.mocks import mock_investment_policy
from moomail_finance_ai.observability import (
    EXTERNAL_TRACE_DENIED_KEYS,
    InMemoryTraceSink,
    ObservabilityRuntime,
    ObservabilitySettings,
    SafeDiagnosticCheckpointer,
    build_observability_runtime,
    generate_text_with_observability,
    llm_observation_scope,
    load_observability_settings,
    sanitize_external_trace_metadata,
)


class FakeConfig:
    provider = "fake-provider"
    model = "fake-model"


class FakeLLM:
    config = FakeConfig()

    def __init__(self, text: str = "ok", *, error: Exception | None = None):
        self.text = text
        self.error = error
        self.calls = 0

    def generate_text(self, prompt: str, **kwargs) -> str:
        del prompt, kwargs
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.text


class NoopPortfolioAgent:
    def run(self, *args, **kwargs):
        del args, kwargs
        raise AssertionError("Portfolio Agent should not run for an unsupported route.")


class EmptyBaselineService:
    def load(self):
        from moomail_finance_ai.agent_schemas import PortfolioBaselinePacket

        return PortfolioBaselinePacket(portfolio_id="portfolio_default")


class FailingFinalizeCheckpointer(SafeDiagnosticCheckpointer):
    def finalize_thread(self, thread_id: str) -> None:
        del thread_id
        raise RuntimeError("synthetic checkpoint finalization failure")


def _enabled_runtime(sink: InMemoryTraceSink, *, checkpoint: bool = False):
    return ObservabilityRuntime(
        settings=ObservabilitySettings(
            langsmith_enabled=True,
            environment="test",
            sampling_rate=1.0,
            checkpoint_enabled=checkpoint,
            checkpoint_retention_threads=2,
        ),
        sink=sink,
    )


def test_llm_instrumentation_wraps_every_generate_text_call():
    sink = InMemoryTraceSink()
    runtime = _enabled_runtime(sink)
    events = []
    llm = FakeLLM()

    with llm_observation_scope(
        run_id="investment_run_test",
        thread_id="thread_test",
        subagent="investment_agent",
        runtime=runtime,
        callback=events.append,
        route="direct_context",
    ):
        result = generate_text_with_observability(
            llm,
            "raw prompt must not leave the process",
            purpose="investment_planning",
        )

    assert result == "ok"
    assert llm.calls == 1
    assert [event.status for event in events] == ["started", "completed"]
    assert all(event.purpose == "investment_planning" for event in events)
    assert events[-1].duration_ms is not None
    assert events[-1].attempt == 1
    llm_spans = [record for record in sink.records if record.run_type == "llm"]
    assert len(llm_spans) == 1
    assert llm_spans[0].metadata["purpose"] == "investment_planning"
    assert "input_tokens" not in llm_spans[0].outputs
    assert "output_tokens" not in llm_spans[0].outputs
    assert "total_tokens" not in llm_spans[0].outputs
    assert "prompt" not in json.dumps(llm_spans[0].model_dump()).lower()


def test_llm_client_construction_is_not_counted_as_call():
    events = []
    GeminiLLMClient(GeminiConfig(api_key="unused", model="test-model"))
    OpenAILLMClient(OpenAIConfig(api_key="unused", model="test-model"))
    assert events == []


def test_llm_result_captures_usage_when_available(monkeypatch):
    gemini = GeminiLLMClient(GeminiConfig(api_key="unused", model="gemini-test"))
    openai = OpenAILLMClient(OpenAIConfig(api_key="unused", model="gpt-test"))
    monkeypatch.setattr(
        gemini,
        "_request_json",
        lambda *args, **kwargs: {
            "candidates": [{"content": {"parts": [{"text": "gemini output"}]}}],
            "usageMetadata": {
                "promptTokenCount": 11,
                "candidatesTokenCount": 7,
                "totalTokenCount": 18,
            },
        },
    )
    monkeypatch.setattr(
        openai,
        "_request_json",
        lambda *args, **kwargs: {
            "output_text": "openai output",
            "usage": {"input_tokens": 13, "output_tokens": 5, "total_tokens": 18},
        },
    )

    gemini_result = gemini.generate_text_result("secret input")
    openai_result = openai.generate_text_result("secret input")

    gemini_usage = (
        gemini_result.input_tokens,
        gemini_result.output_tokens,
        gemini_result.total_tokens,
    )
    assert gemini_usage == (
        11,
        7,
        18,
    )
    openai_usage = (
        openai_result.input_tokens,
        openai_result.output_tokens,
        openai_result.total_tokens,
    )
    assert openai_usage == (
        13,
        5,
        18,
    )


def test_langsmith_processors_redact_financial_and_secret_fields():
    sanitized = sanitize_external_trace_metadata(
        {
            "run_id": "run-safe",
            "thread_id": "thread-safe",
            "route": "delegate_portfolio",
            "provider": "openai",
            "model": "gpt-test",
            "prompt": "show account 123 and holdings",
            "api_key": "sk-secret",
            "account_id": "123",
            "raw_broker_payload": {"positions": []},
            "portfolio_snapshot": {"total_value": 1000},
            "ips": {"target": 0.5},
            "unexpected": "drop me",
        }
    )

    assert sanitized == {
        "run_id": "run-safe",
        "thread_id": "thread-safe",
        "route": "delegate_portfolio",
        "provider": "openai",
        "model": "gpt-test",
    }
    assert EXTERNAL_TRACE_DENIED_KEYS.isdisjoint(sanitized)


def test_langsmith_export_failure_does_not_fail_llm_call():
    runtime = _enabled_runtime(InMemoryTraceSink(fail_on_start=True))
    events = []

    with llm_observation_scope(
        run_id="run-safe",
        thread_id="thread-safe",
        subagent="investment_agent",
        runtime=runtime,
        callback=events.append,
    ):
        result = generate_text_with_observability(
            FakeLLM("still works"),
            "private prompt",
            purpose="investment_planning",
        )

    assert result == "still works"
    assert [event.status for event in events] == ["started", "completed"]
    assert runtime.failures == ["RuntimeError"]


def test_failed_llm_call_emits_sanitized_lifecycle():
    sink = InMemoryTraceSink()
    runtime = _enabled_runtime(sink)
    events = []

    with pytest.raises(RuntimeError, match="provider secret"):
        with llm_observation_scope(
            run_id="run-safe",
            thread_id="thread-safe",
            subagent="investment_agent",
            runtime=runtime,
            callback=events.append,
        ):
            generate_text_with_observability(
                FakeLLM(error=RuntimeError("provider secret sk-hidden123456")),
                "private prompt",
                purpose="investment_planning",
            )

    assert [event.status for event in events] == ["started", "failed"]
    assert events[-1].error_category == "RuntimeError"
    serialized = json.dumps([record.model_dump(mode="json") for record in sink.records])
    assert "private prompt" not in serialized
    assert "sk-hidden" not in serialized


def test_langgraph_trace_contains_root_named_nodes_and_llm_child_span():
    response = json.dumps(
        {
            "route": "unsupported",
            "route_reasons": ["unsupported_request"],
            "warnings": ["Request cannot be completed from available evidence."],
        }
    )
    sink = InMemoryTraceSink()
    runtime = _enabled_runtime(sink)
    agent = InvestmentAgent(
        portfolio_agent=NoopPortfolioAgent(),
        ips=mock_investment_policy(),
        planner=LLMInvestmentPlanner(FakeLLM(response)),
        portfolio_baseline_service=EmptyBaselineService(),
        observability=runtime,
    )

    state = agent.run("Unsupported request", thread_id="conversation-42")

    names = [record.name for record in sink.records]
    assert names[0] == "moomail.investment_agent"
    assert "investment.load_ips" in names
    assert "investment.plan_investment" in names
    assert "llm.investment_planning" in names
    llm_span = next(record for record in sink.records if record.run_type == "llm")
    parent = next(record for record in sink.records if record.span_id == llm_span.parent_span_id)
    assert parent.name == "investment.plan_investment"
    assert state.thread_id == "conversation-42"
    assert state.total_llm_calls == 1
    assert [event.status for event in state.status_events].count("llm_call_started") == 1
    assert [event.status for event in state.status_events].count("llm_call_completed") == 1


def test_checkpointing_is_opt_in_and_retains_only_safe_summaries():
    disabled = ObservabilityRuntime()
    assert disabled.checkpointer is None

    response = json.dumps(
        {
            "route": "unsupported",
            "route_reasons": ["unsupported_request"],
            "warnings": ["No supported route."],
        }
    )
    runtime = _enabled_runtime(InMemoryTraceSink(), checkpoint=True)
    agent = InvestmentAgent(
        portfolio_agent=NoopPortfolioAgent(),
        ips=mock_investment_policy(),
        planner=LLMInvestmentPlanner(FakeLLM(response)),
        portfolio_baseline_service=EmptyBaselineService(),
        observability=runtime,
    )

    agent.run("private query with account 123", thread_id="diagnostic-thread")
    summaries = agent.inspect_diagnostic_checkpoints("diagnostic-thread")

    assert summaries
    assert any(summary.run_id for summary in summaries)
    assert runtime.checkpointer is not None
    assert "diagnostic-thread" not in runtime.checkpointer.storage
    serialized = json.dumps([summary.model_dump(mode="json") for summary in summaries])
    assert "private query" not in serialized
    assert "account 123" not in serialized
    assert "portfolio_snapshot" not in serialized


def test_checkpoint_finalization_failure_is_a_nonfatal_user_trace_warning():
    response = json.dumps(
        {
            "route": "unsupported",
            "route_reasons": ["unsupported_request"],
            "warnings": ["No supported route."],
        }
    )
    runtime = ObservabilityRuntime(
        settings=ObservabilitySettings(checkpoint_enabled=True),
        checkpointer=FailingFinalizeCheckpointer(),
    )
    agent = InvestmentAgent(
        portfolio_agent=NoopPortfolioAgent(),
        ips=mock_investment_policy(),
        planner=LLMInvestmentPlanner(FakeLLM(response)),
        portfolio_baseline_service=EmptyBaselineService(),
        observability=runtime,
    )

    state = agent.run("Unsupported request", thread_id="checkpoint-failure")

    warning = next(
        event for event in state.status_events if event.status == "observability_degraded"
    )
    assert warning.event_type == "warning"
    assert warning.metadata["error_location"] == "observability"
    assert state.final_report is not None


def test_langsmith_is_disabled_without_explicit_config():
    settings = load_observability_settings(
        env={
            "LANGSMITH_TRACING": "true",
            "LANGSMITH_API_KEY": "not-used",
            "MOOMAIL_ENVIRONMENT": "development",
        }
    )
    runtime = build_observability_runtime(env={"LANGSMITH_TRACING": "true"})

    assert settings.langsmith_enabled is False
    assert runtime.settings.langsmith_enabled is False
    assert runtime.checkpointer is None


def test_langgraph_invocation_has_trace_correlation_config():
    runtime = ObservabilityRuntime(
        settings=ObservabilitySettings(environment="staging")
    )

    config = runtime.graph_config(run_id="investment_run_123", thread_id="thread_456")

    assert config["run_name"] == "moomail.investment_agent"
    assert config["configurable"]["thread_id"] == "thread_456"
    assert config["metadata"] == {
        "run_id": "investment_run_123",
        "thread_id": "thread_456",
        "app_version": "1.5",
        "environment": "staging",
        "subagent": "investment_agent",
    }


def test_moomail_trace_is_independent_from_langsmith():
    response = json.dumps(
        {
            "route": "unsupported",
            "route_reasons": ["unsupported_request"],
            "warnings": ["No supported route."],
        }
    )
    sink = InMemoryTraceSink()
    runtime = ObservabilityRuntime(
        settings=ObservabilitySettings(langsmith_enabled=False),
        sink=sink,
    )
    agent = InvestmentAgent(
        portfolio_agent=NoopPortfolioAgent(),
        ips=mock_investment_policy(),
        planner=LLMInvestmentPlanner(FakeLLM(response)),
        portfolio_baseline_service=EmptyBaselineService(),
        observability=runtime,
    )

    state = agent.run("Unsupported request")

    assert sink.records == []
    assert state.total_llm_calls == 1
    statuses = [event.status for event in state.status_events]
    assert "llm_call_started" in statuses
    assert "llm_call_completed" in statuses


def test_langsmith_export_failure_does_not_fail_chat_or_change_dashboard():
    from moomail_finance_ai.chat_api import ChatService

    response = json.dumps(
        {
            "route": "unsupported",
            "route_reasons": ["unsupported_request"],
            "warnings": ["No supported route."],
        }
    )
    runtime = _enabled_runtime(InMemoryTraceSink(fail_on_start=True))
    agent = InvestmentAgent(
        portfolio_agent=NoopPortfolioAgent(),
        ips=mock_investment_policy(),
        planner=LLMInvestmentPlanner(FakeLLM(response)),
        portfolio_baseline_service=EmptyBaselineService(),
        observability=runtime,
    )
    dashboard = object()

    class StableDashboardService:
        def latest_snapshot(self):
            return dashboard

    service = ChatService(
        investment_agent=agent,
        portfolio_data_service=StableDashboardService(),
    )

    before = service.portfolio_dashboard()
    state = service.run("Unsupported request")
    after = service.portfolio_dashboard()

    assert state.final_report is not None
    assert any(event.status == "observability_degraded" for event in state.status_events)
    assert before is dashboard
    assert after is dashboard
