from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable
from uuid import uuid4

from moomail_finance_ai.config import OpenDConfig, load_opend_config
from moomail_finance_ai.guardrails import review_report
from moomail_finance_ai.memory import FileMemoryStore, seed_default_memories
from moomail_finance_ai.metrics import calculate_snapshot_metrics, v1_us_equity_holdings
from moomail_finance_ai.mocks import mock_investment_policy
from moomail_finance_ai.opend import MoomooOpenDClient, ReadOnlyOpenDClient, RecordedOpenDClient
from moomail_finance_ai.opend_portfolio import (
    OpenDPortfolioDataError,
    build_portfolio_agent_packet,
    build_portfolio_snapshot_from_report,
)
from moomail_finance_ai.research import LocalResearchStore, LocalSentimentAgent
from moomail_finance_ai.research_fixtures import build_sample_research_store
from moomail_finance_ai.schemas import (
    AgentState,
    AuditRecord,
    Citation,
    FinalReport,
    GuardrailCheck,
    GuardrailResult,
    InvestmentPolicy,
    PortfolioAgentPacket,
    Recommendation,
    SentimentScopeItem,
    StatusEvent,
)
from moomail_finance_ai.sql_store import PortfolioSqlStore


StatusCallback = Callable[[StatusEvent], None]


