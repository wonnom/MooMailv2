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
from moomail_finance_ai.mcp.gateway import (
    DirectToolGateway,
    MCPToolGateway,
    StdioMCPToolGateway,
    local_stdio_server_configs,
)
from moomail_finance_ai.metrics import MetricResult
from moomail_finance_ai.mocks import mock_investment_policy
from moomail_finance_ai.opend import OpenDFieldReport
from moomail_finance_ai.opend_portfolio import (
    OPEND_FUND_ASSETS_CASH_SWEEP_ID,
    build_portfolio_agent_packet,
)
from moomail_finance_ai.schemas import (
    InvestmentPolicy,
    PortfolioAgentPacket,
    PortfolioSnapshot,
    StrictModel,
    StatusEvent,
)
from moomail_finance_ai.agent_schemas import PortfolioContextPlan, PortfolioTask
from moomail_finance_ai.agent_schemas import PortfolioEvidencePlan, PortfolioRequest
from moomail_finance_ai.asset_resolver import PortfolioAssetCandidate
from moomail_finance_ai.portfolio_evidence_planner import (
    DeterministicPortfolioEvidencePlanner,
    PortfolioEvidencePlanner,
    fallback_portfolio_task_from_query,
    portfolio_evidence_plan_to_context_plan,
    portfolio_request_to_task,
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


class EffectiveCashSummary(StrictModel):
    currency: str
    cash_value: float
    auto_invested_fund_assets_value: float
    cash_equivalent_value: float
    effective_cash_value: float
    effective_cash_weight: float
    literal_cash_balances: list[dict[str, Any]] = Field(default_factory=list)
    auto_invested_fund_assets: list[dict[str, Any]] = Field(default_factory=list)
    cash_equivalent_holdings: list[dict[str, Any]] = Field(default_factory=list)


class PortfolioHistoryContext(StrictModel):
    history_status: dict[str, Any]
    latest_portfolio_state: dict[str, Any] | None = None
    portfolio_growth: list[dict[str, Any]] = Field(default_factory=list)
    allocation_history: list[dict[str, Any]] = Field(default_factory=list)
    position_state_changes: list[dict[str, Any]] = Field(default_factory=list)


class PortfolioAgentResult(StrictModel):
    run_id: str
    portfolio_id: str
    context_plan: PortfolioContextPlan | None = None
    evidence_plan: PortfolioEvidencePlan | None = None
    snapshot: PortfolioSnapshot
    portfolio_packet: PortfolioAgentPacket
    metrics: list[MetricResult]
    storage_result: dict[str, Any]
    metrics_storage_result: dict[str, Any]
    effective_cash: EffectiveCashSummary
    history_status: dict[str, Any]
    history_context: PortfolioHistoryContext
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
        history_context: PortfolioHistoryContext | None = None,
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
        history_context: PortfolioHistoryContext | None = None,
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
                history_context=history_context,
            ),
            system_instruction=PORTFOLIO_EVALUATOR_SYSTEM_PROMPT,
            max_output_tokens=8192,
            temperature=0.1,
        )
        model = getattr(getattr(self.llm, "config", None), "model", None)
        return _evaluation_from_text(text, model=model)


