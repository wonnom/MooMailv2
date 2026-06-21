from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from moomail_finance_ai.config import OpenDConfig
from moomail_finance_ai.mcp.finance_metrics_mcp import build_finance_metrics_mcp_module
from moomail_finance_ai.mcp.opend_mcp import build_opend_mcp_module
from moomail_finance_ai.mcp.portfolio_sql_mcp import build_portfolio_sql_mcp_module
from moomail_finance_ai.metrics import calculate_snapshot_metrics
from moomail_finance_ai.mocks import mock_investment_policy, mock_portfolio_packet
from moomail_finance_ai.opend import (
    OpenDConnectionStatus,
    OpenDFieldReport,
    OpenDTableResult,
    RecordedOpenDClient,
)
from moomail_finance_ai.portfolio_agent import (
    LLMPortfolioEvaluator,
    MCPPortfolioAgent,
    PortfolioEvaluation,
    _evaluation_from_text,
)
from moomail_finance_ai.sql_store import PortfolioSqlStore
from scripts.portfolio_agent_review import portfolio_agent_terminal_summary_lines


def test_portfolio_agent_runs_pipeline_through_three_mcp_modules(tmp_path, recorded_opend_client):
    store = PortfolioSqlStore(tmp_path / "portfolio.sqlite")
    evaluator = CapturingEvaluator()
    agent = MCPPortfolioAgent(
        opend_mcp=build_opend_mcp_module(client=recorded_opend_client, config=OpenDConfig()),
        finance_metrics_mcp=build_finance_metrics_mcp_module(),
        portfolio_sql_mcp=build_portfolio_sql_mcp_module(store=store),
        evaluator=evaluator,
    )

    result = agent.run("Review my portfolio risk", mock_investment_policy())

    assert result.snapshot.holdings[0].ticker == "AAPL"
    assert {metric.metric_name for metric in result.metrics} == {
        "asset_type_allocation",
        "benchmark_reference",
        "cash_weight",
        "position_weights",
        "single_position_concentration",
    }
    assert result.storage_result["status"] == "inserted"
    assert result.metrics_storage_result["metrics_stored"] == 0
    assert result.metrics_storage_result["weight_rows_stored"] == 2
    assert result.effective_cash.effective_cash_value == 100.0
    assert result.effective_cash.effective_cash_weight == 0.1
    assert result.history_context.history_status["snapshot_count"] == 0
    assert result.history_context.portfolio_growth == []
    assert result.history_context.allocation_history == []
    assert result.history_context.position_state_changes == []
    assert result.evaluation.summary == "Portfolio-only evaluation complete."
    assert evaluator.context["storage_result"]["status"] == "pending"
    assert evaluator.context["history_status"]["snapshot_count"] == 0
    terminal_summary = "\n".join(portfolio_agent_terminal_summary_lines(result))
    assert "Effective cash: USD 100.00 (10.00%)" in terminal_summary
    assert "SQL storage: inserted value_snapshot_id=" in terminal_summary
    assert "History before this run: 0 value snapshot(s)" in terminal_summary
    assert evaluator.calls == 1
    assert store.table_count("portfolio_value_snapshots") == 1
    assert store.table_count("portfolio_weight_snapshots") == 2
    assert store.table_count("position_states") == 1
    assert "moomail-opend-mcp:opend_get_portfolio_context" in result.tool_calls
    assert "moomail-finance-metrics-mcp:calculate_snapshot_metrics" in result.tool_calls
    assert "moomail-portfolio-sql-mcp:portfolio_sql_store_daily_value_snapshot" in (
        result.tool_calls
    )
    assert "moomail-portfolio-sql-mcp:portfolio_sql_store_weight_snapshots" in (
        result.tool_calls
    )
    assert "moomail-portfolio-sql-mcp:portfolio_sql_get_portfolio_growth" in result.tool_calls
    assert "moomail-portfolio-sql-mcp:portfolio_sql_get_allocation_history" in result.tool_calls
    assert "moomail-portfolio-sql-mcp:portfolio_sql_get_position_state_changes" in (
        result.tool_calls
    )
    assert result.tool_calls.index(
        "moomail-portfolio-sql-mcp:portfolio_sql_get_portfolio_growth"
    ) < result.tool_calls.index(
        "moomail-portfolio-sql-mcp:portfolio_sql_store_daily_value_snapshot"
    )
    assert [
        event.status
        for event in result.status_events
        if event.status
        in {
            "evaluating_portfolio",
            "portfolio_evaluation_ready",
            "updating_portfolio_history",
        }
    ] == [
        "evaluating_portfolio",
        "portfolio_evaluation_ready",
        "updating_portfolio_history",
    ]


