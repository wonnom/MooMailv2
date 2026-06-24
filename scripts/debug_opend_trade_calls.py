from __future__ import annotations

import argparse
import json
import time
from typing import Any, Callable

from moomail_finance_ai.config import OpenDConfig, load_opend_config
from moomail_finance_ai.opend import MoomooOpenDClient


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Run read-only OpenD Trade API diagnostics for account funds and positions. "
            "No trade unlock or order APIs are called."
        )
    )
    parser.add_argument("--env-file", default=None, help="Optional local env file path.")
    parser.add_argument(
        "--account-id",
        type=int,
        default=None,
        help="Optional account id override.",
    )
    parser.add_argument(
        "--show-rows",
        action="store_true",
        help="Include one redacted sample row for successful calls.",
    )
    args = parser.parse_args()

    config = load_opend_config(env_file=args.env_file)
    client = MoomooOpenDClient(config)

    report: dict[str, Any] = {
        "config": _config_summary(config),
        "connection": client.check_connection().model_dump(mode="json"),
        "account_selection": {},
        "calls": [],
    }
    if not report["connection"]["ok"]:
        print(json.dumps(report, indent=2, sort_keys=True))
        return

    accounts_result = _run_trade_call(
        client,
        "get_acc_list",
        {},
        lambda trd_ctx: trd_ctx.get_acc_list(),
        capture_rows=True,
        show_rows=args.show_rows,
    )
    account_rows = accounts_result.pop("_raw_rows", [])
    report["calls"].append(accounts_result)

    selected_account_id, selection_reason = _select_account_id(
        account_rows,
        config=config,
        override=args.account_id,
    )
    report["account_selection"] = {
        "selected_account_id": _redact_identifier(selected_account_id),
        "selection_reason": selection_reason,
    }

    account_variants = _account_variants(
        selected_account_id=selected_account_id,
        config=config,
    )
    for variant in account_variants:
        report["calls"].append(
            _run_trade_call(
                client,
                "accinfo_query",
                _display_parameters(variant),
                lambda trd_ctx, variant=variant: trd_ctx.accinfo_query(
                    trd_env=client._enum("TrdEnv", config.trade_env),
                    acc_id=variant["acc_id"],
                    acc_index=variant["acc_index"],
                    refresh_cache=variant["refresh_cache"],
                    currency=client._enum("Currency", config.base_currency),
                ),
                capture_rows=False,
                show_rows=args.show_rows,
            )
        )

    position_variants = _position_variants(
        selected_account_id=selected_account_id,
        config=config,
    )
    for variant in position_variants:
        report["calls"].append(
            _run_trade_call(
                client,
                "position_list_query",
                _display_parameters(variant),
                lambda trd_ctx, variant=variant: trd_ctx.position_list_query(
                    position_market=client._enum("TrdMarket", variant["position_market"]),
                    trd_env=client._enum("TrdEnv", config.trade_env),
                    acc_id=variant["acc_id"],
                    acc_index=variant["acc_index"],
                    refresh_cache=variant["refresh_cache"],
                ),
                capture_rows=False,
                show_rows=args.show_rows,
            )
        )

    print(json.dumps(report, indent=2, sort_keys=True))


def _run_trade_call(
    client: MoomooOpenDClient,
    name: str,
    parameters: dict[str, Any],
    call: Callable[[Any], tuple[Any, Any]],
    *,
    capture_rows: bool = False,
    show_rows: bool,
) -> dict[str, Any]:
    started = time.monotonic()
    result: dict[str, Any] = {"name": name, "parameters": parameters}
    try:
        with client._trade_context() as trd_ctx:
            ret, data = call(trd_ctx)
        result["ret"] = _jsonable(ret)
        result["ok"] = ret == client._load_sdk().RET_OK
        result["elapsed_ms"] = round((time.monotonic() - started) * 1000, 2)
        if result["ok"]:
            rows = _records_from_table(data)
            if capture_rows:
                result["_raw_rows"] = rows
            result["row_count"] = len(rows)
            result["fields"] = sorted({field for row in rows for field in row})
            result["rows"] = [_redact_row(row) for row in rows]
            if show_rows and rows:
                result["sample_row"] = _redact_row(rows[0])
            elif not show_rows:
                result.pop("rows", None)
        else:
            result["error"] = str(data)
    except Exception as exc:
        result["ok"] = False
        result["elapsed_ms"] = round((time.monotonic() - started) * 1000, 2)
        result["exception_type"] = type(exc).__name__
        result["error"] = str(exc)
    return result


