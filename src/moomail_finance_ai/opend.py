from __future__ import annotations

import os
import socket
from contextlib import contextmanager
from datetime import UTC, datetime
from importlib import import_module
from pathlib import Path
from typing import Any, Iterator, Protocol

from pydantic import Field

from moomail_finance_ai.config import OpenDConfig
from moomail_finance_ai.schemas import StrictModel


class OpenDDependencyError(RuntimeError):
    """Raised when the optional moomoo OpenAPI SDK is unavailable."""


class OpenDConnectionError(RuntimeError):
    """Raised when OpenD is unavailable or returns an error."""


class OpenDConnectionStatus(StrictModel):
    ok: bool
    host: str
    port: int
    checked_at: datetime
    message: str


class OpenDTableResult(StrictModel):
    name: str
    rows: list[dict[str, Any]]
    fields: list[str]
    source: str = "opend"
    as_of: datetime
    warnings: list[str] = Field(default_factory=list)


class OpenDFieldReport(StrictModel):
    generated_at: datetime
    connection: OpenDConnectionStatus
    tables: list[OpenDTableResult]
    warnings: list[str] = Field(default_factory=list)


class ReadOnlyOpenDClient(Protocol):
    def check_connection(self) -> OpenDConnectionStatus: ...

    def get_account_list(self) -> OpenDTableResult: ...

    def get_account_funds(self) -> OpenDTableResult: ...

    def get_positions(self) -> OpenDTableResult: ...

    def get_market_snapshots(self, codes: list[str]) -> OpenDTableResult: ...

    def explore_fields(self) -> OpenDFieldReport: ...


class MoomooOpenDClient:
    """Read-only OpenD adapter.

    This class intentionally exposes account, funds, positions, and quote reads only.
    It does not implement trade unlock, place order, modify order, or cancel order.
    """

    def __init__(self, config: OpenDConfig):
        self.config = config
        self._sdk: Any | None = None

    def check_connection(self) -> OpenDConnectionStatus:
        preflight = self._check_socket()
        if preflight is not None:
            return preflight
        try:
            with self._quote_context():
                return OpenDConnectionStatus(
                    ok=True,
                    host=self.config.host,
                    port=self.config.port,
                    checked_at=_now(),
                    message="Connected to OpenD quote context.",
                )
        except Exception as exc:
            return OpenDConnectionStatus(
                ok=False,
                host=self.config.host,
                port=self.config.port,
                checked_at=_now(),
                message=str(exc),
            )

    def _check_socket(self) -> OpenDConnectionStatus | None:
        try:
            with socket.create_connection(
                (self.config.host, self.config.port),
                timeout=self.config.connection_timeout_seconds,
            ):
                return None
        except OSError as exc:
            return OpenDConnectionStatus(
                ok=False,
                host=self.config.host,
                port=self.config.port,
                checked_at=_now(),
                message=f"OpenD socket unavailable: {exc}",
            )

    def get_account_list(self) -> OpenDTableResult:
        with self._trade_context() as trd_ctx:
            ret, data = trd_ctx.get_acc_list()
        return self._table_from_response("accounts", ret, data)

    def get_account_funds(self) -> OpenDTableResult:
        with self._trade_context() as trd_ctx:
            ret, data = trd_ctx.accinfo_query(
                trd_env=self._enum("TrdEnv", self.config.trade_env),
                acc_id=self.config.account_id or 0,
                acc_index=self.config.account_index,
                refresh_cache=True,
                currency=self._enum("Currency", self.config.base_currency),
            )
        return self._table_from_response("funds", ret, data)

    def get_positions(self) -> OpenDTableResult:
        with self._trade_context() as trd_ctx:
            ret, data = trd_ctx.position_list_query(
                position_market=self._enum("TrdMarket", self.config.trade_market),
                trd_env=self._enum("TrdEnv", self.config.trade_env),
                acc_id=self.config.account_id or 0,
                acc_index=self.config.account_index,
                refresh_cache=True,
            )
        return self._table_from_response("positions", ret, data)

    def get_market_snapshots(self, codes: list[str]) -> OpenDTableResult:
        if not codes:
            return OpenDTableResult(name="quotes", rows=[], fields=[], as_of=_now())
        with self._quote_context() as quote_ctx:
            ret, data = quote_ctx.get_market_snapshot(codes)
            try:
                return self._table_from_response("quotes", ret, data)
            except OpenDConnectionError as batch_error:
                rows: list[dict[str, Any]] = []
                warnings = [f"Batch quote query failed: {batch_error}"]
                for code in codes:
                    ret, data = quote_ctx.get_market_snapshot([code])
                    try:
                        single_result = self._table_from_response(f"quote:{code}", ret, data)
                    except OpenDConnectionError as exc:
                        warnings.append(f"{code} quote query failed: {exc}")
                        continue
                    rows.extend(single_result.rows)
        fields = sorted({field for row in rows for field in row})
        return OpenDTableResult(
            name="quotes",
            rows=rows,
            fields=fields,
            as_of=_now(),
            warnings=warnings,
        )

    def explore_fields(self) -> OpenDFieldReport:
        connection = self.check_connection()
        tables: list[OpenDTableResult] = []
        warnings: list[str] = []
        if not connection.ok:
            return OpenDFieldReport(
                generated_at=_now(),
                connection=connection,
                tables=tables,
                warnings=["OpenD connection failed; no fields explored."],
            )

        for fetch in (self.get_account_list, self.get_account_funds, self.get_positions):
            try:
                tables.append(fetch())
            except Exception as exc:
                warnings.append(f"{fetch.__name__} failed: {exc}")

        position_codes = _position_codes(next((table for table in tables if table.name == "positions"), None))
        if position_codes:
            try:
                tables.append(self.get_market_snapshots(position_codes))
            except Exception as exc:
                warnings.append(f"get_market_snapshots failed: {exc}")
        else:
            warnings.append("No position codes found; quote fields were not explored.")

        return OpenDFieldReport(
            generated_at=_now(),
            connection=connection,
            tables=tables,
            warnings=warnings,
        )

    @contextmanager
    def _quote_context(self) -> Iterator[Any]:
        sdk = self._load_sdk()
        self._configure_sdk(sdk)
        quote_ctx = sdk.OpenQuoteContext(
            host=self.config.host,
            port=self.config.port,
            is_encrypt=self.config.is_encrypt,
        )
        try:
            yield quote_ctx
        finally:
            quote_ctx.close()

    @contextmanager
    def _trade_context(self) -> Iterator[Any]:
        sdk = self._load_sdk()
        self._configure_sdk(sdk)
        trd_ctx = sdk.OpenSecTradeContext(
            filter_trdmarket=self._enum("TrdMarket", self.config.trade_market),
            host=self.config.host,
            port=self.config.port,
            security_firm=self._enum("SecurityFirm", self.config.security_firm),
        )
        try:
            yield trd_ctx
        finally:
            trd_ctx.close()

    def _load_sdk(self) -> Any:
        if self._sdk is not None:
            return self._sdk
        if self.config.protobuf_implementation:
            os.environ.setdefault(
                "PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION",
                self.config.protobuf_implementation,
            )
        try:
            self._sdk = import_module("moomoo")
        except ModuleNotFoundError as exc:
            raise OpenDDependencyError(
                "The optional moomoo OpenAPI SDK is not installed. Install with "
                "`pip install moomoo-api` or `pip install -e '.[opend]'`."
            ) from exc
        return self._sdk

    def _configure_sdk(self, sdk: Any) -> None:
        if self.config.rsa_private_key_path is not None:
            sdk.SysConfig.set_init_rsa_file(str(self.config.rsa_private_key_path))
        if hasattr(sdk, "SysConfig") and hasattr(sdk.SysConfig, "enable_console_log"):
            sdk.SysConfig.enable_console_log(False)

    def _enum(self, enum_name: str, value: str) -> Any:
        enum_type = getattr(self._load_sdk(), enum_name)
        try:
            return getattr(enum_type, value)
        except AttributeError as exc:
            raise ValueError(f"Unknown moomoo enum {enum_name}.{value}") from exc

    def _table_from_response(self, name: str, ret: Any, data: Any) -> OpenDTableResult:
        sdk = self._load_sdk()
        if ret != sdk.RET_OK:
            raise OpenDConnectionError(f"{name} query failed: {data}")
        rows = _records_from_table(data)
        fields = sorted({field for row in rows for field in row})
        return OpenDTableResult(name=name, rows=rows, fields=fields, as_of=_now())


