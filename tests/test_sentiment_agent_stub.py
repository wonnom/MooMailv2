from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from moomail_finance_ai.sentiment_agent_stub import SentimentAgentStub
from moomail_finance_ai.agent_schemas import SentimentPacket, SentimentTask


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "agent"


def test_sentiment_stub_accepts_scoped_task_and_preserves_scope():
    agent = SentimentAgentStub()
    task = SentimentTask(
        tickers=["goog"],
        companies_entities=["Alphabet Inc."],
        themes=["portfolio thesis", "earnings"],
        requested_evidence_types=["earnings_transcript", "shareholder_letter"],
        key_questions=["What has changed in the thesis?"],
        reason="Material portfolio holding needs research context.",
    )

    packet = agent.run(task)

    assert agent.calls == 1
    assert agent.last_task is not None
    assert agent.last_task.tickers == ["GOOG"]
    assert packet.retrieval_status == "not_implemented"
    assert packet.task is not None
    assert packet.task.themes == ["portfolio thesis", "earnings"]
    assert packet.task.key_questions == ["What has changed in the thesis?"]
    assert [scope.ticker for scope in packet.scope] == ["GOOG"]
    assert {doc.document_type for doc in packet.missing_documents} == {
        "earnings_transcript",
        "shareholder_letter",
    }
    assert {doc.ticker for doc in packet.missing_documents if doc.ticker} == {"GOOG"}
    assert {doc.entity for doc in packet.missing_documents if doc.entity} == {
        "Alphabet Inc."
    }


def test_sentiment_stub_accepts_dict_payload_and_rejects_malformed_payload():
    agent = SentimentAgentStub()

    packet = agent.run(
        {
            "tickers": ["asml"],
            "requested_evidence_types": ["annual_report"],
            "key_questions": ["Summarize management commentary."],
        }
    )

    assert agent.last_task is not None
    assert agent.last_task.tickers == ["ASML"]
    assert packet.missing_documents[0].document_type == "annual_report"

    with pytest.raises(ValidationError):
        agent.run({"tickers": ["GOOG"], "unsupported_field": True})


def test_sentiment_stub_requires_no_external_research_config(monkeypatch):
    monkeypatch.delenv("NEO4J_URI", raising=False)
    monkeypatch.delenv("NEO4J_USERNAME", raising=False)
    monkeypatch.delenv("NEO4J_PASSWORD", raising=False)
    monkeypatch.delenv("PINECONE_API_KEY", raising=False)

    packet = SentimentAgentStub().run(
        SentimentTask(
            tickers=["MSFT"],
            requested_evidence_types=["quarterly_report"],
        )
    )

    assert packet.retrieval_status == "not_implemented"
    assert "neo4j_research_store" in packet.data_quality.missing_fields


def test_sentiment_stub_returns_no_fabricated_research_or_citations():
    packet = SentimentAgentStub().run(
        SentimentTask(tickers=["AAPL"], requested_evidence_types=["filing"])
    )

    assert packet.holdings == []
    assert packet.citations == []
    assert packet.portfolio_level_sentiment.citations == []
    assert packet.contradictions == []
    assert packet.open_questions == []
    assert packet.source_metadata == {}
    assert "No sentiment stance" in packet.portfolio_level_sentiment.summary


def test_sentiment_stub_fixture_matches_generated_contract_shape():
    task = SentimentTask.model_validate(_fixture("sentiment_task_full_review.json"))
    packet = SentimentAgentStub().run(task)
    expected = SentimentPacket.model_validate(_fixture("sentiment_packet_stub.json"))

    assert packet.retrieval_status == expected.retrieval_status
    assert packet.task is not None
    assert packet.task.tickers == expected.task.tickers
    assert packet.scope[0].ticker == expected.scope[0].ticker
    assert packet.holdings == expected.holdings
    assert packet.citations == expected.citations


def test_future_success_fixture_validates_contract_shape_only():
    packet = SentimentPacket.model_validate(_fixture("sentiment_packet_future_success.json"))

    assert packet.retrieval_status == "sufficient"
    assert packet.holdings[0].ticker == "GOOG"
    assert packet.holdings[0].citations
    assert packet.source_metadata["retriever"] == "neo4j_graphrag"


def _fixture(name: str):
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))
