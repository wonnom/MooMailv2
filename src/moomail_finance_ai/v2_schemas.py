from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from moomail_finance_ai.schemas import (
    Citation,
    DataQuality,
    FinalReport,
    GuardrailCheck,
    InvestmentPolicy,
    MemoryRecord,
    PortfolioAgentPacket,
    PortfolioLevelSentiment,
    SentimentHolding,
    SentimentScopeItem,
    StrictModel,
)


InvestmentMode = Literal[
    "review",
    "portfolio_fact",
    "risk_check",
    "what_changed",
    "deep_dive",
    "compare",
    "unsupported",
]
PortfolioTaskType = Literal[
    "full_review",
    "portfolio_fact",
    "risk_check",
    "what_changed",
    "deep_dive",
    "compare",
    "unsupported",
]
PortfolioOutputKind = Literal[
    "snapshot",
    "allocation",
    "performance",
    "risk",
    "effective_cash",
    "candidate_issues",
    "sentiment_candidates",
    "history_context",
]
PersistenceMode = Literal["auto", "persist", "skip"]
HistoryQuery = Literal[
    "none",
    "history_status",
    "latest_state",
    "portfolio_growth",
    "allocation_history",
]
MetricGroup = Literal[
    "allocation",
    "concentration",
    "effective_cash",
    "risk",
    "performance",
    "all",
]
SentimentCandidateEvidenceType = Literal[
    "portfolio_fact",
    "holding_weight",
    "risk_metric",
    "performance_change",
    "history_change",
    "user_named",
]
EvidenceType = Literal[
    "filing",
    "earnings_transcript",
    "shareholder_letter",
    "annual_report",
    "quarterly_report",
    "research_note",
    "management_commentary",
    "unknown",
]
RetrievalStatus = Literal[
    "not_implemented",
    "missing_corpus",
    "empty_result",
    "partial",
    "sufficient",
]
GuardrailOutputStatus = Literal["approved", "revised", "blocked"]
TraceEventType = Literal[
    "status",
    "graph_node",
    "subagent_call",
    "tool_call",
    "warning",
    "error",
]
SubagentName = Literal[
    "investment_agent",
    "portfolio_agent",
    "sentiment_agent",
    "guardrails",
    "memory",
]


class PortfolioTask(StrictModel):
    task_type: PortfolioTaskType = "full_review"
    source_query: str
    requested_tickers: list[str] = Field(default_factory=list)
    history_window: str | None = "30d"
    required_outputs: list[PortfolioOutputKind] = Field(
        default_factory=lambda: [
            "snapshot",
            "allocation",
            "risk",
            "effective_cash",
            "candidate_issues",
            "sentiment_candidates",
        ]
    )
    persistence_mode: PersistenceMode = "auto"
    focus_areas: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    @field_validator("requested_tickers")
    @classmethod
    def _normalize_requested_tickers(cls, tickers: list[str]) -> list[str]:
        return _normalize_tickers(tickers)


class PortfolioContextPlan(StrictModel):
    needs_current_snapshot: bool = True
    needs_sql_history: bool = True
    history_queries: list[HistoryQuery] = Field(
        default_factory=lambda: ["history_status", "latest_state"]
    )
    tickers: list[str] = Field(default_factory=list)
    metric_groups: list[MetricGroup] = Field(
        default_factory=lambda: ["allocation", "concentration", "effective_cash"]
    )
    persist_observation: bool = True
    history_window: str | None = "30d"
    row_limit: int = Field(default=30, ge=1, le=500)
    warnings: list[str] = Field(default_factory=list)

    @field_validator("tickers")
    @classmethod
    def _normalize_plan_tickers(cls, tickers: list[str]) -> list[str]:
        return _normalize_tickers(tickers)

    @model_validator(mode="after")
    def _validate_history_intent(self) -> PortfolioContextPlan:
        if "none" in self.history_queries and len(self.history_queries) > 1:
            raise ValueError("history_queries cannot combine 'none' with other history queries.")
        if not self.needs_sql_history and self.history_queries != ["none"]:
            raise ValueError("history_queries must be ['none'] when needs_sql_history is false.")
        if self.needs_sql_history and self.history_queries == ["none"]:
            raise ValueError("history_queries cannot be ['none'] when needs_sql_history is true.")
        return self


