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
from moomail_finance_ai.mocks import mock_investment_policy  # noqa: E402
from moomail_finance_ai.opend import MoomooOpenDClient, RecordedOpenDClient  # noqa: E402
from moomail_finance_ai.opend_portfolio import (  # noqa: E402
    build_portfolio_agent_packet,
    build_portfolio_snapshot_from_report,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a normalized OpenD portfolio snapshot.")
    parser.add_argument("--env-file", default=None, help="Optional local env file path.")
    parser.add_argument(
        "--from-report",
        default=None,
        help="Use a saved OpenD field report instead of calling the live gateway.",
    )
    parser.add_argument("--output", default=None, help="Optional full JSON output path.")
    parser.add_argument("--full-json", action="store_true", help="Print the full normalized packet.")
    args = parser.parse_args()

    config = load_opend_config(env_file=args.env_file)
    if args.from_report:
        report = RecordedOpenDClient.from_path(args.from_report).explore_fields()
    else:
        report = MoomooOpenDClient(config).explore_fields()
    ips = mock_investment_policy()
    snapshot = build_portfolio_snapshot_from_report(
        report,
        portfolio_id=ips.portfolio_id,
        base_currency=config.base_currency,
        treat_fund_assets_as_cash_sweep=config.treat_fund_assets_as_cash_sweep,
    )
    packet = build_portfolio_agent_packet(snapshot, ips, report)
    payload = json.dumps(packet.model_dump(mode="json"), indent=2)

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(payload + "\n", encoding="utf-8")

    if args.full_json:
        print(payload)
    else:
        summary = {
            "portfolio_id": packet.portfolio_id,
            "as_of": packet.snapshot.as_of.isoformat(),
            "holdings_count": len(packet.snapshot.holdings),
            "cash_balances_count": len(packet.snapshot.cash),
            "candidate_issues_count": len(packet.candidate_issues),
            "missing_fields": packet.data_quality.missing_fields,
            "warnings": packet.data_quality.warnings,
        }
        print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
