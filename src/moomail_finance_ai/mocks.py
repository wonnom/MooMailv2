from __future__ import annotations

from datetime import UTC, datetime

from moomail_finance_ai.schemas import (
    AllocationSlice,
    CandidateIssue,
    CashBalance,
    Citation,
    DataQuality,
    Holding,
    InvestmentPolicy,
    MemoryRecord,
    Money,
    PerformanceSummary,
    PortfolioAgentPacket,
    PortfolioLevelSentiment,
    PortfolioSnapshot,
    RiskSummary,
    SentimentAgentPacket,
    SentimentHolding,
    SentimentScopeItem,
)


def fixed_now() -> datetime:
    return datetime(2026, 5, 23, 0, 0, tzinfo=UTC)


def mock_investment_policy() -> InvestmentPolicy:
    return InvestmentPolicy(
        policy_id="ips_default",
        portfolio_id="portfolio_default",
        benchmark="SPY",
        goals=["Long-term risk-adjusted growth", "Preserve flexibility with a modest cash buffer"],
        time_horizon="Long-term, generally 3 to 10 years",
        risk_tolerance="Moderate to high, with attention to concentration and drawdown risk",
        target_cash_allocation=0.05,
        max_single_stock_concentration=0.25,
        material_holding_threshold=0.05,
        sector_concentration_limits={"Information Technology": 0.55},
        preferred_asset_classes=["US equities", "ETFs"],
        forbidden_assets=[],
        personal_beliefs=[
            "Prefer long-term ownership over short-term trading",
            "Use research-backed thesis updates rather than price action alone",
        ],
    )


def mock_memory_records() -> list[MemoryRecord]:
    now = fixed_now()
    return [
        MemoryRecord(
            memory_id="mem_long_horizon",
            memory_type="user_preference",
            scope={"portfolio_id": "portfolio_default"},
            content="The user prefers long-term portfolio analysis over short-term trading.",
            created_at=now,
            requires_user_approval=True,
        ),
        MemoryRecord(
            memory_id="mem_concentration_watch",
            memory_type="risk_concern",
            scope={"portfolio_id": "portfolio_default"},
            content="Prior reviews should pay attention to mega-cap technology concentration.",
            created_at=now,
        ),
    ]


def mock_portfolio_packet() -> PortfolioAgentPacket:
    now = fixed_now()
    holdings = [
        Holding(
            asset_id="asset_msft_us",
            ticker="MSFT",
            name="Microsoft Corporation",
            asset_type="equity",
            exchange="NASDAQ",
            currency="USD",
            quantity=80,
            market_price=500.0,
            market_value=40000.0,
            portfolio_weight=0.40,
            unrealized_pnl=8000.0,
            sector="Information Technology",
            source="mock_moomoo",
            as_of=now,
        ),
        Holding(
            asset_id="asset_aapl_us",
            ticker="AAPL",
            name="Apple Inc.",
            asset_type="equity",
            exchange="NASDAQ",
            currency="USD",
            quantity=120,
            market_price=250.0,
            market_value=30000.0,
            portfolio_weight=0.30,
            unrealized_pnl=3000.0,
            sector="Information Technology",
            source="mock_moomoo",
            as_of=now,
        ),
        Holding(
            asset_id="asset_vti_us",
            ticker="VTI",
            name="Vanguard Total Stock Market ETF",
            asset_type="etf",
            exchange="NYSEARCA",
            currency="USD",
            quantity=100,
            market_price=250.0,
            market_value=25000.0,
            portfolio_weight=0.25,
            unrealized_pnl=2500.0,
            sector="Diversified",
            source="mock_moomoo",
            as_of=now,
        ),
    ]
    snapshot = PortfolioSnapshot(
        portfolio_id="portfolio_default",
        as_of=now,
        base_currency="USD",
        total_value=Money(amount=100000.0, currency="USD", source="mock_moomoo", as_of=now),
        cash=[CashBalance(account_id="mock_moomoo_primary", amount=5000.0, currency="USD", weight=0.05)],
        holdings=holdings,
        data_quality=DataQuality(
            freshness_status="fresh",
            warnings=["Mock portfolio data; replace with OpenD in Milestone 2."],
        ),
    )
    return PortfolioAgentPacket(
        portfolio_id="portfolio_default",
        snapshot=snapshot,
        allocation={
            "by_asset": [
                AllocationSlice(name="MSFT", value=40000.0, weight=0.40, currency="USD"),
                AllocationSlice(name="AAPL", value=30000.0, weight=0.30, currency="USD"),
                AllocationSlice(name="VTI", value=25000.0, weight=0.25, currency="USD"),
                AllocationSlice(name="Cash", value=5000.0, weight=0.05, currency="USD"),
            ],
            "by_sector": [
                AllocationSlice(
                    name="Information Technology", value=70000.0, weight=0.70, currency="USD"
                ),
                AllocationSlice(name="Diversified", value=25000.0, weight=0.25, currency="USD"),
                AllocationSlice(name="Cash", value=5000.0, weight=0.05, currency="USD"),
            ],
            "by_currency": [AllocationSlice(name="USD", value=100000.0, weight=1.0, currency="USD")],
        },
        performance=PerformanceSummary(
            summary=(
                "Mock performance view: unrealized gains are positive, but transaction-level "
                "history is unavailable, so attribution is incomplete."
            ),
            periods=[],
            benchmark="SPY",
            warnings=["No SQL history is available in the static prototype."],
        ),
        risk=RiskSummary(
            concentration=[
                {"ticker": "MSFT", "weight": 0.40, "limit": 0.25},
                {"ticker": "AAPL", "weight": 0.30, "limit": 0.25},
                {"sector": "Information Technology", "weight": 0.70, "limit": 0.55},
            ],
            volatility=None,
            drawdown=None,
            beta=None,
            warnings=["Volatility, drawdown, and beta require historical price or snapshot data."],
        ),
        candidate_issues=[
            CandidateIssue(
                issue_type="single_position_concentration",
                description="MSFT and AAPL exceed the mock IPS single-stock concentration limit.",
                evidence=["MSFT weight 40%", "AAPL weight 30%", "IPS limit 25%"],
                severity="high",
            ),
            CandidateIssue(
                issue_type="sector_concentration",
                description="Technology exposure exceeds the mock IPS sector limit.",
                evidence=["Information Technology weight 70%", "IPS limit 55%"],
                severity="medium",
            ),
        ],
        data_quality=snapshot.data_quality,
    )


