from __future__ import annotations

import argparse
import json

from moomail_finance_ai.chat_api import chat_response
from moomail_finance_ai.portfolio_agent import build_default_portfolio_agent
from moomail_finance_ai.investment_agent import build_default_investment_agent
from moomail_finance_ai.mocks import mock_investment_policy


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the local Finance AI runtime.")
    parser.add_argument("query", nargs="*", default=["Review", "my", "portfolio"])
    parser.add_argument("--agent", choices=["portfolio", "investment"], default="investment")
    parser.add_argument("--env-file", default="config/local.env")
    parser.add_argument("--from-report", default="reports/opend/field-report.json")
    parser.add_argument("--db", default="data/portfolio-history.sqlite")
    parser.add_argument("--llm-provider", default=None, choices=["gemini", "openai"])
    parser.add_argument("--json", action="store_true", help="Print the full state as JSON.")
    args = parser.parse_args()

    query = " ".join(args.query)
    agent = None
    try:
        if args.agent == "portfolio":
            agent = build_default_portfolio_agent(
                env_file=args.env_file,
                from_report=args.from_report,
                db_path=args.db,
                llm_provider=args.llm_provider,
            )
            state = agent.run(query, mock_investment_policy())
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