@dataclass
class FullInvestmentAgent:
    portfolio_client: ReadOnlyOpenDClient
    sql_store: PortfolioSqlStore
    memory_store: FileMemoryStore
    research_store: LocalResearchStore
    ips: InvestmentPolicy

    def run(self, query: str, *, status_callback: StatusCallback | None = None) -> AgentState:
        run_id = f"run_{uuid4().hex[:12]}"
        state = AgentState(run_id=run_id, user_query=query)
        emit = lambda status, message: self._emit(state, status, message, status_callback)

        emit("classifying_query", "Classifying the investment query.")
        state.mode = self._classify_query(query)

        emit("loading_policy", "Loading the canonical Investment Policy Statement.")
        state.ips = self.ips

        emit("retrieving_memory", "Retrieving long-term investment memory.")
        state.memory_context = self.memory_store.retrieve(query)

        emit("retrieving_portfolio", "Retrieving portfolio data and building a normalized snapshot.")
        try:
            report = self.portfolio_client.explore_fields()
            snapshot = build_portfolio_snapshot_from_report(
                report,
                portfolio_id=self.ips.portfolio_id,
                base_currency="USD",
            )
            state.portfolio_packet = build_portfolio_agent_packet(snapshot, self.ips, report)
        except Exception as exc:
            state.final_report = self._blocked_report(state, str(exc))
            emit("checking_guardrails", "Running final guardrail review.")
            state.guardrail_result = self._critical_data_guardrail(str(exc))
            emit("saving_audit_summary", "Saving blocked audit summary.")
            state.audit_record = self._build_audit_record(state)
            self.sql_store.store_audit_record(state.audit_record)
            emit("complete", "Portfolio review blocked by critical missing data.")
            return state

        emit("saving_snapshot", "Saving portfolio snapshot and metrics to SQL.")
        stored = self.sql_store.store_snapshot(state.portfolio_packet.snapshot, source_report=report)
        metrics = calculate_snapshot_metrics(state.portfolio_packet.snapshot, self.ips)
        self.sql_store.store_metrics(stored.snapshot_id, metrics)
        history_status = self.sql_store.history_status(self.ips.portfolio_id)

        emit("selecting_research_scope", "Selecting material US-equity holdings for research.")
        state.sentiment_scope = self._decide_sentiment_scope(state.portfolio_packet)

        emit("retrieving_research", "Retrieving curated research and sentiment evidence.")
        state.sentiment_packet = LocalSentimentAgent(self.research_store).run(state.sentiment_scope)

        emit("synthesizing_report", "Synthesizing the final portfolio review.")
        state.final_report = self._synthesize(state, history_status.data_quality.warnings)

        emit("checking_guardrails", "Running final guardrail review.")
        state.guardrail_result = review_report(state.final_report)

        emit("saving_audit_summary", "Saving audit summary and durable review memory.")
        state.audit_record = self._build_audit_record(state)
        if state.guardrail_result.passed:
            tickers = [item.ticker for item in state.sentiment_scope]
            memory = self.memory_store.write_review_summary(
                portfolio_id=self.ips.portfolio_id,
                run_id=state.run_id,
                summary=state.final_report.summary,
                tickers=tickers,
            )
            state.audit_record.memory_updates.append(memory)
        self.sql_store.store_audit_record(state.audit_record)

        emit("complete", "Full Investment Agent run complete.")
        return state

    def _emit(
        self,
        state: AgentState,
        status: str,
        message: str,
        status_callback: StatusCallback | None,
    ) -> None:
        event = StatusEvent(
            run_id=state.run_id,
            status=status,
            message=message,
            timestamp=datetime.now(UTC),
        )
        state.status_events.append(event)
        if status_callback is not None:
            status_callback(event)

    def _classify_query(self, query: str):
        lowered = query.lower()
        if "risk" in lowered:
            return "risk_check"
        if "rebalance" in lowered:
            return "rebalance"
        if "compare" in lowered:
            return "compare"
        if "hold" in lowered or "buy" in lowered:
            return "buy_or_hold"
        return "review"

    def _decide_sentiment_scope(self, portfolio_packet: PortfolioAgentPacket) -> list[SentimentScopeItem]:
        scope = []
        for holding in v1_us_equity_holdings(portfolio_packet.snapshot):
            if abs(holding.portfolio_weight) >= self.ips.material_holding_threshold:
                scope.append(
                    SentimentScopeItem(
                        ticker=holding.ticker,
                        reason=(
                            f"Material v1 US-equity holding with portfolio weight "
                            f"{holding.portfolio_weight:.2%}."
                        ),
                    )
                )
        return scope

    def _synthesize(self, state: AgentState, history_warnings: list[str]) -> FinalReport:
        assert state.mode is not None
        assert state.portfolio_packet is not None
        assert state.sentiment_packet is not None
        citations = _unique_citations(
            citation for holding in state.sentiment_packet.holdings for citation in holding.citations
        )
        missing_data = _missing_data(state, history_warnings)
        evidence_ids = [citation.citation_id for citation in citations]
        recommendations = [
            Recommendation(
                title="Use the v1 US-equity review as the decision boundary",
                rationale=(
                    "The full OpenD account snapshot is stored for accounting, while v1 analysis "
                    "focuses on US equities with curated research coverage and explicit gaps."
                ),
                supporting_evidence=evidence_ids,
                constraints=[
                    "No trade placement, executable order, or exact share-count instruction is provided.",
                    "Non-US-equity and non-equity holdings are preserved but outside v1 recommendation scope.",
                ],
                missing_data=missing_data,
            )
        ]
        return FinalReport(
            run_id=state.run_id,
            mode=state.mode,
            title="Full Portfolio Review",
            as_of=state.portfolio_packet.snapshot.as_of,
            summary=(
                "The full Investment Agent stored the portfolio snapshot, calculated deterministic "
                "metrics, retrieved long-term memory, and connected available curated research to "
                "the v1 US-equity review."
            ),
            portfolio_snapshot=state.portfolio_packet.snapshot.model_dump(mode="json"),
            portfolio_analysis={
                "allocation": {
                    key: [item.model_dump(mode="json") for item in values]
                    for key, values in state.portfolio_packet.allocation.items()
                },
                "performance": state.portfolio_packet.performance.model_dump(mode="json"),
                "risk": state.portfolio_packet.risk.model_dump(mode="json"),
                "candidate_issues": [
                    issue.model_dump(mode="json") for issue in state.portfolio_packet.candidate_issues
                ],
                "memory_context_count": len(state.memory_context),
            },
            sentiment_analysis=state.sentiment_packet.model_dump(mode="json"),
            recommendations=recommendations,
            missing_data=missing_data,
            assumptions=[
                "V1 recommendations are limited to US equities.",
                "Recorded OpenD data may be used when live OpenD is not explicitly requested.",
                f"The active IPS benchmark is {self.ips.benchmark}.",
            ],
            citations=citations,
            disclaimer=(
                "This is investment analysis for personal decision support, not licensed "
                "financial advice."
            ),
        )

    def _blocked_report(self, state: AgentState, reason: str) -> FinalReport:
        mode = state.mode or "review"
        return FinalReport(
            run_id=state.run_id,
            mode=mode,
            title="Portfolio Review Blocked",
            as_of=datetime.now(UTC),
            summary="Portfolio recommendations are blocked because critical portfolio data is missing.",
            portfolio_snapshot={},
            portfolio_analysis={},
            sentiment_analysis={},
            recommendations=[],
            missing_data=[f"Critical portfolio data unavailable: {reason}"],
            assumptions=["No recommendation was produced without portfolio context."],
            citations=[],
            disclaimer=(
                "This is investment analysis for personal decision support, not licensed "
                "financial advice."
            ),
        )

    def _critical_data_guardrail(self, reason: str) -> GuardrailResult:
        return GuardrailResult(
            passed=False,
            checks=[
                GuardrailCheck(
                    check="critical_portfolio_data",
                    passed=False,
                    message=f"Portfolio recommendations blocked: {reason}",
                )
            ],
            required_revisions=["Retrieve portfolio data before making recommendations."],
            blocked_reason="Critical portfolio data missing.",
        )

    def _build_audit_record(self, state: AgentState) -> AuditRecord:
        assert state.mode is not None
        assert state.final_report is not None
        assert state.guardrail_result is not None
        return AuditRecord(
            run_id=state.run_id,
            timestamp=datetime.now(UTC),
            user_query=state.user_query,
            mode=state.mode,
            tools_called=[
                "opend_client",
                "portfolio_sql_store",
                "finance_metrics",
                "research_store",
                "memory_store",
                "guardrail_review",
            ],
            data_timestamps=[state.final_report.as_of.isoformat()],
            source_ids=[citation.document_id for citation in state.final_report.citations],
            assumptions=state.final_report.assumptions,
            guardrail_result=state.guardrail_result,
            output_summary=state.final_report.summary,
            memory_updates=[],
        )


