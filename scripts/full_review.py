from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from moomail_finance_ai.full_agent import build_default_full_agent  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the full local Investment Agent.")
    parser.add_argument("query", nargs="*", default=["Review", "my", "portfolio"])
    parser.add_argument("--from-report", default="reports/opend/field-report.json")
    parser.add_argument("--db", default="data/portfolio-history.sqlite")
    parser.add_argument("--memory", default="data/investment-memory.json")
    parser.add_argument("--output", default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    agent = build_default_full_agent(
        from_report=args.from_report,
        db_path=args.db,
        memory_path=args.memory,
    )
    state = agent.run(" ".join(args.query))
    payload = json.dumps(state.model_dump(mode="json"), indent=2)
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(payload + "\n", encoding="utf-8")
    if args.json:
        print(payload)
    else:
        report = state.final_report
        guardrail = state.guardrail_result
        if report is None or guardrail is None:
            print("No final report produced.")
            return
        print(f"# {report.title}")
        print()
        print(report.summary)
        print()
        print(f"Guardrails passed: {guardrail.passed}")
        print(f"Citations: {len(report.citations)}")
        print(f"Missing data items: {len(report.missing_data)}")


if __name__ == "__main__":
    main()

