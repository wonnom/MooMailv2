from __future__ import annotations

import argparse
import json

from moomail_finance_ai.agent_schemas import AssetHint, PortfolioRequest
from moomail_finance_ai.chat_api import chat_response
from moomail_finance_ai.portfolio_agent import build_default_portfolio_agent
from moomail_finance_ai.investment_agent import build_default_investment_agent
from moomail_finance_ai.mocks import mock_investment_policy


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


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the local Finance AI runtime.")
    parser.add_argument("query", nargs="*", default=["Review", "my", "portfolio"])
    parser.add_argument("--agent", choices=["portfolio", "investment"], default="investment")
    parser.add_argument("--env-file", default="config/local.env")
    parser.add_argument("--from-report", default="reports/opend/field-report.json")
    parser.add_argument("--db", default="data/portfolio-history.sqlite")
    parser.add_argument("--llm-provider", default=None, choices=["gemini", "openai"])
    parser.add_argument("--portfolio-task-intent", choices=PORTFOLIO_TASK_INTENTS)
    parser.add_argument(
        "--portfolio-output-goal",
        action="append",
        choices=PORTFOLIO_OUTPUT_GOALS,
        default=[],
    )
    parser.add_argument("--portfolio-asset", action="append", default=[])
    parser.add_argument("--portfolio-time-range", default="30d")
    parser.add_argument(
        "--portfolio-freshness",
        choices=PORTFOLIO_FRESHNESS_REQUIREMENTS,
        default="latest_required",
    )
    parser.add_argument("--json", action="store_true", help="Print the full state as JSON.")
    args = parser.parse_args()

    query = " ".join(args.query)
    agent = None
    try:
        if args.agent == "portfolio":
            portfolio_request = _portfolio_request_from_args(args, query, parser)
            agent = build_default_portfolio_agent(
                env_file=args.env_file,
                from_report=args.from_report,
                db_path=args.db,
                llm_provider=args.llm_provider,
            )
            state = agent.run(
                query,
                mock_investment_policy(),
                portfolio_request=portfolio_request,
            )
        else:
            agent = build_default_investment_agent(
                env_file=args.env_file,
                from_report=args.from_report,
                db_path=args.db,
                llm_provider=args.llm_provider,
            )
            state = agent.run(query)

        if args.json:
            print(json.dumps(state.model_dump(mode="json"), indent=2))
        else:
            print(format_terminal_report(chat_response(state)))
    finally:
        close = getattr(agent, "close", None)
        if callable(close):
            close()


def _portfolio_request_from_args(
    args: argparse.Namespace,
    query: str,
    parser: argparse.ArgumentParser,
) -> PortfolioRequest:
    if not args.portfolio_task_intent or not args.portfolio_output_goal:
        parser.error(
            "--agent portfolio requires --portfolio-task-intent and at least one "
            "--portfolio-output-goal; raw free-text portfolio planning is unsupported."
        )
    return PortfolioRequest(
        task_intent=args.portfolio_task_intent,
        asset_hints=[AssetHint(raw_input=asset) for asset in args.portfolio_asset],
        time_range=args.portfolio_time_range,
        freshness_requirement=args.portfolio_freshness,
        output_goals=args.portfolio_output_goal,
        source_query=query,
    )


def format_terminal_report(payload: dict) -> str:
    report = payload.get("final_report")
    guardrail = payload.get("guardrail_result")
    if not report:
        return "Agent run did not produce a final report."
    lines = [
        f"# {report['title']}",
        "",
        f"Agent: {payload.get('agent_type', 'unknown')}",
        f"Mode: {payload.get('mode') or report.get('mode')}",
        f"As of: {report.get('as_of')}",
        "",
        "## Summary",
        report["summary"],
    ]
    recommendations = report.get("recommendations") or []
    if recommendations:
        lines.extend(["", "## Recommendations"])
    for recommendation in recommendations:
        lines.extend(
            [
                f"- {recommendation['title']}",
                f"  Rationale: {recommendation['rationale']}",
            ]
        )
    missing_data = report.get("missing_data") or []
    if missing_data:
        lines.extend(["", "## Missing Data"])
        lines.extend(f"- {item}" for item in missing_data)
    if guardrail:
        lines.extend(["", "## Guardrails", f"Passed: {guardrail.get('passed')}"])
        for check in guardrail.get("checks", []):
            status = "pass" if check.get("passed") else "fail"
            lines.append(f"- {check.get('check')}: {status} - {check.get('message')}")
    return "\n".join(lines)
