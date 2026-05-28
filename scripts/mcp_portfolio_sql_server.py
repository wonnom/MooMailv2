from __future__ import annotations

import argparse

from moomail_finance_ai.mcp.portfolio_sql_mcp import build_portfolio_sql_mcp_module
from moomail_finance_ai.mcp.stdio import JsonRpcMCPServer


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the local portfolio SQL MCP server.")
    parser.add_argument(
        "--db-path",
        default="data/portfolio-history.sqlite",
        help="SQLite database path for portfolio history.",
    )
    args = parser.parse_args()
    JsonRpcMCPServer(build_portfolio_sql_mcp_module(db_path=args.db_path)).serve_forever()


if __name__ == "__main__":
    main()
