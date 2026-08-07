from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable, Protocol
from uuid import uuid4

from langgraph.graph import END, StateGraph

from moomail_finance_ai.mocks import mock_investment_policy
from moomail_finance_ai.mcp.gateway import MCPToolGateway
from moomail_finance_ai.portfolio_agent import (
    PortfolioAnalysisUnavailableError,
    PortfolioAgentResult,
    PortfolioEvaluator,
    PortfolioLLMCallBudgetExceededError,
    build_default_portfolio_agent,
)
from moomail_finance_ai.schemas import (
    FinalReport,
    InvestmentPolicy,
    Recommendation,
)
from moomail_finance_ai.investment_guardrails import review_investment_report
from moomail_finance_ai.investment_planner import (
    InvestmentPlanValidationError,
    InvestmentPlanningUnavailableError,
    InvestmentPlanner,
    InvestmentTurnPlanner,
    LLMInvestmentPlanner,
    UnavailableInvestmentPlanner,
    investment_plan_to_query_plan,
    investment_turn_to_plan,
    legacy_plan_to_turn_decision,
    validate_investment_turn_decision,
)
from moomail_finance_ai.portfolio_baseline import build_default_portfolio_baseline_service
from moomail_finance_ai.observability import (
    ObservabilityRuntime,
    build_observability_runtime,
    llm_observation_scope,
)
from moomail_finance_ai.portfolio_evidence_planner import (
    PortfolioEvidencePlanValidationError,
    PortfolioEvidencePlanningUnavailableError,
)
from moomail_finance_ai.sentiment_agent_stub import SentimentAgentStub
from moomail_finance_ai.agent_trace import sanitize_trace_event
from moomail_finance_ai.agent_schemas import (
    InvestmentAgentState,
    InvestmentPlan,
    InvestmentQueryPlan,
    InvestmentTurnDecision,
    LLMCallTrace,
    PortfolioBaselinePacket,
    PortfolioContextPlan,
    PortfolioTask,
    SentimentCandidate,
    SentimentPacket,
    SentimentTask,
    SynthesisInput,
    TraceEvent,
    PortfolioAgentEvidencePacket,
)


US_EQUITY_EXCHANGES = {"US", "NASDAQ", "NYSE", "AMEX", "ARCA", "BATS"}


class PortfolioAgentProtocol(Protocol):
    def run(
        self,
        query: str,
        ips: InvestmentPolicy,
        *,
        status_callback=None,
        portfolio_task: PortfolioTask | None = None,
        portfolio_request=None,
    ) -> PortfolioAgentResult: ...


class SentimentAgentProtocol(Protocol):
    def run(self, task: SentimentTask) -> SentimentPacket: ...


class PortfolioBaselineProtocol(Protocol):
    def load(self) -> PortfolioBaselinePacket: ...


