from __future__ import annotations

from moomail_finance_ai.mcp.finance_metrics_mcp import build_finance_metrics_mcp_module
from moomail_finance_ai.mcp.fastmcp import build_fastmcp_server


def main() -> None:
    build_fastmcp_server(build_finance_metrics_mcp_module()).run("stdio")


if __name__ == "__main__":
    main()
