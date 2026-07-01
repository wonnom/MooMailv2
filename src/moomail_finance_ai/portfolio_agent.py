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
    MCPGatewayError,
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
    DataQuality,
    InvestmentPolicy,
    Money,
    PortfolioAgentPacket,
    PortfolioSnapshot,
    StrictModel,
    StatusEvent,
)
from moomail_finance_ai.agent_schemas import PortfolioContextPlan, PortfolioTask
from moomail_finance_ai.agent_schemas import (
    PortfolioEvidencePacket,
    PortfolioEvidencePlan,
    PortfolioRequest,
)
from moomail_finance_ai.asset_resolver import (
    PortfolioAssetCandidate,
    build_portfolio_asset_candidates,
)
from moomail_finance_ai.portfolio_data_service import snapshot_from_latest_state
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


class PortfolioCurrentContext(StrictModel):
    snapshot: PortfolioSnapshot
    source_report: OpenDFieldReport | None = None
    source: str
    history_status: dict[str, Any] | None = None
    latest_portfolio_state: dict[str, Any] | None = None
    warnings: list[str] = Field(default_factory=list)


class PortfolioAgentResult(StrictModel):
    run_id: str
    portfolio_id: str
    context_plan: PortfolioContextPlan | None = None
    evidence_plan: PortfolioEvidencePlan | None = None
    evidence_packet: PortfolioEvidencePacket
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