class SentimentCandidate(StrictModel):
    ticker: str | None = None
    asset_id: str | None = None
    reason: str = Field(min_length=1)
    evidence_type: SentimentCandidateEvidenceType
    rank: int = Field(ge=1)
    source_portfolio_facts: dict[str, Any] = Field(default_factory=dict)

    @field_validator("ticker")
    @classmethod
    def _normalize_candidate_ticker(cls, ticker: str | None) -> str | None:
        if ticker is None:
            return None
        normalized = _normalize_tickers([ticker])
        return normalized[0] if normalized else None

    @model_validator(mode="after")
    def _require_asset_context(self) -> SentimentCandidate:
        if not self.ticker and not self.asset_id:
            raise ValueError("SentimentCandidate requires ticker or asset_id context.")
        return self


class V2PortfolioAgentPacket(StrictModel):
    portfolio_id: str
    context_plan: PortfolioContextPlan
    base_packet: PortfolioAgentPacket | None = None
    history_context: dict[str, Any] = Field(default_factory=dict)
    effective_cash: dict[str, Any] = Field(default_factory=dict)
    sentiment_candidates: list[SentimentCandidate] = Field(default_factory=list)
    data_quality: DataQuality = Field(default_factory=DataQuality)
    warnings: list[str] = Field(default_factory=list)


class SentimentTask(StrictModel):
    tickers: list[str] = Field(default_factory=list)
    companies_entities: list[str] = Field(default_factory=list)
    themes: list[str] = Field(default_factory=list)
    time_window: str | None = "1y"
    requested_evidence_types: list[EvidenceType] = Field(
        default_factory=lambda: [
            "filing",
            "earnings_transcript",
            "shareholder_letter",
            "annual_report",
            "quarterly_report",
        ]
    )
    key_questions: list[str] = Field(default_factory=list)
    reason: str = Field(default="Investment Agent requested sentiment/research context.")
    candidate_refs: list[SentimentCandidate] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    @field_validator("tickers")
    @classmethod
    def _normalize_sentiment_tickers(cls, tickers: list[str]) -> list[str]:
        return _normalize_tickers(tickers)

    @classmethod
    def from_candidates(
        cls,
        candidates: list[SentimentCandidate],
        *,
        reason: str = "Portfolio Agent suggested sentiment review candidates.",
        time_window: str | None = "1y",
        key_questions: list[str] | None = None,
    ) -> SentimentTask:
        return cls(
            tickers=[candidate.ticker for candidate in candidates if candidate.ticker],
            reason=reason,
            time_window=time_window,
            key_questions=key_questions or [],
            candidate_refs=candidates,
        )


class MissingResearchDocument(StrictModel):
    ticker: str | None = None
    entity: str | None = None
    document_type: EvidenceType | None = None
    reason: str


class SentimentPacket(StrictModel):
    retrieval_status: RetrievalStatus
    task: SentimentTask | None = None
    scope: list[SentimentScopeItem] = Field(default_factory=list)
    holdings: list[SentimentHolding] = Field(default_factory=list)
    portfolio_level_sentiment: PortfolioLevelSentiment = Field(
        default_factory=lambda: PortfolioLevelSentiment(
            summary="GraphRAG sentiment retrieval is not implemented in V2."
        )
    )
    missing_documents: list[MissingResearchDocument] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    data_quality: DataQuality = Field(default_factory=DataQuality)
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_stub_has_no_fake_research(self) -> SentimentPacket:
        if self.retrieval_status != "not_implemented":
            return self
        nested_citations = [
            citation
            for holding in self.holdings
            for citation in holding.citations
        ] + list(self.portfolio_level_sentiment.citations)
        if self.holdings or self.citations or nested_citations:
            raise ValueError(
                "SentimentPacket with retrieval_status='not_implemented' cannot include "
                "holdings or citations."
            )
        return self


