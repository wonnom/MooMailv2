from __future__ import annotations

from typing import Any

from moomail_finance_ai.mcp.registry import (
    MCPResourceSpec,
    MCPToolSpec,
    RegisteredMCPModule,
    object_schema,
)
from moomail_finance_ai.metrics import (
    METRIC_VERSION,
    US_EQUITY_ANALYSIS_SCOPE,
    MetricResult,
    calculate_asset_type_allocation,
    calculate_benchmark_reference,
    calculate_cash_weight,
    calculate_position_weights,
    calculate_single_position_concentration,
    calculate_snapshot_metrics,
)
from moomail_finance_ai.schemas import InvestmentPolicy, PortfolioSnapshot


SERVER_NAME = "moomail-finance-metrics-mcp"
SERVER_VERSION = "0.1.0"


def build_finance_metrics_mcp_module() -> RegisteredMCPModule:
    module = RegisteredMCPModule(server_name=SERVER_NAME, version=SERVER_VERSION)
    module.add_tool(
        MCPToolSpec(
            name="calculate_cash_weight",
            description=(
                "Calculate portfolio cash weight. Prefer a PortfolioSnapshot input; "
                "total_value/cash_value are accepted for connector smoke tests."
            ),
            input_schema=object_schema(
                {
                    "snapshot": {
                        "type": "object",
                        "description": "PortfolioSnapshot JSON.",
                    },
                    "total_value": {"type": "number"},
                    "cash_value": {"type": "number"},
                }
            ),
        ),
        _calculate_cash_weight,
    )
    module.add_tool(
        MCPToolSpec(
            name="calculate_position_weights",
            description="Calculate position weights for the selected portfolio scope.",
            input_schema=_snapshot_scope_schema(),
        ),
        _calculate_position_weights,
    )
    module.add_tool(
        MCPToolSpec(
            name="calculate_single_position_concentration",
            description="Identify positions above the IPS single-stock concentration limit.",
            input_schema=_snapshot_ips_scope_schema(),
        ),
        _calculate_single_position_concentration,
    )
    module.add_tool(
        MCPToolSpec(
            name="calculate_asset_type_allocation",
            description="Calculate full-portfolio allocation by asset type.",
            input_schema=_snapshot_schema(),
        ),
        _calculate_asset_type_allocation,
    )
    module.add_tool(
        MCPToolSpec(
            name="calculate_benchmark_reference",
            description="Return the benchmark reference configured in the Investment Policy.",
            input_schema=_ips_schema(),
        ),
        _calculate_benchmark_reference,
    )
    module.add_tool(
        MCPToolSpec(
            name="calculate_snapshot_metrics",
            description="Calculate the full deterministic metric set for a snapshot and IPS.",
            input_schema=_snapshot_ips_scope_schema(),
        ),
        _calculate_snapshot_metrics,
    )
    module.add_tool(
        MCPToolSpec(
            name="list_metric_definitions",
            description="List deterministic metric names, scopes, and version information.",
            input_schema=object_schema(),
        ),
        lambda _arguments: metric_definitions(),
    )
    module.add_resource(
        MCPResourceSpec(
            uri="finance-metrics://definitions",
            name="Finance Metric Definitions",
            description="Metric names, version, scope defaults, and implementation notes.",
        ),
        metric_definitions,
    )
    module.add_resource(
        MCPResourceSpec(
            uri="finance-metrics://version",
            name="Finance Metric Version",
            description="The deterministic metric implementation version.",
        ),
        lambda: {"metric_version": METRIC_VERSION, "default_scope": US_EQUITY_ANALYSIS_SCOPE},
    )
    return module


