from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
import traceback
from typing import Any

from moomail_finance_ai.full_agent import build_default_full_agent
from moomail_finance_ai.mocks import mock_investment_policy
from moomail_finance_ai.portfolio_agent import (
    PortfolioAgentResult,
    PortfolioEvaluator,
    build_default_portfolio_agent,
)
from moomail_finance_ai.schemas import AgentState, StatusEvent
from moomail_finance_ai.v2_investment_agent import V2InvestmentAgent
from moomail_finance_ai.v2_investment_agent import build_default_v2_investment_agent
from moomail_finance_ai.v2_schemas import InvestmentAgentState as V2InvestmentAgentState
from moomail_finance_ai.v2_schemas import TraceEvent
from moomail_finance_ai.v2_trace import sanitize_public_text, trace_event_to_public_dict


class ChatService:
    def __init__(
        self,
        *,
        from_report: str | Path | None = "reports/opend/field-report.json",
        db_path: str | Path = "data/portfolio-history.sqlite",
        memory_path: str | Path = "data/chat-investment-memory.json",
        env_file: str | Path | None = "config/local.env",
        llm_provider: str | None = None,
        portfolio_evaluator: PortfolioEvaluator | None = None,
        v2_investment_agent: V2InvestmentAgent | None = None,
        default_agent: str = "investment",
    ):
        self.from_report = from_report
        self.db_path = db_path
        self.memory_path = memory_path
        self.env_file = env_file
        self.llm_provider = llm_provider
        self.portfolio_evaluator = portfolio_evaluator
        self.v2_investment_agent = v2_investment_agent
        self.default_agent = default_agent

    def run(
        self,
        query: str,
        *,
        status_callback=None,
        agent: str | None = None,
    ) -> AgentState | PortfolioAgentResult | V2InvestmentAgentState:
        selected_agent = agent or self.default_agent
        if selected_agent == "portfolio":
            portfolio_agent = build_default_portfolio_agent(
                env_file=self.env_file,
                from_report=self.from_report,
                db_path=self.db_path,
                llm_provider=self.llm_provider,
                evaluator=self.portfolio_evaluator,
            )
            return portfolio_agent.run(
                query,
                mock_investment_policy(),
                status_callback=status_callback,
            )
        if selected_agent in {"investment_v2", "v2_investment"}:
            v2_agent = self.v2_investment_agent or build_default_v2_investment_agent(
                env_file=self.env_file,
                from_report=self.from_report,
                db_path=self.db_path,
                llm_provider=self.llm_provider,
                portfolio_evaluator=self.portfolio_evaluator,
            )
            return v2_agent.run(query, status_callback=status_callback)
        if selected_agent != "investment":
            raise ValueError(f"Unsupported chat agent: {selected_agent}")
        agent = build_default_full_agent(
            from_report=self.from_report,
            db_path=self.db_path,
            memory_path=self.memory_path,
        )
        return agent.run(query, status_callback=status_callback)


def chat_response(
    state: AgentState | PortfolioAgentResult | V2InvestmentAgentState,
) -> dict[str, Any]:
    if isinstance(state, V2InvestmentAgentState):
        return v2_state_response(state)
    if isinstance(state, PortfolioAgentResult):
        return portfolio_agent_response(state)
    return state_response(state)


def v2_state_response(state: V2InvestmentAgentState) -> dict[str, Any]:
    return {
        "agent_type": "investment_agent_v2",
        "run_id": state.run_id,
        "mode": state.mode,
        "status_events": [trace_event_to_public_dict(event) for event in state.status_events],
        "query_plan": state.query_plan.model_dump(mode="json") if state.query_plan else None,
        "portfolio_packet": (
            state.portfolio_packet.model_dump(mode="json") if state.portfolio_packet else None
        ),
        "sentiment_packet": (
            state.sentiment_packet.model_dump(mode="json") if state.sentiment_packet else None
        ),
        "synthesis": state.synthesis.model_dump(mode="json") if state.synthesis else None,
        "final_report": state.final_report.model_dump(mode="json") if state.final_report else None,
        "guardrail_result": (
            state.guardrail_review.model_dump(mode="json") if state.guardrail_review else None
        ),
        "audit_record": None,
    }