class RecordedOpenDClient:
    """File-backed OpenD client for offline tests and development.

    The recording is a saved `OpenDFieldReport`, usually produced by
    `scripts/explore_opend_fields.py --output reports/opend/field-report.json`.
    """

    def __init__(self, report: OpenDFieldReport):
        self.report = report

    @classmethod
    def from_path(cls, path: str | Path) -> RecordedOpenDClient:
        report_path = Path(path).expanduser()
        return cls(OpenDFieldReport.model_validate_json(report_path.read_text(encoding="utf-8")))

    def check_connection(self) -> OpenDConnectionStatus:
        return self.report.connection.model_copy(
            update={
                "message": f"Loaded recorded OpenD report: {self.report.connection.message}",
            }
        )

    def get_account_list(self) -> OpenDTableResult:
        return self._table("accounts")

    def get_account_funds(self) -> OpenDTableResult:
        return self._table("funds")

    def get_positions(self) -> OpenDTableResult:
        return self._table("positions")

    def get_market_snapshots(self, codes: list[str]) -> OpenDTableResult:
        quotes = self._table("quotes")
        if not codes:
            return quotes.model_copy(update={"rows": [], "fields": []})
        code_set = set(codes)
        rows = [row for row in quotes.rows if row.get("code") in code_set]
        fields = sorted({field for row in rows for field in row})
        missing_codes = sorted(code_set - {str(row.get("code")) for row in rows})
        warnings = list(quotes.warnings)
        if missing_codes:
            warnings.append(f"Recorded quote rows missing for: {', '.join(missing_codes)}")
        return quotes.model_copy(update={"rows": rows, "fields": fields, "warnings": warnings})

    def explore_fields(self) -> OpenDFieldReport:
        return self.report

    def _table(self, name: str) -> OpenDTableResult:
        table = next((table for table in self.report.tables if table.name == name), None)
        if table is None:
            raise OpenDConnectionError(f"Recorded OpenD report is missing {name} table.")
        return table


def _records_from_table(data: Any) -> list[dict[str, Any]]:
    if hasattr(data, "to_dict"):
        records = data.to_dict("records")
    elif isinstance(data, list):
        records = data
    elif isinstance(data, dict):
        records = [data]
    else:
        raise TypeError(f"Unsupported OpenD table response type: {type(data)!r}")
    return [{str(key): _jsonable(value) for key, value in row.items()} for row in records]


def _jsonable(value: Any) -> Any:
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _position_codes(table: OpenDTableResult | None) -> list[str]:
    if table is None:
        return []
    codes = []
    for row in table.rows:
        code = row.get("code")
        if isinstance(code, str) and code:
            codes.append(code)
    return codes


def _now() -> datetime:
    return datetime.now(UTC)
