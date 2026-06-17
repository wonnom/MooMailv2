from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable, Protocol
from uuid import uuid4

from langgraph.graph import END, StateGraph

from moomail_finance_ai.mocks import mock_investment_policy
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
from moomail_finance_ai.v2_guardrails import review_v2_report
from moomail_finance_ai.sentiment_agent_stub import V2SentimentAgentStub
from moomail_finance_ai.v2_trace import sanitize_trace_event
from moomail_finance_ai.v2_schemas import (
    InvestmentAgentState,
    InvestmentQueryPlan,
    PortfolioContextPlan,
    PortfolioTask,
    SentimentCandidate,
    SentimentPacket,
    SentimentTask,
    SynthesisInput,
    TraceEvent,
    V2PortfolioAgentPacket,
)


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
HISTORY_TERMS = ("what changed", "changed", "history", "growth", "performance")
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
US_EQUITY_EXCHANGES = {"US", "NASDAQ", "NYSE", "AMEX", "ARCA", "BATS"}


class PortfolioAgentProtocol(Protocol):
    def run(
        self,
        query: str,
        ips: InvestmentPolicy,
        *,
        status_callback=None,
        portfolio_task: PortfolioTask | None = None,
    ) -> PortfolioAgentResult: ...


class SentimentAgentProtocol(Protocol):
    def run(self, task: SentimentTask) -> SentimentPacket: ...


