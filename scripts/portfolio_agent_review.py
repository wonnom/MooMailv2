from __future__ import annotations

import argparse
import json

from moomail_finance_ai.agent_schemas import AssetHint, PortfolioRequest
from moomail_finance_ai.mocks import mock_investment_policy
from moomail_finance_ai.portfolio_agent import (
    PortfolioAgentResult,
    build_default_portfolio_agent,
)


PORTFOLIO_TASK_INTENTS = [
    "full_review",
    "portfolio_fact",
    "risk_check",
    "what_changed",
    "deep_dive",
    "compare",
]
PORTFOLIO_OUTPUT_GOALS = [
    "snapshot",
    "allocation_context",
    "performance_context",
    "risk_context",
    "effective_cash",
    "position_changes",
    "portfolio_patterns",
    "derived_metrics",
    "sentiment_context_needs",
]
PORTFOLIO_FRESHNESS_REQUIREMENTS = ["latest_required", "cached_ok", "history_only"]
DEFAULT_REVIEW_OUTPUT_GOALS = [
    "snapshot",
    "allocation_context",
    "risk_context",
    "portfolio_patterns",
]


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the MCP-backed Portfolio Agent.")
    parser.add_argument("query", nargs="*", default=["Review", "my", "portfolio"])
    parser.add_argument("--env-file", default="config/local.env")
    parser.add_argument("--from-report", default=None)
    parser.add_argument("--db", default="data/portfolio-history.sqlite")
    parser.add_argument("--llm-provider", default=None, choices=["gemini", "openai"])
    parser.add_argument("--task-intent", choices=PORTFOLIO_TASK_INTENTS, default="full_review")
    parser.add_argument("--output-goal", action="append", choices=PORTFOLIO_OUTPUT_GOALS)
    parser.add_argument("--asset", action="append", default=[])
    parser.add_argument("--time-range", default="30d")
    parser.add_argument(
        "--freshness",
        choices=PORTFOLIO_FRESHNESS_REQUIREMENTS,
        default="latest_required",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    agent = build_default_portfolio_agent(
        env_file=args.env_file,
        from_report=args.from_report,
        db_path=args.db,
        llm_provider=args.llm_provider,
    )
    try:
        query = " ".join(args.query)
        request = PortfolioRequest(
            task_intent=args.task_intent,
            asset_hints=[AssetHint(raw_input=asset) for asset in args.asset],
            time_range=args.time_range,
            freshness_requirement=args.freshness,
            output_goals=args.output_goal or DEFAULT_REVIEW_OUTPUT_GOALS,
            source_query=query,
        )
        result = agent.run(
            query,
            mock_investment_policy(),
            portfolio_request=request,
        )
        if args.json:
            print(json.dumps(result.model_dump(mode="json"), indent=2))
            return

        print("\n".join(portfolio_agent_terminal_summary_lines(result)))
    finally:
        agent.close()


def portfolio_agent_terminal_summary_lines(result: PortfolioAgentResult) -> list[str]:
    snapshot = result.snapshot
    effective_cash = result.effective_cash
    history_status = result.history_status
    lines = [
        "# Portfolio Agent Review",
        "",
        result.evaluation.summary,
        "",
        f"Portfolio value: {_format_currency(snapshot.total_value.amount, snapshot.total_value.currency)}",
        (
            "Effective cash: "
            f"{_format_currency(effective_cash.effective_cash_value, effective_cash.currency)} "
            f"({_format_percent(effective_cash.effective_cash_weight)})"
        ),
        f"Holdings: {len(snapshot.holdings)} | Cash lines: {len(snapshot.cash)}",
        (
            "SQL storage: "
            f"{result.storage_result.get('status')} "
            f"value_snapshot_id={result.storage_result.get('value_snapshot_id')}"
        ),
        (
            "History before this run: "
            f"{history_status.get('snapshot_count', 0)} value snapshot(s), "
            f"freshness={history_status.get('data_quality', {}).get('freshness_status', 'unknown')}"
        ),
        f"Metrics calculated: {len(result.metrics)}",
        f"Weight rows stored: {result.metrics_storage_result.get('weight_rows_stored', 0)}",
        f"Tool calls: {len(result.tool_calls)}",
    ]
    if result.warnings:
        lines.extend(["", "Warnings:"])
        for warning in result.warnings:
            lines.append(f"- {warning}")
    return lines


def _format_currency(value: float, currency: str) -> str:
    return f"{currency} {value:,.2f}"


def _format_percent(value: float) -> str:
    return f"{value:.2%}"


if __name__ == "__main__":
    main()
