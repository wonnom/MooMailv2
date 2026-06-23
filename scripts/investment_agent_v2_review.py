from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from moomail_finance_ai.v2_investment_agent import build_default_v2_investment_agent  # noqa: E402
from moomail_finance_ai.v2_schemas import InvestmentAgentState  # noqa: E402
from moomail_finance_ai.v2_trace import sanitize_trace_events  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the V2 Investment Agent supervisor.")
    parser.add_argument("query", nargs="*", default=["Review", "my", "portfolio"])
    parser.add_argument("--env-file", default="config/local.env")
    parser.add_argument("--from-report", default="reports/opend/field-report.json")
    parser.add_argument("--db", default="data/portfolio-history.sqlite")
    parser.add_argument("--llm-provider", default=None, choices=["gemini", "openai"])
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    agent = build_default_v2_investment_agent(
        env_file=args.env_file,
        from_report=args.from_report,
        db_path=args.db,
        llm_provider=args.llm_provider,
    )
    try:
        state = agent.run(" ".join(args.query))
        if args.json:
            print(json.dumps(state.model_dump(mode="json"), indent=2))
            return

        print("\n".join(v2_terminal_summary_lines(state, graph_runtime=agent.graph_runtime)))
    finally:
        agent.close()


def v2_terminal_summary_lines(
    state: InvestmentAgentState,
    *,
    graph_runtime: str = "unknown",
) -> list[str]:
    final_report = state.final_report
    guardrail = state.guardrail_review
    lines = [
        "# V2 Investment Agent Review",
        "",
        f"Mode: {state.mode}",
        f"Graph runtime: {graph_runtime}",
    ]
    if final_report is not None:
        lines.extend(
            [
                "",
                final_report.summary,
                "",
                f"Missing data: {len(final_report.missing_data)}",
                f"Recommendations: {len(final_report.recommendations)}",
            ]
        )
    if guardrail is not None:
        lines.extend(
            [
                "",
                f"Guardrails: {guardrail.output_status}",
                f"Guardrails passed: {guardrail.passed}",
            ]
        )
        failed = [check for check in guardrail.checks if not check.passed]
        if failed:
            lines.append("Failed guardrail checks:")
            lines.extend(f"- {check.check}: {check.message}" for check in failed)
        else:
            lines.append(f"Guardrail checks: {len(guardrail.checks)} passed")
    if state.status_events:
        lines.extend(["", "Trace:"])
        for event in sanitize_trace_events(state.status_events):
            label = event.event_type
            if event.tool_name:
                label = f"{label}:{event.tool_name}"
            lines.append(f"- {event.status} [{label}] {event.message}")
    return lines


if __name__ == "__main__":
    main()