def test_portfolio_agent_contract_includes_otc_warning_and_effective_cash_sweep(tmp_path):
    report = _otc_and_cash_sweep_report()
    store = PortfolioSqlStore(tmp_path / "portfolio.sqlite")
    agent = MCPPortfolioAgent(
        opend_mcp=build_opend_mcp_module(
            client=RecordedOpenDClient(report),
            config=OpenDConfig(base_currency="USD", treat_fund_assets_as_cash_sweep=True),
        ),
        finance_metrics_mcp=build_finance_metrics_mcp_module(),
        portfolio_sql_mcp=build_portfolio_sql_mcp_module(store=store),
        evaluator=CapturingEvaluator(),
    )

    result = agent.run("How much effective cash do I have?", mock_investment_policy())

    assert result.snapshot.data_quality.missing_fields == ["quotes_for_all_positions"]
    assert result.effective_cash.cash_value == 3.0
    assert result.effective_cash.auto_invested_fund_assets_value == 250.0
    assert result.effective_cash.effective_cash_value == 253.0
    assert result.effective_cash.effective_cash_weight == 0.253
    assert any("US.TCEHY" in warning for warning in result.warnings)
    assert any("auto-invested money-market" in warning for warning in result.warnings)
    assert result.storage_result["status"] == "skipped"
    assert result.context_plan is not None
    assert result.context_plan.needs_sql_history is False
    assert result.context_plan.persist_observation is False
    assert store.table_count("portfolio_value_snapshots") == 0
    assert store.table_count("portfolio_weight_snapshots") == 0
    assert store.table_count("data_quality_events") == 0


def test_portfolio_agent_daily_storage_is_idempotent(tmp_path, recorded_opend_client):
    store = PortfolioSqlStore(tmp_path / "portfolio.sqlite")
    agent = MCPPortfolioAgent(
        opend_mcp=build_opend_mcp_module(client=recorded_opend_client, config=OpenDConfig()),
        finance_metrics_mcp=build_finance_metrics_mcp_module(),
        portfolio_sql_mcp=build_portfolio_sql_mcp_module(store=store),
        evaluator=CapturingEvaluator(),
    )
    ips = mock_investment_policy()

    first = agent.run("Review my portfolio", ips)
    second = agent.run("Review my portfolio again", ips)

    assert first.storage_result["status"] == "inserted"
    assert first.history_context.history_status["snapshot_count"] == 0
    assert second.storage_result["status"] == "updated"
    assert second.history_context.history_status["snapshot_count"] == 1
    assert len(second.history_context.portfolio_growth) == 1
    assert second.storage_result["value_snapshot_id"] == first.storage_result["value_snapshot_id"]
    assert second.metrics_storage_result["metrics_stored"] == 0
    assert store.table_count("portfolio_value_snapshots") == 1
    assert store.table_count("portfolio_weight_snapshots") == 2


def test_llm_portfolio_evaluator_parses_structured_json_from_llm():
    evaluator = LLMPortfolioEvaluator(FakeLLM())
    packet = mock_portfolio_packet()
    ips = mock_investment_policy()
    metrics = calculate_snapshot_metrics(packet.snapshot, ips)

    evaluation = evaluator.evaluate(
        query="Review my portfolio",
        ips=ips,
        snapshot=packet.snapshot,
        portfolio_packet=packet,
        metrics=metrics,
        storage_result={"status": "inserted"},
        history_status={"snapshot_count": 1, "data_quality": {"warnings": []}},
    )

    assert evaluation.summary == "Cash is modest and one holding is material."
    assert evaluation.risks == ["Single-name concentration should be monitored."]
    assert evaluation.llm_model == "gemini-test"


def test_llm_portfolio_evaluator_prompt_requires_query_first_summary():
    llm = CapturingLLM()
    evaluator = LLMPortfolioEvaluator(llm)
    packet = mock_portfolio_packet()
    ips = mock_investment_policy()
    metrics = calculate_snapshot_metrics(packet.snapshot, ips)

    evaluator.evaluate(
        query="How much effective cash do I have?",
        ips=ips,
        snapshot=packet.snapshot,
        portfolio_packet=packet,
        metrics=metrics,
        storage_result={"status": "inserted"},
        history_status={"snapshot_count": 1, "data_quality": {"warnings": []}},
    )

    assert "How much effective cash do I have?" in llm.prompt
    assert "Answer user_query directly in the summary" in llm.prompt
    assert "auto_invested_fund_assets_value" in llm.prompt
    assert "summary must answer the user_query directly" in llm.system_instruction


