from pathlib import Path

import pytest

from moomail_finance_ai.config import load_env_file, load_opend_config


def test_load_opend_config_defaults():
    config = load_opend_config(env={})

    assert config.host == "127.0.0.1"
    assert config.port == 11111
    assert config.connection_timeout_seconds == 2.0
    assert config.is_encrypt is None
    assert config.protobuf_implementation == "python"
    assert config.security_firm == "FUTUINC"
    assert config.trade_market == "US"
    assert config.trade_env == "REAL"
    assert config.base_currency == "USD"
    assert config.account_id is None
    assert config.account_index == 0
    assert config.treat_fund_assets_as_cash_sweep is False


def test_explicit_missing_opend_env_file_raises_actionable_error(tmp_path):
    missing = tmp_path / "missing.env"

    with pytest.raises(FileNotFoundError, match="Explicit OpenD environment file") as exc_info:
        load_opend_config(env={}, env_file=missing)

    assert str(missing) in str(exc_info.value)
    assert "Omit env_file" in str(exc_info.value)


def test_omitted_opend_env_file_uses_documented_defaults():
    config = load_opend_config(env={}, env_file=None)

    assert config.host == "127.0.0.1"
    assert config.port == 11111


def test_load_opend_config_from_env_values():
    config = load_opend_config(
        env={
            "MOOMAIL_OPEND_HOST": "localhost",
            "MOOMAIL_OPEND_PORT": "22222",
            "MOOMAIL_OPEND_CONNECTION_TIMEOUT_SECONDS": "0.5",
            "MOOMAIL_OPEND_IS_ENCRYPT": "true",
            "MOOMAIL_OPEND_RSA_PRIVATE_KEY_PATH": "~/conn_key.txt",
            "MOOMAIL_PROTOBUF_IMPLEMENTATION": "python",
            "MOOMAIL_MOOMOO_SECURITY_FIRM": "futuinc",
            "MOOMAIL_MOOMOO_TRADE_MARKET": "us",
            "MOOMAIL_MOOMOO_TRADE_ENV": "real",
            "MOOMAIL_MOOMOO_BASE_CURRENCY": "usd",
            "MOOMAIL_MOOMOO_ACCOUNT_ID": "123456",
            "MOOMAIL_MOOMOO_ACCOUNT_INDEX": "2",
            "MOOMAIL_MOOMOO_TREAT_FUND_ASSETS_AS_CASH_SWEEP": "true",
        }
    )

    assert config.host == "localhost"
    assert config.port == 22222
    assert config.connection_timeout_seconds == 0.5
    assert config.is_encrypt is True
    assert config.rsa_private_key_path == Path("~/conn_key.txt").expanduser()
    assert config.protobuf_implementation == "python"
    assert config.security_firm == "FUTUINC"
    assert config.trade_market == "US"
    assert config.trade_env == "REAL"
    assert config.base_currency == "USD"
    assert config.account_id == 123456
    assert config.account_index == 2
    assert config.treat_fund_assets_as_cash_sweep is True


def test_load_env_file_parses_simple_key_values(tmp_path):
    env_path = tmp_path / "local.env"
    env_path.write_text(
        """
        # comment
        MOOMAIL_OPEND_HOST="127.0.0.2"
        MOOMAIL_OPEND_PORT=12345
        """,
        encoding="utf-8",
    )

    values = load_env_file(env_path)

    assert values == {
        "MOOMAIL_OPEND_HOST": "127.0.0.2",
        "MOOMAIL_OPEND_PORT": "12345",
    }


def test_load_env_file_strips_inline_comments(tmp_path):
    env_path = tmp_path / "local.env"
    env_path.write_text(
        """
        MOOMAIL_RUN_LIVE_CONNECTOR_TESTS=1 # ONLY TURN ON WHEN LIVE
        MOOMAIL_OPENAI_MODEL="gpt-test" # quoted value with comment
        MOOMAIL_LITERAL=abc#not-a-comment
        """,
        encoding="utf-8",
    )

    values = load_env_file(env_path)

    assert values["MOOMAIL_RUN_LIVE_CONNECTOR_TESTS"] == "1"
    assert values["MOOMAIL_OPENAI_MODEL"] == "gpt-test"
    assert values["MOOMAIL_LITERAL"] == "abc#not-a-comment"
