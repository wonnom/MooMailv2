from __future__ import annotations

from moomail_finance_ai.mcp.gateway import (
    MCPGatewayResult,
    MCPPermissionError,
    MCPServerUnavailableError,
    MCPToolExecutionError,
)


def test_mcp_gateway_result_is_frontend_and_trace_safe():
    result = MCPGatewayResult(
        server_name="moomail-finance-metrics-mcp",
        tool_name="calculate_cash_weight",
        structured_content={"metric_name": "cash_weight", "value": 0.125},
        content=[{"type": "text", "text": "cash weight"}],
        duration_ms=12.5,
    )

    payload = result.model_dump(mode="json")

    assert payload["server_name"] == "moomail-finance-metrics-mcp"
    assert payload["tool_name"] == "calculate_cash_weight"
    assert payload["structured_content"]["value"] == 0.125
    assert payload["is_error"] is False
    assert payload["error_message"] is None


def test_mcp_gateway_error_types_carry_context():
    errors = [
        MCPPermissionError("denied", server_name="moomail-opend-mcp", consumer="investment_agent"),
        MCPServerUnavailableError("offline", server_name="moomail-opend-mcp"),
        MCPToolExecutionError(
            "failed",
            server_name="moomail-opend-mcp",
            tool_name="opend_get_positions",
        ),
    ]

    assert [type(error).__name__ for error in errors] == [
        "MCPPermissionError",
        "MCPServerUnavailableError",
        "MCPToolExecutionError",
    ]
    assert errors[0].consumer == "investment_agent"
    assert errors[2].tool_name == "opend_get_positions"
