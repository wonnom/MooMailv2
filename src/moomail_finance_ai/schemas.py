from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


FreshnessStatus = Literal["fresh", "stale", "unknown"]
Mode = Literal["review", "rebalance", "deep_dive", "risk_check", "what_changed", "buy_or_hold", "compare"]
SourceQuality = Literal["primary", "secondary", "commentary", "unknown"]
SentimentStance = Literal["positive", "mixed", "negative", "unclear"]
Severity = Literal["low", "medium", "high"]


class Money(StrictModel):
    amount: float
    currency: str = Field(min_length=3, max_length=3)
    source: str | None = None
    as_of: datetime | None = None


class DataQuality(StrictModel):
    freshness_status: FreshnessStatus = "unknown"
    missing_fields: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class Citation(StrictModel):
    citation_id: str
    source_type: str
    title: str
    publisher: str
    document_date: str | None = None
    ingestion_date: str | None = None
    ticker: str | None = None
    company: str | None = None
    chunk_id: str | None = None
    document_id: str
    location: dict[str, Any] = Field(default_factory=dict)
    snippet: str
    source_quality: SourceQuality = "unknown"


class CashBalance(StrictModel):
    account_id: str
    amount: float
    currency: str = Field(min_length=3, max_length=3)
    weight: float


class Holding(StrictModel):
    asset_id: str
    ticker: str
    name: str
    asset_type: str
    exchange: str | None = None
    currency: str = Field(min_length=3, max_length=3)
    quantity: float
    market_price: float
    market_value: float
    portfolio_weight: float
    unrealized_pnl: float | None = None
    sector: str | None = None
    source: str
    as_of: datetime


class PortfolioSnapshot(StrictModel):
    portfolio_id: str
    as_of: datetime
    base_currency: str = Field(min_length=3, max_length=3)
    total_value: Money
    cash: list[CashBalance]
    holdings: list[Holding]
    data_quality: DataQuality


class AllocationSlice(StrictModel):
    name: str
    value: float
    weight: float
    currency: str = Field(min_length=3, max_length=3)


class PerformanceSummary(StrictModel):
    summary: str
    periods: list[dict[str, Any]] = Field(default_factory=list)
    benchmark: str
    warnings: list[str] = Field(default_factory=list)


class RiskSummary(StrictModel):
    concentration: list[dict[str, Any]] = Field(default_factory=list)
    volatility: float | None = None
    drawdown: float | None = None
    beta: float | None = None
    correlation: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class CandidateIssue(StrictModel):
    issue_type: str
    description: str
    evidence: list[str] = Field(default_factory=list)
    severity: Severity


class PortfolioAgentPacket(StrictModel):
    portfolio_id: str
    snapshot: PortfolioSnapshot
    allocation: dict[str, list[AllocationSlice]]
    performance: PerformanceSummary
    risk: RiskSummary
    candidate_issues: list[CandidateIssue] = Field(default_factory=list)
    data_quality: DataQuality


class SentimentScopeItem(StrictModel):
    ticker: str
    reason: str


class SentimentHolding(StrictModel):
    ticker: str
    company: str
    stance: SentimentStance
    thesis_summary: str
    recent_developments: list[str] = Field(default_factory=list)
    management_tone: str | None = None
    risks: list[str] = Field(default_factory=list)
    catalysts: list[str] = Field(default_factory=list)
    contradictions: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)


class PortfolioLevelSentiment(StrictModel):
    summary: str
    themes: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)


class SentimentAgentPacket(StrictModel):
    scope: list[SentimentScopeItem]
    holdings: list[SentimentHolding]
    portfolio_level_sentiment: PortfolioLevelSentiment
    data_quality: DataQuality


class InvestmentPolicy(StrictModel):
    policy_id: str
    portfolio_id: str
    benchmark: str = "SPY"
    goals: list[str]
    time_horizon: str
    risk_tolerance: str
    target_cash_allocation: float
    max_single_stock_concentration: float
    material_holding_threshold: float = 0.05
    sector_concentration_limits: dict[str, float] = Field(default_factory=dict)
    preferred_asset_classes: list[str] = Field(default_factory=list)
    forbidden_assets: list[str] = Field(default_factory=list)
    personal_beliefs: list[str] = Field(default_factory=list)


class MemoryRecord(StrictModel):
    memory_id: str
    memory_type: Literal[
        "user_preference",
        "investment_thesis",
        "past_recommendation",
        "decision_record",
        "portfolio_review_summary",
        "risk_concern",
        "watchlist_interest",
        "agent_observation",
    ]
    scope: dict[str, Any] = Field(default_factory=dict)
    content: str
    created_at: datetime
    expires_at: datetime | None = None
    status: Literal["active", "inactive", "superseded"] = "active"
    source_run_id: str | None = None
    requires_user_approval: bool = False


class GuardrailCheck(StrictModel):
    check: str
    passed: bool
    message: str


class GuardrailResult(StrictModel):
    passed: bool
    checks: list[GuardrailCheck]
    required_revisions: list[str] = Field(default_factory=list)
    blocked_reason: str | None = None


class Recommendation(StrictModel):
    title: str
    rationale: str
    supporting_evidence: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    missing_data: list[str] = Field(default_factory=list)


class FinalReport(StrictModel):
    run_id: str
    mode: Mode
    title: str
    as_of: datetime
    summary: str
    portfolio_snapshot: dict[str, Any]
    portfolio_analysis: dict[str, Any]
    sentiment_analysis: dict[str, Any]
    recommendations: list[Recommendation]
    missing_data: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    disclaimer: str | None = None


class StatusEvent(StrictModel):
    event_type: Literal["status"] = "status"
    run_id: str
    status: str
    message: str
    timestamp: datetime


class AuditRecord(StrictModel):
    run_id: str
    timestamp: datetime
    user_query: str
    mode: Mode
    tools_called: list[str] = Field(default_factory=list)
    data_timestamps: list[str] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    guardrail_result: GuardrailResult
    output_summary: str
    memory_updates: list[MemoryRecord] = Field(default_factory=list)
