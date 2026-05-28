from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping

from pydantic import Field, field_validator

from moomail_finance_ai.schemas import StrictModel


class OpenDConfig(StrictModel):
    host: str = "127.0.0.1"
    port: int = 11111
    connection_timeout_seconds: float = 2.0
    is_encrypt: bool | None = None
    rsa_private_key_path: Path | None = None
    protobuf_implementation: str = "python"
    security_firm: str = "FUTUINC"
    trade_market: str = "US"
    trade_env: str = "REAL"
    base_currency: str = Field(default="USD", min_length=3, max_length=3)
    account_id: int | None = None
    account_index: int = 0

    @field_validator("security_firm", "trade_market", "trade_env", "base_currency")
    @classmethod
    def uppercase(cls, value: str) -> str:
        return value.upper()

    @field_validator("rsa_private_key_path", mode="before")
    @classmethod
    def blank_path_to_none(cls, value: str | Path | None) -> Path | None:
        if value is None or value == "":
            return None
        return Path(value).expanduser()


def load_env_file(path: str | Path) -> dict[str, str]:
    env_path = Path(path).expanduser()
    values: dict[str, str] = {}
    if not env_path.exists():
        raise FileNotFoundError(f"Environment file not found: {env_path}")

    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = _clean_env_value(value)
    return values


def load_opend_config(
    *,
    env: Mapping[str, str] | None = None,
    env_file: str | Path | None = None,
) -> OpenDConfig:
    merged = dict(os.environ if env is None else env)
    if env_file is not None:
        merged.update(load_env_file(env_file))

    return OpenDConfig(
        host=merged.get("MOOMAIL_OPEND_HOST", "127.0.0.1"),
        port=_parse_int(merged.get("MOOMAIL_OPEND_PORT"), default=11111),
        connection_timeout_seconds=_parse_float(
            merged.get("MOOMAIL_OPEND_CONNECTION_TIMEOUT_SECONDS"),
            default=2.0,
        ),
        is_encrypt=_parse_optional_bool(merged.get("MOOMAIL_OPEND_IS_ENCRYPT")),
        rsa_private_key_path=merged.get("MOOMAIL_OPEND_RSA_PRIVATE_KEY_PATH") or None,
        protobuf_implementation=merged.get("MOOMAIL_PROTOBUF_IMPLEMENTATION", "python"),
        security_firm=merged.get("MOOMAIL_MOOMOO_SECURITY_FIRM", "FUTUINC"),
        trade_market=merged.get("MOOMAIL_MOOMOO_TRADE_MARKET", "US"),
        trade_env=merged.get("MOOMAIL_MOOMOO_TRADE_ENV", "REAL"),
        base_currency=merged.get("MOOMAIL_MOOMOO_BASE_CURRENCY", "USD"),
        account_id=_parse_optional_int(merged.get("MOOMAIL_MOOMOO_ACCOUNT_ID")),
        account_index=_parse_int(merged.get("MOOMAIL_MOOMOO_ACCOUNT_INDEX"), default=0),
    )


def _parse_int(value: str | None, *, default: int) -> int:
    if value is None or value == "":
        return default
    return int(value)


def _parse_float(value: str | None, *, default: float) -> float:
    if value is None or value == "":
        return default
    return float(value)


def _parse_optional_int(value: str | None) -> int | None:
    if value is None or value == "":
        return None
    return int(value)


def _parse_optional_bool(value: str | None) -> bool | None:
    if value is None or value == "" or value.lower() in {"auto", "none", "null"}:
        return None
    if value.lower() in {"1", "true", "yes", "y", "on"}:
        return True
    if value.lower() in {"0", "false", "no", "n", "off"}:
        return False
    raise ValueError(f"Invalid optional bool value: {value}")


def _clean_env_value(value: str) -> str:
    value = _strip_inline_comment(value.strip()).strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _strip_inline_comment(value: str) -> str:
    in_single_quote = False
    in_double_quote = False
    for index, char in enumerate(value):
        if char == "'" and not in_double_quote:
            in_single_quote = not in_single_quote
        elif char == '"' and not in_single_quote:
            in_double_quote = not in_double_quote
        elif (
            char == "#"
            and not in_single_quote
            and not in_double_quote
            and (index == 0 or value[index - 1].isspace())
        ):
            return value[:index]
    return value