class InvestmentQueryPlan(StrictModel):
    mode: InvestmentMode
    needs_portfolio_agent: bool
    needs_sentiment_agent: bool
    portfolio_task: PortfolioTask | None = None
    sentiment_task: SentimentTask | None = None
    missing_data: list[str] = Field(default_factory=list)
    plan_warnings: list[str] = Field(default_factory=list)
    route_reason: str | None = None

    @model_validator(mode="after")
    def _validate_routing_invariants(self) -> InvestmentQueryPlan:
        if self.needs_portfolio_agent and self.portfolio_task is None:
            raise ValueError("portfolio_task is required when needs_portfolio_agent is true.")
        if not self.needs_portfolio_agent and self.portfolio_task is not None:
            raise ValueError("portfolio_task must be omitted when needs_portfolio_agent is false.")
        if self.needs_sentiment_agent and self.sentiment_task is None:
            raise ValueError("sentiment_task is required when needs_sentiment_agent is true.")
        if not self.needs_sentiment_agent and self.sentiment_task is not None:
            raise ValueError("sentiment_task must be omitted when needs_sentiment_agent is false.")
        return self


class SynthesisInput(StrictModel):
    run_id: str
    user_query: str
    query_plan: InvestmentQueryPlan
    ips: InvestmentPolicy | None = None
    portfolio_packet: V2PortfolioAgentPacket | None = None
    sentiment_packet: SentimentPacket | None = None
    memory_context: list[MemoryRecord] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class GuardrailReview(StrictModel):
    passed: bool
    output_status: GuardrailOutputStatus
    checks: list[GuardrailCheck] = Field(min_length=1)
    required_revisions: list[str] = Field(default_factory=list)
    blocked_reason: str | None = None
    revised_output_summary: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_status_metadata(self) -> GuardrailReview:
        if self.output_status == "blocked" and not self.blocked_reason:
            raise ValueError("blocked guardrail reviews require blocked_reason.")
        if self.output_status == "revised" and not (
            self.required_revisions or self.revised_output_summary
        ):
            raise ValueError("revised guardrail reviews require revision metadata.")
        if not self.passed and not (self.required_revisions or self.blocked_reason):
            raise ValueError("failed guardrail reviews require revisions or blocked_reason.")
        return self


class TraceEvent(StrictModel):
    event_type: TraceEventType = "status"
    run_id: str
    status: str
    message: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    node: str | None = None
    subagent: SubagentName | None = None
    server_name: str | None = None
    tool_name: str | None = None
    input_summary: str | None = None
    output_summary: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    error_type: str | None = None
    error_message: str | None = None

    @model_validator(mode="after")
    def _validate_trace_specifics(self) -> TraceEvent:
        if self.event_type == "tool_call" and not self.tool_name:
            raise ValueError("tool_call trace events require tool_name.")
        if self.event_type == "subagent_call" and not self.subagent:
            raise ValueError("subagent_call trace events require subagent.")
        if self.event_type == "graph_node" and not self.node:
            raise ValueError("graph_node trace events require node.")
        if self.event_type == "error" and not (self.error_type or self.error_message):
            raise ValueError("error trace events require error_type or error_message.")
        return self


class InvestmentAgentState(StrictModel):
    run_id: str
    user_query: str
    mode: InvestmentMode | None = None
    portfolio_id: str = "portfolio_default"
    ips: InvestmentPolicy | None = None
    query_plan: InvestmentQueryPlan | None = None
    memory_context: list[MemoryRecord] = Field(default_factory=list)
    portfolio_packet: V2PortfolioAgentPacket | None = None
    sentiment_packet: SentimentPacket | None = None
    synthesis: SynthesisInput | None = None
    guardrail_review: GuardrailReview | None = None
    final_report: FinalReport | None = None
    status_events: list[TraceEvent] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    audit_refs: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_mode_consistency(self) -> InvestmentAgentState:
        if (
            self.mode is not None
            and self.query_plan is not None
            and self.mode != self.query_plan.mode
        ):
            raise ValueError("InvestmentAgentState mode must match query_plan mode.")
        return self


def _normalize_tickers(tickers: list[str]) -> list[str]:
    normalized = []
    seen = set()
    for ticker in tickers:
        value = ticker.strip().upper()
        if not value or value in seen:
            continue
        seen.add(value)
        normalized.append(value)
    return normalized