def state_response(state: AgentState) -> dict[str, Any]:
    return {
        "agent_type": "investment_agent",
        "run_id": state.run_id,
        "mode": state.mode,
        "status_events": [event.model_dump(mode="json") for event in state.status_events],
        "final_report": state.final_report.model_dump(mode="json") if state.final_report else None,
        "guardrail_result": state.guardrail_result.model_dump(mode="json")
        if state.guardrail_result
        else None,
        "audit_record": state.audit_record.model_dump(mode="json") if state.audit_record else None,
    }


def portfolio_agent_response(result: PortfolioAgentResult) -> dict[str, Any]:
    return {
        "agent_type": "portfolio_agent",
        "run_id": result.run_id,
        "mode": "portfolio",
        "status_events": [event.model_dump(mode="json") for event in result.status_events],
        "portfolio_agent_result": result.model_dump(mode="json"),
        "final_report": {
            "title": "Portfolio Agent Evaluation",
            "mode": "portfolio",
            "as_of": result.snapshot.as_of.isoformat(),
            "summary": result.evaluation.summary,
            "portfolio_snapshot": result.snapshot.model_dump(mode="json"),
            "portfolio_analysis": {
                "allocation": {
                    key: [item.model_dump(mode="json") for item in values]
                    for key, values in result.portfolio_packet.allocation.items()
                },
                "performance": result.portfolio_packet.performance.model_dump(mode="json"),
                "risk": result.portfolio_packet.risk.model_dump(mode="json"),
                "candidate_issues": [
                    issue.model_dump(mode="json")
                    for issue in result.portfolio_packet.candidate_issues
                ],
                "evaluation": result.evaluation.model_dump(mode="json"),
                "metrics": [metric.model_dump(mode="json") for metric in result.metrics],
                "effective_cash": result.effective_cash.model_dump(mode="json"),
                "storage_result": result.storage_result,
                "metrics_storage_result": result.metrics_storage_result,
                "history_status": result.history_status,
                "history_context": result.history_context.model_dump(mode="json"),
                "tool_calls": result.tool_calls,
            },
            "sentiment_analysis": {},
            "recommendations": [],
            "missing_data": result.warnings,
            "citations": [],
        },
        "guardrail_result": {
            "passed": True,
            "checks": [
                {
                    "check": "portfolio_agent_scope",
                    "passed": True,
                    "message": "Portfolio Agent returned portfolio-only analysis.",
                }
            ],
        },
        "audit_record": None,
    }


def status_event_payload(event: StatusEvent | Any) -> dict[str, Any]:
    if isinstance(event, TraceEvent):
        return {"type": "status", "event": trace_event_to_public_dict(event)}
    return {"type": "status", "event": event.model_dump(mode="json")}


def error_event_payload(exc: BaseException) -> dict[str, Any]:
    message = str(exc) or exc.__class__.__name__
    return {
        "type": "error",
        "error": {
            "error_type": exc.__class__.__name__,
            "message": sanitize_public_text(message),
            "timestamp": datetime.now(UTC).isoformat(),
            "traceback": [
                sanitize_public_text(line)
                for line in traceback.format_exception(type(exc), exc, exc.__traceback__)
            ],
        },
    }


def stream_payloads(
    service: ChatService,
    query: str,
    *,
    agent: str | None = None,
) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []

    def emit(event: StatusEvent) -> None:
        payloads.append(status_event_payload(event))

    try:
        state = service.run(query, agent=agent, status_callback=emit)
    except Exception as exc:
        payloads.append(error_event_payload(exc))
        return payloads
    payloads.append({"type": "final", "state": chat_response(state)})
    return payloads
