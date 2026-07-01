from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from moomail_finance_ai.mcp.finance_metrics_mcp import build_finance_metrics_mcp_module
from moomail_finance_ai.mcp.gateway import DirectToolGateway
from moomail_finance_ai.mcp.opend_mcp import build_opend_mcp_module
from moomail_finance_ai.mcp.portfolio_sql_mcp import build_portfolio_sql_mcp_module
from moomail_finance_ai.portfolio_data_service import PortfolioDataService
from scripts.serve_chat import ChatHandler


def test_portfolio_data_service_refresh_pulls_opend_calculates_metrics_and_stores_sql(
    tmp_path,
    recorded_opend_client,
):
    db_path = tmp_path / "portfolio.sqlite"
    service = PortfolioDataService(
        DirectToolGateway(
            [
                build_opend_mcp_module(client=recorded_opend_client),
                build_finance_metrics_mcp_module(),
                build_portfolio_sql_mcp_module(db_path=db_path),
            ]
        )
    )

    result = service.refresh()

    assert result.status == "refreshed"
    assert result.connection.ok is True
    assert result.dashboard.portfolio_snapshot is not None
    assert result.dashboard.portfolio_snapshot.holdings[0].ticker == "AAPL"
    assert result.dashboard.metrics
    assert result.storage_result is not None
    assert result.storage_result["status"] == "inserted"
    assert result.storage_result["weight_rows_stored"] == 2


def test_latest_snapshot_reads_sql_and_metrics_without_opend(
    tmp_path,
    recorded_opend_client,
):
    db_path = tmp_path / "portfolio.sqlite"
    refresh_service = PortfolioDataService(
        DirectToolGateway(
            [
                build_opend_mcp_module(client=recorded_opend_client),
                build_finance_metrics_mcp_module(),
                build_portfolio_sql_mcp_module(db_path=db_path),
            ]
        )
    )
    refresh_service.refresh()
    read_service = PortfolioDataService(
        DirectToolGateway(
            [
                build_finance_metrics_mcp_module(),
                build_portfolio_sql_mcp_module(db_path=db_path),
            ]
        )
    )

    dashboard = read_service.latest_snapshot()

    assert dashboard.portfolio_snapshot is not None
    assert dashboard.portfolio_snapshot.holdings[0].ticker == "AAPL"
    assert dashboard.metrics
    assert dashboard.history_status["snapshot_count"] == 1
    assert dashboard.source_summary["source"] == "portfolio_sql_latest_state"


def test_connection_status_degrades_to_disconnected_when_opend_server_is_unavailable(tmp_path):
    service = PortfolioDataService(
        DirectToolGateway([build_portfolio_sql_mcp_module(db_path=tmp_path / "portfolio.sqlite")])
    )

    status = service.connection_status()

    assert status.ok is False
    assert status.status == "disconnected"
    assert "not configured" in (status.error or "")


def test_refresh_returns_stale_dashboard_when_opend_refresh_fails(tmp_path, recorded_opend_client):
    db_path = tmp_path / "portfolio.sqlite"
    PortfolioDataService(
        DirectToolGateway(
            [
                build_opend_mcp_module(client=recorded_opend_client),
                build_finance_metrics_mcp_module(),
                build_portfolio_sql_mcp_module(db_path=db_path),
            ]
        )
    ).refresh()
    failing_refresh_service = PortfolioDataService(
        DirectToolGateway(
            [
                build_finance_metrics_mcp_module(),
                build_portfolio_sql_mcp_module(db_path=db_path),
            ]
        )
    )

    result = failing_refresh_service.refresh()

    assert result.status == "failed"
    assert result.dashboard.portfolio_snapshot is not None
    assert result.dashboard.portfolio_snapshot.holdings[0].ticker == "AAPL"
    assert result.errors
    assert "last-known data" in " ".join(result.warnings)


def test_portfolio_status_and_dashboard_routes_delegate_to_deterministic_service():
    service = StaticPortfolioDataService()
    handler = object.__new__(ChatHandler)
    handler.service = service
    captured: list[dict] = []
    handler._json = lambda payload, status=200: captured.append(payload)
    handler.send_error = lambda status: captured.append({"error": status})

    handler.path = "/api/portfolio/status"
    handler.do_GET()
    handler.path = "/api/portfolio/dashboard"
    handler.do_GET()

    assert captured[0]["status"] == "connected"
    assert captured[1]["portfolio_id"] == "portfolio_default"
    assert captured[1]["source_summary"]["source"] == "test"


def test_portfolio_refresh_route_delegates_without_reading_chat_payload():
    service = StaticPortfolioDataService()
    handler = object.__new__(ChatHandler)
    handler.service = service
    captured: list[dict] = []
    handler._json = lambda payload, status=200: captured.append(payload)
    handler.send_error = lambda status: captured.append({"error": status})

    handler.path = "/api/portfolio/refresh"
    handler.do_POST()

    assert captured[0]["status"] == "refreshed"
    assert captured[0]["connection"]["status"] == "connected"


def test_dashboard_refresh_does_not_call_agents_or_llm():
    source = Path("src/moomail_finance_ai/portfolio_data_service.py").read_text(encoding="utf-8")

    assert "PortfolioAgent" not in source
    assert "InvestmentAgent" not in source
    assert "SentimentAgent" not in source
    assert "LLMPortfolioEvaluator" not in source
    assert "build_llm_client" not in source


class StaticPortfolioDataService:
    def portfolio_connection_status(self):
        return self.connection_status()

    def portfolio_dashboard(self):
        return self.latest_snapshot()

    def portfolio_refresh(self):
        return self.refresh()

    def connection_status(self):
        from moomail_finance_ai.portfolio_data_service import PortfolioConnectionStatus

        return PortfolioConnectionStatus(
            ok=True,
            status="connected",
            checked_at=datetime(2026, 5, 23, tzinfo=UTC),
            message="ok",
        )

    def latest_snapshot(self):
        from moomail_finance_ai.portfolio_data_service import PortfolioDashboardSnapshot

        return PortfolioDashboardSnapshot(
            portfolio_id="portfolio_default",
            last_updated_at=datetime(2026, 5, 23, tzinfo=UTC),
            source_summary={"source": "test"},
        )

    def refresh(self):
        from moomail_finance_ai.portfolio_data_service import PortfolioRefreshResult

        connection = self.connection_status()
        dashboard = self.latest_snapshot().model_copy(update={"connection": connection})
        return PortfolioRefreshResult(
            status="refreshed",
            dashboard=dashboard,
            connection=connection,
        )