PORTFOLIO_PATTERN_THRESHOLDS: dict[str, float] = {
    "single_position_concentration_weight": 0.25,
    "effective_cash_target_gap": 0.02,
    "large_allocation_weight": 0.10,
    "large_quantity_delta_abs": 1.0,
    "average_cost_delta_pct": 0.05,
}


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
            planner_candidates = self._asset_candidates_for_request(
                portfolio_request,
                ips,
                asset_candidates or [],
                emit,
            )
            evidence_plan = self.evidence_planner.plan(
                portfolio_request,
                ips,
                planner_candidates,
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
            plan = portfolio_evidence_plan_to_context_plan(
                evidence_plan,
                runtime_requires_current_snapshot=evidence_plan.needs_current_values,
            )
        else:
            task = portfolio_task or interpret_portfolio_task(query)
            plan = plan_portfolio_context(task)
        emit(
            "planning_portfolio_context",
            f"Planned bounded portfolio context for {task.task_type}.",
        )
        self._record_planned_tools(plan, evidence_plan=evidence_plan)

        self._initialize_sql_if_needed(plan, emit)
        current_context = (
            self._read_current_context_for_evidence_plan(ips, evidence_plan, plan, emit)
            if evidence_plan is not None
            else self._read_current_context(ips, plan, emit)
        )
        snapshot = current_context.snapshot
        source_report = current_context.source_report
        snapshot_json = snapshot.model_dump(mode="json")
        ips_json = ips.model_dump(mode="json")

        metrics = self._calculate_metrics(snapshot_json, ips_json, plan, emit)
        history_context = self._read_history_context(
            ips,
            snapshot,
            plan,
            emit,
            current_context=current_context,
        )
        history_status = history_context.history_status
        portfolio_packet = _portfolio_packet_with_history(
            build_portfolio_agent_packet(snapshot, ips, source_report),
            history_status,
        )
        effective_cash = build_effective_cash_summary(snapshot)
        pending_storage_result = (
            _pending_storage_result(snapshot)
            if source_report is not None
            else _skipped_storage_result(
                snapshot,
                plan,
                reason=f"{current_context.source}_has_no_current_opend_observation",
            )
        )

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

        storage_result = (
            self._write_portfolio_history(
                snapshot,
                snapshot_json,
                source_report,
                plan,
                ips,
                emit,
            )
            if source_report is not None
            else _skipped_storage_result(
                snapshot,
                plan,
                reason=f"{current_context.source}_has_no_current_opend_observation",
            )
        )
        metrics_storage_result = _metrics_storage_skip_result(storage_result)
        result_warnings = _result_warnings(
            portfolio_packet,
            history_status,
            evaluation,
            plan,
            current_context_warnings=current_context.warnings,
        )
        evidence_packet = _build_evidence_packet(
            portfolio_id=snapshot.portfolio_id,
            task_intent=evidence_plan.task_intent if evidence_plan else task.task_type,
            evidence_plan=evidence_plan,
            snapshot=snapshot,
            portfolio_packet=portfolio_packet,
            metrics=metrics,
            effective_cash=effective_cash,
            history_context=history_context,
            evaluation=evaluation,
            warnings=result_warnings,
            tool_calls=list(self.tool_calls),
            ips=ips,
        )

        emit("complete", "Portfolio Agent run complete.")
        return PortfolioAgentResult(
            run_id=run_id,
            portfolio_id=snapshot.portfolio_id,
            context_plan=plan,
            evidence_plan=evidence_plan,
            evidence_packet=evidence_packet,
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
            warnings=_dedupe([*result_warnings, *evidence_packet.warnings]),
        )

    def close(self) -> None:
        close = getattr(self.gateway, "close", None)
        if callable(close):
            close()

    def _asset_candidates_for_request(
        self,
        request: PortfolioRequest,
        ips: InvestmentPolicy,
        fixture_candidates: list[PortfolioAssetCandidate | dict[str, Any]],
        emit,
    ) -> list[PortfolioAssetCandidate]:
        if not request.asset_hints:
            return build_portfolio_asset_candidates(fixture_candidates=fixture_candidates)
        latest_state = self._read_sql_latest_state_for_policy(ips, emit)
        sql_rows = []
        if latest_state is not None:
            sql_rows.extend(latest_state.get("active_positions") or [])
            sql_rows.extend(latest_state.get("weights") or [])
        candidates = build_portfolio_asset_candidates(
            sql_assets=sql_rows,
            fixture_candidates=fixture_candidates,
        )
        if candidates:
            emit(
                "portfolio_asset_candidates_ready",
                "Loaded SQL/latest portfolio asset candidates for deterministic resolution.",
            )
        return candidates

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
    ) -> PortfolioCurrentContext:
        if not plan.needs_current_snapshot:
            raise ValueError("Portfolio Agent currently requires a current snapshot.")
        emit("retrieving_opend_portfolio", "Reading current portfolio context from OpenD MCP.")
        context = self._call(
            OPEND_SERVER,
            "opend_get_portfolio_context",
            {"portfolio_id": ips.portfolio_id, "base_currency": self.base_currency},
        )
        return PortfolioCurrentContext(
            snapshot=PortfolioSnapshot.model_validate(context["snapshot"]),
            source_report=OpenDFieldReport.model_validate(context["source_report"]),
            source="opend_current_context",
        )

    def _read_current_context_for_evidence_plan(
        self,
        ips: InvestmentPolicy,
        evidence_plan: PortfolioEvidencePlan,
        plan: PortfolioContextPlan,
        emit,
    ) -> PortfolioCurrentContext:
        if evidence_plan.freshness_requirement == "latest_required":
            return self._read_current_context(ips, plan, emit)

        latest_state = self._read_sql_latest_state_for_policy(ips, emit)
        policy_history_status = self._read_history_status_for_policy(ips, emit)
        sql_snapshot = snapshot_from_latest_state(latest_state, base_currency=self.base_currency)

        if evidence_plan.freshness_requirement == "history_only":
            emit(
                "skipping_opend_history_only",
                "OpenD current context skipped by history_only evidence policy.",
            )
            return PortfolioCurrentContext(
                snapshot=sql_snapshot
                or _empty_portfolio_snapshot(
                    ips.portfolio_id,
                    base_currency=self.base_currency,
                    reason="history_only_sql_snapshot_unavailable",
                ),
                source="history_only_sql",
                history_status=policy_history_status,
                latest_portfolio_state=latest_state,
                warnings=(
                    []
                    if sql_snapshot is not None
                    else ["No stored SQL latest state was available for a history_only run."]
                ),
            )

        if _history_status_is_fresh(policy_history_status) and sql_snapshot is not None:
            emit(
                "using_cached_sql_latest_state",
                "Using fresh SQL latest state for cached_ok evidence policy.",
            )
            return PortfolioCurrentContext(
                snapshot=sql_snapshot,
                source="cached_sql_latest_state",
                history_status=policy_history_status,
                latest_portfolio_state=latest_state,
            )

        try:
            return self._read_current_context(ips, plan, emit)
        except MCPGatewayError as exc:
            warning = (
                "Cached portfolio data is stale or missing and OpenD current context is "
                f"unavailable: {exc}"
            )
            emit("stale_cache_warning", warning)
            return PortfolioCurrentContext(
                snapshot=sql_snapshot
                or _empty_portfolio_snapshot(
                    ips.portfolio_id,
                    base_currency=self.base_currency,
                    reason="cached_ok_current_context_unavailable",
                ),
                source="stale_or_missing_cached_sql",
                history_status=policy_history_status,
                latest_portfolio_state=latest_state,
                warnings=[warning],
            )

    def _read_sql_latest_state_for_policy(
        self,
        ips: InvestmentPolicy,
        emit,
    ) -> dict[str, Any] | None:
        try:
            self._call(PORTFOLIO_SQL_SERVER, "portfolio_sql_initialize", {})
            latest_state = self._call(
                PORTFOLIO_SQL_SERVER,
                "portfolio_sql_get_latest_portfolio_state",
                {"portfolio_id": ips.portfolio_id},
            )
            if latest_state:
                self.tool_calls.append(
                    "actual_detail:"
                    f"{PORTFOLIO_SQL_SERVER}:portfolio_sql_get_latest_portfolio_state "
                    "policy_probe=true"
                )
            return latest_state
        except MCPGatewayError:
            emit(
                "skipping_sql_latest_state",
                "SQL latest-state policy probe skipped because SQL MCP is unavailable.",
            )
            return None

    def _read_history_status_for_policy(self, ips: InvestmentPolicy, emit) -> dict[str, Any] | None:
        try:
            self._call(PORTFOLIO_SQL_SERVER, "portfolio_sql_initialize", {})
            return self._call(
                PORTFOLIO_SQL_SERVER,
                "portfolio_sql_get_history_status",
                {
                    "portfolio_id": ips.portfolio_id,
                    "now": datetime.now(UTC).isoformat(),
                    "min_snapshots_for_history": 1,
                },
            )
        except MCPGatewayError:
            emit(
                "skipping_history_status",
                "SQL history-status policy probe skipped because SQL MCP is unavailable.",
            )
            return None

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
        *,
        current_context: PortfolioCurrentContext | None = None,
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
            if current_context and current_context.history_status is not None:
                history_status = current_context.history_status
            else:
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
            if current_context and current_context.latest_portfolio_state is not None:
                latest_portfolio_state = current_context.latest_portfolio_state
            else:
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

    def _record_planned_tools(
        self,
        plan: PortfolioContextPlan,
        *,
        evidence_plan: PortfolioEvidencePlan | None = None,
    ) -> None:
        needs_policy_sql = bool(
            evidence_plan
            and evidence_plan.needs_current_values
            and evidence_plan.freshness_requirement == "cached_ok"
        )
        needs_history_only_sql = bool(
            evidence_plan and evidence_plan.freshness_requirement == "history_only"
        )
        if (
            plan.needs_sql_history
            or plan.persist_observation
            or needs_policy_sql
            or needs_history_only_sql
        ):
            self.tool_calls.append(f"planned:{PORTFOLIO_SQL_SERVER}:portfolio_sql_initialize")
        else:
            self.tool_calls.append(
                f"skipped:{PORTFOLIO_SQL_SERVER}:portfolio_sql_initialize "
                "reason=no_sql_history_or_persistence"
            )
        if plan.needs_current_snapshot and (
            evidence_plan is None or evidence_plan.freshness_requirement == "latest_required"
        ):
            self.tool_calls.append(f"planned:{OPEND_SERVER}:opend_get_portfolio_context")
        elif evidence_plan is not None and evidence_plan.freshness_requirement == "history_only":
            self.tool_calls.append(
                f"skipped:{OPEND_SERVER}:opend_get_portfolio_context reason=history_only"
            )
        elif evidence_plan is not None and evidence_plan.freshness_requirement == "cached_ok":
            self.tool_calls.append(
                f"skipped:{OPEND_SERVER}:opend_get_portfolio_context "
                "reason=cached_ok_until_sql_cache_insufficient"
            )
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
        self._record_planned_history_tools(plan, evidence_plan=evidence_plan)
        self._record_planned_persistence_tools(plan)

    def _record_planned_history_tools(
        self,
        plan: PortfolioContextPlan,
        *,
        evidence_plan: PortfolioEvidencePlan | None = None,
    ) -> None:
        history_tools = {
            "history_status": "portfolio_sql_get_history_status",
            "latest_state": "portfolio_sql_get_latest_portfolio_state",
            "portfolio_growth": "portfolio_sql_get_portfolio_growth",
            "allocation_history": "portfolio_sql_get_allocation_history",
            "position_state_changes": "portfolio_sql_get_position_state_changes",
        }
        policy_queries = set()
        if evidence_plan and evidence_plan.freshness_requirement in {"cached_ok", "history_only"}:
            policy_queries.update({"history_status", "latest_state"})
        if not plan.needs_sql_history:
            reason = _history_skip_reason(plan)
            for query_name, tool_name in history_tools.items():
                if query_name in policy_queries:
                    self.tool_calls.append(
                        f"planned:{PORTFOLIO_SQL_SERVER}:{tool_name} reason=freshness_policy"
                    )
                    continue
                self.tool_calls.append(
                    f"skipped:{PORTFOLIO_SQL_SERVER}:{tool_name} reason={reason}"
                )
            return
        requested = set(plan.history_queries) | policy_queries
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
                    f"skipped:{PORTFOLIO_SQL_SERVER}:{tool_name} reason=persist_observation_false"
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
        evaluator=evaluator
        or LLMPortfolioEvaluator.from_env(
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
    match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*([dwmy])\s*", history_window.lower())
    if match is None:
        return None
    value = float(match.group(1))
    multiplier = {"d": 1, "w": 7, "m": 30, "y": 365}[match.group(2)]
    return value * multiplier


def _position_state_change_sort_key(change: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(change.get("change_at") or ""),
        str(change.get("ticker") or ""),
        str(change.get("asset_id") or ""),
    )


def _position_change_scopes(plan: PortfolioContextPlan) -> list[dict[str, str | None]]:
    if plan.position_change_scopes:
        return [
            {"asset_id": scope.asset_id, "ticker": scope.ticker}
            for scope in plan.position_change_scopes
        ]
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


def _skipped_storage_result(
    snapshot: PortfolioSnapshot,
    plan: PortfolioContextPlan,
    *,
    reason: str = "persist_observation_false",
) -> dict[str, Any]:
    return {
        "status": "skipped",
        "portfolio_id": snapshot.portfolio_id,
        "snapshot_date": snapshot.as_of.date().isoformat(),
        "reason": reason,
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


def _build_evidence_packet(
    *,
    portfolio_id: str,
    task_intent: str,
    evidence_plan: PortfolioEvidencePlan | None,
    snapshot: PortfolioSnapshot,
    portfolio_packet: PortfolioAgentPacket,
    metrics: list[MetricResult],
    effective_cash: EffectiveCashSummary,
    history_context: PortfolioHistoryContext,
    evaluation: PortfolioEvaluation,
    warnings: list[str],
    tool_calls: list[str],
    ips: InvestmentPolicy,
) -> PortfolioEvidencePacket:
    valid_task_intents = {
        "full_review",
        "portfolio_fact",
        "risk_check",
        "what_changed",
        "deep_dive",
        "compare",
    }
    packet_intent = task_intent if task_intent in valid_task_intents else "full_review"
    detected_patterns = _detect_portfolio_patterns(
        evidence_plan=evidence_plan,
        snapshot=snapshot,
        portfolio_packet=portfolio_packet,
        effective_cash=effective_cash,
        history_context=history_context,
        ips=ips,
        warnings=warnings,
    )
    limitations = _evidence_limitations(evidence_plan, history_context, warnings)
    return PortfolioEvidencePacket(
        portfolio_id=portfolio_id,
        task_intent=packet_intent,
        resolved_assets=evidence_plan.resolved_assets if evidence_plan else [],
        facts=_evidence_facts(snapshot, history_context),
        derived_metrics={
            "metrics": [metric.model_dump(mode="json") for metric in metrics],
            "effective_cash": effective_cash.model_dump(mode="json"),
            "allocation": {
                key: [item.model_dump(mode="json") for item in values]
                for key, values in portfolio_packet.allocation.items()
            },
            "performance": portfolio_packet.performance.model_dump(mode="json"),
            "risk": portfolio_packet.risk.model_dump(mode="json"),
        },
        position_changes=_sanitize_position_changes(history_context.position_state_changes),
        detected_patterns=detected_patterns,
        portfolio_only_interpretation=_portfolio_interpretation(evaluation),
        limitations=limitations,
        needs_sentiment_context=_sentiment_context_needs(evidence_plan, detected_patterns),
        warnings=_dedupe(warnings),
        tool_refs=list(tool_calls),
    )


def _evidence_facts(
    snapshot: PortfolioSnapshot,
    history_context: PortfolioHistoryContext,
) -> dict[str, Any]:
    return {
        "snapshot": {
            "portfolio_id": snapshot.portfolio_id,
            "as_of": snapshot.as_of.isoformat(),
            "base_currency": snapshot.base_currency,
            "total_value": snapshot.total_value.model_dump(mode="json"),
            "holding_count": len(snapshot.holdings),
            "cash_balance_count": len(snapshot.cash),
            "freshness_status": snapshot.data_quality.freshness_status,
        },
        "holdings": [
            {
                "asset_id": holding.asset_id,
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
        "cash": [
            {
                "currency": cash.currency,
                "amount": cash.amount,
                "weight": cash.weight,
            }
            for cash in snapshot.cash
        ],
        "history_status": history_context.history_status,
        "latest_state_available": history_context.latest_portfolio_state is not None,
        "portfolio_growth": list(history_context.portfolio_growth),
        "allocation_history": list(history_context.allocation_history),
    }


def _sanitize_position_changes(changes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sanitized = []
    for change in changes:
        payload = dict(change)
        payload.pop("account_id", None)
        sanitized.append(payload)
    return sanitized


def _detect_portfolio_patterns(
    *,
    evidence_plan: PortfolioEvidencePlan | None,
    snapshot: PortfolioSnapshot,
    portfolio_packet: PortfolioAgentPacket,
    effective_cash: EffectiveCashSummary,
    history_context: PortfolioHistoryContext,
    ips: InvestmentPolicy,
    warnings: list[str],
) -> list[dict[str, Any]]:
    detectors = set(evidence_plan.pattern_detectors if evidence_plan else [])
    if not detectors:
        detectors = {
            "concentration",
            "cash_effective_cash",
            "stale_data",
            "unsupported_quote_warnings",
            "portfolio_outliers",
        }
    patterns: list[dict[str, Any]] = []
    if "concentration" in detectors:
        limit = max(
            ips.max_single_stock_concentration,
            PORTFOLIO_PATTERN_THRESHOLDS["single_position_concentration_weight"],
        )
        for holding in snapshot.holdings:
            if abs(holding.portfolio_weight) > limit:
                patterns.append(
                    {
                        "type": "concentration",
                        "severity": "high",
                        "ticker": holding.ticker,
                        "weight": holding.portfolio_weight,
                        "threshold": limit,
                        "description": "Holding weight exceeds the concentration threshold.",
                    }
                )
    if "cash_effective_cash" in detectors:
        gap = effective_cash.effective_cash_weight - ips.target_cash_allocation
        if abs(gap) >= PORTFOLIO_PATTERN_THRESHOLDS["effective_cash_target_gap"]:
            patterns.append(
                {
                    "type": "cash_effective_cash",
                    "severity": "medium",
                    "effective_cash_weight": effective_cash.effective_cash_weight,
                    "target_cash_allocation": ips.target_cash_allocation,
                    "description": "Effective cash differs from the IPS target cash allocation.",
                }
            )
    if "stale_data" in detectors:
        freshness = str(
            (history_context.history_status.get("data_quality") or {}).get(
                "freshness_status",
                snapshot.data_quality.freshness_status,
            )
        )
        if freshness != "fresh" or snapshot.data_quality.freshness_status != "fresh":
            patterns.append(
                {
                    "type": "stale_data",
                    "severity": "medium",
                    "freshness_status": freshness,
                    "description": "Portfolio evidence is not confirmed fresh.",
                }
            )
    if "unsupported_quote_warnings" in detectors:
        quote_warnings = [
            warning
            for warning in warnings
            if "quote" in warning.casefold()
            or "unsupported" in warning.casefold()
            or "otc" in warning.casefold()
        ]
        for warning in quote_warnings:
            patterns.append(
                {
                    "type": "unsupported_quote_warnings",
                    "severity": "medium",
                    "description": warning,
                }
            )
    if "large_position_changes" in detectors:
        for change in history_context.position_state_changes:
            quantity_delta = change.get("quantity_delta")
            if quantity_delta is not None and abs(float(quantity_delta)) >= (
                PORTFOLIO_PATTERN_THRESHOLDS["large_quantity_delta_abs"]
            ):
                patterns.append(
                    {
                        "type": "large_position_changes",
                        "severity": "medium",
                        "ticker": change.get("ticker"),
                        "quantity_delta": quantity_delta,
                        "description": "Position quantity changed by the configured threshold.",
                    }
                )
    if "average_cost_shifts" in detectors:
        for change in history_context.position_state_changes:
            previous = change.get("previous_average_cost")
            delta = change.get("average_cost_delta")
            if previous in (None, 0) or delta is None:
                continue
            pct_delta = abs(float(delta)) / abs(float(previous))
            if pct_delta >= PORTFOLIO_PATTERN_THRESHOLDS["average_cost_delta_pct"]:
                patterns.append(
                    {
                        "type": "average_cost_shifts",
                        "severity": "medium",
                        "ticker": change.get("ticker"),
                        "average_cost_delta_pct": pct_delta,
                        "description": "Average cost changed by the configured threshold.",
                    }
                )
    if "allocation_drift" in detectors:
        for holding in snapshot.holdings:
            if abs(holding.portfolio_weight) >= (
                PORTFOLIO_PATTERN_THRESHOLDS["large_allocation_weight"]
            ):
                patterns.append(
                    {
                        "type": "allocation_drift",
                        "severity": "low",
                        "ticker": holding.ticker,
                        "weight": holding.portfolio_weight,
                        "description": (
                            "Holding is material enough to include in allocation review."
                        ),
                    }
                )
    if "portfolio_outliers" in detectors:
        for issue in portfolio_packet.candidate_issues:
            patterns.append(
                {
                    "type": issue.issue_type,
                    "severity": issue.severity,
                    "description": issue.description,
                    "evidence": list(issue.evidence),
                }
            )
    return patterns


def _portfolio_interpretation(evaluation: PortfolioEvaluation) -> list[str]:
    values = [evaluation.summary]
    values.extend(evaluation.strengths)
    values.extend(evaluation.risks)
    values.extend(evaluation.ips_mismatches)
    values.extend(evaluation.history_observations)
    values.extend(evaluation.open_questions)
    return _dedupe([value for value in values if value])


def _evidence_limitations(
    evidence_plan: PortfolioEvidencePlan | None,
    history_context: PortfolioHistoryContext,
    warnings: list[str],
) -> list[str]:
    limitations = ["No sentiment or fundamental evidence was reviewed by Portfolio Agent."]
    if history_context.history_status.get("skipped"):
        limitations.append("SQL history was skipped because the evidence plan did not need it.")
    if (
        evidence_plan
        and "position_state_changes" in evidence_plan.history_queries
        and not history_context.position_state_changes
    ):
        limitations.append("No position-state changes matched the resolved scope and time range.")
    for asset in evidence_plan.resolved_assets if evidence_plan else []:
        if asset.resolution_status != "resolved":
            limitations.append(
                f"Asset hint '{asset.input}' resolved as {asset.resolution_status}."
            )
    for warning in warnings:
        lowered = warning.casefold()
        if "stale" in lowered or "no stored" in lowered or "unavailable" in lowered:
            limitations.append(warning)
    return _dedupe(limitations)


def _sentiment_context_needs(
    evidence_plan: PortfolioEvidencePlan | None,
    detected_patterns: list[dict[str, Any]],
) -> list[str]:
    if not evidence_plan:
        return []
    if "sentiment_context_needed" not in evidence_plan.pattern_detectors:
        return []
    needs = [
        "Investment Agent may request Sentiment Agent context for market or fundamental evidence."
    ]
    if detected_patterns:
        needs.append("Portfolio patterns are available as candidate context for sentiment review.")
    return needs


def _history_status_is_fresh(history_status: dict[str, Any] | None) -> bool:
    if not history_status:
        return False
    data_quality = history_status.get("data_quality") or {}
    return data_quality.get("freshness_status") == "fresh"


def _empty_portfolio_snapshot(
    portfolio_id: str,
    *,
    base_currency: str,
    reason: str,
) -> PortfolioSnapshot:
    now = datetime.now(UTC)
    return PortfolioSnapshot(
        portfolio_id=portfolio_id,
        as_of=now,
        base_currency=base_currency,
        total_value=Money(amount=0.0, currency=base_currency, source="empty", as_of=now),
        cash=[],
        holdings=[],
        data_quality=DataQuality(
            freshness_status="unknown",
            missing_fields=["portfolio_snapshot"],
            warnings=[f"Portfolio snapshot unavailable: {reason}."],
        ),
    )


def _result_warnings(
    packet: PortfolioAgentPacket,
    history_status: dict[str, Any],
    evaluation: PortfolioEvaluation,
    plan: PortfolioContextPlan,
    *,
    current_context_warnings: list[str] | None = None,
) -> list[str]:
    warnings = list(packet.data_quality.warnings)
    warnings.extend(plan.warnings)
    warnings.extend(packet.performance.warnings)
    warnings.extend(history_status.get("data_quality", {}).get("warnings", []))
    warnings.extend(evaluation.warnings)
    warnings.extend(current_context_warnings or [])
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
