import json
from datetime import UTC, datetime

from moomail_finance_ai.chat_api import ChatService, stream_payloads
from moomail_finance_ai.opend import OpenDConnectionStatus, OpenDFieldReport, OpenDTableResult
from moomail_finance_ai.portfolio_agent import PortfolioEvaluation
from scripts.serve_chat import WEB


def test_milestone6_chat_service_returns_full_report(tmp_path):
    report_path = _write_recorded_report(tmp_path)
    service = ChatService(
        from_report=report_path,
        db_path=tmp_path / "chat.sqlite",
        memory_path=tmp_path / "memory.json",
    )

    state = service.run("Review my portfolio")

    assert state.final_report is not None
    assert state.status_events
    assert state.final_report.citations
    assert state.guardrail_result is not None
    assert state.guardrail_result.passed is True


def test_milestone6_stream_endpoint_emits_status_and_final_events(tmp_path):
    report_path = _write_recorded_report(tmp_path)
    service = ChatService(
        from_report=report_path,
        db_path=tmp_path / "chat.sqlite",
        memory_path=tmp_path / "memory.json",
    )
    lines = stream_payloads(service, "Review my portfolio")

    assert any(line["type"] == "status" for line in lines)
    assert lines[-1]["type"] == "final"
    assert lines[-1]["state"]["final_report"]["citations"]


def test_chat_service_can_stream_portfolio_agent_response(tmp_path):
    report_path = _write_recorded_report(tmp_path)
    service = ChatService(
        from_report=report_path,
        db_path=tmp_path / "portfolio-chat.sqlite",
        portfolio_evaluator=FakePortfolioEvaluator(),
    )

    lines = stream_payloads(service, "Review my portfolio", agent="portfolio")
    final = lines[-1]["state"]

    assert any(line["type"] == "status" for line in lines)
    assert final["agent_type"] == "portfolio_agent"
    assert final["final_report"]["summary"] == "Portfolio evaluator test summary."
    assert final["final_report"]["portfolio_analysis"]["storage_result"]["status"] == "inserted"
    assert final["final_report"]["portfolio_analysis"]["evaluation"]["risks"] == [
        "Concentration requires review."
    ]


def test_milestone6_frontend_files_include_streaming_and_citation_controls():
    html = (WEB / "index.html").read_text(encoding="utf-8")
    ts = (WEB / "static" / "app.ts").read_text(encoding="utf-8")

    assert "/static/app.js" in html
    assert "agentSelect" in html
    assert "sendButton" in html
    assert "hideChatButton" in html
    assert "showChatButton" in html
    assert "chatResizeHandle" in html
    assert "/api/chat/stream" in ts
    assert "setChatHidden" in ts
    assert "resizeChatTo" in ts
    assert "renderPortfolioEvaluation" in ts
    assert "renderCitations" in ts
    assert "source_quality_rank" in ts


def _write_recorded_report(tmp_path):
    now = datetime(2026, 5, 24, tzinfo=UTC)
    report = OpenDFieldReport(
        generated_at=now,
        connection=OpenDConnectionStatus(
            ok=True,
            host="127.0.0.1",
            port=11111,
            checked_at=now,
            message="ok",
        ),
        tables=[
            OpenDTableResult(
                name="funds",
                rows=[{"total_assets": 1000.0, "cash": 100.0, "currency": "USD"}],
                fields=["total_assets", "cash", "currency"],
                as_of=now,
            ),
            OpenDTableResult(
                name="positions",
                rows=[
                    {
                        "code": "US.AAPL",
                        "stock_name": "Apple",
                        "position_market": "US",
                        "qty": 2,
                        "nominal_price": 300,
                        "market_val": 600,
                        "unrealized_pl": 100,
                        "currency": "USD",
                        "position_side": "LONG",
                    }
                ],
                fields=["code", "stock_name", "qty", "nominal_price", "market_val"],
                as_of=now,
            ),
            OpenDTableResult(
                name="quotes",
                rows=[
                    {
                        "code": "US.AAPL",
                        "name": "Apple",
                        "last_price": 300,
                        "equity_valid": True,
                        "option_valid": False,
                    }
                ],
                fields=["code", "name", "last_price", "equity_valid", "option_valid"],
                as_of=now,
            ),
        ],
    )
    path = tmp_path / "field-report.json"
    path.write_text(report.model_dump_json(), encoding="utf-8")
    return path


class FakePortfolioEvaluator:
    def evaluate(self, **kwargs):
        return PortfolioEvaluation(
            summary="Portfolio evaluator test summary.",
            strengths=["OpenD data normalized."],
            risks=["Concentration requires review."],
            history_observations=["Daily snapshot policy was applied."],
        )
