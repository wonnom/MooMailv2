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


def test_milestone6_stream_endpoint_emits_error_event_when_agent_fails():
    lines = stream_payloads(ExplodingChatService(), "Review my portfolio", agent="portfolio")

    assert lines[-1]["type"] == "error"
    assert lines[-1]["error"]["error_type"] == "RuntimeError"
    assert lines[-1]["error"]["message"] == "synthetic stream failure"
    assert "RuntimeError" in "".join(lines[-1]["error"]["traceback"])


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
    assert final["final_report"]["portfolio_snapshot"]["holdings"][0]["ticker"] == "AAPL"
    assert final["final_report"]["portfolio_analysis"]["storage_result"]["status"] == "inserted"
    assert (
        final["final_report"]["portfolio_analysis"]["effective_cash"]["effective_cash_value"]
        == 100.0
    )
    assert (
        final["final_report"]["portfolio_analysis"]["history_context"]["history_status"][
            "snapshot_count"
        ]
        == 0
    )
    assert final["final_report"]["portfolio_analysis"]["evaluation"]["risks"] == [
        "Concentration requires review."
    ]


def test_chat_service_portfolio_agent_handles_legacy_chat_db(tmp_path):
    report_path = _write_recorded_report(tmp_path)
    db_path = tmp_path / "legacy-chat.sqlite"
    _create_legacy_agent_runs_table(db_path)
    service = ChatService(
        from_report=report_path,
        db_path=db_path,
        portfolio_evaluator=FakePortfolioEvaluator(),
    )

    lines = stream_payloads(service, "Review my portfolio", agent="portfolio")
    final = lines[-1]["state"]

    assert final["agent_type"] == "portfolio_agent"
    assert final["final_report"]["portfolio_analysis"]["storage_result"]["status"] == "inserted"


def test_chat_service_can_call_v2_investment_agent_with_recorded_portfolio(tmp_path):
    report_path = _write_recorded_report(tmp_path)
    service = ChatService(
        from_report=report_path,
        db_path=tmp_path / "investment-v2-chat.sqlite",
        portfolio_evaluator=FakePortfolioEvaluator(),
        default_agent="investment_v2",
    )

    lines = stream_payloads(service, "Review my portfolio.", agent="investment_v2")
    final = lines[-1]["state"]

    assert any(line["type"] == "status" for line in lines)
    assert final["agent_type"] == "investment_agent_v2"
    assert final["query_plan"]["needs_sentiment_agent"] is True
    assert final["sentiment_packet"]["retrieval_status"] == "not_implemented"
    assert final["final_report"]["portfolio_analysis"]["allocation"]["by_asset"]
    assert final["final_report"]["portfolio_analysis"]["risk"]
    assert "Sentiment Agent GraphRAG retrieval is not implemented in V2." in (
        final["final_report"]["missing_data"]
    )
    assert final["guardrail_result"]["passed"] is True


def test_chat_defaults_use_canonical_portfolio_history_db():
    service = ChatService()
    serve_chat_source = (WEB.parent / "scripts" / "serve_chat.py").read_text(encoding="utf-8")

    assert str(service.db_path) == "data/portfolio-history.sqlite"
    assert 'default="data/portfolio-history.sqlite"' in serve_chat_source
    assert "investment_v2" in serve_chat_source
    assert "data/chat-portfolio-history.sqlite" not in serve_chat_source


def test_milestone6_frontend_files_include_streaming_and_citation_controls():
    html = (WEB / "index.html").read_text(encoding="utf-8")
    static_dir = WEB / "static"
    frontend_source = "\n".join(
        (static_dir / name).read_text(encoding="utf-8")
        for name in [
            "app.ts",
            "chat_panel.ts",
            "dom.ts",
            "format.ts",
            "layout.ts",
            "report_components.ts",
            "stream_client.ts",
            "types.ts",
        ]
    )

    assert "/static/app.js" in html
    assert "agentSelect" in html
    assert 'value="investment_v2">Investment<' in html
    assert "Investment Legacy" not in html
    assert "chat-controls" in html
    assert 'rows="4"' in html
    assert "sendButton" in html
    assert "hideChatButton" in html
    assert "showChatButton" in html
    assert "chatResizeHandle" in html
    assert "portfolioPositions" in html
    assert "allocationSort" in html
    assert "data-allocation-view=\"pie\"" in html
    assert "from \"./report_components.js\"" in frontend_source
    assert "from \"./stream_client.js\"" in frontend_source
    assert "/api/chat/stream" in frontend_source
    assert "isPortfolioSnapshot" in frontend_source
    assert "addReasoningSummary" in frontend_source
    assert "route_reason" in frontend_source
    assert "portfolio_packet" in frontend_source
    assert "Sentiment retrieval" in frontend_source
    assert "setChatHidden" in frontend_source
    assert "resizeChatTo" in frontend_source
    assert "renderPortfolioSnapshot" in frontend_source
    assert "effective_cash" in frontend_source
    assert "Effective cash" in frontend_source
    assert "sortAllocationRows" in frontend_source
    assert "renderAllocationPie" in frontend_source
    assert "renderPortfolioEvaluation" in frontend_source
    assert "renderCitations" in frontend_source
    assert "source_quality_rank" in frontend_source
    assert "payload.type === \"error\"" in frontend_source
    assert "renderStreamError" in frontend_source
    assert "traceback" in frontend_source


def _create_legacy_agent_runs_table(db_path):
    import sqlite3

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE agent_runs (
                run_id TEXT PRIMARY KEY,
                timestamp TEXT NOT NULL,
                user_query TEXT NOT NULL,
                mode TEXT NOT NULL,
                tools_called_json TEXT NOT NULL,
                data_timestamps_json TEXT NOT NULL,
                source_ids_json TEXT NOT NULL,
                assumptions_json TEXT NOT NULL,
                guardrail_result_json TEXT NOT NULL,
                output_summary TEXT NOT NULL,
                memory_updates_json TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            INSERT INTO agent_runs (
                run_id, timestamp, user_query, mode, tools_called_json,
                data_timestamps_json, source_ids_json, assumptions_json,
                guardrail_result_json, output_summary, memory_updates_json
            )
            VALUES (
                'legacy_run', '2026-05-23T00:00:00+00:00', 'Review', 'review',
                '[]', '[]', '[]', '[]', '{}', 'legacy summary', '[]'
            )
            """
        )


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


class ExplodingChatService:
    def run(self, query, *, agent=None, status_callback=None):
        raise RuntimeError("synthetic stream failure")
