from __future__ import annotations

from pathlib import Path


DOCS = Path(__file__).resolve().parents[1] / "docs" / "finance-ai"


def test_readme_records_closeout_and_remaining_stubs():
    text = (DOCS / "V1_2_Tasks" / "README.md").read_text(encoding="utf-8")

    assert "V1.2 skeleton complete as of 2026-06-15" in text
    assert "What Changed From V1.1" in text
    assert "Still mock/stub/not fully developed" in text
    assert "Sentiment Agent is a stub only" in text
    assert "not as a separate compiled LangGraph subgraph" in text
    assert "Pinecone memory is not connected" in text
    assert "Neo4j GraphRAG" in text


def test_closeout_docs_name_core_test_files_and_live_opt_in():
    testing = (DOCS / "TESTING.md").read_text(encoding="utf-8")
    task6 = (DOCS / "V1_2_Tasks" / "TASK_6_DOCUMENTATION_AND_TESTS.md").read_text(
        encoding="utf-8"
    )

    for test_file in [
        "tests/test_agent_schemas.py",
        "tests/test_investment_agent.py",
        "tests/test_portfolio_planner.py",
        "tests/test_sentiment_agent_stub.py",
        "tests/test_investment_guardrails.py",
        "tests/test_agent_trace.py",
    ]:
        assert test_file in testing
        assert test_file in task6

    assert "MOOMAIL_RUN_LIVE_CONNECTOR_TESTS=1" in testing
    assert "Live OpenD connector tests remain opt-in" in task6


def test_action_plan_and_decision_log_mark_v1_2_skeleton_complete():
    action_plan = (DOCS / "ACTION_PLAN.md").read_text(encoding="utf-8")
    decision_log = (DOCS / "DECISION_LOG.md").read_text(encoding="utf-8")

    assert "V1.2 skeleton is complete as of 2026-06-15" in action_plan
    assert "V1.2 skeleton is complete" in decision_log
    assert "V1.2 | Complete skeleton" in decision_log
    assert "deterministic/template-style" in decision_log
    assert "official MCP client/host runtime" in decision_log
