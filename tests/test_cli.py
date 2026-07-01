from __future__ import annotations

import sys

import pytest

from moomail_finance_ai.cli import main


def test_portfolio_cli_requires_structured_request_flags(monkeypatch, capsys):
    monkeypatch.setattr(
        sys,
        "argv",
        ["finance-ai", "Review", "my", "portfolio", "--agent", "portfolio"],
    )

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 2
    assert "--agent portfolio requires --portfolio-task-intent" in capsys.readouterr().err
