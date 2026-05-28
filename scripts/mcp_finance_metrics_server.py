from __future__ import annotations

from moomail_finance_ai.mcp.finance_metrics_mcp import build_finance_metrics_mcp_module
from moomail_finance_ai.mcp.stdio import JsonRpcMCPServer


def main() -> None:
    JsonRpcMCPServer(build_finance_metrics_mcp_module()).serve_forever()


if __name__ == "__main__":
    main()
