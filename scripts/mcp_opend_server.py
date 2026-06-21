from __future__ import annotations

import argparse

from moomail_finance_ai.mcp.fastmcp import build_fastmcp_server
from moomail_finance_ai.mcp.opend_mcp import build_opend_mcp_module


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the local read-only OpenD MCP server.")
    parser.add_argument("--env-file", default=None, help="Optional OpenD env file path.")
    parser.add_argument(
        "--from-report",
        default=None,
        help="Optional recorded OpenD field report JSON for offline development.",
    )
    args = parser.parse_args()
    module = build_opend_mcp_module(env_file=args.env_file, from_report=args.from_report)
    build_fastmcp_server(module).run("stdio")


if __name__ == "__main__":
    main()