@dataclass
class InvestmentAgent:
    portfolio_agent: PortfolioAgentProtocol
    sentiment_agent: SentimentAgentProtocol = field(default_factory=SentimentAgentStub)
    ips: InvestmentPolicy = field(default_factory=mock_investment_policy)
    planner: InvestmentPlanner | InvestmentTurnPlanner = field(
        default_factory=lambda: UnavailableInvestmentPlanner(
            "Investment planning requires a configured LLM planner. No deterministic "
            "keyword or regex fallback planner is available."
        )
    )
    portfolio_baseline_service: PortfolioBaselineProtocol | None = None
    observability: ObservabilityRuntime = field(default_factory=ObservabilityRuntime)
    graph_runtime: str = field(init=False)
    _status_callback: Callable[[TraceEvent], None] | None = field(
        default=None,
        init=False,
        repr=False,
    )
    _active_baseline: PortfolioBaselinePacket | None = field(
        default=None,
        init=False,
        repr=False,
    )
    _active_llm_calls: list[LLMCallTrace] = field(
        default_factory=list,
        init=False,
        repr=False,
    )
    _active_status_events: list[TraceEvent] = field(
        default_factory=list,
        init=False,
        repr=False,
    )

    def __post_init__(self) -> None:
        self.graph = self._build_graph()

    def run(
        self,
        query: str,
        *,
        status_callback=None,
        thread_id: str | None = None,
    ) -> InvestmentAgentState:
        run_id = f"investment_run_{uuid4().hex[:12]}"
        state = InvestmentAgentState(
            run_id=run_id,
            thread_id=thread_id or f"thread_{uuid4().hex[:12]}",
            user_query=query,
        )
        self._status_callback = status_callback
        self._active_baseline = None
        self._active_llm_calls = []
        self._active_status_events = []
        observability_failure_offset = len(self.observability.failures)
        try:
            graph_config = self.observability.graph_config(
                run_id=state.run_id,
                thread_id=state.thread_id,
            )
            with llm_observation_scope(
                run_id=state.run_id,
                thread_id=state.thread_id,
                subagent="investment_agent",
                runtime=self.observability,
                callback=lambda call: self._handle_llm_lifecycle(state, call),
                expected_call_count=1,
            ):
                with self.observability.span(
                    "moomail.investment_agent",
                    run_type="chain",
                    metadata=graph_config["metadata"],
                    inputs={"status": "started"},
                ):
                    result = self.graph.invoke(state, config=graph_config)
            state = (
                result
                if isinstance(result, InvestmentAgentState)
                else InvestmentAgentState.model_validate(result)
            )
        except (InvestmentPlanningUnavailableError, InvestmentPlanValidationError) as exc:
            state = self._planning_failure_state(state, exc)
        except Exception as exc:
            self._emit_error(state, exc, status="investment_agent_error")
            raise
        finally:
            if self.observability.checkpointer is not None:
                try:
                    self.observability.checkpointer.finalize_thread(state.thread_id)
                except Exception as exc:
                    self.observability.failures.append(exc.__class__.__name__)
            new_observability_failures = self.observability.failures[
                observability_failure_offset:
            ]
            if new_observability_failures:
                self._emit(
                    state,
                    "observability_degraded",
                    (
                        "Developer tracing was unavailable, but it did not change the "
                        "Investment Agent result."
                    ),
                    event_type="warning",
                    metadata={
                        "error_location": "observability",
                        "warning_count": len(new_observability_failures),
                    },
                )
            self._status_callback = None
            self._active_baseline = None
            self._active_llm_calls = []
            self._active_status_events = []
        return state

    def close(self) -> None:
        close = getattr(self.portfolio_agent, "close", None)
        if callable(close):
            close()

    def _build_graph(self):
        self.graph_runtime = "langgraph_state_graph"
        graph = StateGraph(InvestmentAgentState)
        graph.add_node("load_ips", self._observed_node("load_ips", self._load_ips_node))
        graph.add_node(
            "load_baseline",
            self._observed_node("load_baseline", self._load_baseline_node),
        )
        graph.add_node(
            "plan_investment",
            self._observed_node("plan_investment", self._plan_investment_node),
        )
        graph.add_node(
            "validate_plan",
            self._observed_node("validate_plan", self._validate_plan_node),
        )
        graph.add_node(
            "call_portfolio",
            self._observed_node("call_portfolio", self._call_portfolio_node),
        )
        graph.add_node(
            "route_sentiment",
            self._observed_node("route_sentiment", self._route_sentiment_node),
        )
        graph.add_node(
            "call_sentiment",
            self._observed_node("call_sentiment", self._call_sentiment_node),
        )
        graph.add_node("synthesize", self._observed_node("synthesize", self._synthesize_node))
        graph.add_node("guardrail", self._observed_node("guardrail", self._guardrail_node))
        graph.add_node(
            "final_output",
            self._observed_node("final_output", self._final_output_node),
        )
        graph.set_entry_point("load_ips")
        graph.add_edge("load_ips", "load_baseline")
        graph.add_edge("load_baseline", "plan_investment")
        graph.add_edge("plan_investment", "validate_plan")
        graph.add_conditional_edges(
            "validate_plan",
            self._route_after_validation,
            {
                "call_portfolio": "call_portfolio",
                "route_sentiment": "route_sentiment",
                "synthesize": "synthesize",
            },
        )
        graph.add_edge("call_portfolio", "route_sentiment")
        graph.add_conditional_edges(
            "route_sentiment",
            self._route_after_sentiment_scope,
            {"call_sentiment": "call_sentiment", "synthesize": "synthesize"},
        )
        graph.add_edge("call_sentiment", "synthesize")
        graph.add_edge("synthesize", "guardrail")
        graph.add_edge("guardrail", "final_output")
        graph.add_edge("final_output", END)
        return graph.compile(checkpointer=self.observability.checkpointer)

    def _observed_node(self, name: str, node):
        def observed(state: InvestmentAgentState) -> InvestmentAgentState:
            decision = state.validated_turn_decision or state.turn_decision
            with self.observability.span(
                f"investment.{name}",
                run_type="chain",
                metadata={
                    "run_id": state.run_id,
                    "thread_id": state.thread_id,
                    "node": name,
                    "subagent": "investment_agent",
                    "route": decision.route if decision is not None else None,
                    "environment": self.observability.settings.environment,
                    "app_version": "1.5",
                },
                inputs={"status": "started"},
            ):
                return node(state)

        observed.__name__ = f"observed_{name}"
        return observed

    def inspect_diagnostic_checkpoints(self, thread_id: str):
        if self.observability.checkpointer is None:
            return []
        return self.observability.checkpointer.inspect(thread_id)

    def _load_ips_node(self, state: InvestmentAgentState) -> InvestmentAgentState:
        self._emit(state, "loading_policy", "Loading the Investment Policy Statement.")
        state.ips = self.ips
        state.portfolio_id = self.ips.portfolio_id
        return state

    def _load_baseline_node(self, state: InvestmentAgentState) -> InvestmentAgentState:
        self._emit(
            state,
            "loading_portfolio_baseline",
            "Loading bounded saved portfolio context.",
            phase="baseline_context",
        )
        try:
            if self.portfolio_baseline_service is None:
                state.portfolio_baseline = PortfolioBaselinePacket(
                    portfolio_id=state.portfolio_id,
                    limitations=["Portfolio baseline service is not configured."],
                )
            else:
                state.portfolio_baseline = self.portfolio_baseline_service.load()
        except Exception as exc:
            state.portfolio_baseline = PortfolioBaselinePacket(
                portfolio_id=state.portfolio_id,
                limitations=["Portfolio baseline context could not be loaded."],
            )
            self._emit(
                state,
                "portfolio_baseline_unavailable",
                "Saved portfolio context is unavailable; routing will fail closed or delegate.",
                event_type="warning",
                phase="baseline_context",
                error_type=exc.__class__.__name__,
                error_message=str(exc) or exc.__class__.__name__,
            )
        baseline = state.portfolio_baseline
        assert baseline is not None
        self._active_baseline = baseline
        self._emit(
            state,
            "portfolio_baseline_ready",
            "Bounded saved portfolio context is ready for Investment planning.",
            phase="baseline_context",
            metadata={
                "baseline_version": baseline.schema_version,
                "as_of": baseline.as_of.isoformat() if baseline.as_of else None,
                "capability_count": len(baseline.capabilities),
                "warning_count": len(baseline.warnings),
            },
        )
        return state

    def _plan_investment_node(self, state: InvestmentAgentState) -> InvestmentAgentState:
        assert state.ips is not None
        assert state.portfolio_baseline is not None
        self._emit(
            state,
            "planning_investment",
            "Planning the request with saved portfolio evidence in one structured turn.",
            phase="investment_planner",
        )
        started_at = datetime.now(UTC)
        uses_instrumented_client = hasattr(self.planner, "llm")
        if _planner_attempts_outbound_llm(self.planner) and not uses_instrumented_client:
            self._record_investment_llm_call(
                state,
                started_at=started_at,
                status="started",
            )
        try:
            with llm_observation_scope(
                callback=lambda call: self._handle_llm_lifecycle(state, call),
            ):
                planner_output = _invoke_investment_turn_planner(
                    self.planner,
                    state.user_query,
                    state.ips,
                    state.portfolio_baseline,
                )
        except Exception as exc:
            if _planner_attempts_outbound_llm(self.planner) and not uses_instrumented_client:
                self._record_investment_llm_call(
                    state,
                    started_at=started_at,
                    status="failed",
                    error=exc,
                )
            raise
        if _planner_attempts_outbound_llm(self.planner) and not uses_instrumented_client:
            self._record_investment_llm_call(
                state,
                started_at=started_at,
                status="completed",
                decision=planner_output,
            )
        if isinstance(planner_output, InvestmentPlan):
            state.investment_plan = planner_output
            state.turn_decision = legacy_plan_to_turn_decision(planner_output)
            planner_type = "legacy_investment_plan"
        else:
            state.turn_decision = planner_output
            planner_type = "investment_turn_decision"
        assert state.turn_decision is not None
        self._emit(
            state,
            "investment_turn_ready",
            "Investment planner produced a bounded route decision.",
            phase="investment_planner",
            metadata={
                "planner_type": planner_type,
                "route": state.turn_decision.route,
                "route_reasons": list(state.turn_decision.route_reasons),
                "portfolio_task_intent": (
                    state.turn_decision.portfolio_request.task_intent
                    if state.turn_decision.portfolio_request
                    else None
                ),
                "required_evidence": list(state.turn_decision.required_evidence),
                "missing_evidence": list(state.turn_decision.missing_evidence),
                "actual_call_count": state.total_llm_calls,
            },
        )
        self._emit(
            state,
            "investment_plan_ready",
            "Compatibility Investment plan projection is ready.",
            phase="investment_planner",
            metadata={"planner_type": planner_type},
        )
        return state

    def _validate_plan_node(self, state: InvestmentAgentState) -> InvestmentAgentState:
        assert state.turn_decision is not None
        assert state.portfolio_baseline is not None
        self._emit(
            state,
            "validating_investment_route",
            "Validating safety, source integrity, and evidence coverage before routing.",
            phase="portfolio_request_validator",
        )
        try:
            validation = validate_investment_turn_decision(
                state.turn_decision,
                state.portfolio_baseline,
                original_query=state.user_query,
            )
        except InvestmentPlanValidationError as exc:
            self._emit(
                state,
                "investment_route_rejected",
                "Investment route was rejected before subagent calls.",
                event_type="error",
                phase="portfolio_request_validator",
                error_type=exc.__class__.__name__,
                error_message=str(exc),
            )
            raise
        state.validated_turn_decision = validation.decision
        state.investment_plan = investment_turn_to_plan(validation.decision)
        state.query_plan = investment_plan_to_query_plan(state.investment_plan)
        state.mode = state.investment_plan.mode
        state.evidence_coverage = (
            validation.coverage.model_dump(mode="json")
            if validation.coverage is not None
            else {
                "is_valid": None,
                "limitation": None,
            }
        )
        state.warnings = _dedupe([*state.warnings, *validation.warnings])
        coverage_result = (
            "covered"
            if validation.coverage is not None and validation.coverage.is_valid
            else "not_covered"
            if validation.coverage is not None
            else "delegated"
        )
        self._emit(
            state,
            "investment_route_validated",
            "Investment route passed deterministic pre-subagent validation.",
            phase="evidence_coverage",
            metadata={
                "result": "valid",
                "route": validation.decision.route,
                "route_reasons": list(validation.decision.route_reasons),
                "required_evidence": list(validation.decision.required_evidence),
                "missing_evidence": list(validation.decision.missing_evidence),
                "coverage_result": coverage_result,
                "fallback_used": validation.fallback_used,
                "baseline_version": state.portfolio_baseline.schema_version,
                "capability_count": len(state.portfolio_baseline.capabilities),
                "warning_count": len(validation.warnings),
                "actual_call_count": state.total_llm_calls,
            },
        )
        self._emit(
            state,
            "investment_plan_validated",
            "Compatibility Investment plan passed deterministic validation.",
            phase="portfolio_request_validator",
            metadata={"result": "valid"},
        )
        return state

    def _route_after_validation(self, state: InvestmentAgentState) -> str:
        assert state.validated_turn_decision is not None
        route = state.validated_turn_decision.route
        if route in {"delegate_portfolio", "delegate_both"}:
            return "call_portfolio"
        if route == "delegate_sentiment":
            return "route_sentiment"
        return "synthesize"

    def _route_after_sentiment_scope(self, state: InvestmentAgentState) -> str:
        assert state.query_plan is not None
        return "call_sentiment" if state.query_plan.needs_sentiment_agent else "synthesize"

    def _call_portfolio_node(self, state: InvestmentAgentState) -> InvestmentAgentState:
        assert state.query_plan is not None
        assert state.ips is not None
        if not state.query_plan.needs_portfolio_agent:
            self._emit(state, "skipping_portfolio_agent", "Portfolio Agent is not needed.")
            return state
        assert state.query_plan.portfolio_task is not None

        self._emit(
            state,
            "calling_portfolio_agent",
            "Calling the Portfolio Agent.",
            event_type="subagent_call",
            subagent="portfolio_agent",
        )
        forwarded_event_count = len(
            [event for event in state.status_events if event.child_run_id is not None]
        )
        try:
            with llm_observation_scope(
                callback=lambda call: self._handle_llm_lifecycle(state, call),
                route=(
                    state.validated_turn_decision.route
                    if state.validated_turn_decision is not None
                    else None
                ),
            ):
                result = self.portfolio_agent.run(
                    state.query_plan.portfolio_task.source_query,
                    state.ips,
                    portfolio_task=state.query_plan.portfolio_task,
                    portfolio_request=(
                        state.investment_plan.portfolio_request if state.investment_plan else None
                    ),
                    status_callback=lambda event: self._forward_portfolio_status(state, event),
                )
        except PortfolioEvidencePlanningUnavailableError as exc:
            warning = str(exc) or exc.__class__.__name__
            state.warnings = _dedupe([*state.warnings, warning])
            self._emit(
                state,
                "portfolio_evidence_planner_unavailable",
                "Portfolio evidence planning is unavailable; continuing with a limitation.",
                event_type="error",
                subagent="portfolio_agent",
                phase="portfolio_evidence_planner",
                error_type=exc.__class__.__name__,
                error_message=warning,
            )
            return state
        except PortfolioEvidencePlanValidationError as exc:
            warning = str(exc) or exc.__class__.__name__
            state.warnings = _dedupe([*state.warnings, warning])
            self._emit(
                state,
                "portfolio_evidence_compilation_failed",
                "Portfolio evidence compilation failed before evidence tools executed.",
                event_type="error",
                subagent="portfolio_agent",
                phase="portfolio_evidence_planner",
                error_type=exc.__class__.__name__,
                error_message=warning,
                metadata={
                    "route": state.validated_turn_decision.route,
                    "expected_call_count": 1,
                    "actual_call_count": state.total_llm_calls,
                },
            )
            return state
        except PortfolioAnalysisUnavailableError as exc:
            for call in exc.llm_calls:
                if call not in state.llm_calls:
                    state.llm_calls.append(call)
            state.total_llm_calls = len(state.llm_calls)
            warning = str(exc) or exc.__class__.__name__
            state.warnings = _dedupe([*state.warnings, warning])
            if not any(
                event.child_run_id == exc.run_id
                and event.status == "portfolio_analysis_failed"
                for event in state.status_events
            ):
                self._emit(
                    state,
                    "portfolio_analysis_failed",
                    "Portfolio analysis failed; deterministic dashboard state was not replaced.",
                    event_type="error",
                    subagent="portfolio_agent",
                    phase="llm_call",
                    child_run_id=exc.run_id,
                    error_type=exc.__class__.__name__,
                    error_message=warning,
                    metadata={
                        "route": state.validated_turn_decision.route,
                        "expected_call_count": 2,
                        "actual_call_count": state.total_llm_calls,
                    },
                )
            return state
        except PortfolioLLMCallBudgetExceededError as exc:
            warning = str(exc)
            state.warnings = _dedupe([*state.warnings, warning])
            self._emit(
                state,
                "portfolio_llm_budget_exceeded",
                "Portfolio analysis stopped before an unplanned model invocation.",
                event_type="error",
                subagent="portfolio_agent",
                phase="llm_call",
                error_type=exc.__class__.__name__,
                error_message=warning,
                metadata={
                    "route": state.validated_turn_decision.route,
                    "expected_call_count": 2,
                    "actual_call_count": state.total_llm_calls,
                    "budget_limit": exc.limit,
                },
            )
            return state
        except Exception as exc:
            warning = str(exc) or exc.__class__.__name__
            state.warnings = _dedupe([*state.warnings, warning])
            self._emit(
                state,
                "portfolio_execution_failed",
                "Portfolio evidence execution failed; deterministic dashboard state was not replaced.",
                event_type="error",
                subagent="portfolio_agent",
                phase="deterministic_tool_execution",
                error_type=exc.__class__.__name__,
                error_message=warning,
                metadata={
                    "route": state.validated_turn_decision.route,
                    "expected_call_count": 1,
                    "actual_call_count": state.total_llm_calls,
                },
            )
            return state
        for call in result.llm_calls:
            if call not in state.llm_calls:
                state.llm_calls.append(call)
        state.total_llm_calls = len(state.llm_calls)
        expected_portfolio_calls = result.expected_llm_calls.get("portfolio_analysis", 0)
        actual_portfolio_calls = result.actual_llm_calls.get(
            "portfolio_analysis",
            result.total_llm_calls,
        )
        if actual_portfolio_calls > expected_portfolio_calls:
            error = PortfolioLLMCallBudgetExceededError(
                purpose="portfolio_analysis",
                limit=expected_portfolio_calls,
                attempted=actual_portfolio_calls,
            )
            state.warnings = _dedupe([*state.warnings, str(error)])
            self._emit(
                state,
                "portfolio_llm_budget_exceeded",
                "Portfolio Agent made an unplanned model invocation and its result was rejected.",
                event_type="error",
                subagent="portfolio_agent",
                phase="llm_call",
                error_type=error.__class__.__name__,
                error_message=str(error),
                metadata={
                    "route": state.validated_turn_decision.route,
                    "expected_call_count": 1 + expected_portfolio_calls,
                    "actual_call_count": state.total_llm_calls,
                    "budget_limit": expected_portfolio_calls,
                },
            )
            return state
        if state.total_llm_calls > 2:
            error = PortfolioLLMCallBudgetExceededError(
                purpose="delegated_total",
                limit=2,
                attempted=state.total_llm_calls,
            )
            state.warnings = _dedupe([*state.warnings, str(error)])
            self._emit(
                state,
                "delegated_llm_budget_exceeded",
                "Delegated run exceeded the two-call model budget and was rejected.",
                event_type="error",
                subagent="portfolio_agent",
                phase="llm_call",
                error_type=error.__class__.__name__,
                error_message=str(error),
                metadata={
                    "route": state.validated_turn_decision.route,
                    "expected_call_count": 2,
                    "actual_call_count": state.total_llm_calls,
                    "budget_limit": 2,
                },
            )
            return state
        state.portfolio_packet = adapt_portfolio_result_to_evidence_packet(result, state.ips)
        forwarded_live = len(
            [event for event in state.status_events if event.child_run_id is not None]
        ) > forwarded_event_count
        if not forwarded_live:
            for event in result.status_events:
                self._forward_portfolio_status(state, event)
            self._emit_portfolio_evidence_trace(state, result)
            self._emit_portfolio_tool_trace(
                state,
                state.portfolio_packet.tool_calls,
                child_run_id=result.run_id,
            )
        return state

    def _forward_portfolio_status(self, state: InvestmentAgentState, event) -> None:
        if getattr(event, "run_id", None) is None:
            return
        status = str(event.status)
        if status in {
            "planned_portfolio_tool",
            "called_portfolio_tool",
            "skipped_portfolio_tool",
            "portfolio_tool_detail",
        }:
            tool_event = _portfolio_tool_trace_event(str(event.message))
            nested = TraceEvent(
                event_type="tool_call",
                run_id=state.run_id,
                status=tool_event["status"],
                message=tool_event["message"],
                timestamp=event.timestamp,
                phase="deterministic_tool_execution",
                subagent="portfolio_agent",
                server_name=tool_event["server_name"],
                tool_name=tool_event["tool_name"],
                input_summary=tool_event["input_summary"],
                output_summary=tool_event["output_summary"],
                group_key=f"portfolio.tools.{tool_event['metadata']['tool_call_kind']}",
                child_run_id=event.run_id,
                metadata=tool_event["metadata"],
            )
        else:
            event_type = (
                "error"
                if status.endswith("_failed") or status.endswith("_error")
                else "warning"
                if "warning" in status or status.startswith("skipping_")
                else "graph_node"
            )
            nested = TraceEvent(
                event_type=event_type,
                run_id=state.run_id,
                status=status,
                message=str(event.message),
                timestamp=event.timestamp,
                phase=_portfolio_status_phase(status),
                node=status if event_type == "graph_node" else None,
                subagent="portfolio_agent",
                group_key=f"portfolio.{_portfolio_status_phase(status)}",
                child_run_id=event.run_id,
                error_type="PortfolioAgentError" if event_type == "error" else None,
                error_message=str(event.message) if event_type == "error" else None,
            )
        nested = sanitize_trace_event(nested)
        signature = (
            nested.child_run_id,
            nested.status,
            nested.tool_name,
            nested.timestamp,
        )
        if any(
            (
                existing.child_run_id,
                existing.status,
                existing.tool_name,
                existing.timestamp,
            )
            == signature
            for existing in state.status_events
        ):
            return
        state.status_events.append(nested)
        self._active_status_events.append(nested)
        if self._status_callback is not None:
            self._status_callback(nested)

    def _route_sentiment_node(self, state: InvestmentAgentState) -> InvestmentAgentState:
        assert state.query_plan is not None
        plan = state.query_plan
        candidates = (
            state.portfolio_packet.sentiment_candidates if state.portfolio_packet else []
        )
        if not plan.needs_sentiment_agent:
            self._emit(
                state,
                "skipping_sentiment_agent",
                "Sentiment Agent is not needed for this portfolio-only query.",
            )
            return state

        seed_task = plan.sentiment_task or SentimentTask()
        scoped_task = _sentiment_task_from_plan_and_candidates(
            seed_task,
            candidates,
            state.user_query,
        )
        state.query_plan = plan.model_copy(update={"sentiment_task": scoped_task})
        self._emit(
            state,
            "routing_sentiment_agent",
            "Prepared a scoped Sentiment Agent stub task.",
        )
        return state

    def _call_sentiment_node(self, state: InvestmentAgentState) -> InvestmentAgentState:
        assert state.query_plan is not None
        if not state.query_plan.needs_sentiment_agent:
            return state
        assert state.query_plan.sentiment_task is not None
        self._emit(
            state,
            "calling_sentiment_agent",
            "Calling the Sentiment Agent stub.",
            event_type="subagent_call",
            subagent="sentiment_agent",
        )
        state.sentiment_packet = self.sentiment_agent.run(state.query_plan.sentiment_task)
        self._emit(
            state,
            "sentiment_stub_status",
            "Sentiment Agent returned structured missing-research status.",
            event_type="status",
            subagent="sentiment_agent",
            metadata={
                "retrieval_status": state.sentiment_packet.retrieval_status,
                "missing_documents_count": len(state.sentiment_packet.missing_documents),
                "warning_count": len(state.sentiment_packet.warnings),
            },
        )
        return state

    def _synthesize_node(self, state: InvestmentAgentState) -> InvestmentAgentState:
        assert state.query_plan is not None
        self._emit(state, "synthesizing_report", "Synthesizing the Investment Agent report.")
        state.synthesis = SynthesisInput(
            run_id=state.run_id,
            user_query=state.user_query,
            query_plan=state.query_plan,
            ips=state.ips,
            portfolio_packet=state.portfolio_packet,
            sentiment_packet=state.sentiment_packet,
            memory_context=[],
            warnings=list(state.warnings),
        )
        state.final_report = synthesize_final_report(state)
        return state

    def _guardrail_node(self, state: InvestmentAgentState) -> InvestmentAgentState:
        assert state.final_report is not None
        self._emit(state, "checking_guardrails", "Running investment output guardrails.")
        state.guardrail_review = review_investment_report(state)
        self._emit(
            state,
            (
                "guardrails_passed"
                if state.guardrail_review.passed
                else "guardrails_blocked"
            ),
            "Investment output guardrails completed.",
            event_type="status",
            subagent="guardrails",
            metadata={
                "passed": state.guardrail_review.passed,
                "output_status": state.guardrail_review.output_status,
                "check_count": len(state.guardrail_review.checks),
            },
        )
        return state

    def _final_output_node(self, state: InvestmentAgentState) -> InvestmentAgentState:
        self._emit(state, "complete", "Investment Agent run complete.")
        return state

    def _emit(
        self,
        state: InvestmentAgentState,
        status: str,
        message: str,
        *,
        event_type: str = "graph_node",
        subagent: str | None = "investment_agent",
        server_name: str | None = None,
        tool_name: str | None = None,
        input_summary: str | None = None,
        output_summary: str | None = None,
        group_key: str | None = None,
        child_run_id: str | None = None,
        metadata: dict | None = None,
        phase: str | None = None,
        error_type: str | None = None,
        error_message: str | None = None,
    ) -> None:
        event = sanitize_trace_event(TraceEvent(
            event_type=event_type,
            run_id=state.run_id,
            status=status,
            message=message,
            timestamp=datetime.now(UTC),
            phase=phase,
            node=status if event_type == "graph_node" else None,
            subagent=subagent,
            server_name=server_name,
            tool_name=tool_name,
            input_summary=input_summary,
            output_summary=output_summary,
            group_key=group_key,
            child_run_id=child_run_id,
            metadata=metadata or {},
            error_type=error_type,
            error_message=error_message,
        ))
        state.status_events.append(event)
        self._active_status_events.append(event)
        if self._status_callback is not None:
            self._status_callback(event)

    def _emit_error(
        self,
        state: InvestmentAgentState,
        exc: BaseException,
        *,
        status: str,
    ) -> None:
        self._emit(
            state,
            status,
            "Investment Agent run failed.",
            event_type="error",
            subagent="investment_agent",
            error_type=exc.__class__.__name__,
            error_message=str(exc) or exc.__class__.__name__,
            metadata={"error_location": "investment_agent.run"},
        )

    def _record_investment_llm_call(
        self,
        state: InvestmentAgentState,
        *,
        started_at: datetime,
        status: str,
        decision: InvestmentTurnDecision | InvestmentPlan | None = None,
        error: BaseException | None = None,
    ) -> None:
        ended_at = datetime.now(UTC) if status != "started" else None
        duration_ms = (
            max(0.0, (ended_at - started_at).total_seconds() * 1000)
            if ended_at is not None
            else None
        )
        provider, model = _planner_identity(self.planner)
        route = (
            decision.route
            if isinstance(decision, InvestmentTurnDecision)
            else "legacy_plan"
            if isinstance(decision, InvestmentPlan)
            else None
        )
        metadata = {
            "baseline_version": (
                state.portfolio_baseline.schema_version
                if state.portfolio_baseline is not None
                else "unknown"
            ),
            "capability_count": (
                len(state.portfolio_baseline.capabilities)
                if state.portfolio_baseline is not None
                else 0
            ),
            "expected_call_count": 1,
        }
        if route in {
            "direct_context",
            "delegate_portfolio",
            "delegate_sentiment",
            "delegate_both",
            "unsupported",
        }:
            metadata["route"] = route
        call = LLMCallTrace(
            run_id=state.run_id,
            purpose="investment_planning",
            provider=provider,
            model=model,
            subagent="investment_agent",
            status=status,
            started_at=started_at,
            ended_at=ended_at,
            duration_ms=duration_ms,
            attempt=1,
            error_category=error.__class__.__name__ if error is not None else None,
            metadata=metadata,
        )
        self._handle_llm_lifecycle(state, call)

    def _handle_llm_lifecycle(
        self,
        state: InvestmentAgentState,
        call: LLMCallTrace,
    ) -> None:
        if call.status in {"completed", "failed"}:
            if call not in state.llm_calls:
                state.llm_calls.append(call)
            if call not in self._active_llm_calls:
                self._active_llm_calls.append(call)
            state.total_llm_calls = len(state.llm_calls)
        self._emit(
            state,
            f"llm_call_{call.status}",
            f"{call.subagent.replace('_', ' ').title()} {call.purpose.replace('_', ' ')} call "
            f"{call.status}.",
            event_type="llm_call",
            phase="llm_call",
            subagent=call.subagent,
            group_key=f"llm.{call.purpose}",
            child_run_id=call.run_id if call.run_id != state.run_id else None,
            metadata={
                "llm_purpose": call.purpose,
                "provider": call.provider,
                "model": call.model,
                "duration_ms": call.duration_ms,
                "input_tokens": call.input_tokens,
                "output_tokens": call.output_tokens,
                "total_tokens": call.total_tokens,
                "attempt": call.attempt,
                "error_category": call.error_category,
                "route": call.metadata.get("route"),
                "budget_limit": call.metadata.get("budget_limit"),
                "expected_call_count": call.metadata.get("expected_call_count"),
                "actual_call_count": state.total_llm_calls,
            },
        )

    def _planning_failure_state(
        self,
        state: InvestmentAgentState,
        exc: BaseException,
    ) -> InvestmentAgentState:
        message = str(exc) or exc.__class__.__name__
        state.ips = state.ips or self.ips
        state.portfolio_id = state.ips.portfolio_id if state.ips else state.portfolio_id
        state.portfolio_baseline = state.portfolio_baseline or self._active_baseline
        state.llm_calls = list(self._active_llm_calls)
        state.total_llm_calls = len(state.llm_calls)
        state.status_events = list(self._active_status_events)
        state.mode = "unsupported"
        state.turn_decision = _planning_unavailable_decision(message)
        state.validated_turn_decision = state.turn_decision
        state.investment_plan = _planning_unavailable_plan(message)
        state.query_plan = investment_plan_to_query_plan(state.investment_plan)
        state.warnings = _dedupe([*state.warnings, message])
        self._emit(
            state,
            "investment_planner_unavailable",
            "Investment planning is unavailable; no deterministic fallback was used.",
            event_type="error",
            phase="investment_planner",
            error_type=exc.__class__.__name__,
            error_message=message,
        )
        state.final_report = _planning_unavailable_report(state, message)
        self._guardrail_node(state)
        self._emit(
            state,
            "complete_with_planning_failure",
            "Investment Agent stopped before subagent calls because planning failed.",
        )
        return state

    def _emit_portfolio_tool_trace(
        self,
        state: InvestmentAgentState,
        tool_calls: list[str],
        *,
        child_run_id: str,
    ) -> None:
        for tool_call in tool_calls:
            event = _portfolio_tool_trace_event(tool_call)
            self._emit(
                state,
                event["status"],
                event["message"],
                event_type="tool_call",
                subagent="portfolio_agent",
                server_name=event["server_name"],
                tool_name=event["tool_name"],
                input_summary=event["input_summary"],
                output_summary=event["output_summary"],
                metadata=event["metadata"],
                phase="deterministic_tool_execution",
                child_run_id=child_run_id,
            )

    def _emit_portfolio_evidence_trace(
        self,
        state: InvestmentAgentState,
        result: PortfolioAgentResult,
    ) -> None:
        expected_total_calls = 1 + result.expected_llm_calls.get("portfolio_analysis", 0)
        if result.evidence_plan is not None:
            self._emit(
                state,
                "portfolio_evidence_plan_ready",
                "Portfolio Agent returned a bounded evidence plan.",
                phase="portfolio_evidence_planner",
                metadata={
                    "portfolio_task_intent": result.evidence_plan.task_intent,
                    "asset_hint_count": len(result.evidence_plan.resolved_assets),
                    "warning_count": len(result.evidence_plan.warnings),
                    "analysis_requirement": (
                        state.investment_plan.portfolio_request.analysis_requirement
                        if state.investment_plan and state.investment_plan.portfolio_request
                        else None
                    ),
                    "expected_call_count": expected_total_calls,
                    "actual_call_count": state.total_llm_calls,
                },
                child_run_id=result.run_id,
            )
        for call in result.llm_calls:
            self._emit(
                state,
                "portfolio_llm_call_failed"
                if call.status == "failed"
                else "portfolio_llm_call_completed",
                "Portfolio analysis LLM call failed."
                if call.status == "failed"
                else "Portfolio analysis LLM call completed within budget.",
                event_type="llm_call",
                phase="llm_call",
                subagent="portfolio_agent",
                metadata={
                    "llm_purpose": call.purpose,
                    "provider": call.provider,
                    "model": call.model,
                    "duration_ms": call.duration_ms,
                    "attempt": call.attempt,
                    "error_category": call.error_category,
                    "route": state.validated_turn_decision.route,
                    "expected_call_count": expected_total_calls,
                    "actual_call_count": state.total_llm_calls,
                },
                child_run_id=result.run_id,
            )
        self._emit(
            state,
            "portfolio_evidence_packet_ready",
            "Portfolio Agent returned separated deterministic evidence.",
            phase="deterministic_tool_execution",
            metadata={
                "portfolio_task_intent": result.evidence_packet.task_intent,
                "warning_count": len(result.evidence_packet.warnings),
            },
            child_run_id=result.run_id,
        )


