from datetime import UTC, datetime
from pathlib import Path

from moomail_finance_ai.full_agent import FullInvestmentAgent, build_default_full_agent
from moomail_finance_ai.mocks import mock_investment_policy
from moomail_finance_ai.opend import OpenDConnectionStatus, OpenDFieldReport, OpenDTableResult
from moomail_finance_ai.research_fixtures import build_sample_research_store
from moomail_finance_ai.sql_store import PortfolioSqlStore
from moomail_finance_ai.memory import FileMemoryStore


def test_milestone5_full_agent_runs_end_to_end_with_recorded_data(tmp_path):
    report_path = _write_recorded_report(tmp_path)
    agent = build_default_full_agent(
        from_report=report_path,
        db_path=tmp_path / "history.sqlite",
        memory_path=tmp_path / "memory.json",
    )

    state = agent.run("Review my portfolio")

    assert state.final_report is not None
    assert state.guardrail_result is not None
    assert state.audit_record is not None
    assert state.guardrail_result.passed is True
    assert state.final_report.citations
    assert state.final_report.sentiment_analysis
    assert state.final_report.portfolio_analysis
    assert state.final_report.missing_data
    assert state.audit_record.memory_updates
    assert agent.sql_store.table_count("portfolio_snapshots") == 1
    assert agent.sql_store.table_count("calculated_metrics") == 5
    assert agent.sql_store.table_count("agent_runs") == 1


def test_milestone5_full_agent_has_no_trading_surface():
    public_methods = {
        name
        for name in dir(FullInvestmentAgent)
        if not name.startswith("_") and callable(getattr(FullInvestmentAgent, name))
    }

    assert public_methods == {"run"}
    assert not any("trade" in method or "order" in method for method in public_methods)


def test_milestone5_critical_missing_portfolio_data_blocks_recommendations(tmp_path):
    class EmptyPortfolioClient:
        def explore_fields(self):
            now = datetime.now(UTC)
            return OpenDFieldReport(
                generated_at=now,
                connection=OpenDConnectionStatus(
                    ok=False,
                    host="127.0.0.1",
                    port=11111,
                    checked_at=now,
                    message="blocked",
                ),
                tables=[],
            )

    agent = FullInvestmentAgent(
        portfolio_client=EmptyPortfolioClient(),
        sql_store=PortfolioSqlStore(tmp_path / "history.sqlite"),
        memory_store=FileMemoryStore(tmp_path / "memory.json"),
        research_store=build_sample_research_store(),
        ips=mock_investment_policy(),
    )

    state = agent.run("Review my portfolio")

    assert state.final_report is not None
    assert state.guardrail_result is not None
    assert state.guardrail_result.passed is False
    assert state.final_report.recommendations == []
    assert "Critical portfolio data unavailable" in state.final_report.missing_data[0]
    assert agent.sql_store.table_count("agent_runs") == 1


def test_milestone5_noncritical_missing_data_is_visible(tmp_path):
    report_path = _write_recorded_report(tmp_path)
    agent = build_default_full_agent(
        from_report=report_path,
        db_path=tmp_path / "history.sqlite",
        memory_path=tmp_path / "memory.json",
    )

    state = agent.run("Review my portfolio")

    assert state.final_report is not None
    assert any("Missing curated document types" in item for item in state.final_report.missing_data)
    assert any("historical analysis needs" in item for item in state.final_report.missing_data)


def _write_recorded_report(tmp_path: Path) -> Path:
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
                    },
                    {
                        "code": "US.MSFT",
                        "stock_name": "Microsoft",
                        "position_market": "US",
                        "qty": 1,
                        "nominal_price": 300,
                        "market_val": 300,
                        "unrealized_pl": 10,
                        "currency": "USD",
                        "position_side": "LONG",
                    },
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
                    },
                    {
                        "code": "US.MSFT",
                        "name": "Microsoft",
                        "last_price": 300,
                        "equity_valid": True,
                        "option_valid": False,
                    },
                ],
                fields=["code", "name", "last_price", "equity_valid", "option_valid"],
                as_of=now,
            ),
        ],
    )
    path = tmp_path / "field-report.json"
    path.write_text(report.model_dump_json(), encoding="utf-8")
    return path
