from __future__ import annotations

from collections import Counter
from datetime import UTC, date, datetime
from typing import Literal

from pydantic import Field

from moomail_finance_ai.schemas import (
    Citation,
    DataQuality,
    PortfolioLevelSentiment,
    SentimentAgentPacket,
    SentimentHolding,
    SentimentScopeItem,
    SentimentStance,
    SourceQuality,
    StrictModel,
)


DocumentType = Literal[
    "annual_report",
    "quarterly_report",
    "earnings_transcript",
    "shareholder_letter",
    "curated_research",
    "filing",
]

ChunkKind = Literal[
    "thesis",
    "development",
    "management_tone",
    "risk",
    "catalyst",
    "contradiction",
]

ChunkSentiment = Literal["positive", "mixed", "negative", "unclear"]

SOURCE_QUALITY_RANK: dict[SourceQuality, int] = {
    "primary": 100,
    "secondary": 70,
    "commentary": 40,
    "unknown": 0,
}

EXPECTED_DOCUMENT_TYPES: set[str] = {
    "annual_report",
    "quarterly_report",
    "earnings_transcript",
    "shareholder_letter",
}


class ResearchDocumentMetadata(StrictModel):
    document_id: str
    ticker: str
    company: str
    document_type: DocumentType
    title: str
    source: str
    publisher: str
    document_date: date
    ingestion_date: date
    author: str | None = None
    source_quality: SourceQuality
    entity_mapping_quality: Literal["exact", "manual", "fuzzy", "unknown"] = "exact"


class ResearchChunk(StrictModel):
    chunk_id: str
    document_id: str
    ticker: str
    text: str
    kind: ChunkKind
    sentiment: ChunkSentiment = "unclear"
    topics: list[str] = Field(default_factory=list)
    graph_entities: list[str] = Field(default_factory=list)
    graph_relationships: list[dict[str, str]] = Field(default_factory=list)
    section: str | None = None


class ResearchDocument(StrictModel):
    metadata: ResearchDocumentMetadata
    chunks: list[ResearchChunk]


class RetrievedChunk(StrictModel):
    metadata: ResearchDocumentMetadata
    chunk: ResearchChunk
    score: float
    source_quality_rank: int


class GraphContext(StrictModel):
    ticker: str
    entities: list[str] = Field(default_factory=list)
    relationships: list[dict[str, str]] = Field(default_factory=list)


class LocalResearchStore:
    def __init__(self) -> None:
        self._documents: dict[str, ResearchDocumentMetadata] = {}
        self._chunks: list[ResearchChunk] = []

    def ingest_document(self, document: ResearchDocument) -> None:
        self._documents[document.metadata.document_id] = document.metadata
        for chunk in document.chunks:
            if chunk.document_id != document.metadata.document_id:
                raise ValueError(
                    f"Chunk {chunk.chunk_id} document id does not match parent document."
                )
            if chunk.ticker != document.metadata.ticker:
                raise ValueError(f"Chunk {chunk.chunk_id} ticker does not match parent document.")
            self._chunks.append(chunk)

    def retrieve(
        self,
        ticker: str,
        *,
        query: str | None = None,
        limit: int = 12,
        kinds: set[ChunkKind] | None = None,
    ) -> list[RetrievedChunk]:
        query_terms = _terms(query or ticker)
        results = []
        for chunk in self._chunks:
            if chunk.ticker != ticker:
                continue
            if kinds is not None and chunk.kind not in kinds:
                continue
            metadata = self._documents[chunk.document_id]
            quality_rank = SOURCE_QUALITY_RANK[metadata.source_quality]
            score = _chunk_score(chunk, query_terms) + quality_rank / 1000
            results.append(
                RetrievedChunk(
                    metadata=metadata,
                    chunk=chunk,
                    score=score,
                    source_quality_rank=quality_rank,
                )
            )
        return sorted(
            results,
            key=lambda result: (
                result.source_quality_rank,
                result.score,
                result.metadata.document_date,
                result.chunk.chunk_id,
            ),
            reverse=True,
        )[:limit]

    def graph_context(self, ticker: str) -> GraphContext:
        entities = set()
        relationships = []
        for chunk in self._chunks:
            if chunk.ticker != ticker:
                continue
            entities.update(chunk.graph_entities)
            relationships.extend(chunk.graph_relationships)
        return GraphContext(
            ticker=ticker,
            entities=sorted(entities),
            relationships=relationships,
        )

    def document_types_for(self, ticker: str) -> set[str]:
        return {
            metadata.document_type
            for metadata in self._documents.values()
            if metadata.ticker == ticker
        }


