from __future__ import annotations

import re
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
PortfolioTaskIntent = Literal[
    "full_review",
    "portfolio_fact",
    "risk_check",
    "what_changed",
    "deep_dive",
    "compare",
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
PortfolioOutputGoal = Literal[
    "snapshot",
    "allocation_context",
    "performance_context",
    "risk_context",
    "effective_cash",
    "position_changes",
    "portfolio_patterns",
    "derived_metrics",
    "sentiment_context_needs",
]
FreshnessRequirement = Literal["latest_required", "cached_ok", "history_only"]
AssetResolutionStatus = Literal[
    "resolved",
    "ambiguous",
    "not_in_portfolio",
    "unsupported_market",
    "unknown",
]
PositionChangeScope = Literal[
    "none",
    "asset_scoped",
    "ticker_scoped",
    "portfolio_wide",
]
PersistenceMode = Literal["auto", "persist", "skip"]
AnswerConstraint = Literal[
    "no_trade_execution",
    "no_order_preparation",
    "no_exact_share_count",
    "source_backed",
    "portfolio_only",
]
HistoryQuery = Literal[
    "none",
    "history_status",
    "latest_state",
    "portfolio_growth",
    "allocation_history",
    "position_state_changes",
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
TracePhase = Literal[
    "investment_planner",
    "portfolio_request_validator",
    "asset_resolver",
    "portfolio_evidence_planner",
    "portfolio_policy",
    "deterministic_tool_execution",
    "synthesis",
    "guardrail",
]
SubagentName = Literal[
    "investment_agent",
    "portfolio_agent",
    "sentiment_agent",
    "guardrails",
    "memory",
]


class AssetHint(StrictModel):
    raw_input: str
    market_hint: str | None = None
    company_entity_label: str | None = None
    source_field: str = Field(default="user_query", min_length=1)

    @field_validator("raw_input")
    @classmethod
    def _validate_raw_input(cls, raw_input: str) -> str:
        if not raw_input.strip():
            raise ValueError("raw_input must contain a logical asset hint.")
        return raw_input

    @field_validator("market_hint")
    @classmethod
    def _normalize_market_hint(cls, market_hint: str | None) -> str | None:
        if market_hint is None:
            return None
        normalized = market_hint.strip().upper()
        return normalized or None


class AssetResolution(StrictModel):
    input: str = Field(min_length=1)
    canonical_symbol: str | None = None
    sql_asset_id: str | None = None
    display_name: str | None = None
    resolution_status: AssetResolutionStatus
    warnings: list[str] = Field(default_factory=list)
    source: str = Field(default="asset_resolver", min_length=1)

    @field_validator("canonical_symbol")
    @classmethod
    def _normalize_canonical_symbol(cls, symbol: str | None) -> str | None:
        if symbol is None:
            return None
        normalized = symbol.strip().upper()
        return normalized or None

    @model_validator(mode="after")
    def _validate_resolved_identifiers(self) -> AssetResolution:
        if self.resolution_status == "resolved" and not self.canonical_symbol:
            raise ValueError("resolved assets require canonical_symbol.")
        return self


class PortfolioRequest(StrictModel):
    task_intent: PortfolioTaskIntent
    asset_hints: list[AssetHint] = Field(default_factory=list)
    time_range: str | None = "30d"
    freshness_requirement: FreshnessRequirement = "cached_ok"
    output_goals: list[PortfolioOutputGoal] = Field(default_factory=lambda: ["snapshot"])
    source_query: str
    warnings: list[str] = Field(default_factory=list)

    @field_validator("time_range")
    @classmethod
    def _validate_time_range(cls, time_range: str | None) -> str | None:
        return _validate_optional_window(time_range)

    @field_validator("output_goals")
    @classmethod
    def _validate_output_goals(
        cls,
        output_goals: list[PortfolioOutputGoal],
    ) -> list[PortfolioOutputGoal]:
        if not output_goals:
            raise ValueError("PortfolioRequest output_goals cannot be empty.")
        return _dedupe_strings(output_goals)

    @field_validator("source_query")
    @classmethod
    def _validate_source_query(cls, source_query: str) -> str:
        if not source_query.strip():
            raise ValueError("PortfolioRequest source_query cannot be blank.")
        return source_query


class InvestmentPlan(StrictModel):
    mode: InvestmentMode
    needs_portfolio_agent: bool
    needs_sentiment_agent: bool
    portfolio_request: PortfolioRequest | None = None
    sentiment_task: SentimentTask | None = None
    logical_asset_hints: list[AssetHint] = Field(default_factory=list)
    themes: list[str] = Field(default_factory=list)
    time_horizon: str | None = "90d"
    freshness_requirement: FreshnessRequirement = "cached_ok"
    answer_constraints: list[AnswerConstraint] = Field(
        default_factory=lambda: [
            "no_trade_execution",
            "no_order_preparation",
            "no_exact_share_count",
        ]
    )
    warnings: list[str] = Field(default_factory=list)

    @field_validator("time_horizon")
    @classmethod
    def _validate_time_horizon(cls, time_horizon: str | None) -> str | None:
        return _validate_optional_window(time_horizon)

    @field_validator("answer_constraints")
    @classmethod
    def _validate_answer_constraints(
        cls,
        answer_constraints: list[AnswerConstraint],
    ) -> list[AnswerConstraint]:
        if not answer_constraints:
            raise ValueError("InvestmentPlan answer_constraints cannot be empty.")
        return _dedupe_strings(answer_constraints)

    @model_validator(mode="after")
    def _validate_planner_routing(self) -> InvestmentPlan:
        if self.needs_portfolio_agent and self.portfolio_request is None:
            raise ValueError(
                "portfolio_request is required when needs_portfolio_agent is true."
            )
        if not self.needs_portfolio_agent and self.portfolio_request is not None:
            raise ValueError(
                "portfolio_request must be omitted when needs_portfolio_agent is false."
            )
        if self.needs_sentiment_agent and self.sentiment_task is None:
            raise ValueError("sentiment_task is required when needs_sentiment_agent is true.")
        if not self.needs_sentiment_agent and self.sentiment_task is not None:
            raise ValueError("sentiment_task must be omitted when needs_sentiment_agent is false.")
        return self


class PortfolioEvidencePlan(StrictModel):
    task_intent: PortfolioTaskIntent
    resolved_assets: list[AssetResolution] = Field(default_factory=list)
    history_queries: list[HistoryQuery] = Field(default_factory=lambda: ["history_status"])
    metric_groups: list[MetricGroup] = Field(default_factory=lambda: ["allocation"])
    needs_current_values: bool = True
    history_window: str | None = "30d"
    freshness_requirement: FreshnessRequirement = "cached_ok"
    position_change_scope: PositionChangeScope = "none"
    persistence_mode: PersistenceMode = "auto"
    pattern_detectors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    @field_validator("history_window")
    @classmethod
    def _validate_history_window(cls, history_window: str | None) -> str | None:
        return _validate_optional_window(history_window)

    @field_validator("pattern_detectors")
    @classmethod
    def _dedupe_pattern_detectors(cls, pattern_detectors: list[str]) -> list[str]:
        return _dedupe_strings(pattern_detectors)

    @model_validator(mode="after")
    def _validate_history_queries(self) -> PortfolioEvidencePlan:
        if "none" in self.history_queries and len(self.history_queries) > 1:
            raise ValueError("history_queries cannot combine 'none' with other history queries.")
        return self


class PortfolioEvidencePacket(StrictModel):
    portfolio_id: str
    task_intent: PortfolioTaskIntent
    resolved_assets: list[AssetResolution] = Field(default_factory=list)
    facts: dict[str, Any] = Field(default_factory=dict)
    derived_metrics: dict[str, Any] = Field(default_factory=dict)
    position_changes: list[dict[str, Any]] = Field(default_factory=list)
    detected_patterns: list[dict[str, Any] | str] = Field(default_factory=list)
    portfolio_only_interpretation: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    needs_sentiment_context: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    tool_refs: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _reject_trade_execution_interpretation(self) -> PortfolioEvidencePacket:
        checked_values = (
            list(self.portfolio_only_interpretation)
            + list(self.limitations)
            + _flatten_packet_pattern_strings(self.detected_patterns)
        )
        for value in checked_values:
            if _contains_trade_execution_language(value):
                raise ValueError(
                    "PortfolioEvidencePacket cannot contain final recommendation or "
                    "trade execution language."
                )
        return self


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


class PortfolioAgentEvidencePacket(StrictModel):
    portfolio_id: str
    context_plan: PortfolioContextPlan
    base_packet: PortfolioAgentPacket | None = None
    history_context: dict[str, Any] = Field(default_factory=dict)
    effective_cash: dict[str, Any] = Field(default_factory=dict)
    sentiment_candidates: list[SentimentCandidate] = Field(default_factory=list)
    tool_calls: list[str] = Field(default_factory=list)
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
            summary="GraphRAG sentiment retrieval is not implemented."
        )
    )
    contradictions: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    source_metadata: dict[str, Any] = Field(default_factory=dict)
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
        if self.contradictions or self.open_questions or self.source_metadata:
            raise ValueError(
                "SentimentPacket with retrieval_status='not_implemented' cannot include "
                "research-derived contradictions, open questions, or source metadata."
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
    portfolio_packet: PortfolioAgentEvidencePacket | None = None
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
    phase: TracePhase | None = None
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
    investment_plan: InvestmentPlan | None = None
    query_plan: InvestmentQueryPlan | None = None
    memory_context: list[MemoryRecord] = Field(default_factory=list)
    portfolio_packet: PortfolioAgentEvidencePacket | None = None
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


def _validate_optional_window(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    if not normalized:
        return None
    if not re.fullmatch(r"\d+(?:d|w|m|y)", normalized):
        raise ValueError("time window must use forms like 30d, 12w, 6m, or 1y.")
    return normalized


def _dedupe_strings(values: list[str]) -> list:
    deduped = []
    seen = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


def _flatten_packet_pattern_strings(patterns: list[dict[str, Any] | str]) -> list[str]:
    values: list[str] = []
    for pattern in patterns:
        if isinstance(pattern, str):
            values.append(pattern)
        elif isinstance(pattern, dict):
            for value in pattern.values():
                if isinstance(value, str):
                    values.append(value)
                elif isinstance(value, list):
                    values.extend(item for item in value if isinstance(item, str))
    return values


def _contains_trade_execution_language(value: str) -> bool:
    lowered = value.casefold()
    phrases = (
        "place order",
        "submit order",
        "execute trade",
        "trade execution",
        "order preparation",
        "market order",
        "limit order",
        "final recommendation: buy",
        "final recommendation: sell",
        "buy exactly",
        "sell exactly",
        "exact share count",
        "exact share-count",
    )
    return any(phrase in lowered for phrase in phrases)


InvestmentPlan.model_rebuild()
