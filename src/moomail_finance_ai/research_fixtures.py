from __future__ import annotations

from datetime import date

from moomail_finance_ai.research import (
    LocalResearchStore,
    ResearchChunk,
    ResearchDocument,
    ResearchDocumentMetadata,
)


def build_sample_research_store() -> LocalResearchStore:
    store = LocalResearchStore()
    store.ingest_document(_aapl_quarterly_report())
    store.ingest_document(_aapl_commentary_note())
    store.ingest_document(_msft_transcript())
    return store


def _aapl_quarterly_report() -> ResearchDocument:
    metadata = ResearchDocumentMetadata(
        document_id="doc_aapl_q_report_mock",
        ticker="AAPL",
        company="Apple Inc.",
        document_type="quarterly_report",
        title="Apple Mock Quarterly Report",
        source="manual_corpus",
        publisher="Company",
        document_date=date(2026, 5, 1),
        ingestion_date=date(2026, 5, 24),
        author=None,
        source_quality="primary",
        entity_mapping_quality="manual",
    )
    return ResearchDocument(
        metadata=metadata,
        chunks=[
            ResearchChunk(
                chunk_id="aapl_thesis_services",
                document_id=metadata.document_id,
                ticker="AAPL",
                text="Services durability supports the long-term thesis despite uneven hardware cycles.",
                kind="thesis",
                sentiment="positive",
                topics=["services", "durability", "hardware"],
                graph_entities=["Apple", "Services", "Hardware"],
                graph_relationships=[
                    {"source": "Services", "relationship": "SUPPORTS", "target": "Apple thesis"}
                ],
                section="Segment discussion",
            ),
            ResearchChunk(
                chunk_id="aapl_development_services",
                document_id=metadata.document_id,
                ticker="AAPL",
                text="Recent services growth helped offset softer regional hardware demand.",
                kind="development",
                sentiment="mixed",
                topics=["services", "regional demand"],
                graph_entities=["Services", "Hardware"],
                graph_relationships=[
                    {"source": "Services", "relationship": "OFFSETS", "target": "Hardware weakness"}
                ],
                section="Recent developments",
            ),
            ResearchChunk(
                chunk_id="aapl_risk_hardware",
                document_id=metadata.document_id,
                ticker="AAPL",
                text="Hardware replacement cycles remain uneven and could pressure near-term growth.",
                kind="risk",
                sentiment="negative",
                topics=["hardware", "replacement cycle", "growth"],
                graph_entities=["Hardware"],
                graph_relationships=[
                    {"source": "Hardware cycle", "relationship": "AFFECTS", "target": "Revenue growth"}
                ],
                section="Risk factors",
            ),
            ResearchChunk(
                chunk_id="aapl_catalyst_refresh",
                document_id=metadata.document_id,
                ticker="AAPL",
                text="Product refresh cycles and services attach rates are potential catalysts.",
                kind="catalyst",
                sentiment="positive",
                topics=["product refresh", "services"],
                graph_entities=["Product refresh", "Services"],
                graph_relationships=[
                    {"source": "Product refresh", "relationship": "CATALYST_FOR", "target": "Demand"}
                ],
                section="Outlook",
            ),
            ResearchChunk(
                chunk_id="aapl_contradiction_valuation",
                document_id=metadata.document_id,
                ticker="AAPL",
                text="A premium valuation may limit upside if hardware growth remains uneven.",
                kind="contradiction",
                sentiment="negative",
                topics=["valuation", "hardware", "upside"],
                graph_entities=["Valuation", "Hardware"],
                graph_relationships=[
                    {"source": "Valuation", "relationship": "CONTRADICTS", "target": "Upside thesis"}
                ],
                section="Valuation discussion",
            ),
            ResearchChunk(
                chunk_id="aapl_management_tone",
                document_id=metadata.document_id,
                ticker="AAPL",
                text="Management tone was measured and operationally disciplined.",
                kind="management_tone",
                sentiment="mixed",
                topics=["management", "operations"],
                graph_entities=["Management"],
                graph_relationships=[
                    {"source": "Management", "relationship": "GUIDES", "target": "Operations"}
                ],
                section="Management commentary",
            ),
        ],
    )


def _aapl_commentary_note() -> ResearchDocument:
    metadata = ResearchDocumentMetadata(
        document_id="doc_aapl_commentary_mock",
        ticker="AAPL",
        company="Apple Inc.",
        document_type="curated_research",
        title="Apple Mock Commentary Note",
        source="manual_corpus",
        publisher="Curated note",
        document_date=date(2026, 5, 10),
        ingestion_date=date(2026, 5, 24),
        author="Internal",
        source_quality="commentary",
        entity_mapping_quality="manual",
    )
    return ResearchDocument(
        metadata=metadata,
        chunks=[
            ResearchChunk(
                chunk_id="aapl_commentary_services",
                document_id=metadata.document_id,
                ticker="AAPL",
                text="Commentary remains constructive on services mix but less certain on hardware demand.",
                kind="thesis",
                sentiment="mixed",
                topics=["services", "hardware"],
                graph_entities=["Services", "Hardware"],
                graph_relationships=[],
                section="Summary",
            )
        ],
    )


def _msft_transcript() -> ResearchDocument:
    metadata = ResearchDocumentMetadata(
        document_id="doc_msft_transcript_mock",
        ticker="MSFT",
        company="Microsoft Corporation",
        document_type="earnings_transcript",
        title="Microsoft Mock Earnings Transcript",
        source="manual_corpus",
        publisher="Company",
        document_date=date(2026, 4, 25),
        ingestion_date=date(2026, 5, 24),
        author=None,
        source_quality="primary",
        entity_mapping_quality="manual",
    )
    return ResearchDocument(
        metadata=metadata,
        chunks=[
            ResearchChunk(
                chunk_id="msft_thesis_cloud_ai",
                document_id=metadata.document_id,
                ticker="MSFT",
                text="Cloud and AI workload demand remain the central long-term thesis.",
                kind="thesis",
                sentiment="positive",
                topics=["cloud", "ai", "enterprise demand"],
                graph_entities=["Cloud", "AI"],
                graph_relationships=[
                    {"source": "AI workloads", "relationship": "SUPPORTS", "target": "Cloud demand"}
                ],
                section="Prepared remarks",
            ),
            ResearchChunk(
                chunk_id="msft_risk_capex",
                document_id=metadata.document_id,
                ticker="MSFT",
                text="Elevated AI infrastructure spending could delay margin expansion.",
                kind="risk",
                sentiment="negative",
                topics=["ai", "capex", "margin"],
                graph_entities=["AI infrastructure", "Margin"],
                graph_relationships=[
                    {"source": "AI capex", "relationship": "PRESSURES", "target": "Margin expansion"}
                ],
                section="Risk discussion",
            ),
            ResearchChunk(
                chunk_id="msft_catalyst_enterprise",
                document_id=metadata.document_id,
                ticker="MSFT",
                text="Enterprise adoption of AI features is a potential catalyst for durable growth.",
                kind="catalyst",
                sentiment="positive",
                topics=["enterprise", "ai", "growth"],
                graph_entities=["Enterprise AI"],
                graph_relationships=[
                    {"source": "Enterprise AI", "relationship": "CATALYST_FOR", "target": "Growth"}
                ],
                section="Outlook",
            ),
        ],
    )

