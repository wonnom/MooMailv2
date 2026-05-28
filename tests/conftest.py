from __future__ import annotations

from datetime import UTC, datetime

import pytest

from moomail_finance_ai.opend import (
    OpenDConnectionStatus,
    OpenDFieldReport,
    OpenDTableResult,
    RecordedOpenDClient,
)


@pytest.fixture
def sample_opend_report() -> OpenDFieldReport:
    now = datetime(2026, 5, 23, tzinfo=UTC)
    return OpenDFieldReport(
        generated_at=now,
        connection=OpenDConnectionStatus(
            ok=True,
            host="127.0.0.1",
            port=11111,
            checked_at=now,
            message="ok",
        ),
        tables=[
            OpenDTableResult(
                name="accounts",
                rows=[{"acc_id": "redacted"}],
                fields=["acc_id"],
                as_of=now,
            ),
            OpenDTableResult(
                name="funds",
                rows=[{"total_assets": 1000.0, "cash": 100.0, "currency": "USD"}],
                fields=["total_assets", "cash", "currency"],
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
                    }
                ],
                fields=[
                    "code",
                    "stock_name",
                    "position_market",
                    "qty",
                    "nominal_price",
                    "market_val",
                ],
                as_of=now,
            ),
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
                fields=["code", "name", "last_price", "option_valid", "equity_valid"],
                as_of=now,
            ),
        ],
    )


@pytest.fixture
def recorded_opend_client(sample_opend_report: OpenDFieldReport) -> RecordedOpenDClient:
    return RecordedOpenDClient(sample_opend_report)


@pytest.fixture
def sample_opend_report_path(tmp_path, sample_opend_report: OpenDFieldReport):
    report_path = tmp_path / "field-report.json"
    report_path.write_text(sample_opend_report.model_dump_json(), encoding="utf-8")
    return report_path
