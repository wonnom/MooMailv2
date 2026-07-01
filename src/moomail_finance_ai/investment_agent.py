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
    PortfolioAgentResult,
    PortfolioEvaluator,
    build_default_portfolio_agent,
)
from moomail_finance_ai.schemas import (
    FinalReport,
    InvestmentPolicy,
    Recommendation,
)
from moomail_finance_ai.investment_guardrails import review_investment_report
from moomail_finance_ai.investment_planner import (
    DeterministicInvestmentPlanner,
    InvestmentPlanValidationError,
    InvestmentPlanner,
    extract_ticker_strings,
    investment_plan_to_query_plan,
    validate_investment_plan,
)
from moomail_finance_ai.sentiment_agent_stub import SentimentAgentStub
from moomail_finance_ai.agent_trace import sanitize_trace_event
from moomail_finance_ai.agent_schemas import (
    InvestmentAgentState,
    InvestmentQueryPlan,
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


@dataclass
class InvestmentAgent:
    portfolio_agent: PortfolioAgentProtocol
    sentiment_agent: SentimentAgentProtocol = field(default_factory=SentimentAgentStub)
    ips: InvestmentPolicy = field(default_factory=mock_investment_policy)
    planner: InvestmentPlanner = field(default_factory=DeterministicInvestmentPlanner)
    graph_runtime: str = field(init=False)
    _status_callback: Callable[[TraceEvent], None] | None = field(
        default=None,
        init=False,
        repr=False,
    )

    def __post_init__(self) -> None:
        self.graph = self._build_graph()

    def run(self, query: str, *, status_callback=None) -> InvestmentAgentState:
        state = InvestmentAgentState(
            run_id=f"investment_run_{uuid4().hex[:12]}",
            user_query=query,
        )
        self._status_callback = status_callback
        try:
            result = self.graph.invoke(state)
            if isinstance(result, InvestmentAgentState):
                return result
            return InvestmentAgentState.model_validate(result)
        except Exception as exc:
            self._emit_error(state, exc, status="investment_agent_error")
            raise
        finally:
            self._status_callback = None

    def close(self) -> None:
        close = getattr(self.portfolio_agent, "close", None)
        if callable(close):
            close()

    def _build_graph(self):
        self.graph_runtime = "langgraph_state_graph"
        graph = StateGraph(InvestmentAgentState)
        graph.add_node("load_ips", self._load_ips_node)
        graph.add_node("plan_investment", self._plan_investment_node)
        graph.add_node("validate_plan", self._validate_plan_node)
        graph.add_node("call_portfolio", self._call_portfolio_node)
        graph.add_node("route_sentiment", self._route_sentiment_node)
        graph.add_node("call_sentiment", self._call_sentiment_node)
        graph.add_node("synthesize", self._synthesize_node)
        graph.add_node("guardrail", self._guardrail_node)
        graph.add_node("final_output", self._final_output_node)
        graph.set_entry_point("load_ips")
        graph.add_edge("load_ips", "plan_investment")
        graph.add_edge("plan_investment", "validate_plan")
        graph.add_edge("validate_plan", "call_portfolio")
        graph.add_edge("call_portfolio", "route_sentiment")
        graph.add_edge("route_sentiment", "call_sentiment")
        graph.add_edge("call_sentiment", "synthesize")
        graph.add_edge("synthesize", "guardrail")
        graph.add_edge("guardrail", "final_output")
        graph.add_edge("final_output", END)
        return graph.compile()

    def _load_ips_node(self, state: InvestmentAgentState) -> InvestmentAgentState:
        self._emit(state, "loading_policy", "Loading the Investment Policy Statement.")
        state.ips = self.ips
        state.portfolio_id = self.ips.portfolio_id
        return state

    def _plan_investment_node(self, state: InvestmentAgentState) -> InvestmentAgentState:
        assert state.ips is not None
        self._emit(
            state,
            "planning_investment",
            "Planning the investment query with the structured Investment planner.",
            phase="investment_planner",
        )
        state.investment_plan = self.planner.plan(state.user_query, state.ips)
        state.query_plan = investment_plan_to_query_plan(state.investment_plan)
        state.mode = state.investment_plan.mode
        self._emit(
            state,
            "investment_plan_ready",
            "Investment planner produced a bounded plan.",
            phase="investment_planner",
            metadata={
                "mode": state.investment_plan.mode,
                "needs_portfolio_agent": state.investment_plan.needs_portfolio_agent,
                "needs_sentiment_agent": state.investment_plan.needs_sentiment_agent,
                "portfolio_task_intent": (
                    state.investment_plan.portfolio_request.task_intent
                    if state.investment_plan.portfolio_request
                    else None
                ),
                "asset_hint_count": len(state.investment_plan.logical_asset_hints),
                "answer_constraint_count": len(state.investment_plan.answer_constraints),
            },
        )
        return state

    def _validate_plan_node(self, state: InvestmentAgentState) -> InvestmentAgentState:
        assert state.investment_plan is not None
        self._emit(
            state,
            "validating_investment_plan",
            "Validating structured planner output before subagent calls.",
            phase="portfolio_request_validator",
        )
        try:
            validation = validate_investment_plan(state.investment_plan)
        except InvestmentPlanValidationError as exc:
            self._emit(
                state,
                "investment_plan_rejected",
                "Investment planner output was rejected before subagent calls.",
                event_type="error",
                phase="portfolio_request_validator",
                error_type=exc.__class__.__name__,
                error_message=str(exc),
            )
            raise
        state.warnings = [*state.warnings, *validation.warnings]
        self._emit(
            state,
            "investment_plan_validated",
            "Investment planner output passed deterministic validation.",
            phase="portfolio_request_validator",
            metadata={"warning_count": len(validation.warnings), "result": "valid"},
        )
        return state

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
        result = self.portfolio_agent.run(
            state.query_plan.portfolio_task.source_query,
            state.ips,
            portfolio_task=state.query_plan.portfolio_task,
            portfolio_request=(
                state.investment_plan.portfolio_request if state.investment_plan else None
            ),
        )
        state.portfolio_packet = adapt_portfolio_result_to_evidence_packet(result, state.ips)
        self._emit_portfolio_evidence_trace(state, result)
        self._emit_portfolio_tool_trace(state, state.portfolio_packet.tool_calls)
        return state

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
            metadata=metadata or {},
            error_type=error_type,
            error_message=error_message,
        ))
        state.status_events.append(event)
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

    def _emit_portfolio_tool_trace(
        self,
        state: InvestmentAgentState,
        tool_calls: list[str],
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
            )

    def _emit_portfolio_evidence_trace(
        self,
        state: InvestmentAgentState,
        result: PortfolioAgentResult,
    ) -> None:
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
                },
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
        )