def metric_definitions() -> dict[str, Any]:
    return {
        "metric_version": METRIC_VERSION,
        "default_scope": US_EQUITY_ANALYSIS_SCOPE,
        "metrics": [
            {
                "name": "cash_weight",
                "scope": "full_portfolio",
                "description": "Cash divided by total portfolio value.",
            },
            {
                "name": "position_weights",
                "scope": US_EQUITY_ANALYSIS_SCOPE,
                "description": "Scoped holding weights, defaulting to US equities.",
            },
            {
                "name": "single_position_concentration",
                "scope": US_EQUITY_ANALYSIS_SCOPE,
                "description": "Positions whose scoped weight exceeds the IPS limit.",
            },
            {
                "name": "asset_type_allocation",
                "scope": "full_portfolio",
                "description": "Full-portfolio allocation by asset type plus cash.",
            },
            {
                "name": "benchmark_reference",
                "scope": US_EQUITY_ANALYSIS_SCOPE,
                "description": "Benchmark identifier from the IPS; return math is future work.",
            },
        ],
    }


def _calculate_cash_weight(arguments: dict[str, Any]) -> MetricResult:
    if "snapshot" in arguments:
        return calculate_cash_weight(_snapshot(arguments))
    total_value = float(arguments["total_value"])
    cash_value = float(arguments["cash_value"])
    value = 0.0 if total_value == 0 else cash_value / total_value
    return MetricResult(
        metric_name="cash_weight",
        value=value,
        input_scope={"scope": "full_portfolio"},
        source_inputs={"total_value": total_value, "cash_value": cash_value},
    )


def _calculate_position_weights(arguments: dict[str, Any]) -> MetricResult:
    return calculate_position_weights(_snapshot(arguments), scope=_scope(arguments))


def _calculate_single_position_concentration(arguments: dict[str, Any]) -> MetricResult:
    return calculate_single_position_concentration(
        _snapshot(arguments),
        _ips(arguments),
        scope=_scope(arguments),
    )


def _calculate_asset_type_allocation(arguments: dict[str, Any]) -> MetricResult:
    return calculate_asset_type_allocation(_snapshot(arguments))


def _calculate_benchmark_reference(arguments: dict[str, Any]) -> MetricResult:
    return calculate_benchmark_reference(_ips(arguments))


def _calculate_snapshot_metrics(arguments: dict[str, Any]) -> list[MetricResult]:
    return calculate_snapshot_metrics(_snapshot(arguments), _ips(arguments), scope=_scope(arguments))


def _snapshot(arguments: dict[str, Any]) -> PortfolioSnapshot:
    return PortfolioSnapshot.model_validate(arguments["snapshot"])


def _ips(arguments: dict[str, Any]) -> InvestmentPolicy:
    return InvestmentPolicy.model_validate(arguments["ips"])


def _scope(arguments: dict[str, Any]) -> str:
    return str(arguments.get("scope") or US_EQUITY_ANALYSIS_SCOPE)


def _snapshot_schema() -> dict[str, Any]:
    return object_schema(
        {"snapshot": {"type": "object", "description": "PortfolioSnapshot JSON."}},
        required=["snapshot"],
    )


def _ips_schema() -> dict[str, Any]:
    return object_schema(
        {"ips": {"type": "object", "description": "InvestmentPolicy JSON."}},
        required=["ips"],
    )


def _snapshot_scope_schema() -> dict[str, Any]:
    return object_schema(
        {
            "snapshot": {"type": "object", "description": "PortfolioSnapshot JSON."},
            "scope": {
                "type": "string",
                "enum": [US_EQUITY_ANALYSIS_SCOPE, "full_portfolio"],
                "default": US_EQUITY_ANALYSIS_SCOPE,
            },
        },
        required=["snapshot"],
    )


def _snapshot_ips_scope_schema() -> dict[str, Any]:
    return object_schema(
        {
            "snapshot": {"type": "object", "description": "PortfolioSnapshot JSON."},
            "ips": {"type": "object", "description": "InvestmentPolicy JSON."},
            "scope": {
                "type": "string",
                "enum": [US_EQUITY_ANALYSIS_SCOPE, "full_portfolio"],
                "default": US_EQUITY_ANALYSIS_SCOPE,
            },
        },
        required=["snapshot", "ips"],
    )