def build_default_full_agent(
    *,
    from_report: str | Path | None = "reports/opend/field-report.json",
    db_path: str | Path = "data/portfolio-history.sqlite",
    memory_path: str | Path = "data/investment-memory.json",
    env_file: str | Path | None = None,
) -> FullInvestmentAgent:
    config = load_opend_config(env_file=env_file)
    client: ReadOnlyOpenDClient
    if from_report is not None and Path(from_report).exists():
        client = RecordedOpenDClient.from_path(from_report)
    else:
        client = MoomooOpenDClient(config)

    memory_store = FileMemoryStore(memory_path)
    seed_default_memories(memory_store)
    return FullInvestmentAgent(
        portfolio_client=client,
        sql_store=PortfolioSqlStore(db_path),
        memory_store=memory_store,
        research_store=build_sample_research_store(),
        ips=mock_investment_policy(),
    )


def _missing_data(state: AgentState, history_warnings: list[str]) -> list[str]:
    missing = []
    if state.portfolio_packet:
        missing.extend(state.portfolio_packet.data_quality.missing_fields)
        missing.extend(state.portfolio_packet.data_quality.warnings)
        missing.extend(state.portfolio_packet.performance.warnings)
        missing.extend(state.portfolio_packet.risk.warnings)
    if state.sentiment_packet:
        missing.extend(state.sentiment_packet.data_quality.missing_fields)
        missing.extend(state.sentiment_packet.data_quality.warnings)
        for holding in state.sentiment_packet.holdings:
            missing.extend(holding.open_questions)
    missing.extend(history_warnings)
    return _dedupe(missing)


def _unique_citations(citations) -> list[Citation]:
    seen = set()
    unique = []
    for citation in citations:
        if citation.citation_id in seen:
            continue
        seen.add(citation.citation_id)
        unique.append(citation)
    return unique


def _dedupe(values: list[str]) -> list[str]:
    seen = set()
    result = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
