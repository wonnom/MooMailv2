from __future__ import annotations

from pathlib import Path


DOCS = Path(__file__).resolve().parents[1] / "docs" / "finance-ai"
V3 = DOCS / "V3_Tasks"


def test_v3_readme_records_backend_mcp_boundary_and_task_map():
    text = (V3 / "README.md").read_text(encoding="utf-8")

    assert "MCP becomes shared backend" in text
    assert "infrastructure for deterministic app flows" in text
    assert "deterministic app flows and agentic analysis flows" in text
    assert "The frontend calls backend APIs" in text
    assert "V3.0" in text
    assert "V3.1" in text
    assert "V3.2" in text
    assert "V3.3" in text


def test_v3_docs_capture_gateway_modes_and_fastmcp_migration():
    task1 = (V3 / "TASK_1_FASTMCP_SERVER_MIGRATION.md").read_text(encoding="utf-8")
    task2 = (V3 / "TASK_2_GATEWAY_MODES.md").read_text(encoding="utf-8")

    assert "FastMCP servers" in task1
    assert "Preserve OpenD, SQL, and metrics business logic" in task1
    assert "MCPToolGateway.call_tool" in task1
    assert "DirectToolGateway" in task2
    assert "test/dev parity adapter only" in task2
    assert "StdioMCPToolGateway" in task2
    assert "official MCP client" in task2


def test_v3_docs_record_retirement_candidates_without_premature_deletion():
    readme = (V3 / "README.md").read_text(encoding="utf-8")
    task3 = (V3 / "TASK_3_AGENT_GATEWAY_MIGRATION.md").read_text(encoding="utf-8")

    assert "Do not delete these before V3 parity is proven" in readme
    assert "src/moomail_finance_ai/mcp/stdio.py" in readme
    assert "RegisteredMCPModule" in readme
    assert "_MCPStdioClient" in readme
    assert "agents should no longer receive `RegisteredMCPModule` objects" in task3
    assert "Keep domain tests" in task3