def _account_variants(
    *,
    selected_account_id: int | None,
    config: OpenDConfig,
) -> list[dict[str, Any]]:
    variants = [
        {
            "label": "selected_account_cached",
            "acc_id": selected_account_id or 0,
            "acc_index": config.account_index,
            "refresh_cache": False,
        },
        {
            "label": "selected_account_forced_refresh",
            "acc_id": selected_account_id or 0,
            "acc_index": config.account_index,
            "refresh_cache": True,
        },
    ]
    if selected_account_id:
        variants.append(
            {
                "label": "account_index_cached",
                "acc_id": 0,
                "acc_index": config.account_index,
                "refresh_cache": False,
            }
        )
    return variants


def _position_variants(
    *,
    selected_account_id: int | None,
    config: OpenDConfig,
) -> list[dict[str, Any]]:
    acc_id = selected_account_id or 0
    return [
        {
            "label": "selected_account_market_cached",
            "acc_id": acc_id,
            "acc_index": config.account_index,
            "position_market": config.trade_market,
            "refresh_cache": False,
        },
        {
            "label": "selected_account_all_markets_cached",
            "acc_id": acc_id,
            "acc_index": config.account_index,
            "position_market": "NONE",
            "refresh_cache": False,
        },
        {
            "label": "selected_account_market_forced_refresh",
            "acc_id": acc_id,
            "acc_index": config.account_index,
            "position_market": config.trade_market,
            "refresh_cache": True,
        },
    ]


def _select_account_id(
    accounts: list[dict[str, Any]],
    *,
    config: OpenDConfig,
    override: int | None,
) -> tuple[int | None, str]:
    if override is not None:
        return override, "cli_override"
    if config.account_id is not None:
        return config.account_id, "config_account_id"
    for row in accounts:
        if (
            row.get("trd_env") == config.trade_env
            and row.get("security_firm") == config.security_firm
            and row.get("acc_status") == "ACTIVE"
            and config.trade_market in set(row.get("trdmarket_auth") or [])
        ):
            return _optional_int(row.get("acc_id")), "first_active_matching_account"
    return None, "no_matching_account_found_using_account_index"


def _config_summary(config: OpenDConfig) -> dict[str, Any]:
    return {
        "host": config.host,
        "port": config.port,
        "security_firm": config.security_firm,
        "trade_market": config.trade_market,
        "trade_env": config.trade_env,
        "base_currency": config.base_currency,
        "account_id_configured": config.account_id is not None,
        "account_index": config.account_index,
    }


def _display_parameters(parameters: dict[str, Any]) -> dict[str, Any]:
    displayed = dict(parameters)
    if "acc_id" in displayed:
        displayed["acc_id"] = _redact_identifier(displayed["acc_id"])
    return displayed


def _records_from_table(data: Any) -> list[dict[str, Any]]:
    if hasattr(data, "to_dict"):
        records = data.to_dict("records")
    elif isinstance(data, list):
        records = data
    elif isinstance(data, dict):
        records = [data]
    else:
        return []
    return [{str(key): _jsonable(value) for key, value in row.items()} for row in records]


def _redact_row(row: dict[str, Any]) -> dict[str, Any]:
    redacted = {}
    for key, value in row.items():
        if key in {"acc_id", "card_num", "uni_card_num", "position_id"}:
            redacted[key] = _redact_identifier(value)
        else:
            redacted[key] = value
    return redacted


def _redact_identifier(value: Any) -> str | None:
    if value in (None, 0, "0", ""):
        return None if value is None else str(value)
    text = str(value)
    return f"...{text[-4:]}" if len(text) > 4 else "..."


def _optional_int(value: Any) -> int | None:
    if value in (None, "", "N/A"):
        return None
    return int(value)


def _jsonable(value: Any) -> Any:
    if hasattr(value, "item"):
        return value.item()
    return value


if __name__ == "__main__":
    main()