@dataclass
class V2InvestmentAgent:
    portfolio_agent: PortfolioAgentProtocol
    sentiment_agent: SentimentAgentProtocol = field(default_factory=V2SentimentAgentStub)
    ips: InvestmentPolicy = field(default_factory=mock_investment_policy)
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
            run_id=f"v2_run_{uuid4().hex[:12]}",
            user_query=query,
        )
        self._status_callback = status_callback
        try:
            result = self.graph.invoke(state)
            if isinstance(result, InvestmentAgentState):
                return result
            return InvestmentAgentState.model_validate(result)
        except Exception as exc:
            self._emit_error(state, exc, status="v2_agent_error")
            raise
        finally:
            self._status_callback = None

    def _build_graph(self):
        self.graph_runtime = "langgraph_state_graph"
        graph = StateGraph(InvestmentAgentState)
        graph.add_node("classify_query", self._classify_query_node)
        graph.add_node("load_ips", self._load_ips_node)
        graph.add_node("call_portfolio", self._call_portfolio_node)
        graph.add_node("route_sentiment", self._route_sentiment_node)
        graph.add_node("call_sentiment", self._call_sentiment_node)
        graph.add_node("synthesize", self._synthesize_node)
        graph.add_node("guardrail", self._guardrail_node)
        graph.add_node("final_output", self._final_output_node)
        graph.set_entry_point("classify_query")
        graph.add_edge("classify_query", "load_ips")
        graph.add_edge("load_ips", "call_portfolio")
        graph.add_edge("call_portfolio", "route_sentiment")
        graph.add_edge("route_sentiment", "call_sentiment")
        graph.add_edge("call_sentiment", "synthesize")
        graph.add_edge("synthesize", "guardrail")
        graph.add_edge("guardrail", "final_output")
        graph.add_edge("final_output", END)
        return graph.compile()

    def _classify_query_node(self, state: InvestmentAgentState) -> InvestmentAgentState:
        self._emit(state, "classifying_query", "Classifying the V2 investment query.")
        state.query_plan = classify_investment_query(state.user_query)
        state.mode = state.query_plan.mode
        self._emit(
            state,
            "planning_subagent_calls",
            "Planning bounded subagent calls from the structured query plan.",
            metadata={
                "phase": "planning",
                "result": state.query_plan.route_reason,
            },
        )
        return state

    def _load_ips_node(self, state: InvestmentAgentState) -> InvestmentAgentState:
        self._emit(state, "loading_policy", "Loading the V2 Investment Policy Statement.")
        state.ips = self.ips
        state.portfolio_id = self.ips.portfolio_id
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
            "Calling the V1 Portfolio Agent through the V2 adapter.",
            event_type="subagent_call",
            subagent="portfolio_agent",
        )
        result = self.portfolio_agent.run(
            state.query_plan.portfolio_task.source_query,
            state.ips,
            portfolio_task=state.query_plan.portfolio_task,
        )
        state.portfolio_packet = adapt_portfolio_result_to_v2(result, state.ips)
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
            "Calling the V2 Sentiment Agent stub.",
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
        self._emit(state, "synthesizing_report", "Synthesizing the V2 Investment Agent report.")
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
        self._emit(state, "checking_guardrails", "Running V2 output guardrails.")
        state.guardrail_review = review_v2_report(state)
        self._emit(
            state,
            (
                "guardrails_passed"
                if state.guardrail_review.passed
                else "guardrails_blocked"
            ),
            "V2 output guardrails completed.",
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
        self._emit(state, "complete", "V2 Investment Agent run complete.")
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
        error_type: str | None = None,
        error_message: str | None = None,
    ) -> None:
        event = sanitize_trace_event(TraceEvent(
            event_type=event_type,
            run_id=state.run_id,
            status=status,
            message=message,
            timestamp=datetime.now(UTC),
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
            "V2 Investment Agent run failed.",
            event_type="error",
            subagent="investment_agent",
            error_type=exc.__class__.__name__,
            error_message=str(exc) or exc.__class__.__name__,
            metadata={"error_location": "v2_investment_agent.run"},
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
            )


def classify_investment_query(query: str) -> InvestmentQueryPlan:
    lowered = query.lower()
    tickers = _extract_tickers(query)
    explicit_sentiment = _contains_any(lowered, SENTIMENT_TERMS)
    needs_portfolio = True
    needs_sentiment = False

    if _contains_any(lowered, TRADE_EXECUTION_TERMS):
        return InvestmentQueryPlan(
            mode="unsupported",
            needs_portfolio_agent=False,
            needs_sentiment_agent=False,
            route_reason="Trade execution requests are outside the allowed V2 scope.",
            plan_warnings=["Trade execution is not supported."],
        )

    if _contains_any(lowered, COMPARE_TERMS):
        mode = "compare"
    elif _contains_any(lowered, HISTORY_TERMS):
        mode = "what_changed"
    elif _contains_any(lowered, RISK_TERMS):
        mode = "risk_check"
    elif explicit_sentiment:
        mode = "deep_dive"
    elif _contains_any(lowered, PORTFOLIO_FACT_TERMS):
        mode = "portfolio_fact"
    else:
        mode = "review"

    if mode in {"review", "deep_dive", "compare", "risk_check"}:
        needs_sentiment = True
    if explicit_sentiment:
        needs_sentiment = True

    portfolio_task = PortfolioTask(
        task_type=_portfolio_task_type_for_mode(mode),
        source_query=query,
        requested_tickers=tickers,
        history_window="90d" if mode == "what_changed" else "30d",
        required_outputs=_required_portfolio_outputs(mode),
        persistence_mode="auto",
        focus_areas=_focus_areas_for_mode(mode, explicit_sentiment),
    )
    sentiment_task = None
    if needs_sentiment:
        sentiment_task = SentimentTask(
            tickers=tickers,
            themes=_sentiment_themes_for_query(lowered),
            key_questions=[query],
            reason=_sentiment_reason(mode, explicit_sentiment),
        )
    return InvestmentQueryPlan(
        mode=mode,
        needs_portfolio_agent=needs_portfolio,
        needs_sentiment_agent=needs_sentiment,
        portfolio_task=portfolio_task,
        sentiment_task=sentiment_task,
        route_reason=_route_reason(mode, needs_sentiment),
    )


def adapt_portfolio_result_to_v2(
    result: PortfolioAgentResult,
    ips: InvestmentPolicy,
) -> V2PortfolioAgentPacket:
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
    return V2PortfolioAgentPacket(
        portfolio_id=result.portfolio_id,
        context_plan=context_plan,
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
            title="Use V2 as an orchestration check, not a trading engine",
            rationale=(
                "The V2 Investment Agent has routed the query through portfolio evidence"
                " and any available sentiment stub output, while keeping trade execution"
                " out of scope."
            ),
            constraints=[
                (
                    "No trade placement, order entry, exact share-count instruction, "
                    "or execution path."
                ),
                "Sentiment output is limited to the V2 stub until GraphRAG is implemented.",
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
            "Task 2 uses a thin V2 Investment Agent supervisor with a V1 Portfolio Agent adapter.",
            "Neo4j GraphRAG and Pinecone memory are intentionally not connected in Task 2.",
        ],
        citations=[],
        disclaimer=(
            "This is investment analysis for personal decision support, not licensed "
            "financial advice."
        ),
    )


def build_default_v2_investment_agent(
    *,
    env_file: str | Path | None = "config/local.env",
    from_report: str | Path | None = "reports/opend/field-report.json",
    db_path: str | Path = "data/portfolio-history.sqlite",
    llm_provider: str | None = None,
    portfolio_evaluator: PortfolioEvaluator | None = None,
    ips: InvestmentPolicy | None = None,
) -> V2InvestmentAgent:
    return V2InvestmentAgent(
        portfolio_agent=build_default_portfolio_agent(
            env_file=env_file,
            from_report=from_report,
            db_path=db_path,
            llm_provider=llm_provider,
            evaluator=portfolio_evaluator,
        ),
        sentiment_agent=V2SentimentAgentStub(),
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
        return "Portfolio Agent returned a V2 packet without a V1 base packet."
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
        missing.append("Sentiment Agent GraphRAG retrieval is not implemented in V2.")
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
    }.get(mode, "V2 Portfolio Review")


def _final_report_mode(mode: str) -> str:
    if mode in {"risk_check", "what_changed", "deep_dive", "compare", "review"}:
        return mode
    return "review"


def _portfolio_task_type_for_mode(mode: str) -> str:
    if mode == "portfolio_fact":
        return "portfolio_fact"
    if mode in {"risk_check", "what_changed", "deep_dive", "compare", "unsupported"}:
        return mode
    return "full_review"


def _required_portfolio_outputs(mode: str) -> list[str]:
    if mode == "portfolio_fact":
        return ["snapshot", "allocation", "effective_cash"]
    if mode == "what_changed":
        return ["snapshot", "performance", "history_context", "sentiment_candidates"]
    if mode == "risk_check":
        return ["snapshot", "risk", "candidate_issues", "sentiment_candidates"]
    return [
        "snapshot",
        "allocation",
        "performance",
        "risk",
        "effective_cash",
        "candidate_issues",
        "sentiment_candidates",
        "history_context",
    ]


def _focus_areas_for_mode(mode: str, explicit_sentiment: bool) -> list[str]:
    focus = [mode]
    if explicit_sentiment:
        focus.append("sentiment")
    return focus


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


def _sentiment_reason(mode: str, explicit_sentiment: bool) -> str:
    if explicit_sentiment:
        return "User asked for sentiment, research, news, outlook, or thesis context."
    return f"Mode {mode} benefits from material-holding sentiment context."


def _route_reason(mode: str, needs_sentiment: bool) -> str:
    if needs_sentiment:
        return f"Routed as {mode}; Portfolio Agent plus Sentiment Agent stub are needed."
    return f"Routed as {mode}; portfolio-only evidence is enough."


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in text for term in terms)


def _extract_tickers(query: str) -> list[str]:
    tickers = []
    for match in re.finditer(r"\b(?:US\.)?([A-Z]{1,5})(?:\.[A-Z]{1,4})?\b", query):
        ticker = match.group(1)
        if ticker in {"USD", "ETF", "AI", "CEO", "CFO", "IPO"}:
            continue
        tickers.append(ticker)
    return _dedupe(tickers)


def _dedupe(values: list[str]) -> list[str]:
    seen = set()
    result = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