def _invoke_investment_turn_planner(
    planner: InvestmentPlanner | InvestmentTurnPlanner,
    query: str,
    ips: InvestmentPolicy,
    baseline: PortfolioBaselinePacket,
) -> InvestmentTurnDecision | InvestmentPlan:
    plan_turn = getattr(planner, "plan_turn", None)
    if callable(plan_turn):
        return plan_turn(query, ips, baseline)
    plan = getattr(planner, "plan", None)
    if callable(plan):
        return plan(query, ips)
    raise InvestmentPlanningUnavailableError(
        "Investment planner does not expose a supported structured planning method."
    )


def _planner_identity(
    planner: InvestmentPlanner | InvestmentTurnPlanner,
) -> tuple[str, str]:
    llm = getattr(planner, "llm", None)
    config = getattr(llm, "config", None)
    provider = str(getattr(config, "provider", None) or planner.__class__.__name__)
    model = str(getattr(config, "model", None) or planner.__class__.__name__)
    return provider[:80], model[:160]


def _planner_attempts_outbound_llm(
    planner: InvestmentPlanner | InvestmentTurnPlanner,
) -> bool:
    return bool(getattr(planner, "outbound_llm", True))


def classify_investment_query(
    query: str,
    planner: InvestmentPlanner | None = None,
) -> InvestmentQueryPlan:
    if planner is None:
        raise InvestmentPlanningUnavailableError(
            "classify_investment_query requires an injected LLM-backed planner. "
            "Deterministic keyword classification has been removed."
        )
    return investment_plan_to_query_plan(planner.plan(query, mock_investment_policy()))


