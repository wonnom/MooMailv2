from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import uuid4

from moomail_finance_ai.guardrails import review_report
from moomail_finance_ai.mocks import mock_investment_policy, mock_memory_records, mock_portfolio_packet
from moomail_finance_ai.mocks import mock_sentiment_packet
from moomail_finance_ai.schemas import (
    AgentState,
    AuditRecord,
    FinalReport,
    InvestmentPolicy,
    PortfolioAgentPacket,
    Recommendation,
    SentimentAgentPacket,
    SentimentScopeItem,
    StatusEvent,
)


@dataclass
class MockPortfolioAgent:
    calls: int = 0

    def run(self, query: str, ips: InvestmentPolicy) -> PortfolioAgentPacket:
        self.calls += 1
        return mock_portfolio_packet()


@dataclass
class MockSentimentAgent:
    calls: int = 0

    def run(self, scope: list[SentimentScopeItem]) -> SentimentAgentPacket:
        self.calls += 1
        return mock_sentiment_packet(scope)


@dataclass
class InvestmentAgentPrototype:
    portfolio_agent: MockPortfolioAgent = field(default_factory=MockPortfolioAgent)
    sentiment_agent: MockSentimentAgent = field(default_factory=MockSentimentAgent)

    def run(self, query: str) -> AgentState:
        run_id = f"run_{uuid4().hex[:12]}"
        state = AgentState(run_id=run_id, user_query=query)
        self._emit(state, "classifying_query", "Classifying the investment query.")
        state.mode = self._classify_query(query)

        self._emit(state, "loading_policy", "Loading the canonical Investment Policy Statement.")
        state.ips = mock_investment_policy()

        self._emit(state, "retrieving_memory", "Retrieving relevant long-term memory.")
        state.memory_context = mock_memory_records()

        self._emit(state, "retrieving_portfolio", "Calling the Portfolio Agent with mock data.")
        state.portfolio_packet = self.portfolio_agent.run(query, state.ips)

        self._emit(state, "selecting_research_scope", "Selecting portfolio holdings for research review.")
        state.sentiment_scope = self._decide_sentiment_scope(state.portfolio_packet, state.ips)

        if self._should_call_sentiment_agent(query):
            self._emit(state, "retrieving_research", "Calling the Sentiment Agent with mock research.")
            state.sentiment_packet = self.sentiment_agent.run(state.sentiment_scope)

        self._emit(state, "synthesizing_report", "Synthesizing the investment report.")
        state.final_report = self._synthesize(state)

        self._emit(state, "checking_guardrails", "Running final guardrail review.")
        state.guardrail_result = review_report(state.final_report)

        self._emit(state, "saving_audit_summary", "Creating a simple audit summary.")
        state.audit_record = self._build_audit_record(state)

        self._emit(state, "complete", "Prototype run complete.")
        return state

    def _emit(self, state: AgentState, status: str, message: str) -> None:
        state.status_events.append(
            StatusEvent(
                run_id=state.run_id,
                status=status,
                message=message,
                timestamp=datetime.now(UTC),
            )
        )

    def _classify_query(self, query: str):
        lowered = query.lower()
        if "risk" in lowered:
            return "risk_check"
        if "rebalance" in lowered:
            return "rebalance"
        if "compare" in lowered:
            return "compare"
        return "review"

    def _should_call_sentiment_agent(self, query: str) -> bool:
        mechanical_terms = ("cash balance", "allocation by ticker", "current holdings only")
        lowered = query.lower()
        return not any(term in lowered for term in mechanical_terms)

    def _decide_sentiment_scope(
        self,
        portfolio_packet: PortfolioAgentPacket,
        ips: InvestmentPolicy,
    ) -> list[SentimentScopeItem]:
        scope = []
        for holding in portfolio_packet.snapshot.holdings:
            if holding.asset_type == "equity" and holding.portfolio_weight >= ips.material_holding_threshold:
                scope.append(
                    SentimentScopeItem(
                        ticker=holding.ticker,
                        reason=(
                            f"Material equity holding with weight {holding.portfolio_weight:.0%}, "
                            f"above threshold {ips.material_holding_threshold:.0%}."
                        ),
                    )
                )
        return scope

    def _synthesize(self, state: AgentState) -> FinalReport:
        assert state.mode is not None
        assert state.ips is not None
        assert state.portfolio_packet is not None
        citations = []
        if state.sentiment_packet:
            citations = [
                citation
                for holding in state.sentiment_packet.holdings
                for citation in holding.citations
            ]
        portfolio = state.portfolio_packet
        sentiment = state.sentiment_packet
        missing_data = [
            "SQL portfolio history is not connected in Milestone 1.",
            "OpenD live data is not connected in Milestone 1.",
            "Real GraphRAG research retrieval is not connected in Milestone 1.",
        ]
        if portfolio.performance.warnings:
            missing_data.extend(portfolio.performance.warnings)
        if portfolio.risk.warnings:
            missing_data.extend(portfolio.risk.warnings)

        recommendations = [
            Recommendation(
                title="Treat concentration as the main portfolio risk to investigate",
                rationale=(
                    "The mock portfolio is heavily weighted toward MSFT, AAPL, and the technology "
                    "sector. This conflicts with the mock IPS concentration limits, so the first "
                    "optimization question is whether this concentration is intentional and still "
                    "supported by current thesis evidence."
                ),
                supporting_evidence=[citation.citation_id for citation in citations],
                constraints=[
                    "No trade execution or exact share-count recommendation is provided.",
                    "Use allocation ranges and IPS limits rather than executable orders.",
                ],
                missing_data=missing_data[:3],
            )
        ]

        return FinalReport(
            run_id=state.run_id,
            mode=state.mode,
            title="Mock Portfolio Review",
            as_of=portfolio.snapshot.as_of,
            summary=(
                "The mocked portfolio review flags concentration as the main issue: MSFT and AAPL "
                "are both above the mock IPS single-stock limit, while the available mock research "
                "is constructive but still tied to large-cap technology assumptions."
            ),
            portfolio_snapshot=portfolio.snapshot.model_dump(mode="json"),
            portfolio_analysis={
                "allocation": {
                    key: [slice_.model_dump(mode="json") for slice_ in slices]
                    for key, slices in portfolio.allocation.items()
                },
                "performance": portfolio.performance.model_dump(mode="json"),
                "risk": portfolio.risk.model_dump(mode="json"),
                "candidate_issues": [
                    issue.model_dump(mode="json") for issue in portfolio.candidate_issues
                ],
            },
            sentiment_analysis=sentiment.model_dump(mode="json") if sentiment else {},
            recommendations=recommendations,
            missing_data=missing_data,
            assumptions=[
                "Milestone 1 uses mocked data to validate contracts and orchestration.",
                f"The active IPS benchmark is {state.ips.benchmark}.",
            ],
            citations=citations,
            disclaimer=(
                "This is investment analysis for personal decision support, not licensed "
                "financial advice."
            ),
        )

    def _build_audit_record(self, state: AgentState) -> AuditRecord:
        assert state.mode is not None
        assert state.final_report is not None
        assert state.guardrail_result is not None
        source_ids = [citation.document_id for citation in state.final_report.citations]
        return AuditRecord(
            run_id=state.run_id,
            timestamp=datetime.now(UTC),
            user_query=state.user_query,
            mode=state.mode,
            tools_called=["mock_portfolio_agent", "mock_sentiment_agent", "guardrail_review"],
            data_timestamps=[state.final_report.as_of.isoformat()],
            source_ids=source_ids,
            assumptions=state.final_report.assumptions,
            guardrail_result=state.guardrail_result,
            output_summary=state.final_report.summary,
            memory_updates=[],
        )

