from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from moomail_finance_ai.schemas import (
    DataQuality,
    PortfolioLevelSentiment,
    SentimentScopeItem,
)
from moomail_finance_ai.agent_schemas import (
    EvidenceType,
    MissingResearchDocument,
    SentimentPacket,
    SentimentTask,
)


STUB_WARNING = "Sentiment Agent is a stub; no research retrieval was performed."
GRAPHRAG_WARNING = "Neo4j GraphRAG is not implemented."


@dataclass
class SentimentAgentStub:
    """Deterministic contract stub for the future GraphRAG Sentiment Agent."""

    calls: int = 0
    last_task: SentimentTask | None = None

    def run(self, task: SentimentTask | dict[str, Any]) -> SentimentPacket:
        validated_task = SentimentTask.model_validate(task)
        self.calls += 1
        self.last_task = validated_task
        return build_missing_research_packet(validated_task)


def build_missing_research_packet(task: SentimentTask) -> SentimentPacket:
    return SentimentPacket(
        retrieval_status="not_implemented",
        task=task,
        scope=_scope_from_task(task),
        holdings=[],
        portfolio_level_sentiment=PortfolioLevelSentiment(
            summary=(
                "GraphRAG sentiment retrieval is not implemented. "
                "No sentiment stance, company claims, or citations were produced."
            )
        ),
        contradictions=[],
        open_questions=[],
        source_metadata={},
        missing_documents=_missing_documents_from_task(task),
        citations=[],
        data_quality=DataQuality(
            freshness_status="unknown",
            missing_fields=["graph_rag_corpus", "neo4j_research_store"],
            warnings=[STUB_WARNING, GRAPHRAG_WARNING],
        ),
        warnings=["Sentiment Agent is a stub.", GRAPHRAG_WARNING],
    )


def _scope_from_task(task: SentimentTask) -> list[SentimentScopeItem]:
    return [
        SentimentScopeItem(ticker=ticker, reason=task.reason)
        for ticker in task.tickers
    ]


def _missing_documents_from_task(task: SentimentTask) -> list[MissingResearchDocument]:
    evidence_types = task.requested_evidence_types or ["unknown"]
    documents: list[MissingResearchDocument] = []

    for evidence_type in evidence_types:
        documents.extend(_missing_documents_for_tickers(task, evidence_type))
        documents.extend(_missing_documents_for_entities(task, evidence_type))
        if not task.tickers and not task.companies_entities:
            documents.append(
                MissingResearchDocument(
                    document_type=evidence_type,
                    reason=_missing_reason(evidence_type),
                )
            )

    return documents


def _missing_documents_for_tickers(
    task: SentimentTask,
    evidence_type: EvidenceType,
) -> list[MissingResearchDocument]:
    return [
        MissingResearchDocument(
            ticker=ticker,
            document_type=evidence_type,
            reason=_missing_reason(evidence_type),
        )
        for ticker in task.tickers
    ]


def _missing_documents_for_entities(
    task: SentimentTask,
    evidence_type: EvidenceType,
) -> list[MissingResearchDocument]:
    return [
        MissingResearchDocument(
            entity=entity,
            document_type=evidence_type,
            reason=_missing_reason(evidence_type),
        )
        for entity in task.companies_entities
    ]


def _missing_reason(evidence_type: EvidenceType) -> str:
    return (
        f"{GRAPHRAG_WARNING} The sentiment stub cannot retrieve "
        f"{evidence_type.replace('_', ' ')} evidence."
    )
