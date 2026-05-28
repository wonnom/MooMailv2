from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from moomail_finance_ai.config import load_opend_config  # noqa: E402
from moomail_finance_ai.guardrails import review_report  # noqa: E402
from moomail_finance_ai.metrics import calculate_snapshot_metrics  # noqa: E402
from moomail_finance_ai.mocks import mock_investment_policy  # noqa: E402
from moomail_finance_ai.opend import MoomooOpenDClient, RecordedOpenDClient  # noqa: E402
from moomail_finance_ai.opend_portfolio import (  # noqa: E402
    build_portfolio_agent_packet,
    build_portfolio_snapshot_from_report,
)
from moomail_finance_ai.schemas import AuditRecord, FinalReport  # noqa: E402
from moomail_finance_ai.sql_store import PortfolioSqlStore  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Persist a portfolio snapshot, deterministic metrics, and audit summary."
    )
    parser.add_argument("--from-report", default=None, help="Use a saved OpenD field report.")
    parser.add_argument("--env-file", default=None, help="Optional local env file for live OpenD.")
    parser.add_argument("--db", default="data/portfolio-history.sqlite", help="SQLite DB path.")
    parser.add_argument("--output", default=None, help="Optional summary JSON output path.")
    args = parser.parse_args()

    config = load_opend_config(env_file=args.env_file)
    client = (
        RecordedOpenDClient.from_path(args.from_report)
        if args.from_report
        else MoomooOpenDClient(config)
    )
    report = client.explore_fields()
    ips = mock_investment_policy()
    snapshot = build_portfolio_snapshot_from_report(
        report,
        portfolio_id=ips.portfolio_id,
        base_currency=config.base_currency,
    )
    packet = build_portfolio_agent_packet(snapshot, ips, report)
    metrics = calculate_snapshot_metrics(snapshot, ips)

    store = PortfolioSqlStore(args.db)
    stored = store.store_snapshot(snapshot, source_report=report)
    metrics_count = store.store_metrics(stored.snapshot_id, metrics)
    audit = _audit_for_demo(packet.snapshot.as_of, stored.snapshot_id)
    store.store_audit_record(audit)
    history_status = store.history_status(ips.portfolio_id)

    summary = {
        "db": args.db,
        "snapshot_id": stored.snapshot_id,
        "portfolio_id": stored.portfolio_id,
        "as_of": stored.as_of.isoformat(),
        "holdings_count": stored.holdings_count,
        "quotes_count": stored.quotes_count,
        "metrics_count": metrics_count,
        "agent_runs_count": store.table_count("agent_runs"),
        "history_status": history_status.model_dump(mode="json"),
        "data_quality_warnings": packet.data_quality.warnings,
    }
    payload = json.dumps(summary, indent=2)
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(payload + "\n", encoding="utf-8")
    print(payload)


def _audit_for_demo(as_of: datetime, snapshot_id: str) -> AuditRecord:
    report = FinalReport(
        run_id=f"history_demo_{snapshot_id}",
        mode="review",
        title="Recorded Portfolio History Demo",
        as_of=as_of,
        summary="Stored a recorded OpenD portfolio snapshot and deterministic metric set.",
        portfolio_snapshot={},
        portfolio_analysis={},
        sentiment_analysis={},
        recommendations=[],
        missing_data=[],
        assumptions=["Recorded OpenD report used instead of live gateway call."],
        citations=[],
    )
    guardrail_result = review_report(
        report.model_copy(
            update={
                "recommendations": [],
                "missing_data": ["Sentiment and full review synthesis are outside Milestone 3."],
            }
        )
    )
    return AuditRecord(
        run_id=report.run_id,
        timestamp=datetime.now(UTC),
        user_query="Milestone 3 recorded portfolio history demo",
        mode="review",
        tools_called=["recorded_opend_client", "portfolio_sql_store", "finance_metrics"],
        data_timestamps=[as_of.isoformat()],
        source_ids=[snapshot_id],
        assumptions=report.assumptions,
        guardrail_result=guardrail_result,
        output_summary=report.summary,
        memory_updates=[],
    )


if __name__ == "__main__":
    main()

