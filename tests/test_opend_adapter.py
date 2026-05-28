from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import patch

from moomail_finance_ai.config import OpenDConfig
from moomail_finance_ai.opend import (
    MoomooOpenDClient,
    OpenDConnectionStatus,
    OpenDDependencyError,
    OpenDFieldReport,
    OpenDTableResult,
    RecordedOpenDClient,
)


def test_opend_client_is_read_only_surface():
    public_methods = {
        name
        for name in dir(MoomooOpenDClient)
        if not name.startswith("_") and callable(getattr(MoomooOpenDClient, name))
    }

    assert public_methods == {
        "check_connection",
        "explore_fields",
        "get_account_funds",
        "get_account_list",
        "get_market_snapshots",
        "get_positions",
    }
    assert not any("order" in method for method in public_methods)
    assert not any("trade" in method for method in public_methods)


def test_missing_moomoo_sdk_returns_failed_connection_status(monkeypatch):
    def missing_import(name):
        raise ModuleNotFoundError(name)

    monkeypatch.setattr("moomail_finance_ai.opend.import_module", missing_import)
    client = MoomooOpenDClient(OpenDConfig())
    monkeypatch.setattr(client, "_check_socket", lambda: None)

    status = client.check_connection()

    assert status.ok is False
    assert "moomoo OpenAPI SDK is not installed" in status.message


def test_table_from_success_response_normalizes_records_and_fields():
    client = MoomooOpenDClient(OpenDConfig())
    client._sdk = SimpleNamespace(RET_OK=0)
    data = [
        {"code": "US.AAPL", "qty": 10},
        {"code": "US.MSFT", "market_val": 1000.0},
    ]

    result = client._table_from_response("positions", 0, data)

    assert result.name == "positions"
    assert result.rows == data
    assert result.fields == ["code", "market_val", "qty"]
    assert result.as_of.replace(tzinfo=UTC) <= datetime.now(UTC)


def test_table_from_error_response_raises_connection_error():
    client = MoomooOpenDClient(OpenDConfig())
    client._sdk = SimpleNamespace(RET_OK=0)

    try:
        client._table_from_response("positions", -1, "bad connection")
    except Exception as exc:
        assert "positions query failed" in str(exc)
    else:
        raise AssertionError("Expected failing OpenD response to raise")


def test_load_sdk_raises_dependency_error_when_package_missing(monkeypatch):
    def missing_import(name):
        raise ModuleNotFoundError(name)

    monkeypatch.setattr("moomail_finance_ai.opend.import_module", missing_import)
    client = MoomooOpenDClient(OpenDConfig())

    try:
        client._load_sdk()
    except OpenDDependencyError as exc:
        assert "pip install moomoo-api" in str(exc)
    else:
        raise AssertionError("Expected missing optional SDK to raise")


def test_market_snapshot_retries_per_code_after_batch_failure(monkeypatch):
    client = MoomooOpenDClient(OpenDConfig())
    client._sdk = SimpleNamespace(RET_OK=0)

    class FakeQuoteContext:
        def get_market_snapshot(self, codes):
            if len(codes) > 1:
                return -1, "Do not support OTC market data TCEHY"
            if codes == ["US.TCEHY"]:
                return -1, "Do not support OTC market data TCEHY"
            return 0, [{"code": codes[0], "last_price": 123.45}]

    with patch.object(client, "_quote_context") as quote_context:
        quote_context.return_value.__enter__.return_value = FakeQuoteContext()
        quote_context.return_value.__exit__.return_value = None

        result = client.get_market_snapshots(["US.MSFT", "US.TCEHY"])

    assert result.name == "quotes"
    assert result.rows == [{"code": "US.MSFT", "last_price": 123.45}]
    assert result.fields == ["code", "last_price"]
    assert len(result.warnings) == 2
    assert "Batch quote query failed" in result.warnings[0]
    assert "US.TCEHY quote query failed" in result.warnings[1]


def test_recorded_opend_client_serves_saved_field_report(tmp_path):
    now = datetime(2026, 5, 23, tzinfo=UTC)
    report = OpenDFieldReport(
        generated_at=now,
        connection=OpenDConnectionStatus(
            ok=True,
            host="127.0.0.1",
            port=11111,
            checked_at=now,
            message="Connected to OpenD quote context.",
        ),
        tables=[
            OpenDTableResult(
                name="accounts",
                rows=[{"acc_id": "redacted"}],
                fields=["acc_id"],
                as_of=now,
            ),
            OpenDTableResult(
                name="quotes",
                rows=[{"code": "US.AAPL", "last_price": 300.0}],
                fields=["code", "last_price"],
                as_of=now,
            ),
        ],
    )
    report_path = tmp_path / "field-report.json"
    report_path.write_text(report.model_dump_json(), encoding="utf-8")

    client = RecordedOpenDClient.from_path(report_path)

    assert client.check_connection().ok is True
    assert "Loaded recorded OpenD report" in client.check_connection().message
    assert client.get_account_list().rows == [{"acc_id": "redacted"}]
    assert client.get_market_snapshots(["US.AAPL"]).rows == [
        {"code": "US.AAPL", "last_price": 300.0}
    ]
    missing_quotes = client.get_market_snapshots(["US.MSFT"])
    assert missing_quotes.rows == []
    assert "US.MSFT" in missing_quotes.warnings[-1]