def classify_investment_query(query: str) -> InvestmentQueryPlan:
    planner = DeterministicInvestmentPlanner()
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
) -> InvestmentAgent:
    return InvestmentAgent(
        portfolio_agent=build_default_portfolio_agent(
            env_file=env_file,
            from_report=from_report,
            db_path=db_path,
            llm_provider=llm_provider,
            evaluator=portfolio_evaluator,
            gateway=gateway,
            gateway_mode=gateway_mode,
        ),
        sentiment_agent=SentimentAgentStub(),
        ips=ips or mock_investment_policy(),
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
    tickers = _dedupe([*task.tickers, *candidate_tickers, *_extract_tickers(query)])
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
    missing = []
    if state.portfolio_packet:
        missing.extend(state.portfolio_packet.warnings)
    if state.sentiment_packet is not None and state.sentiment_packet.retrieval_status in {
        "not_implemented",
        "missing_corpus",
    }:
        missing.append("Sentiment Agent GraphRAG retrieval is not implemented.")
        missing.extend(state.sentiment_packet.data_quality.missing_fields)
    return _dedupe(missing)


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


def _extract_tickers(query: str) -> list[str]:
    return extract_ticker_strings(query)


def _dedupe(values: list[str]) -> list[str]:
    seen = set()
    result = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
