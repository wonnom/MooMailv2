from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

from pydantic import Field

from moomail_finance_ai.config import load_opend_config
from moomail_finance_ai.llm import TextLLMClient, build_llm_client_from_env
from moomail_finance_ai.mcp.finance_metrics_mcp import (
    SERVER_NAME as FINANCE_METRICS_SERVER,
    build_finance_metrics_mcp_module,
)
from moomail_finance_ai.mcp.opend_mcp import SERVER_NAME as OPEND_SERVER, build_opend_mcp_module
from moomail_finance_ai.mcp.portfolio_sql_mcp import (
    SERVER_NAME as PORTFOLIO_SQL_SERVER,
    build_portfolio_sql_mcp_module,
)
from moomail_finance_ai.mcp.registry import MCPModule
from moomail_finance_ai.metrics import MetricResult
from moomail_finance_ai.mocks import mock_investment_policy
from moomail_finance_ai.opend import OpenDFieldReport
from moomail_finance_ai.opend_portfolio import build_portfolio_agent_packet
from moomail_finance_ai.schemas import (
    InvestmentPolicy,
    PortfolioAgentPacket,
    PortfolioSnapshot,
    StrictModel,
    StatusEvent,
)


class PortfolioEvaluation(StrictModel):
    summary: str
    strengths: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    ips_mismatches: list[str] = Field(default_factory=list)
    history_observations: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    llm_model: str | None = None
    warnings: list[str] = Field(default_factory=list)


class PortfolioAgentResult(StrictModel):
    run_id: str
    portfolio_id: str
    snapshot: PortfolioSnapshot
    portfolio_packet: PortfolioAgentPacket
    metrics: list[MetricResult]
    storage_result: dict[str, Any]
    metrics_storage_result: dict[str, Any]
    history_status: dict[str, Any]
    evaluation: PortfolioEvaluation
    tool_calls: list[str]
    status_events: list[StatusEvent] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class PortfolioEvaluator(Protocol):
    def evaluate(
        self,
        *,
        query: str,
        ips: InvestmentPolicy,
        snapshot: PortfolioSnapshot,
        portfolio_packet: PortfolioAgentPacket,
        metrics: list[MetricResult],
        storage_result: dict[str, Any],
        history_status: dict[str, Any],
    ) -> PortfolioEvaluation: ...


@dataclass
class LLMPortfolioEvaluator:
    llm: TextLLMClient

    @classmethod
    def from_env(
        cls,
        *,
        provider: str | None = None,
        env_file: str | Path | None = "config/local.env",
    ) -> LLMPortfolioEvaluator:
        return cls(build_llm_client_from_env(provider=provider, env_file=env_file))

    def evaluate(
        self,
        *,
        query: str,
        ips: InvestmentPolicy,
        snapshot: PortfolioSnapshot,
        portfolio_packet: PortfolioAgentPacket,
        metrics: list[MetricResult],
        storage_result: dict[str, Any],
        history_status: dict[str, Any],
    ) -> PortfolioEvaluation:
        text = self.llm.generate_text(
            _evaluation_prompt(
                query=query,
                ips=ips,
                snapshot=snapshot,
                portfolio_packet=portfolio_packet,
                metrics=metrics,
                storage_result=storage_result,
                history_status=history_status,
            ),
            system_instruction=PORTFOLIO_EVALUATOR_SYSTEM_PROMPT,
            max_output_tokens=4096,
            temperature=0.1,
        )
        model = getattr(getattr(self.llm, "config", None), "model", None)
        return _evaluation_from_text(text, model=model)