def adapt_portfolio_result_to_evidence_packet(
    result: PortfolioAgentResult,
    ips: InvestmentPolicy,
) -> PortfolioAgentEvidencePacket:
    sentiment_candidates = _sentiment_candidates_from_portfolio(result, ips)
    context_plan = result.context_plan or PortfolioContextPlan(
        needs_current_snapshot=True,
        needs_sql_history=True,
        history_queries=[
            "history_status",
            "latest_state",
            "portfolio_growth",
            "allocation_history",
        ],
        tickers=[candidate.ticker for candidate in sentiment_candidates if candidate.ticker],
        metric_groups=["allocation", "concentration", "effective_cash", "performance"],
        persist_observation=True,
        history_window="30d",
        row_limit=100,
    )
    return PortfolioAgentEvidencePacket(
        portfolio_id=result.portfolio_id,
        context_plan=context_plan,
        evidence_packet=result.evidence_packet,
        base_packet=result.portfolio_packet,
        history_context=result.history_context.model_dump(mode="json"),
        effective_cash=result.effective_cash.model_dump(mode="json"),
        sentiment_candidates=sentiment_candidates,
        tool_calls=list(result.tool_calls),
        data_quality=result.portfolio_packet.data_quality,
        warnings=list(result.warnings),
    )


def synthesize_final_report(state: InvestmentAgentState) -> FinalReport:
    assert state.query_plan is not None
    decision = state.validated_turn_decision
    if decision is not None and decision.route == "direct_context":
        return _direct_context_final_report(state, decision)
    if decision is not None and decision.route == "unsupported":
        return _unsupported_route_final_report(state, decision)
    portfolio_summary = _portfolio_summary(state)
    missing_data = _missing_data(state)
    recommendations = [
        Recommendation(
            title="Use the Investment Agent as an orchestration check, not a trading engine",
            rationale=(
                "The Investment Agent has routed the query through portfolio evidence"
                " and any available sentiment stub output, while keeping trade execution"
                " out of scope."
            ),
            constraints=[
                (
                    "No trade placement, order entry, exact share-count instruction, "
                    "or execution path."
                ),
                "Sentiment output is limited to the stub until GraphRAG is implemented.",
            ],
            missing_data=missing_data,
        )
    ]
    as_of = _report_as_of(state)
    return FinalReport(
        run_id=state.run_id,
        mode=_final_report_mode(state.query_plan.mode),
        title=_report_title(state.query_plan.mode),
        as_of=as_of,
        summary=_summary_text(state, portfolio_summary),
        portfolio_snapshot=_portfolio_snapshot_payload(state),
        portfolio_analysis=_portfolio_analysis_payload(state),
        sentiment_analysis=(
            state.sentiment_packet.model_dump(mode="json") if state.sentiment_packet else {}
        ),
        recommendations=recommendations,
        missing_data=missing_data,
        assumptions=[
            (
                "The Investment Agent uses a thin LangGraph supervisor with a "
                "Portfolio Agent subagent."
            ),
            "Neo4j GraphRAG and Pinecone memory are intentionally not connected in Task 2.",
        ],
        citations=[],
        disclaimer=(
            "This is investment analysis for personal decision support, not licensed "
            "financial advice."
        ),
    )


