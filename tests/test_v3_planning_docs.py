from __future__ import annotations

from pathlib import Path


DOCS = Path(__file__).resolve().parents[1] / "docs" / "finance-ai"
V3 = DOCS / "V3_Tasks"


def test_v3_readme_records_backend_mcp_boundary_and_task_map():
    text = (V3 / "README.md").read_text(encoding="utf-8")

    assert "V3.0, V3.1, V3.2, and V3.3 are complete" in text
    assert "V3.4 is the remaining agent gateway migration" in text
    assert "MCP becomes shared backend" in text
    assert "infrastructure for deterministic app flows" in text
    assert "deterministic app flows and agentic analysis flows" in text
    assert "The frontend calls backend APIs" in text
    assert "V3.0" in text
    assert "V3.1" in text
    assert "V3.2" in text
    assert "V3.3" in text
    assert "V3.4" in text


def test_v3_task0_is_closed_with_backend_contracts_and_permissions():
    task0 = (V3 / "TASK_0_MCP_BACKEND_BOUNDARY.md").read_text(encoding="utf-8")
    architecture = (DOCS / "ARCHITECTURE.md").read_text(encoding="utf-8")
    protocol = (DOCS / "PROTOCOL.md").read_text(encoding="utf-8")
    action_plan = (DOCS / "ACTION_PLAN.md").read_text(encoding="utf-8")

    assert "Status: complete as of 2026-06-17" in task0
    assert "OpenD MCP is a shared backend data boundary" in task0
    assert "PortfolioConnectionStatus" in architecture
    assert "PortfolioDashboardSnapshot" in architecture
    assert "PortfolioRefreshResult" in architecture
    assert "V3 Portfolio Data Lane Protocol" in protocol
    assert "dashboard_refresh" in architecture
    assert "investment_agent" in architecture
    assert "complete as of 2026-06-17" in action_plan


def test_v3_docs_capture_gateway_modes_and_fastmcp_migration():
    task1 = (V3 / "TASK_1_FASTMCP_SERVER_MIGRATION.md").read_text(encoding="utf-8")
    task2 = (V3 / "TASK_2_GATEWAY_MODES.md").read_text(encoding="utf-8")
    action_plan = (DOCS / "ACTION_PLAN.md").read_text(encoding="utf-8")
    mcp_servers = (DOCS / "MCP_SERVERS.md").read_text(encoding="utf-8")

    assert "Status: complete as of 2026-06-17" in task1
    assert "FastMCP servers" in task1
    assert "Preserve OpenD, SQL, and metrics business logic" in task1
    assert "MCPToolGateway.call_tool" in task1
    assert "mcp/fastmcp.py" in action_plan
    assert "Local MCP server scripts run official FastMCP over stdio" in mcp_servers
    assert "DirectToolGateway" in task2
    assert "test/dev parity adapter only" in task2
    assert "StdioMCPToolGateway" in task2
    assert "official MCP client" in task2


def test_v3_docs_record_retirement_candidates_without_premature_deletion():
    readme = (V3 / "README.md").read_text(encoding="utf-8")
    task4 = (V3 / "TASK_4_AGENT_GATEWAY_MIGRATION.md").read_text(encoding="utf-8")

    assert "Do not delete these before V3 parity is proven" in readme
    assert "src/moomail_finance_ai/mcp/stdio.py" in readme
    assert "RegisteredMCPModule" in readme
    assert "_MCPStdioClient" in readme
    assert "agents should no longer receive `RegisteredMCPModule` objects" in task4
    assert "Keep domain tests" in task4


def test_v3_docs_include_deterministic_portfolio_data_lane_implementation_task():
    readme = (V3 / "README.md").read_text(encoding="utf-8")
    task3 = (V3 / "TASK_3_DETERMINISTIC_PORTFOLIO_DATA_LANE.md").read_text(
        encoding="utf-8"
    )
    action_plan = (DOCS / "ACTION_PLAN.md").read_text(encoding="utf-8")

    assert "TASK_3_DETERMINISTIC_PORTFOLIO_DATA_LANE.md" in readme
    assert "Status: complete" in task3
    assert "Implemented routes" in task3
    assert "backend and frontend" in task3
    assert "without asking Portfolio Agent or Investment Agent" in task3
    assert "does not call Portfolio Agent, Investment Agent, an LLM" in task3
    assert "page-load behavior to request dashboard/status API" in task3
    assert "no-agent refresh behavior" in action_plan
    assert "V3.4" in action_plan


def test_decision_log_records_v3_mcp_backend_boundary():
    decision_log = (DOCS / "DECISION_LOG.md").read_text(encoding="utf-8")

    assert "V3.0 MCP Backend Boundary / 2026-06-17" in decision_log
    assert "V3.1 FastMCP Server Migration / 2026-06-17" in decision_log
    assert "V3.2 And V3.3 Closeout / 2026-06-21" in decision_log
    assert "V3 Planning Adjustment / 2026-06-17" in decision_log
    assert "Insert V3.3 as `Deterministic Portfolio Data Lane`" in decision_log
    assert "MCP is backend infrastructure, not only an LLM-agent tool surface" in decision_log
    assert "deterministic dashboard" in decision_log
    assert "backend APIs only" in decision_log