@dataclass
class MCPPortfolioAgent:
    opend_mcp: MCPModule
    finance_metrics_mcp: MCPModule
    portfolio_sql_mcp: MCPModule
    evaluator: PortfolioEvaluator
    base_currency: str = "USD"
    min_snapshots_for_history: int = 2
    tool_calls: list[str] = field(default_factory=list)

    def run(self, query: str, ips: InvestmentPolicy, *, status_callback=None) -> PortfolioAgentResult:
        run_id = f"portfolio_run_{uuid4().hex[:12]}"
        self.tool_calls = []
        status_events: list[StatusEvent] = []
        emit = lambda status, message: _emit(status_events, run_id, status, message, status_callback)
        emit("initializing_portfolio_agent", "Preparing MCP modules for portfolio analysis.")
        self._call(PORTFOLIO_SQL_SERVER, self.portfolio_sql_mcp, "portfolio_sql_initialize", {})
        emit("retrieving_opend_portfolio", "Reading current portfolio context from OpenD MCP.")
        context = self._call(
            OPEND_SERVER,
            self.opend_mcp,
            "opend_get_portfolio_context",
            {"portfolio_id": ips.portfolio_id, "base_currency": self.base_currency},
        )
        snapshot = PortfolioSnapshot.model_validate(context["snapshot"])
        source_report = OpenDFieldReport.model_validate(context["source_report"])
        snapshot_json = snapshot.model_dump(mode="json")
        ips_json = ips.model_dump(mode="json")

        emit("calculating_metrics", "Calculating deterministic portfolio metrics through MCP.")
        metric_rows = self._call(
            FINANCE_METRICS_SERVER,
            self.finance_metrics_mcp,
            "calculate_snapshot_metrics",
            {"snapshot": snapshot_json, "ips": ips_json},
        )
        metrics = [MetricResult.model_validate(row) for row in metric_rows]

        emit("updating_portfolio_history", "Applying idempotent daily snapshot storage policy.")
        storage_result = self._call(
            PORTFOLIO_SQL_SERVER,
            self.portfolio_sql_mcp,
            "portfolio_sql_store_daily_snapshot_if_needed",
            {
                "snapshot": snapshot_json,
                "source_report": source_report.model_dump(mode="json"),
            },
        )
        metrics_storage_result = _metrics_storage_skip_result(storage_result)
        if storage_result.get("status") == "inserted" and storage_result.get("snapshot_id"):
            metrics_storage_result = self._call(
                PORTFOLIO_SQL_SERVER,
                self.portfolio_sql_mcp,
                "portfolio_sql_store_metrics",
                {
                    "snapshot_id": storage_result["snapshot_id"],
                    "metrics": [metric.model_dump(mode="json") for metric in metrics],
                },
            )

        emit("reading_history_status", "Reading portfolio history status from SQL MCP.")
        history_status = self._call(
            PORTFOLIO_SQL_SERVER,
            self.portfolio_sql_mcp,
            "portfolio_sql_history_status",
            {
                "portfolio_id": ips.portfolio_id,
                "now": snapshot.as_of.isoformat(),
                "min_snapshots_for_history": self.min_snapshots_for_history,
            },
        )
        portfolio_packet = _portfolio_packet_with_history(
            build_portfolio_agent_packet(snapshot, ips, source_report),
            history_status,
        )
        emit("evaluating_portfolio", "Running the LLM portfolio-only evaluator.")
        evaluation = self.evaluator.evaluate(
            query=query,
            ips=ips,
            snapshot=snapshot,
            portfolio_packet=portfolio_packet,
            metrics=metrics,
            storage_result=storage_result,
            history_status=history_status,
        )
        emit("complete", "Portfolio Agent run complete.")
        return PortfolioAgentResult(
            run_id=run_id,
            portfolio_id=snapshot.portfolio_id,
            snapshot=snapshot,
            portfolio_packet=portfolio_packet,
            metrics=metrics,
            storage_result=storage_result,
            metrics_storage_result=metrics_storage_result,
            history_status=history_status,
            evaluation=evaluation,
            tool_calls=list(self.tool_calls),
            status_events=status_events,
            warnings=_result_warnings(portfolio_packet, history_status, evaluation),
        )

    def _call(
        self,
        server_name: str,
        module: MCPModule,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> Any:
        self.tool_calls.append(f"{server_name}:{tool_name}")
        return module.call_tool(tool_name, arguments).structured_content


def build_default_portfolio_agent(
    *,
    env_file: str | Path | None = "config/local.env",
    from_report: str | Path | None = None,
    db_path: str | Path = "data/portfolio-history.sqlite",
    llm_provider: str | None = None,
    evaluator: PortfolioEvaluator | None = None,
) -> MCPPortfolioAgent:
    config = load_opend_config(env_file=env_file)
    return MCPPortfolioAgent(
        opend_mcp=build_opend_mcp_module(config=config, env_file=env_file, from_report=from_report),
        finance_metrics_mcp=build_finance_metrics_mcp_module(),
        portfolio_sql_mcp=build_portfolio_sql_mcp_module(db_path=db_path),
        evaluator=evaluator or LLMPortfolioEvaluator.from_env(
            provider=llm_provider,
            env_file=env_file,
        ),
        base_currency=config.base_currency,
    )


def build_default_portfolio_agent_with_mock_policy(
    *,
    env_file: str | Path | None = "config/local.env",
    from_report: str | Path | None = None,
    db_path: str | Path = "data/portfolio-history.sqlite",
    llm_provider: str | None = None,
    evaluator: PortfolioEvaluator | None = None,
) -> tuple[MCPPortfolioAgent, InvestmentPolicy]:
    return (
        build_default_portfolio_agent(
            env_file=env_file,
            from_report=from_report,
            db_path=db_path,
            llm_provider=llm_provider,
            evaluator=evaluator,
        ),
        mock_investment_policy(),
    )


PORTFOLIO_EVALUATOR_SYSTEM_PROMPT = """
You are the Portfolio Agent evaluator for a personal finance AI.
Use only the portfolio snapshot, deterministic metrics, SQL history status, and Investment Policy
Statement supplied by the tool pipeline. Do not use market news, sentiment, external outlook, or
unsupported facts. Do not recommend trade placement, order entry, exact share counts, or execution
instructions. Return a compact JSON object only, with no markdown fences and no prose outside JSON.
Use these keys exactly: summary, strengths, risks, ips_mismatches, history_observations,
open_questions. Keep each list to at most 4 items and each item under 180 characters.
""".strip()


def _evaluation_prompt(
    *,
    query: str,
    ips: InvestmentPolicy,
    snapshot: PortfolioSnapshot,
    portfolio_packet: PortfolioAgentPacket,
    metrics: list[MetricResult],
    storage_result: dict[str, Any],
    history_status: dict[str, Any],
) -> str:
    cash_value = sum(cash.amount for cash in snapshot.cash)
    cash_equivalent_holdings = [
        holding for holding in snapshot.holdings if holding.asset_type == "cash_equivalent"
    ]
    cash_equivalent_value = sum(holding.market_value for holding in cash_equivalent_holdings)
    context = {
        "user_query": query,
        "investment_policy": ips.model_dump(mode="json"),
        "snapshot_summary": {
            "portfolio_id": snapshot.portfolio_id,
            "as_of": snapshot.as_of.isoformat(),
            "base_currency": snapshot.base_currency,
            "total_value": snapshot.total_value.model_dump(mode="json"),
            "cash": [cash.model_dump(mode="json") for cash in snapshot.cash],
            "effective_cash": {
                "cash_value": cash_value,
                "cash_equivalent_value": cash_equivalent_value,
                "effective_cash_value": cash_value + cash_equivalent_value,
                "effective_cash_weight": (
                    0.0
                    if snapshot.total_value.amount == 0
                    else (cash_value + cash_equivalent_value) / snapshot.total_value.amount
                ),
                "cash_equivalent_holdings": [
                    {
                        "ticker": holding.ticker,
                        "name": holding.name,
                        "market_value": holding.market_value,
                        "portfolio_weight": holding.portfolio_weight,
                    }
                    for holding in cash_equivalent_holdings
                ],
            },
            "holdings": [
                {
                    "ticker": holding.ticker,
                    "name": holding.name,
                    "asset_type": holding.asset_type,
                    "exchange": holding.exchange,
                    "currency": holding.currency,
                    "quantity": holding.quantity,
                    "market_price": holding.market_price,
                    "market_value": holding.market_value,
                    "portfolio_weight": holding.portfolio_weight,
                    "unrealized_pnl": holding.unrealized_pnl,
                }
                for holding in snapshot.holdings
            ],
            "data_quality": snapshot.data_quality.model_dump(mode="json"),
        },
        "deterministic_metrics": [metric.model_dump(mode="json") for metric in metrics],
        "candidate_issues": [
            issue.model_dump(mode="json") for issue in portfolio_packet.candidate_issues
        ],
        "storage_result": storage_result,
        "history_status": history_status,
    }
    return (
        "Evaluate the portfolio-only evidence below. Keep the response concise and structured.\n\n"
        f"{json.dumps(context, sort_keys=True)}"
    )


def _evaluation_from_text(text: str, *, model: str | None) -> PortfolioEvaluation:
    try:
        payload = _extract_json_object(text)
        evaluation = PortfolioEvaluation.model_validate(payload)
        return evaluation.model_copy(update={"llm_model": model})
    except Exception as exc:
        recovered = _recover_evaluation_payload(text)
        if recovered is not None:
            evaluation = PortfolioEvaluation.model_validate(recovered)
            warnings = list(evaluation.warnings)
            warnings.append(
                f"Portfolio evaluator returned malformed JSON and was partially recovered: {exc}"
            )
            return evaluation.model_copy(update={"llm_model": model, "warnings": warnings})
        return PortfolioEvaluation(
            summary=_fallback_evaluation_summary(text),
            llm_model=model,
            warnings=[f"Portfolio evaluator returned non-JSON output: {exc}"],
        )


def _extract_json_object(text: str) -> dict[str, Any]:
    stripped = _strip_markdown_fence(text)
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("no JSON object found")
    payload = json.loads(stripped[start : end + 1])
    if not isinstance(payload, dict):
        raise ValueError("JSON output is not an object")
    return payload


def _recover_evaluation_payload(text: str) -> dict[str, Any] | None:
    stripped = _strip_markdown_fence(text)
    summary = _recover_json_string_field(stripped, "summary")
    if summary is None:
        return None
    return {
        "summary": summary,
        "strengths": _recover_json_string_array(stripped, "strengths"),
        "risks": _recover_json_string_array(stripped, "risks"),
        "ips_mismatches": _recover_json_string_array(stripped, "ips_mismatches"),
        "history_observations": _recover_json_string_array(stripped, "history_observations"),
        "open_questions": _recover_json_string_array(stripped, "open_questions"),
    }


def _recover_json_string_field(text: str, field: str) -> str | None:
    match = re.search(rf'"{re.escape(field)}"\s*:\s*"((?:\\.|[^"\\])*)"', text, flags=re.DOTALL)
    if match is None:
        return None
    return _decode_json_string(match.group(1))


def _recover_json_string_array(text: str, field: str) -> list[str]:
    field_match = re.search(rf'"{re.escape(field)}"\s*:\s*\[', text)
    if field_match is None:
        return []
    body_start = field_match.end()
    next_field = re.search(
        r',\s*"(?:summary|strengths|risks|ips_mismatches|history_observations|open_questions)"\s*:',
        text[body_start:],
        flags=re.DOTALL,
    )
    body_end = body_start + next_field.start() if next_field else len(text)
    body = text[body_start:body_end]
    values = [
        _decode_json_string(match.group(1))
        for match in re.finditer(r'"((?:\\.|[^"\\])*)"', body, flags=re.DOTALL)
    ]
    return [value for value in values if value]


def _decode_json_string(value: str) -> str:
    try:
        decoded = json.loads(f'"{value}"')
    except json.JSONDecodeError:
        decoded = value
    return str(decoded).strip()


def _fallback_evaluation_summary(text: str) -> str:
    stripped = _strip_markdown_fence(text).strip()
    if not stripped:
        return "Portfolio evaluator returned no usable summary."
    if stripped.startswith("{") or '"summary"' in stripped:
        return (
            "Portfolio evaluator returned malformed structured output that could not be fully "
            "parsed."
        )
    return stripped[:1000]


def _strip_markdown_fence(text: str) -> str:
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _metrics_storage_skip_result(storage_result: dict[str, Any]) -> dict[str, Any]:
    if storage_result.get("status") == "skipped":
        return {
            "metrics_stored": 0,
            "reason": "Daily snapshot already existed; metrics were not duplicated.",
        }
    return {"metrics_stored": 0, "reason": "Snapshot was not inserted."}


def _portfolio_packet_with_history(
    packet: PortfolioAgentPacket,
    history_status: dict[str, Any],
) -> PortfolioAgentPacket:
    warnings = list(history_status.get("data_quality", {}).get("warnings", []))
    performance = packet.performance.model_copy(update={"warnings": warnings})
    return packet.model_copy(update={"performance": performance})


def _result_warnings(
    packet: PortfolioAgentPacket,
    history_status: dict[str, Any],
    evaluation: PortfolioEvaluation,
) -> list[str]:
    warnings = list(packet.data_quality.warnings)
    warnings.extend(packet.performance.warnings)
    warnings.extend(history_status.get("data_quality", {}).get("warnings", []))
    warnings.extend(evaluation.warnings)
    return _dedupe(warnings)


def _dedupe(values: list[str]) -> list[str]:
    seen = set()
    result = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _emit(
    status_events: list[StatusEvent],
    run_id: str,
    status: str,
    message: str,
    status_callback,
) -> None:
    event = StatusEvent(
        run_id=run_id,
        status=status,
        message=message,
        timestamp=datetime.now(UTC),
    )
    status_events.append(event)
    if status_callback is not None:
        status_callback(event)


GeminiPortfolioEvaluator = LLMPortfolioEvaluator
