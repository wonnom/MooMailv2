from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from moomail_finance_ai.mocks import mock_investment_policy  # noqa: E402
from moomail_finance_ai.portfolio_agent import build_default_portfolio_agent  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the MCP-backed Portfolio Agent.")
    parser.add_argument("query", nargs="*", default=["Review", "my", "portfolio"])
    parser.add_argument("--env-file", default="config/local.env")
    parser.add_argument("--from-report", default=None)
    parser.add_argument("--db", default="data/portfolio-history.sqlite")
    parser.add_argument("--llm-provider", default=None, choices=["gemini", "openai"])
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    agent = build_default_portfolio_agent(
        env_file=args.env_file,
        from_report=args.from_report,
        db_path=args.db,
        llm_provider=args.llm_provider,
    )
    result = agent.run(" ".join(args.query), mock_investment_policy())
    if args.json:
        print(json.dumps(result.model_dump(mode="json"), indent=2))
        return

    print("# Portfolio Agent Review")
    print()
    print(result.evaluation.summary)
    print()
    print(f"Snapshot storage: {result.storage_result.get('status')}")
    print(f"Metrics calculated: {len(result.metrics)}")
    print(f"Tool calls: {len(result.tool_calls)}")
    if result.warnings:
        print()
        print("Warnings:")
        for warning in result.warnings:
            print(f"- {warning}")


if __name__ == "__main__":
    main()
