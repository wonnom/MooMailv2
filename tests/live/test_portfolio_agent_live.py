from __future__ import annotations

import os
from pathlib import Path

import pytest

from moomail_finance_ai.config import OpenDConfig, load_env_file
from moomail_finance_ai.mcp.finance_metrics_mcp import build_finance_metrics_mcp_module
from moomail_finance_ai.mcp.gateway import DirectToolGateway
from moomail_finance_ai.mcp.opend_mcp import build_opend_mcp_module
from moomail_finance_ai.mcp.portfolio_sql_mcp import build_portfolio_sql_mcp_module
from moomail_finance_ai.mocks import mock_investment_policy
from moomail_finance_ai.opend import RecordedOpenDClient
from moomail_finance_ai.portfolio_agent import LLMPortfolioEvaluator, PortfolioAgent


pytestmark = pytest.mark.live_connector


ROOT = Path(__file__).resolve().parents[2]
LOCAL_ENV_PATH = ROOT / "config/local.env"
LOCAL_ENV = load_env_file(LOCAL_ENV_PATH) if LOCAL_ENV_PATH.exists() else {}
CONNECTOR_OPT_IN = "MOOMAIL_RUN_LIVE_CONNECTOR_TESTS"


def test_live_portfolio_agent_llm_evaluator_round_trip_with_gemini(tmp_path, sample_opend_report):
    _require_live_tests()
    if not _env("MOOMAIL_GEMINI_API_KEY") and not _env("GEMINI_API_KEY") and not _env("GOOGLE_API_KEY"):
        pytest.skip("Set MOOMAIL_GEMINI_API_KEY/GEMINI_API_KEY.")
    if not _env("MOOMAIL_GEMINI_MODEL"):
        pytest.skip("Set MOOMAIL_GEMINI_MODEL.")

    agent = PortfolioAgent(
        gateway=DirectToolGateway(
            [
                build_opend_mcp_module(
                    client=RecordedOpenDClient(sample_opend_report),
                    config=OpenDConfig(base_currency="USD"),
                ),
                build_finance_metrics_mcp_module(),
                build_portfolio_sql_mcp_module(db_path=tmp_path / "portfolio.sqlite"),
            ]
        ),
        evaluator=LLMPortfolioEvaluator.from_env(provider="gemini", env_file=LOCAL_ENV_PATH),
    )

    result = agent.run("Review my portfolio using only portfolio evidence", mock_investment_policy())

    assert result.evaluation.summary.strip()
    assert result.evaluation.llm_model == _env("MOOMAIL_GEMINI_MODEL")
    assert result.storage_result["status"] == "inserted"
    assert "moomail-finance-metrics-mcp:calculate_snapshot_metrics" in result.tool_calls


def _require_live_tests() -> None:
    if _env(CONNECTOR_OPT_IN) not in {"1", "true", "TRUE", "yes", "YES"}:
        pytest.skip(f"Set {CONNECTOR_OPT_IN}=1 to run live connector tests.")


def _env(name: str) -> str | None:
    value = os.environ.get(name) or LOCAL_ENV.get(name)
    return value if value else None