def _direct_context_final_report(
    state: InvestmentAgentState,
    decision: InvestmentTurnDecision,
) -> FinalReport:
    baseline = state.portfolio_baseline
    assert baseline is not None
    cited_ids = set(decision.cited_evidence_refs)
    cited_refs = [
        ref.model_dump(mode="json")
        for ref in baseline.evidence_refs
        if ref.ref_id in cited_ids
    ]
    cited_summaries = [
        summary.model_dump(mode="json")
        for summary in baseline.summaries
        if set(summary.evidence_refs) & cited_ids
    ]
    missing_data = _dedupe(
        [
            *baseline.warnings,
            *baseline.limitations,
            *decision.warnings,
        ]
    )
    return FinalReport(
        run_id=state.run_id,
        mode=_final_report_mode(state.query_plan.mode),
        title=_report_title(state.query_plan.mode),
        as_of=baseline.as_of or baseline.generated_at,
        summary=decision.direct_answer or "Baseline-covered portfolio answer.",
        portfolio_snapshot={},
        portfolio_analysis={
            "route": "direct_context",
            "baseline_version": baseline.schema_version,
            "as_of": baseline.as_of.isoformat() if baseline.as_of else None,
            "required_evidence": list(decision.required_evidence),
            "cited_evidence_refs": list(decision.cited_evidence_refs),
            "summaries": cited_summaries,
            "evidence_refs": cited_refs,
            "limitations": list(baseline.limitations),
        },
        sentiment_analysis={},
        recommendations=[],
        missing_data=missing_data,
        assumptions=[
            (
                "The answer uses the bounded stored portfolio baseline and does not "
                "imply a live OpenD refresh."
            )
        ],
        citations=[],
        disclaimer=(
            "This is investment analysis for personal decision support, not licensed "
            "financial advice."
        ),
    )


