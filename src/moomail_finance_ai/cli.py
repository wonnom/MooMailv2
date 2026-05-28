from __future__ import annotations

import argparse
import json

from moomail_finance_ai.agents import InvestmentAgentPrototype
from moomail_finance_ai.schemas import AgentState


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the static Finance AI prototype.")
    parser.add_argument("query", nargs="*", default=["Review", "my", "portfolio"])
    parser.add_argument("--json", action="store_true", help="Print the full state as JSON.")
    args = parser.parse_args()

    state = InvestmentAgentPrototype().run(" ".join(args.query))
    if args.json:
        print(json.dumps(state.model_dump(mode="json"), indent=2))
    else:
        print(format_terminal_report(state))


def format_terminal_report(state: AgentState) -> str:
    if state.final_report is None or state.guardrail_result is None:
        return "Prototype run did not produce a final report."
    report = state.final_report
    lines = [
        f"# {report.title}",
        "",
        f"Mode: {report.mode}",
        f"As of: {report.as_of.isoformat()}",
        "",
        "## Summary",
        report.summary,
        "",
        "## Recommendations",
    ]
    for recommendation in report.recommendations:
        lines.extend(
            [
                f"- {recommendation.title}",
                f"  Rationale: {recommendation.rationale}",
            ]
        )
    lines.extend(["", "## Missing Data"])
    lines.extend(f"- {item}" for item in report.missing_data)
    lines.extend(["", "## Citations"])
    lines.extend(
        f"- {citation.citation_id}: {citation.title} ({citation.document_id})"
        for citation in report.citations
    )
    lines.extend(
        [
            "",
            "## Guardrails",
            f"Passed: {state.guardrail_result.passed}",
        ]
    )
    for check in state.guardrail_result.checks:
        lines.append(f"- {check.check}: {'pass' if check.passed else 'fail'} - {check.message}")
    return "\n".join(lines)

