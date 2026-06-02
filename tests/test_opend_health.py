from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from moomail_finance_ai.config import OpenDConfig
from moomail_finance_ai.opend import (
    OpenDConnectionStatus,
    OpenDFieldReport,
    OpenDTableResult,
    RecordedOpenDClient,
)
from moomail_finance_ai.opend_health import build_opend_health_report


ROOT = Path(__file__).resolve().parents[1]


def test_opend_health_report_warns_but_builds_when_one_quote_is_missing():
    report = _health_report_fixture()
    client = RecordedOpenDClient(report)

    health = build_opend_health_report(
        client,
        OpenDConfig(base_currency="USD", treat_fund_assets_as_cash_sweep=True),
        expected_holdings_count=2,
        source="recorded",
    )

    checks = {check.name: check for check in health.table_checks}
    holdings = health.portfolio_summary["holdings"]
    missing_quote_holding = next(row for row in holdings if row["provider_code"] == "US.TCEHY")

    assert health.status == "warn"
    assert health.errors == []
    assert checks["accounts"].ok is True
    assert checks["funds"].row_count == 1
    assert checks["positions"].row_count == 2
    assert checks["quotes"].warnings == ["Recorded quote rows missing for: US.TCEHY"]
    assert health.quote_coverage["missing_quote_codes"] == ["US.TCEHY"]
    assert health.portfolio_summary["holdings_count"] == 2
    assert missing_quote_holding["quote_available"] is False
    assert health.cash_summary["auto_invested_fund_assets_present"] is True
    assert health.cash_summary["auto_invested_fund_assets_value"] == 250.0
    assert any("auto-invested money-market" in warning for warning in health.warnings)


def test_opend_health_report_fails_on_expected_holdings_mismatch():
    health = build_opend_health_report(
        RecordedOpenDClient(_health_report_fixture()),
        OpenDConfig(base_currency="USD"),
        expected_holdings_count=3,
        source="recorded",
    )

    assert health.status == "fail"
    assert any("Expected holdings count mismatch" in error for error in health.errors)


def test_opend_health_report_handles_missing_quote_table_as_warning():
    report = _health_report_fixture(include_quotes=False)

    health = build_opend_health_report(
        RecordedOpenDClient(report),
        OpenDConfig(base_currency="USD"),
        expected_holdings_count=2,
        source="recorded",
    )

    assert health.status == "warn"
    assert health.quote_coverage["returned_quote_codes"] == []
    assert health.quote_coverage["missing_quote_codes"] == ["US.AAPL", "US.TCEHY"]
    assert any("quotes read failed" in warning for warning in health.warnings)


def test_opend_health_report_cli_runs_recorded_mode(tmp_path):
    report_path = tmp_path / "field-report.json"
    report_path.write_text(_health_report_fixture().model_dump_json(), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "opend_health_report.py"),
            "--from-report",
            str(report_path),
            "--expected-holdings-count",
            "2",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    payload = json.loads(result.stdout)

    assert result.returncode == 0
    assert payload["source"] == "recorded"
    assert payload["status"] == "warn"
    assert payload["quote_coverage"]["missing_quote_codes"] == ["US.TCEHY"]


def _health_report_fixture(*, include_quotes: bool = True) -> OpenDFieldReport:
    now = datetime(2026, 6, 2, tzinfo=UTC)
    tables = [
        OpenDTableResult(
            name="accounts",
            rows=[{"acc_id": "redacted", "trd_env": "REAL"}],
            fields=["acc_id", "trd_env"],
            as_of=now,
        ),
        OpenDTableResult(
            name="funds",
            rows=[
                {
                    "total_assets": 1000.0,
                    "cash": 3.0,
                    "fund_assets": 250.0,
                    "currency": "USD",
                }
            ],
            fields=["cash", "currency", "fund_assets", "total_assets"],
            as_of=now,
        ),
        OpenDTableResult(
            name="positions",
            rows=[
                {
                    "code": "US.AAPL",
                    "stock_name": "Apple",
                    "position_market": "US",
                    "qty": 1,
                    "nominal_price": 300.0,
                    "market_val": 300.0,
                    "unrealized_pl": 10.0,
                    "currency": "USD",
                    "position_side": "LONG",
                },
                {
                    "code": "US.TCEHY",
                    "stock_name": "Tencent",
                    "position_market": "US",
                    "qty": 2,
                    "nominal_price": 100.0,
                    "market_val": 200.0,
                    "unrealized_pl": 5.0,
                    "currency": "USD",
                    "position_side": "LONG",
                },
            ],
            fields=[
                "code",
                "stock_name",
                "position_market",
                "qty",
                "nominal_price",
                "market_val",
                "unrealized_pl",
                "currency",
                "position_side",
            ],
            as_of=now,
        ),
    ]
    if include_quotes:
        tables.append(
            OpenDTableResult(
                name="quotes",
                rows=[
                    {
                        "code": "US.AAPL",
                        "name": "Apple",
                        "last_price": 300.0,
                        "option_valid": False,
                        "equity_valid": True,
                    }
                ],
                fields=["code", "equity_valid", "last_price", "name", "option_valid"],
                as_of=now,
            )
        )
    return OpenDFieldReport(
        generated_at=now,
        connection=OpenDConnectionStatus(
            ok=True,
            host="127.0.0.1",
            port=11111,
            checked_at=now,
            message="ok",
        ),
        tables=tables,
    )
