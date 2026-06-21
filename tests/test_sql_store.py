import json
from datetime import UTC, datetime, timedelta

from moomail_finance_ai.agents import InvestmentAgentPrototype
from moomail_finance_ai.mocks import mock_portfolio_packet
from moomail_finance_ai.opend import OpenDConnectionStatus, OpenDFieldReport, OpenDTableResult
from moomail_finance_ai.sql_store import ALLOWED_COUNT_TABLES, PortfolioSqlStore


def test_store_portfolio_observation_uses_finalized_lean_schema(tmp_path):
    store = PortfolioSqlStore(tmp_path / "portfolio.sqlite")
    snapshot = mock_portfolio_packet().snapshot

    stored = store.store_portfolio_observation(snapshot)

    assert stored.status == "inserted"
    assert store.table_count("portfolios") == 1
    assert store.table_count("broker_accounts") == 1
    assert store.table_count("assets") == len(snapshot.holdings) + len(snapshot.cash)
    assert store.table_count("position_states") == len(snapshot.holdings)
    assert store.table_count("portfolio_value_snapshots") == 1
    assert store.table_count("portfolio_weight_snapshots") == (
        len(snapshot.holdings) + len(snapshot.cash)
    )
    assert store.table_count("data_quality_events") == 1

    with store.connect() as conn:
        table_rows = conn.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
              AND name NOT LIKE 'sqlite_%'
            ORDER BY name
            """
        ).fetchall()
        value = conn.execute("SELECT * FROM portfolio_value_snapshots").fetchone()
        weight_rows = conn.execute("SELECT * FROM portfolio_weight_snapshots").fetchall()

    assert {row["name"] for row in table_rows} == ALLOWED_COUNT_TABLES
    assert value["total_assets"] == snapshot.total_value.amount
    assert value["cash"] == snapshot.cash[0].amount
    assert not any("raw_snapshot" in row["name"] for row in table_rows)
    assert not any("quote" in row["name"] for row in table_rows)
    assert sum(row["weight"] for row in weight_rows) == 1.0


def test_initialize_preserves_and_renames_legacy_agent_runs_table(tmp_path):
    store = PortfolioSqlStore(tmp_path / "portfolio.sqlite")
    with store.connect() as conn:
        conn.execute(
            """
            CREATE TABLE agent_runs (
                run_id TEXT PRIMARY KEY,
                timestamp TEXT NOT NULL,
                user_query TEXT NOT NULL,
                mode TEXT NOT NULL,
                tools_called_json TEXT NOT NULL,
                data_timestamps_json TEXT NOT NULL,
                source_ids_json TEXT NOT NULL,
                assumptions_json TEXT NOT NULL,
                guardrail_result_json TEXT NOT NULL,
                output_summary TEXT NOT NULL,
                memory_updates_json TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            INSERT INTO agent_runs (
                run_id, timestamp, user_query, mode, tools_called_json,
                data_timestamps_json, source_ids_json, assumptions_json,
                guardrail_result_json, output_summary, memory_updates_json
            )
            VALUES (
                'legacy_run', '2026-05-23T00:00:00+00:00', 'Review', 'review',
                '[]', '[]', '[]', '[]', '{}', 'legacy summary', '[]'
            )
            """
        )

    store.initialize()

    with store.connect() as conn:
        tables = {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        agent_run_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(agent_runs)").fetchall()
        }
        legacy_row = conn.execute("SELECT * FROM agent_runs_legacy_v1").fetchone()

    assert "agent_runs" in tables
    assert "agent_runs_legacy_v1" in tables
    assert "portfolio_id" in agent_run_columns
    assert "agent_type" in agent_run_columns
    assert legacy_row["run_id"] == "legacy_run"


def test_same_day_observation_updates_value_and_replaces_weight_rows(tmp_path):
    store = PortfolioSqlStore(tmp_path / "portfolio.sqlite")
    snapshot = mock_portfolio_packet().snapshot.model_copy(
        update={"as_of": datetime(2026, 5, 27, 14, 0, tzinfo=UTC)}
    )
    later_same_day = snapshot.model_copy(
        update={"as_of": datetime(2026, 5, 27, 20, 0, tzinfo=UTC)}
    )

    inserted = store.store_portfolio_observation(snapshot)
    updated = store.store_portfolio_observation(later_same_day)

    assert inserted.status == "inserted"
    assert updated.status == "updated"
    assert updated.value_snapshot_id == inserted.value_snapshot_id
    assert store.table_count("portfolio_value_snapshots") == 1
    assert store.table_count("portfolio_weight_snapshots") == (
        len(snapshot.holdings) + len(snapshot.cash)
    )
    with store.connect() as conn:
        row = conn.execute("SELECT as_of, last_observed_at FROM portfolio_value_snapshots").fetchone()
    assert row["as_of"] == later_same_day.as_of.isoformat()


def test_position_states_update_prices_but_insert_on_quantity_change(tmp_path):
    store = PortfolioSqlStore(tmp_path / "portfolio.sqlite")
    snapshot = mock_portfolio_packet().snapshot
    repriced_holdings = [
        holding.model_copy(
            update={
                "market_price": holding.market_price + 1,
                "market_value": holding.market_value + holding.quantity,
            }
        )
        for holding in snapshot.holdings
    ]
    repriced = snapshot.model_copy(update={"holdings": repriced_holdings})
    changed_quantity = snapshot.model_copy(
        update={
            "as_of": datetime(2026, 5, 24, tzinfo=UTC),
            "holdings": [
                snapshot.holdings[0].model_copy(update={"quantity": 81}),
                *snapshot.holdings[1:],
            ],
        }
    )

    first = store.store_portfolio_observation(snapshot)
    second = store.store_portfolio_observation(repriced)
    third = store.store_portfolio_observation(changed_quantity)

    assert first.position_states_inserted == 3
    assert second.position_states_updated == 3
    assert second.position_states_inserted == 0
    assert third.position_states_inserted == 1
    assert third.position_states_marked_inactive == 1
    assert store.table_count("position_states") == 4


def test_position_state_changes_infer_added_share_average_cost(tmp_path):
    store = PortfolioSqlStore(tmp_path / "portfolio.sqlite")
    first_seen = datetime(2026, 5, 20, tzinfo=UTC)
    second_seen = datetime(2026, 5, 23, tzinfo=UTC)

    first_snapshot = _single_holding_snapshot(
        ticker="AMZN",
        quantity=20,
        average_cost=157.0,
        as_of=first_seen,
    )
    second_snapshot = _single_holding_snapshot(
        ticker="AMZN",
        quantity=25,
        average_cost=174.6,
        as_of=second_seen,
    )
    store.upsert_position_states(
        first_snapshot,
        source_report=_source_report_for_average_cost(first_snapshot, 157.0),
        observed_at=first_seen,
    )
    store.upsert_position_states(
        second_snapshot,
        source_report=_source_report_for_average_cost(second_snapshot, 174.6),
        observed_at=second_seen,
    )

    changes = store.position_state_changes(
        "portfolio_default",
        ticker="AMZN",
        since=datetime(2026, 5, 21, tzinfo=UTC),
        until=datetime(2026, 5, 24, tzinfo=UTC),
    )
    outside_range = store.position_state_changes(
        "portfolio_default",
        ticker="AMZN",
        since=datetime(2026, 5, 24, tzinfo=UTC),
    )

    assert len(changes.changes) == 1
    change = changes.changes[0]
    assert change.change_type == "quantity_and_average_cost_changed"
    assert change.previous_quantity == 20
    assert change.current_quantity == 25
    assert change.quantity_delta == 5
    assert change.previous_average_cost == 157.0
    assert change.current_average_cost == 174.6
    assert change.implied_added_average_cost == 245.0
    assert change.previous_state is not None
    assert change.current_state is not None
    assert outside_range.changes == []


def test_history_status_growth_and_allocation_reads_use_value_snapshots(tmp_path):
    store = PortfolioSqlStore(tmp_path / "portfolio.sqlite")
    empty = store.history_status("portfolio_default")

    assert empty.snapshot_count == 0
    assert empty.data_quality.freshness_status == "unknown"
    assert "portfolio_value_snapshots" in empty.data_quality.missing_fields

    snapshot = mock_portfolio_packet().snapshot.model_copy(
        update={"as_of": datetime(2026, 5, 20, tzinfo=UTC)}
    )
    store.store_portfolio_observation(snapshot)

    stale = store.history_status(
        "portfolio_default",
        now=datetime(2026, 5, 23, tzinfo=UTC),
        stale_after=timedelta(hours=24),
        min_snapshots_for_history=2,
    )
    growth = store.portfolio_growth("portfolio_default")
    allocation = store.allocation_history("portfolio_default")
    latest = store.latest_portfolio_state("portfolio_default")

    assert stale.snapshot_count == 1
    assert stale.data_quality.freshness_status == "stale"
    assert "historical_depth" in stale.data_quality.missing_fields
    assert any("stale" in warning for warning in stale.data_quality.warnings)
    assert growth[0]["total_assets"] == snapshot.total_value.amount
    assert {row["ticker"] for row in allocation} >= {"MSFT", "AAPL", "VTI", "USD"}
    assert latest is not None
    assert latest["value_snapshot"]["portfolio_id"] == "portfolio_default"


def test_agent_run_summary_shape_has_no_hidden_or_full_response_columns(tmp_path):
    store = PortfolioSqlStore(tmp_path / "portfolio.sqlite")
    state = InvestmentAgentPrototype().run("Review my portfolio")
    assert state.audit_record is not None

    stored = store.store_agent_run(
        state.audit_record,
        portfolio_id="portfolio_default",
        snapshot_refs=["value_snap_test"],
        missing_data=["missing_history"],
    )
    linked = store.link_agent_run_sources(
        state.audit_record.run_id,
        [{"source_type": "portfolio_value_snapshot", "source_id": "value_snap_test"}],
    )

    with store.connect() as conn:
        run = conn.execute("SELECT * FROM agent_runs").fetchone()
        columns = [row["name"] for row in conn.execute("PRAGMA table_info(agent_runs)").fetchall()]

    assert stored.stored is True
    assert linked.sources_linked == 1
    assert run["output_summary"] == state.audit_record.output_summary
    assert "final_response" not in columns
    assert "hidden_reasoning" not in columns
    assert json.loads(run["tools_called_json"]) == state.audit_record.tools_called
    assert json.loads(run["snapshot_refs_json"]) == ["value_snap_test"]
    assert json.loads(run["missing_data_json"]) == ["missing_history"]


def _single_holding_snapshot(
    *,
    ticker: str,
    quantity: float,
    average_cost: float,
    as_of: datetime,
):
    snapshot = mock_portfolio_packet().snapshot
    market_value = quantity * average_cost
    holding = snapshot.holdings[0].model_copy(
        update={
            "asset_id": f"asset_{ticker.lower()}_us",
            "ticker": ticker,
            "name": f"{ticker} Test Holding",
            "quantity": quantity,
            "market_price": average_cost,
            "market_value": market_value,
            "portfolio_weight": 1.0,
            "unrealized_pnl": 0.0,
            "as_of": as_of,
        }
    )
    return snapshot.model_copy(
        update={
            "as_of": as_of,
            "cash": [],
            "holdings": [holding],
            "total_value": snapshot.total_value.model_copy(
                update={"amount": market_value, "as_of": as_of}
            ),
        }
    )


def _source_report_for_average_cost(snapshot, average_cost: float) -> OpenDFieldReport:
    holding = snapshot.holdings[0]
    return OpenDFieldReport(
        generated_at=snapshot.as_of,
        connection=OpenDConnectionStatus(
            ok=True,
            host="127.0.0.1",
            port=11111,
            checked_at=snapshot.as_of,
            message="ok",
        ),
        tables=[
            OpenDTableResult(
                name="positions",
                rows=[
                    {
                        "code": holding.asset_id,
                        "average_cost": average_cost,
                        "position_side": "LONG",
                    }
                ],
                fields=["code", "average_cost", "position_side"],
                as_of=snapshot.as_of,
            )
        ],
    )