def mock_sentiment_packet(scope: list[SentimentScopeItem]) -> SentimentAgentPacket:
    citations = {
        "MSFT": Citation(
            citation_id="cite_msft_transcript_mock",
            source_type="earnings_transcript",
            title="Microsoft Mock Earnings Transcript",
            publisher="Company",
            document_date="2026-04-25",
            ingestion_date="2026-05-23",
            ticker="MSFT",
            company="Microsoft Corporation",
            chunk_id="chunk_msft_ai_capex",
            document_id="doc_msft_mock_transcript",
            location={"section": "Prepared remarks"},
            snippet="Management emphasized durable cloud demand while noting continued AI infrastructure spend.",
            source_quality="primary",
        ),
        "AAPL": Citation(
            citation_id="cite_aapl_report_mock",
            source_type="quarterly_report",
            title="Apple Mock Quarterly Report",
            publisher="Company",
            document_date="2026-05-01",
            ingestion_date="2026-05-23",
            ticker="AAPL",
            company="Apple Inc.",
            chunk_id="chunk_aapl_services",
            document_id="doc_aapl_mock_report",
            location={"section": "Segment discussion"},
            snippet="Services growth helped offset uneven hardware demand across regions.",
            source_quality="primary",
        ),
    }
    requested = {item.ticker for item in scope}
    holdings: list[SentimentHolding] = []
    if "MSFT" in requested:
        holdings.append(
            SentimentHolding(
                ticker="MSFT",
                company="Microsoft Corporation",
                stance="positive",
                thesis_summary="Cloud and AI platform demand remain the central mock thesis.",
                recent_developments=["AI infrastructure spending remains elevated."],
                management_tone="Constructive, with emphasis on durable enterprise demand.",
                risks=["Capital intensity could pressure future free cash flow."],
                catalysts=["Continued cloud adoption and AI workload growth."],
                contradictions=["Higher capex may delay margin expansion."],
                open_questions=["How quickly does AI investment convert into incremental revenue?"],
                citations=[citations["MSFT"]],
            )
        )
    if "AAPL" in requested:
        holdings.append(
            SentimentHolding(
                ticker="AAPL",
                company="Apple Inc.",
                stance="mixed",
                thesis_summary="Services durability is constructive, while hardware growth is less clear.",
                recent_developments=["Services continued to support overall profitability."],
                management_tone="Measured and operationally disciplined.",
                risks=["Hardware replacement cycles may stay uneven."],
                catalysts=["Services growth and product refresh cycles."],
                contradictions=["Premium valuation may leave less room for uneven growth."],
                open_questions=["Does services growth offset regional hardware weakness enough?"],
                citations=[citations["AAPL"]],
            )
        )
    portfolio_citations = [citation for holding in holdings for citation in holding.citations]
    return SentimentAgentPacket(
        scope=scope,
        holdings=holdings,
        portfolio_level_sentiment=PortfolioLevelSentiment(
            summary=(
                "Mock research context is constructive but concentrated in large technology "
                "earnings durability and AI-related execution."
            ),
            themes=["Mega-cap technology durability", "AI capital intensity", "Services resilience"],
            risks=["Portfolio qualitative risk is tied to technology growth assumptions."],
            citations=portfolio_citations,
        ),
        data_quality=DataQuality(
            freshness_status="unknown",
            missing_fields=["Real research corpus"],
            warnings=["Mock research packet; replace with GraphRAG retrieval in Milestone 4."],
        ),
    )