def _unsupported_route_final_report(
    state: InvestmentAgentState,
    decision: InvestmentTurnDecision,
) -> FinalReport:
    missing_data = _dedupe([*state.warnings, *decision.warnings])
    summary = (
        missing_data[0]
        if missing_data
        else "This request cannot be answered safely from the available evidence."
    )
    return FinalReport(
        run_id=state.run_id,
        mode="review",
        title="Investment Request Limited",
        as_of=(
            state.portfolio_baseline.as_of
            if state.portfolio_baseline and state.portfolio_baseline.as_of
            else datetime.now(UTC)
        ),
        summary=summary,
        portfolio_snapshot={},
        portfolio_analysis={
            "route": "unsupported",
            "route_reasons": list(decision.route_reasons),
            "required_evidence": list(decision.required_evidence),
            "missing_evidence": list(decision.missing_evidence),
        },
        sentiment_analysis={},
        recommendations=[],
        missing_data=missing_data,
        assumptions=[],
        citations=[],
        disclaimer=(
            "This is investment analysis for personal decision support, not licensed "
            "financial advice."
        ),
    )


def build_default_investment_agent(
    *,
    env_file: str | Path | None = "config/local.env",
    from_report: str | Path | None = "reports/opend/field-report.json",
    db_path: str | Path = "data/portfolio-history.sqlite",
    llm_provider: str | None = None,
    portfolio_evaluator: PortfolioEvaluator | None = None,
    ips: InvestmentPolicy | None = None,
    gateway: MCPToolGateway | None = None,
    gateway_mode: str = "stdio",
    portfolio_baseline_service: PortfolioBaselineProtocol | None = None,
    observability: ObservabilityRuntime | None = None,
) -> InvestmentAgent:
    planner = _build_default_investment_planner(
        provider=llm_provider,
        env_file=env_file,
    )
    baseline_service = portfolio_baseline_service or build_default_portfolio_baseline_service(
        db_path=db_path,
        env_file=env_file,
        gateway=gateway,
        gateway_mode=gateway_mode,
    )
    shared_gateway = gateway or getattr(baseline_service, "gateway", None)
    return InvestmentAgent(
        portfolio_agent=build_default_portfolio_agent(
            env_file=env_file,
            from_report=from_report,
            db_path=db_path,
            llm_provider=llm_provider,
            evaluator=portfolio_evaluator,
            gateway=shared_gateway,
            gateway_mode=gateway_mode,
        ),
        sentiment_agent=SentimentAgentStub(),
        ips=ips or mock_investment_policy(),
        planner=planner,
        portfolio_baseline_service=baseline_service,
        observability=observability or build_observability_runtime(env_file=env_file),
    )


