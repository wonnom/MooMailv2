import json
from datetime import UTC, datetime, timedelta

from moomail_finance_ai.agents import InvestmentAgentPrototype
from moomail_finance_ai.metrics import calculate_snapshot_metrics
from moomail_finance_ai.mocks import mock_investment_policy, mock_portfolio_packet
from moomail_finance_ai.sql_store import PortfolioSqlStore


def test_store_snapshot_metrics_and_audit_summary(tmp_path):
    store = PortfolioSqlStore(tmp_path / "portfolio.sqlite")
    snapshot = mock_portfolio_packet().snapshot
    stored = store.store_snapshot(snapshot)
    metrics = calculate_snapshot_metrics(snapshot, mock_investment_policy())
    metric_count = store.store_metrics(stored.snapshot_id, metrics)

    state = InvestmentAgentPrototype().run("Review my portfolio")
    assert state.audit_record is not None
    store.store_audit_record(state.audit_record)

    assert store.table_count("portfolio_snapshots") == 1
    assert store.table_count("cash_balances") == 1
    assert store.table_count("position_snapshots") == 3
    assert store.table_count("calculated_metrics") == metric_count
    assert store.table_count("agent_runs") == 1

    with store.connect() as conn:
        run = conn.execute("SELECT * FROM agent_runs").fetchone()
        columns = [row["name"] for row in conn.execute("PRAGMA table_info(agent_runs)").fetchall()]

    assert run["output_summary"] == state.audit_record.output_summary
    assert "final_response" not in columns
    assert "hidden_reasoning" not in columns
    assert json.loads(run["tools_called_json"]) == state.audit_record.tools_called


def test_history_status_detects_missing_stale_and_insufficient_history(tmp_path):
    store = PortfolioSqlStore(tmp_path / "portfolio.sqlite")
    empty = store.history_status("portfolio_default")

    assert empty.snapshot_count == 0
    assert empty.data_quality.freshness_status == "unknown"
    assert "portfolio_snapshots" in empty.data_quality.missing_fields

    snapshot = mock_portfolio_packet().snapshot.model_copy(
        update={"as_of": datetime(2026, 5, 20, tzinfo=UTC)}
    )
    store.store_snapshot(snapshot)

    stale = store.history_status(
        "portfolio_default",
        now=datetime(2026, 5, 23, tzinfo=UTC),
        stale_after=timedelta(hours=24),
        min_snapshots_for_history=2,
    )

    assert stale.snapshot_count == 1
    assert stale.data_quality.freshness_status == "stale"
    assert "historical_depth" in stale.data_quality.missing_fields
    assert any("stale" in warning for warning in stale.data_quality.warnings)


def test_store_daily_snapshot_if_needed_skips_same_portfolio_date(tmp_path):
    store = PortfolioSqlStore(tmp_path / "portfolio.sqlite")
    snapshot = mock_portfolio_packet().snapshot.model_copy(
        update={"as_of": datetime(2026, 5, 27, 14, 0, tzinfo=UTC)}
    )
    later_same_day = snapshot.model_copy(
        update={"as_of": datetime(2026, 5, 27, 20, 0, tzinfo=UTC)}
    )

    inserted = store.store_daily_snapshot_if_needed(snapshot)
    skipped = store.store_daily_snapshot_if_needed(later_same_day)

    assert inserted.status == "inserted"
    assert skipped.status == "skipped"
    assert skipped.existing_snapshot_id == inserted.snapshot_id
    assert store.table_count("portfolio_snapshots") == 1
    with store.connect() as conn:
        row = conn.execute("SELECT last_observed_at FROM portfolio_snapshots").fetchone()
    assert row["last_observed_at"] == skipped.last_observed_at.isoformat()