@dataclass
class PortfolioAgent:
    gateway: MCPToolGateway
    evaluator: PortfolioEvaluator
    evidence_planner: PortfolioEvidencePlanner = field(
        default_factory=DeterministicPortfolioEvidencePlanner
    )
    base_currency: str = "USD"
    min_snapshots_for_history: int = 2
    tool_calls: list[str] = field(default_factory=list)

    def run(
        self,
        query: str,
        ips: InvestmentPolicy,
        *,
        status_callback=None,
        portfolio_task: PortfolioTask | None = None,
        portfolio_request: PortfolioRequest | None = None,
        asset_candidates: list[PortfolioAssetCandidate | dict[str, Any]] | None = None,
    ) -> PortfolioAgentResult:
        run_id = f"portfolio_run_{uuid4().hex[:12]}"
        self.tool_calls = []
        status_events: list[StatusEvent] = []

        def emit(status: str, message: str) -> None:
            _emit(status_events, run_id, status, message, status_callback)

        evidence_plan = None
        if portfolio_request is not None:
            emit(
                "planning_portfolio_evidence",
                "Planning bounded portfolio evidence from PortfolioRequest.",
            )
            evidence_plan = self.evidence_planner.plan(
                portfolio_request,
                ips,
                asset_candidates or [],
            )
            for resolution in evidence_plan.resolved_assets:
                emit(
                    f"asset_resolution_{resolution.resolution_status}",
                    f"Asset resolver returned {resolution.resolution_status}.",
                )
            emit(
                "portfolio_evidence_plan_validated",
                "Portfolio evidence planner produced a validated bounded plan.",
            )
            task = portfolio_task or portfolio_request_to_task(
                portfolio_request,
                evidence_plan,
            )
            plan = portfolio_evidence_plan_to_context_plan(evidence_plan)
        else:
            task = portfolio_task or interpret_portfolio_task(query)
            plan = plan_portfolio_context(task)
        emit(
            "planning_portfolio_context",
            f"Planned bounded portfolio context for {task.task_type}.",
        )
        self._record_planned_tools(plan)

        self._initialize_sql_if_needed(plan, emit)
        snapshot, source_report = self._read_current_context(ips, plan, emit)
        snapshot_json = snapshot.model_dump(mode="json")
        ips_json = ips.model_dump(mode="json")

        metrics = self._calculate_metrics(snapshot_json, ips_json, plan, emit)
        history_context = self._read_history_context(ips, snapshot, plan, emit)
        history_status = history_context.history_status
        portfolio_packet = _portfolio_packet_with_history(
            build_portfolio_agent_packet(snapshot, ips, source_report),
            history_status,
        )
        effective_cash = build_effective_cash_summary(snapshot)
        pending_storage_result = _pending_storage_result(snapshot)

        emit("evaluating_portfolio", "Running the LLM portfolio-only evaluator.")
        evaluation = self.evaluator.evaluate(
            query=query,
            ips=ips,
            snapshot=snapshot,
            portfolio_packet=portfolio_packet,
            metrics=metrics,
            storage_result=pending_storage_result,
            history_status=history_status,
            history_context=history_context,
        )
        emit(
            "portfolio_evaluation_ready",
            (
                "Portfolio evaluation complete; storing the current OpenD observation next."
                if plan.persist_observation
                else "Portfolio evaluation complete; SQL persistence is skipped by plan."
            ),
        )

        storage_result = self._write_portfolio_history(
            snapshot,
            snapshot_json,
            source_report,
            plan,
            ips,
            emit,
        )
        metrics_storage_result = _metrics_storage_skip_result(storage_result)

        emit("complete", "Portfolio Agent run complete.")
        return PortfolioAgentResult(
            run_id=run_id,
            portfolio_id=snapshot.portfolio_id,
            context_plan=plan,
            evidence_plan=evidence_plan,
            snapshot=snapshot,
            portfolio_packet=portfolio_packet,
            metrics=metrics,
            storage_result=storage_result,
            metrics_storage_result=metrics_storage_result,
            effective_cash=effective_cash,
            history_status=history_status,
            history_context=history_context,
            evaluation=evaluation,
            tool_calls=list(self.tool_calls),
            status_events=status_events,
            warnings=_result_warnings(portfolio_packet, history_status, evaluation),
        )

    def close(self) -> None:
        close = getattr(self.gateway, "close", None)
        if callable(close):
            close()

    def _initialize_sql_if_needed(self, plan: PortfolioContextPlan, emit) -> None:
        if not (plan.needs_sql_history or plan.persist_observation):
            emit("skipping_sql_initialize", "SQL MCP initialization skipped by context plan.")
            return
        emit("initializing_portfolio_agent", "Preparing MCP modules for portfolio analysis.")
        self._call(PORTFOLIO_SQL_SERVER, "portfolio_sql_initialize", {})

    def _read_current_context(
        self,
        ips: InvestmentPolicy,
        plan: PortfolioContextPlan,
        emit,
    ) -> tuple[PortfolioSnapshot, OpenDFieldReport]:
        if not plan.needs_current_snapshot:
            raise ValueError("Portfolio Agent currently requires a current snapshot.")
        emit("retrieving_opend_portfolio", "Reading current portfolio context from OpenD MCP.")
        context = self._call(
            OPEND_SERVER,
            "opend_get_portfolio_context",
            {"portfolio_id": ips.portfolio_id, "base_currency": self.base_currency},
        )
        return (
            PortfolioSnapshot.model_validate(context["snapshot"]),
            OpenDFieldReport.model_validate(context["source_report"]),
        )

    def _calculate_metrics(
        self,
        snapshot_json: dict[str, Any],
        ips_json: dict[str, Any],
        plan: PortfolioContextPlan,
        emit,
    ) -> list[MetricResult]:
        if not plan.metric_groups:
            emit("skipping_metrics", "Metric calculation skipped by context plan.")
            return []
        emit(
            "calculating_metrics",
            "Calculating deterministic portfolio metrics through MCP.",
        )
        metric_rows = self._call(
            FINANCE_METRICS_SERVER,
            "calculate_snapshot_metrics",
            {"snapshot": snapshot_json, "ips": ips_json},
        )
        self.tool_calls.append(
            "actual_detail:"
            f"{FINANCE_METRICS_SERVER}:calculate_snapshot_metrics "
            f"requested_metric_groups={','.join(plan.metric_groups)} "
            "broad_snapshot_metrics_used=true"
        )
        return [MetricResult.model_validate(row) for row in metric_rows]

    def _read_history_context(
        self,
        ips: InvestmentPolicy,
        snapshot: PortfolioSnapshot,
        plan: PortfolioContextPlan,
        emit,
    ) -> PortfolioHistoryContext:
        if not plan.needs_sql_history:
            emit("skipping_history_reads", "SQL history reads skipped by context plan.")
            return PortfolioHistoryContext(
                history_status=_skipped_history_status(snapshot, "not_needed_for_plan"),
                latest_portfolio_state=None,
                portfolio_growth=[],
                allocation_history=[],
                position_state_changes=[],
            )

        emit(
            "reading_history_status",
            "Reading planned portfolio history from SQL MCP before storing this run.",
        )
        history_status: dict[str, Any] = _skipped_history_status(
            snapshot,
            "history_status_not_requested",
        )
        latest_portfolio_state = None
        portfolio_growth: list[dict[str, Any]] = []
        allocation_history: list[dict[str, Any]] = []
        position_state_changes: list[dict[str, Any]] = []

        if "history_status" in plan.history_queries:
            history_status = self._call(
                PORTFOLIO_SQL_SERVER,
                "portfolio_sql_get_history_status",
                {
                    "portfolio_id": ips.portfolio_id,
                    "now": snapshot.as_of.isoformat(),
                    "min_snapshots_for_history": self.min_snapshots_for_history,
                },
            )
        if "latest_state" in plan.history_queries:
            latest_portfolio_state = self._call(
                PORTFOLIO_SQL_SERVER,
                "portfolio_sql_get_latest_portfolio_state",
                {"portfolio_id": ips.portfolio_id},
            )
        if "portfolio_growth" in plan.history_queries:
            portfolio_growth = self._call(
                PORTFOLIO_SQL_SERVER,
                "portfolio_sql_get_portfolio_growth",
                {"portfolio_id": ips.portfolio_id, "limit": plan.row_limit},
            )
        if "allocation_history" in plan.history_queries:
            allocation_history = self._call(
                PORTFOLIO_SQL_SERVER,
                "portfolio_sql_get_allocation_history",
                {"portfolio_id": ips.portfolio_id, "limit": plan.row_limit},
            )
        if "position_state_changes" in plan.history_queries:
            position_state_changes = self._read_position_state_changes(
                ips,
                snapshot,
                plan,
            )
        return PortfolioHistoryContext(
            history_status=history_status,
            latest_portfolio_state=latest_portfolio_state,
            portfolio_growth=portfolio_growth,
            allocation_history=allocation_history,
            position_state_changes=position_state_changes,
        )

    def _read_position_state_changes(
        self,
        ips: InvestmentPolicy,
        snapshot: PortfolioSnapshot,
        plan: PortfolioContextPlan,
    ) -> list[dict[str, Any]]:
        changes: list[dict[str, Any]] = []
        for scope in _position_change_scopes(plan):
            lookback_days = _history_window_days(plan.history_window)
            until = snapshot.as_of.isoformat()
            arguments: dict[str, Any] = {
                "portfolio_id": ips.portfolio_id,
                "lookback_days": lookback_days,
                "until": until,
                "limit": plan.row_limit,
            }
            if scope["asset_id"]:
                arguments["asset_id"] = scope["asset_id"]
            elif scope["ticker"]:
                arguments["ticker"] = scope["ticker"]
            position_change_result = self._call(
                PORTFOLIO_SQL_SERVER,
                "portfolio_sql_get_position_state_changes",
                arguments,
            )
            self.tool_calls.append(
                "actual_detail:"
                f"{PORTFOLIO_SQL_SERVER}:portfolio_sql_get_position_state_changes "
                f"asset_id={scope['asset_id'] or '*'} "
                f"ticker={scope['ticker'] or '*'} "
                f"lookback_days={lookback_days} "
                f"until={until}"
            )
            changes.extend(position_change_result.get("changes", []))
        return sorted(changes, key=_position_state_change_sort_key)[: plan.row_limit]

    def _write_portfolio_history(
        self,
        snapshot: PortfolioSnapshot,
        snapshot_json: dict[str, Any],
        source_report: OpenDFieldReport,
        plan: PortfolioContextPlan,
        ips: InvestmentPolicy,
        emit,
    ) -> dict[str, Any]:
        if not plan.persist_observation:
            emit("skipping_portfolio_history_update", "SQL persistence skipped by context plan.")
            return _skipped_storage_result(snapshot, plan)

        emit("updating_portfolio_history", "Writing lean portfolio-history rows to SQL MCP.")
        self._call(
            PORTFOLIO_SQL_SERVER,
            "portfolio_sql_upsert_portfolio",
            {
                "portfolio_id": ips.portfolio_id,
                "base_currency": self.base_currency,
            },
        )
        account_result = self._call(
            PORTFOLIO_SQL_SERVER,
            "portfolio_sql_upsert_broker_account",
            {
                "portfolio_id": ips.portfolio_id,
                "base_currency": self.base_currency,
            },
        )
        account_id = account_result["account_id"]
        assets_result = self._call(
            PORTFOLIO_SQL_SERVER,
            "portfolio_sql_upsert_assets",
            {"snapshot": snapshot_json, "include_cash_assets": True},
        )
        position_state_result = self._call(
            PORTFOLIO_SQL_SERVER,
            "portfolio_sql_upsert_position_states",
            {
                "snapshot": snapshot_json,
                "source_report": source_report.model_dump(mode="json"),
                "account_id": account_id,
            },
        )
        value_snapshot_result = self._call(
            PORTFOLIO_SQL_SERVER,
            "portfolio_sql_store_daily_value_snapshot",
            {
                "snapshot": snapshot_json,
                "source_report": source_report.model_dump(mode="json"),
                "account_id": account_id,
            },
        )
        weight_storage_result = self._call(
            PORTFOLIO_SQL_SERVER,
            "portfolio_sql_store_weight_snapshots",
            {
                "snapshot": snapshot_json,
                "source_report": source_report.model_dump(mode="json"),
                "account_id": account_id,
                "value_snapshot_id": value_snapshot_result["value_snapshot_id"],
            },
        )
        data_quality_result = self._call(
            PORTFOLIO_SQL_SERVER,
            "portfolio_sql_store_data_quality_events",
            {
                "snapshot": snapshot_json,
                "source_report": source_report.model_dump(mode="json"),
                "account_id": account_id,
                "value_snapshot_id": value_snapshot_result["value_snapshot_id"],
            },
        )
        return {
            "status": value_snapshot_result["status"],
            "portfolio_id": snapshot.portfolio_id,
            "account_id": account_id,
            "value_snapshot_id": value_snapshot_result["value_snapshot_id"],
            "snapshot_date": value_snapshot_result["snapshot_date"],
            "assets_upserted": assets_result["assets_upserted"],
            "position_states_inserted": position_state_result["inserted"],
            "position_states_updated": position_state_result["updated"],
            "position_states_marked_inactive": position_state_result["marked_inactive"],
            "weight_rows_stored": weight_storage_result["rows_stored"],
            "data_quality_events_stored": data_quality_result["events_stored"],
        }

    def _record_planned_tools(self, plan: PortfolioContextPlan) -> None:
        if plan.needs_sql_history or plan.persist_observation:
            self.tool_calls.append(f"planned:{PORTFOLIO_SQL_SERVER}:portfolio_sql_initialize")
        else:
            self.tool_calls.append(
                f"skipped:{PORTFOLIO_SQL_SERVER}:portfolio_sql_initialize "
                "reason=no_sql_history_or_persistence"
            )
        if plan.needs_current_snapshot:
            self.tool_calls.append(f"planned:{OPEND_SERVER}:opend_get_portfolio_context")
        if plan.metric_groups:
            self.tool_calls.append(
                f"planned:{FINANCE_METRICS_SERVER}:calculate_snapshot_metrics "
                f"metric_groups={','.join(plan.metric_groups)}"
            )
        else:
            self.tool_calls.append(
                f"skipped:{FINANCE_METRICS_SERVER}:calculate_snapshot_metrics "
                "reason=no_metric_groups_requested"
            )
        self._record_planned_history_tools(plan)
        self._record_planned_persistence_tools(plan)

    def _record_planned_history_tools(self, plan: PortfolioContextPlan) -> None:
        history_tools = {
            "history_status": "portfolio_sql_get_history_status",
            "latest_state": "portfolio_sql_get_latest_portfolio_state",
            "portfolio_growth": "portfolio_sql_get_portfolio_growth",
            "allocation_history": "portfolio_sql_get_allocation_history",
            "position_state_changes": "portfolio_sql_get_position_state_changes",
        }
        if not plan.needs_sql_history:
            reason = _history_skip_reason(plan)
            for tool_name in history_tools.values():
                self.tool_calls.append(
                    f"skipped:{PORTFOLIO_SQL_SERVER}:{tool_name} reason={reason}"
                )
            return
        requested = set(plan.history_queries)
        for query_name, tool_name in history_tools.items():
            prefix = "planned" if query_name in requested else "skipped"
            suffix = "" if query_name in requested else " reason=not_requested_by_context_plan"
            self.tool_calls.append(f"{prefix}:{PORTFOLIO_SQL_SERVER}:{tool_name}{suffix}")

    def _record_planned_persistence_tools(self, plan: PortfolioContextPlan) -> None:
        persistence_tools = [
            "portfolio_sql_upsert_portfolio",
            "portfolio_sql_upsert_broker_account",
            "portfolio_sql_upsert_assets",
            "portfolio_sql_upsert_position_states",
            "portfolio_sql_store_daily_value_snapshot",
            "portfolio_sql_store_weight_snapshots",
            "portfolio_sql_store_data_quality_events",
        ]
        for tool_name in persistence_tools:
            if plan.persist_observation:
                self.tool_calls.append(f"planned:{PORTFOLIO_SQL_SERVER}:{tool_name}")
            else:
                self.tool_calls.append(
                    f"skipped:{PORTFOLIO_SQL_SERVER}:{tool_name} "
                    "reason=persist_observation_false"
                )

    def _call(
        self,
        server_name: str,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> Any:
        self.tool_calls.append(f"{server_name}:{tool_name}")
        return self.gateway.call_tool(
            server_name,
            tool_name,
            arguments,
            consumer="portfolio_agent",
        ).structured_content


def build_default_portfolio_agent(
    *,
    env_file: str | Path | None = "config/local.env",
    from_report: str | Path | None = None,
    db_path: str | Path = "data/portfolio-history.sqlite",
    llm_provider: str | None = None,
    evaluator: PortfolioEvaluator | None = None,
    gateway: MCPToolGateway | None = None,
    gateway_mode: str = "stdio",
) -> PortfolioAgent:
    config = load_opend_config(env_file=env_file)
    if gateway is None and gateway_mode == "direct":
        gateway = DirectToolGateway(
            [
                build_opend_mcp_module(config=config, env_file=env_file, from_report=from_report),
                build_finance_metrics_mcp_module(),
                build_portfolio_sql_mcp_module(db_path=db_path),
            ]
        )
    if gateway is None:
        gateway = StdioMCPToolGateway(
            local_stdio_server_configs(
                env_file=env_file,
                from_report=from_report,
                db_path=db_path,
            )
        )
    return PortfolioAgent(
        gateway=gateway,
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
    gateway: MCPToolGateway | None = None,
    gateway_mode: str = "stdio",
) -> tuple[PortfolioAgent, InvestmentPolicy]:
    return (
        build_default_portfolio_agent(
            env_file=env_file,
            from_report=from_report,
            db_path=db_path,
            llm_provider=llm_provider,
            evaluator=evaluator,
            gateway=gateway,
            gateway_mode=gateway_mode,
        ),
        mock_investment_policy(),
    )


def interpret_portfolio_task(query: str) -> PortfolioTask:
    return fallback_portfolio_task_from_query(query)


def plan_portfolio_context(task: PortfolioTask) -> PortfolioContextPlan:
    if task.persistence_mode == "persist":
        persist_observation = True
    elif task.persistence_mode == "skip":
        persist_observation = False
    else:
        persist_observation = task.task_type in {
            "full_review",
            "what_changed",
            "deep_dive",
            "compare",
        }

    if task.task_type in {"full_review", "deep_dive", "compare"}:
        return PortfolioContextPlan(
            needs_current_snapshot=True,
            needs_sql_history=True,
            history_queries=[
                "history_status",
                "latest_state",
                "portfolio_growth",
                "allocation_history",
                "position_state_changes",
            ],
            tickers=task.requested_tickers,
            metric_groups=[
                "allocation",
                "concentration",
                "effective_cash",
                "risk",
                "performance",
            ],
            persist_observation=persist_observation,
            history_window=task.history_window,
            row_limit=100,
        )
    if task.task_type == "what_changed":
        return PortfolioContextPlan(
            needs_current_snapshot=True,
            needs_sql_history=True,
            history_queries=[
                "history_status",
                "latest_state",
                "portfolio_growth",
                "allocation_history",
                "position_state_changes",
            ],
            tickers=task.requested_tickers,
            metric_groups=["allocation", "effective_cash", "performance"],
            persist_observation=persist_observation,
            history_window=task.history_window or "90d",
            row_limit=100,
        )
    if task.task_type == "risk_check":
        return PortfolioContextPlan(
            needs_current_snapshot=True,
            needs_sql_history=False,
            history_queries=["none"],
            tickers=task.requested_tickers,
            metric_groups=["allocation", "concentration", "effective_cash", "risk"],
            persist_observation=persist_observation,
            history_window=task.history_window,
            row_limit=30,
        )
    metric_groups = _metric_groups_for_portfolio_fact(task)
    return PortfolioContextPlan(
        needs_current_snapshot=True,
        needs_sql_history=False,
        history_queries=["none"],
        tickers=task.requested_tickers,
        metric_groups=metric_groups,
        persist_observation=persist_observation,
        history_window=task.history_window,
        row_limit=30,
    )


def _history_window_days(history_window: str | None) -> float | None:
    if not history_window:
        return None
    match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*d\s*", history_window.lower())
    if match is None:
        return None
    return float(match.group(1))


def _position_state_change_sort_key(change: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(change.get("change_at") or ""),
        str(change.get("ticker") or ""),
        str(change.get("asset_id") or ""),
    )


def _position_change_scopes(plan: PortfolioContextPlan) -> list[dict[str, str | None]]:
    if plan.asset_ids:
        scopes = []
        for index, asset_id in enumerate(plan.asset_ids):
            scopes.append(
                {
                    "asset_id": asset_id,
                    "ticker": plan.tickers[index] if index < len(plan.tickers) else None,
                }
            )
        return scopes
    if plan.tickers:
        return [{"asset_id": None, "ticker": ticker} for ticker in plan.tickers]
    return [{"asset_id": None, "ticker": None}]


PORTFOLIO_EVALUATOR_SYSTEM_PROMPT = """
You are the Portfolio Agent evaluator for a personal finance AI.
Use only the portfolio snapshot, deterministic metrics, SQL history status, and Investment Policy
Statement supplied by the tool pipeline. Do not use market news, sentiment, external outlook, or
unsupported facts. Do not recommend trade placement, order entry, exact share counts, or execution
instructions. The summary must answer the user_query directly before giving any overview. If the
query asks for a narrow portfolio-only fact, ranking, allocation, risk, cash, or holding question,
answer that question first instead of defaulting to a broad portfolio review. If the query requires
market sentiment, news, research, or broader synthesis, say what portfolio-only evidence can and
cannot answer. Return a compact JSON object only, with no markdown fences and no prose outside JSON.
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
    history_context: PortfolioHistoryContext | None = None,
) -> str:
    effective_cash = build_effective_cash_summary(snapshot)
    context = {
        "user_query": query,
        "investment_policy": ips.model_dump(mode="json"),
        "snapshot_summary": {
            "portfolio_id": snapshot.portfolio_id,
            "as_of": snapshot.as_of.isoformat(),
            "base_currency": snapshot.base_currency,
            "total_value": snapshot.total_value.model_dump(mode="json"),
            "cash": [cash.model_dump(mode="json") for cash in snapshot.cash],
            "effective_cash": effective_cash.model_dump(mode="json"),
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
        "history_context": (
            history_context.model_dump(mode="json") if history_context is not None else None
        ),
    }
    return (
        "Evaluate the portfolio-only evidence below. Answer user_query directly in the summary, "
        "then add concise supporting observations in the lists.\n\n"
        f"{json.dumps(context, sort_keys=True)}"
    )


def build_effective_cash_summary(snapshot: PortfolioSnapshot) -> EffectiveCashSummary:
    literal_cash_balances = [
        cash for cash in snapshot.cash if cash.account_id != OPEND_FUND_ASSETS_CASH_SWEEP_ID
    ]
    auto_invested_fund_assets = [
        cash for cash in snapshot.cash if cash.account_id == OPEND_FUND_ASSETS_CASH_SWEEP_ID
    ]
    cash_equivalent_holdings = [
        holding for holding in snapshot.holdings if holding.asset_type == "cash_equivalent"
    ]
    cash_value = sum(cash.amount for cash in literal_cash_balances)
    auto_invested_fund_assets_value = sum(cash.amount for cash in auto_invested_fund_assets)
    cash_equivalent_value = sum(holding.market_value for holding in cash_equivalent_holdings)
    effective_cash_value = cash_value + auto_invested_fund_assets_value + cash_equivalent_value
    return EffectiveCashSummary(
        currency=snapshot.base_currency,
        cash_value=cash_value,
        auto_invested_fund_assets_value=auto_invested_fund_assets_value,
        cash_equivalent_value=cash_equivalent_value,
        effective_cash_value=effective_cash_value,
        effective_cash_weight=(
            0.0
            if snapshot.total_value.amount == 0
            else effective_cash_value / snapshot.total_value.amount
        ),
        literal_cash_balances=[cash.model_dump(mode="json") for cash in literal_cash_balances],
        auto_invested_fund_assets=[
            cash.model_dump(mode="json") for cash in auto_invested_fund_assets
        ],
        cash_equivalent_holdings=[
            {
                "ticker": holding.ticker,
                "name": holding.name,
                "market_value": holding.market_value,
                "portfolio_weight": holding.portfolio_weight,
            }
            for holding in cash_equivalent_holdings
        ],
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
    return {
        "metrics_stored": 0,
        "weight_rows_stored": storage_result.get("weight_rows_stored", 0),
        "reason": (
            "Deterministic metric inputs are not persisted in the lean portfolio-history schema; "
            "overall portfolio weights are stored in portfolio_weight_snapshots."
        ),
    }


def _pending_storage_result(snapshot: PortfolioSnapshot) -> dict[str, Any]:
    return {
        "status": "pending",
        "portfolio_id": snapshot.portfolio_id,
        "snapshot_date": snapshot.as_of.date().isoformat(),
        "reason": (
            "The current OpenD observation is stored after portfolio evaluation so the LLM "
            "uses history that existed before this run."
        ),
    }


def _skipped_storage_result(snapshot: PortfolioSnapshot, plan: PortfolioContextPlan) -> dict[str, Any]:
    return {
        "status": "skipped",
        "portfolio_id": snapshot.portfolio_id,
        "snapshot_date": snapshot.as_of.date().isoformat(),
        "reason": "persist_observation_false",
        "context_plan": plan.model_dump(mode="json"),
        "weight_rows_stored": 0,
    }


def _skipped_history_status(snapshot: PortfolioSnapshot, reason: str) -> dict[str, Any]:
    return {
        "snapshot_count": 0,
        "latest_snapshot_at": None,
        "freshness_status": "unknown",
        "as_of": snapshot.as_of.isoformat(),
        "skipped": True,
        "reason": reason,
        "data_quality": {"warnings": []},
    }


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


def _metric_groups_for_portfolio_fact(task: PortfolioTask) -> list[str]:
    outputs = set(task.required_outputs)
    metric_groups = []
    if "allocation" in outputs:
        metric_groups.append("allocation")
    if "effective_cash" in outputs:
        metric_groups.append("effective_cash")
    if "risk" in outputs or "candidate_issues" in outputs:
        metric_groups.extend(["allocation", "concentration", "risk"])
    if not metric_groups:
        metric_groups.append("allocation")
    return _dedupe(metric_groups)


def _history_skip_reason(plan: PortfolioContextPlan) -> str:
    groups = set(plan.metric_groups)
    if groups <= {"allocation", "effective_cash"}:
        return "not_needed_for_cash_query"
    return "not_needed_for_context_plan"


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