def _build_default_investment_planner(
    *,
    provider: str | None,
    env_file: str | Path | None,
) -> InvestmentPlanner | InvestmentTurnPlanner:
    try:
        return LLMInvestmentPlanner.from_env(provider=provider, env_file=env_file)
    except Exception:
        return UnavailableInvestmentPlanner(
            "Investment planning requires a configured LLM provider, API key, and model. "
            "No deterministic keyword or regex fallback planner is available.",
        )


def _portfolio_tool_trace_event(tool_call: str) -> dict:
    if tool_call.startswith("planned:"):
        qualified_tool = tool_call.removeprefix("planned:")
        server_name, tool_name = _split_qualified_tool(qualified_tool)
        return {
            "status": "planned_portfolio_tool",
            "message": "Portfolio Agent planned a bounded tool call.",
            "server_name": server_name,
            "tool_name": tool_name,
            "input_summary": "Portfolio context plan.",
            "output_summary": qualified_tool,
            "metadata": {"tool_call_kind": "planned"},
        }
    if tool_call.startswith("skipped:"):
        skipped = tool_call.removeprefix("skipped:")
        server_name, tool_name = _split_qualified_tool(skipped.split(" ", 1)[0])
        return {
            "status": "skipped_portfolio_tool",
            "message": "Portfolio Agent skipped a bounded tool call.",
            "server_name": server_name,
            "tool_name": tool_name,
            "input_summary": "Portfolio context plan.",
            "output_summary": skipped,
            "metadata": {"tool_call_kind": "skipped"},
        }
    if tool_call.startswith("actual_detail:"):
        return {
            "status": "portfolio_tool_detail",
            "message": "Portfolio Agent emitted tool execution detail.",
            "server_name": None,
            "tool_name": "portfolio_tool_detail",
            "input_summary": None,
            "output_summary": tool_call.removeprefix("actual_detail:"),
            "metadata": {"tool_call_kind": "detail"},
        }
    server_name, tool_name = _split_qualified_tool(tool_call)
    return {
        "status": "called_portfolio_tool",
        "message": "Portfolio Agent completed a bounded tool call.",
        "server_name": server_name,
        "tool_name": tool_name,
        "input_summary": "Bounded Portfolio Agent execution.",
        "output_summary": tool_call,
        "metadata": {"tool_call_kind": "actual"},
    }


def _portfolio_status_phase(status: str) -> str:
    if status.startswith("asset_resolution_"):
        return "asset_resolver"
    if "evidence_plan" in status or status == "planning_portfolio_evidence":
        return "portfolio_evidence_planner"
    if status in {
        "using_cached_portfolio_context",
        "refreshing_portfolio_context",
        "stale_cache_warning",
    }:
        return "portfolio_policy"
    if "evaluation" in status or "analysis" in status:
        return "llm_call"
    return "deterministic_tool_execution"


def _split_qualified_tool(value: str) -> tuple[str | None, str]:
    if ":" in value:
        server_name, tool_name = value.split(":", 1)
        return server_name or None, tool_name or "unknown_tool"
    return None, value or "unknown_tool"


def _sentiment_task_from_plan_and_candidates(
    task: SentimentTask,
    candidates: list[SentimentCandidate],
    query: str,
) -> SentimentTask:
    candidate_tickers = [candidate.ticker for candidate in candidates if candidate.ticker]
    tickers = _dedupe([*task.tickers, *candidate_tickers])
    candidate_themes = [
        str(candidate.source_portfolio_facts.get("theme"))
        for candidate in candidates
        if candidate.source_portfolio_facts.get("theme")
    ]
    return task.model_copy(
        update={
            "tickers": tickers,
            "themes": _dedupe([*task.themes, *candidate_themes]),
            "candidate_refs": candidates,
            "key_questions": task.key_questions or [query],
        }
    )