class LocalSentimentAgent:
    def __init__(self, research_store: LocalResearchStore):
        self.research_store = research_store
        self.calls = 0

    def run(self, scope: list[SentimentScopeItem]) -> SentimentAgentPacket:
        self.calls += 1
        holdings = []
        warnings = []
        for item in scope:
            retrieved = self.research_store.retrieve(item.ticker)
            if not retrieved:
                holdings.append(_empty_holding(item.ticker))
                warnings.append(f"No curated research retrieved for {item.ticker}.")
                continue
            holdings.append(self._holding_from_retrieval(item.ticker, retrieved))

        citations = _unique_citations(
            citation for holding in holdings for citation in holding.citations
        )
        portfolio_risks = [
            risk
            for holding in holdings
            for risk in holding.risks
            if holding.stance != "unclear"
        ]
        themes = _top_topics(
            retrieved_chunk.chunk.topics
            for item in scope
            for retrieved_chunk in self.research_store.retrieve(item.ticker)
        )
        return SentimentAgentPacket(
            scope=scope,
            holdings=holdings,
            portfolio_level_sentiment=PortfolioLevelSentiment(
                summary=_portfolio_summary(holdings),
                themes=themes,
                risks=portfolio_risks[:5],
                citations=citations,
            ),
            data_quality=DataQuality(
                freshness_status="fresh" if not warnings else "unknown",
                missing_fields=["research_documents"] if warnings else [],
                warnings=warnings,
            ),
        )

    def _holding_from_retrieval(
        self,
        ticker: str,
        retrieved: list[RetrievedChunk],
    ) -> SentimentHolding:
        company = retrieved[0].metadata.company
        by_kind = _by_kind(retrieved)
        citations = [_citation_for(result) for result in retrieved]
        missing_research = _missing_research(ticker, self.research_store.document_types_for(ticker))
        contradictions = _texts(by_kind.get("contradiction", []))
        if not contradictions:
            missing_research.append("No disconfirming evidence found in curated corpus.")

        return SentimentHolding(
            ticker=ticker,
            company=company,
            stance=_stance(retrieved),
            thesis_summary=_first_text(by_kind.get("thesis", []), fallback="No thesis chunk found."),
            recent_developments=_texts(by_kind.get("development", [])),
            management_tone=_first_text(by_kind.get("management_tone", []), fallback=None),
            risks=_texts(by_kind.get("risk", [])),
            catalysts=_texts(by_kind.get("catalyst", [])),
            contradictions=contradictions,
            open_questions=missing_research,
            citations=citations,
        )


def _empty_holding(ticker: str) -> SentimentHolding:
    return SentimentHolding(
        ticker=ticker,
        company=ticker,
        stance="unclear",
        thesis_summary=(
            "No curated research was retrieved, so the agent cannot form a source-backed thesis."
        ),
        recent_developments=[],
        management_tone=None,
        risks=[],
        catalysts=[],
        contradictions=[],
        open_questions=[f"Add curated research documents for {ticker}."],
        citations=[],
    )


def _citation_for(result: RetrievedChunk) -> Citation:
    metadata = result.metadata
    chunk = result.chunk
    return Citation(
        citation_id=f"cite_{chunk.chunk_id}",
        source_type=metadata.document_type,
        title=metadata.title,
        publisher=metadata.publisher,
        document_date=metadata.document_date.isoformat(),
        ingestion_date=metadata.ingestion_date.isoformat(),
        ticker=metadata.ticker,
        company=metadata.company,
        chunk_id=chunk.chunk_id,
        document_id=metadata.document_id,
        location={
            "section": chunk.section,
            "source_quality_rank": result.source_quality_rank,
            "retrieval_score": round(result.score, 4),
        },
        snippet=chunk.text[:240],
        source_quality=metadata.source_quality,
    )


def _stance(retrieved: list[RetrievedChunk]) -> SentimentStance:
    sentiments = {result.chunk.sentiment for result in retrieved}
    if "positive" in sentiments and "negative" in sentiments:
        return "mixed"
    if "negative" in sentiments:
        return "negative"
    if "positive" in sentiments:
        return "positive"
    if "mixed" in sentiments:
        return "mixed"
    return "unclear"


def _missing_research(ticker: str, document_types: set[str]) -> list[str]:
    missing = sorted(EXPECTED_DOCUMENT_TYPES - document_types)
    if not missing:
        return []
    return [f"Missing curated document types for {ticker}: {', '.join(missing)}."]


def _portfolio_summary(holdings: list[SentimentHolding]) -> str:
    if not holdings:
        return "No holdings were analyzed."
    unclear = sum(holding.stance == "unclear" for holding in holdings)
    if unclear == len(holdings):
        return "No source-backed portfolio sentiment could be formed from the curated corpus."
    stance_counts = Counter(holding.stance for holding in holdings)
    return (
        "Curated research produced portfolio-level sentiment coverage: "
        + ", ".join(f"{stance}={count}" for stance, count in sorted(stance_counts.items()))
        + "."
    )


def _by_kind(retrieved: list[RetrievedChunk]) -> dict[ChunkKind, list[RetrievedChunk]]:
    grouped: dict[ChunkKind, list[RetrievedChunk]] = {}
    for result in retrieved:
        grouped.setdefault(result.chunk.kind, []).append(result)
    return grouped


def _texts(results: list[RetrievedChunk]) -> list[str]:
    return [result.chunk.text for result in results]


def _first_text(results: list[RetrievedChunk], fallback: str | None) -> str | None:
    return results[0].chunk.text if results else fallback


def _unique_citations(citations) -> list[Citation]:
    seen = set()
    unique = []
    for citation in citations:
        if citation.citation_id in seen:
            continue
        seen.add(citation.citation_id)
        unique.append(citation)
    return unique


def _top_topics(topic_groups, limit: int = 5) -> list[str]:
    counter: Counter[str] = Counter()
    for topics in topic_groups:
        counter.update(topics)
    return [topic for topic, _ in counter.most_common(limit)]


def _chunk_score(chunk: ResearchChunk, query_terms: set[str]) -> float:
    chunk_terms = _terms(" ".join([chunk.text, " ".join(chunk.topics), chunk.kind]))
    if not query_terms:
        return 0.0
    return len(query_terms & chunk_terms) / max(len(query_terms), 1)


def _terms(text: str) -> set[str]:
    return {
        token.strip(".,:;!?()[]{}\"'").lower()
        for token in text.split()
        if token.strip(".,:;!?()[]{}\"'")
    }


def today_utc_date() -> date:
    return datetime.now(UTC).date()

