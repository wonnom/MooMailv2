from datetime import date

from moomail_finance_ai.research import (
    LocalResearchStore,
    LocalSentimentAgent,
    ResearchChunk,
    ResearchDocument,
    ResearchDocumentMetadata,
)
from moomail_finance_ai.research_fixtures import build_sample_research_store
from moomail_finance_ai.schemas import SentimentScopeItem


def test_ec1_sentiment_agent_returns_complete_packet_for_held_ticker():
    agent = LocalSentimentAgent(build_sample_research_store())

    packet = agent.run([SentimentScopeItem(ticker="AAPL", reason="Held portfolio stock.")])

    holding = packet.holdings[0]
    assert holding.ticker == "AAPL"
    assert holding.company == "Apple Inc."
    assert holding.thesis_summary
    assert holding.recent_developments
    assert holding.risks
    assert holding.catalysts
    assert holding.contradictions
    assert holding.stance == "mixed"
    assert holding.citations
    assert holding.open_questions
    assert "Missing curated document types" in holding.open_questions[0]
    assert packet.portfolio_level_sentiment.summary
    assert packet.portfolio_level_sentiment.citations


def test_ec2_empty_retrieval_warns_instead_of_inventing_analysis():
    agent = LocalSentimentAgent(build_sample_research_store())

    packet = agent.run([SentimentScopeItem(ticker="ZZZZ", reason="No corpus coverage.")])

    holding = packet.holdings[0]
    assert holding.ticker == "ZZZZ"
    assert holding.stance == "unclear"
    assert "No curated research was retrieved" in holding.thesis_summary
    assert holding.citations == []
    assert packet.data_quality.freshness_status == "unknown"
    assert "research_documents" in packet.data_quality.missing_fields
    assert packet.data_quality.warnings == ["No curated research retrieved for ZZZZ."]


def test_ec3_source_quality_is_ranked_and_visible_in_citations():
    store = build_sample_research_store()

    retrieved = store.retrieve("AAPL", query="services hardware")

    assert retrieved[0].metadata.source_quality == "primary"
    assert retrieved[0].source_quality_rank == 100

    packet = LocalSentimentAgent(store).run(
        [SentimentScopeItem(ticker="AAPL", reason="Held portfolio stock.")]
    )
    citation_ranks = [citation.location["source_quality_rank"] for citation in packet.holdings[0].citations]
    citation_qualities = [citation.source_quality for citation in packet.holdings[0].citations]

    assert citation_ranks[0] == 100
    assert "primary" in citation_qualities
    assert "commentary" in citation_qualities


def test_manual_ingestion_validates_chunk_parent_document():
    store = LocalResearchStore()
    document = ResearchDocument(
        metadata=ResearchDocumentMetadata(
            document_id="doc_test",
            ticker="TEST",
            company="Test Co.",
            document_type="curated_research",
            title="Test Note",
            source="manual",
            publisher="Internal",
            document_date=date(2026, 5, 24),
            ingestion_date=date(2026, 5, 24),
            source_quality="secondary",
        ),
        chunks=[
            ResearchChunk(
                chunk_id="bad_chunk",
                document_id="wrong_doc",
                ticker="TEST",
                text="Bad parent id.",
                kind="thesis",
            )
        ],
    )

    try:
        store.ingest_document(document)
    except ValueError as exc:
        assert "does not match parent document" in str(exc)
    else:
        raise AssertionError("Expected bad chunk parent id to fail ingestion")


def test_graph_context_returns_entities_and_relationships():
    store = build_sample_research_store()

    graph = store.graph_context("MSFT")

    assert "AI" in graph.entities
    assert any(relationship["relationship"] == "SUPPORTS" for relationship in graph.relationships)