def test_llm_portfolio_evaluator_recovers_partial_json_without_raw_markdown_summary():
    text = """
    ```json
    {
      "summary": "The portfolio is growth-oriented with almost no cash.",
      "strengths": [
        "No single stock exceeds the concentration limit.",
        "Several core positions have strong unrealized gains."
      ],
      "risks": [
        "Cash balance is near zero.",
        "Option spread introduces downside risk.",
        "Geopolitical and regulatory risks"
    """

    evaluation = _evaluation_from_text(text, model="gemini-test")

    assert evaluation.summary == "The portfolio is growth-oriented with almost no cash."
    assert evaluation.strengths == [
        "No single stock exceeds the concentration limit.",
        "Several core positions have strong unrealized gains.",
    ]
    assert evaluation.risks == [
        "Cash balance is near zero.",
        "Option spread introduces downside risk.",
        "Geopolitical and regulatory risks",
    ]
    assert not evaluation.summary.startswith("```json")
    assert evaluation.warnings


def _otc_and_cash_sweep_report() -> OpenDFieldReport:
    now = datetime(2026, 6, 3, tzinfo=UTC)
    return OpenDFieldReport(
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
                name="accounts",
                rows=[{"acc_id": "redacted"}],
                fields=["acc_id"],
                as_of=now,
            ),
            OpenDTableResult(
                name="funds",
                rows=[
                    {
                        "total_assets": 1000.0,
                        "cash": 3.0,
                        "fund_assets": 250.0,
                        "currency": "USD",
                    }
                ],
                fields=["cash", "currency", "fund_assets", "total_assets"],
                as_of=now,
            ),
            OpenDTableResult(
                name="positions",
                rows=[
                    {
                        "code": "US.AAPL",
                        "stock_name": "Apple",
                        "position_market": "US",
                        "qty": 1,
                        "nominal_price": 300.0,
                        "market_val": 300.0,
                        "unrealized_pl": 10.0,
                        "currency": "USD",
                        "position_side": "LONG",
                    },
                    {
                        "code": "US.TCEHY",
                        "stock_name": "Tencent",
                        "position_market": "US",
                        "qty": 2,
                        "nominal_price": 100.0,
                        "market_val": 200.0,
                        "unrealized_pl": 5.0,
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
                        "last_price": 300.0,
                        "equity_valid": True,
                        "option_valid": False,
                    }
                ],
                fields=["code", "name", "last_price", "equity_valid", "option_valid"],
                as_of=now,
                warnings=[
                    "US.TCEHY quote query failed: quote:US.TCEHY query failed: "
                    "Do not support OTC market data TCEHY"
                ],
            ),
        ],
    )


class CapturingEvaluator:
    def __init__(self):
        self.calls = 0
        self.context: dict[str, Any] = {}

    def evaluate(self, **kwargs) -> PortfolioEvaluation:
        self.calls += 1
        self.context = kwargs
        return PortfolioEvaluation(
            summary="Portfolio-only evaluation complete.",
            strengths=["Live OpenD snapshot was normalized."],
            risks=["Historical depth is still limited."],
            history_observations=["Daily snapshot policy was applied."],
        )


class FakeLLMConfig:
    model = "gemini-test"


class FakeLLM:
    config = FakeLLMConfig()

    def generate_text(self, *args, **kwargs) -> str:
        return """
        ```json
        {
          "summary": "Cash is modest and one holding is material.",
          "strengths": ["Portfolio data is fresh."],
          "risks": ["Single-name concentration should be monitored."],
          "ips_mismatches": [],
          "history_observations": ["Only one snapshot is available."],
          "open_questions": []
        }
        ```
        """


class CapturingLLM(FakeLLM):
    def __init__(self):
        self.prompt = ""
        self.system_instruction = ""

    def generate_text(self, prompt, **kwargs) -> str:
        self.prompt = prompt
        self.system_instruction = kwargs.get("system_instruction", "")
        return super().generate_text(prompt, **kwargs)
