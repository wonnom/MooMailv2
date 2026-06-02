from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from moomail_finance_ai.config import load_opend_config  # noqa: E402
from moomail_finance_ai.opend import MoomooOpenDClient, RecordedOpenDClient  # noqa: E402
from moomail_finance_ai.opend_health import build_opend_health_report  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run a read-only OpenD health report over connection, accounts, funds, "
            "positions, quotes, and normalized portfolio output."
        )
    )
    parser.add_argument("--env-file", default=None, help="Optional local env file path.")
    parser.add_argument(
        "--from-report",
        default=None,
        help="Use a saved OpenD field report instead of calling the live gateway.",
    )
    parser.add_argument(
        "--portfolio-id",
        default="portfolio_default",
        help="Portfolio id to use in the normalized snapshot summary.",
    )
    parser.add_argument(
        "--expected-holdings-count",
        type=int,
        default=None,
        help="Optional fail-fast check for the expected number of OpenD position rows.",
    )
    parser.add_argument("--output", default=None, help="Optional JSON output path.")
    args = parser.parse_args()

    config = load_opend_config(env_file=args.env_file)
    if args.from_report:
        client = RecordedOpenDClient.from_path(args.from_report)
        source = "recorded"
    else:
        client = MoomooOpenDClient(config)
        source = "live"

    report = build_opend_health_report(
        client,
        config,
        portfolio_id=args.portfolio_id,
        expected_holdings_count=args.expected_holdings_count,
        source=source,
    )
    payload = json.dumps(report.model_dump(mode="json"), indent=2)

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(payload + "\n", encoding="utf-8")

    print(payload)
    return 1 if report.status == "fail" else 0


if __name__ == "__main__":
    raise SystemExit(main())