def _sentiment_candidates_from_portfolio(
    result: PortfolioAgentResult,
    ips: InvestmentPolicy,
) -> list[SentimentCandidate]:
    candidates = []
    rank = 1
    for holding in result.snapshot.holdings:
        if holding.asset_type != "equity":
            continue
        if (holding.exchange or "").upper() not in US_EQUITY_EXCHANGES:
            continue
        if abs(holding.portfolio_weight) < ips.material_holding_threshold:
            continue
        candidates.append(
            SentimentCandidate(
                ticker=holding.ticker,
                asset_id=holding.asset_id,
                reason=(
                    f"Material US-equity holding with portfolio weight "
                    f"{holding.portfolio_weight:.2%}."
                ),
                evidence_type="holding_weight",
                rank=rank,
                source_portfolio_facts={
                    "portfolio_weight": holding.portfolio_weight,
                    "market_value": holding.market_value,
                    "asset_type": holding.asset_type,
                },
            )
        )
        rank += 1
    return candidates


def _portfolio_summary(state: InvestmentAgentState) -> str:
    if not state.portfolio_packet:
        return "Portfolio Agent was not called for this query."
    packet = state.portfolio_packet
    base_packet = packet.base_packet
    if base_packet is None:
        return "Portfolio Agent returned an evidence packet without a base portfolio packet."
    total_value = base_packet.snapshot.total_value.amount
    currency = base_packet.snapshot.total_value.currency
    holdings = len(base_packet.snapshot.holdings)
    return f"Portfolio value is {currency} {total_value:,.2f} across {holdings} holding(s)."


def _summary_text(state: InvestmentAgentState, portfolio_summary: str) -> str:
    if state.query_plan and state.query_plan.mode == "unsupported":
        return "This request is outside scope because trade execution is not supported."
    parts = [portfolio_summary]
    if state.portfolio_packet and state.portfolio_packet.base_packet:
        risks = state.portfolio_packet.base_packet.risk.warnings
        if risks:
            parts.append("Portfolio risk warnings are visible in the portfolio analysis.")
    if state.sentiment_packet is not None:
        if state.sentiment_packet.retrieval_status in {"not_implemented", "missing_corpus"}:
            parts.append(
                "Sentiment research is listed as a limitation because GraphRAG is not "
                "connected yet."
            )
    return " ".join(parts)


def _missing_data(state: InvestmentAgentState) -> list[str]:
    missing = list(state.warnings)
    if state.portfolio_packet:
        missing.extend(state.portfolio_packet.warnings)
    if state.sentiment_packet is not None and state.sentiment_packet.retrieval_status in {
        "not_implemented",
        "missing_corpus",
    }:
        missing.append("Sentiment Agent GraphRAG retrieval is not implemented.")
        missing.extend(state.sentiment_packet.data_quality.missing_fields)
    return _dedupe(missing)


def _planning_unavailable_plan(message: str) -> InvestmentPlan:
    return InvestmentPlan(
        mode="unsupported",
        needs_portfolio_agent=False,
        needs_sentiment_agent=False,
        portfolio_request=None,
        sentiment_task=None,
        logical_asset_hints=[],
        themes=["planning_unavailable"],
        time_horizon=None,
        freshness_requirement="cached_ok",
        answer_constraints=[
            "no_trade_execution",
            "no_order_preparation",
            "no_exact_share_count",
            "source_backed",
        ],
        warnings=[message],
    )


def _planning_unavailable_decision(message: str) -> InvestmentTurnDecision:
    return InvestmentTurnDecision(
        route="unsupported",
        route_reasons=["unsupported_request"],
        warnings=[message],
    )


def _planning_unavailable_report(
    state: InvestmentAgentState,
    message: str,
) -> FinalReport:
    missing_data = _dedupe([*state.warnings, message])
    return FinalReport(
        run_id=state.run_id,
        mode="review",
        title="Investment Planning Unavailable",
        as_of=datetime.now(UTC),
        summary=(
            "The Investment Agent could not create a structured LLM plan, so it stopped "
            "before calling portfolio or sentiment subagents. No keyword or regex planner "
            "was used as a fallback."
        ),
        portfolio_snapshot={},
        portfolio_analysis={},
        sentiment_analysis={},
        recommendations=[
            Recommendation(
                title="Configure or retry the LLM planner",
                rationale=message,
                constraints=[
                    "No deterministic keyword or regex planning fallback is available.",
                    (
                        "No trade placement, order preparation, or exact share-count "
                        "instruction was produced."
                    ),
                ],
                missing_data=missing_data,
            )
        ],
        missing_data=missing_data,
        assumptions=[
            "Planning must come from the configured LLM-backed planner.",
            (
                "Deterministic validation and tool execution remain available only "
                "after a valid plan exists."
            ),
        ],
        citations=[],
        disclaimer=(
            "This is investment analysis for personal decision support, not licensed "
            "financial advice."
        ),
    )


def _portfolio_snapshot_payload(state: InvestmentAgentState) -> dict:
    if not state.portfolio_packet or not state.portfolio_packet.base_packet:
        return {}
    return state.portfolio_packet.base_packet.snapshot.model_dump(mode="json")


def _portfolio_analysis_payload(state: InvestmentAgentState) -> dict:
    if not state.portfolio_packet:
        return {}
    payload = {
        "context_plan": state.portfolio_packet.context_plan.model_dump(mode="json"),
        "evidence_packet": (
            state.portfolio_packet.evidence_packet.model_dump(mode="json")
            if state.portfolio_packet.evidence_packet
            else None
        ),
        "history_context": state.portfolio_packet.history_context,
        "effective_cash": state.portfolio_packet.effective_cash,
        "sentiment_candidates": [
            candidate.model_dump(mode="json")
            for candidate in state.portfolio_packet.sentiment_candidates
        ],
        "tool_calls": list(state.portfolio_packet.tool_calls),
        "base_packet": (
            state.portfolio_packet.base_packet.model_dump(mode="json")
            if state.portfolio_packet.base_packet
            else None
        ),
    }
    if state.portfolio_packet.base_packet:
        base_packet = state.portfolio_packet.base_packet
        payload.update(
            {
                "allocation": {
                    key: [item.model_dump(mode="json") for item in values]
                    for key, values in base_packet.allocation.items()
                },
                "performance": base_packet.performance.model_dump(mode="json"),
                "risk": base_packet.risk.model_dump(mode="json"),
                "candidate_issues": [
                    issue.model_dump(mode="json")
                    for issue in base_packet.candidate_issues
                ],
                "data_quality": base_packet.data_quality.model_dump(mode="json"),
            }
        )
    return payload


def _report_as_of(state: InvestmentAgentState) -> datetime:
    if state.portfolio_packet and state.portfolio_packet.base_packet:
        return state.portfolio_packet.base_packet.snapshot.as_of
    return datetime.now(UTC)


def _report_title(mode: str) -> str:
    return {
        "portfolio_fact": "Portfolio Fact Check",
        "risk_check": "Portfolio Risk Check",
        "what_changed": "Portfolio Change Review",
        "deep_dive": "Investment Deep Dive",
        "compare": "Investment Comparison",
        "unsupported": "Unsupported Request",
    }.get(mode, "Portfolio Review")


def _final_report_mode(mode: str) -> str:
    if mode in {"risk_check", "what_changed", "deep_dive", "compare", "review"}:
        return mode
    return "review"


def _dedupe(values: list[str]) -> list[str]:
    seen = set()
    result = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
