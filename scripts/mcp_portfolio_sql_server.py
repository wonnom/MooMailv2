from __future__ import annotations

import argparse

from moomail_finance_ai.mcp.fastmcp import build_fastmcp_server
from moomail_finance_ai.mcp.portfolio_sql_mcp import build_portfolio_sql_mcp_module


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the local portfolio SQL MCP server.")
    parser.add_argument(
        "--db-path",
        default="data/portfolio-history.sqlite",
        help="SQLite database path for portfolio history.",
    )
    args = parser.parse_args()
    build_fastmcp_server(build_portfolio_sql_mcp_module(db_path=args.db_path)).run("stdio")


if __name__ == "__main__":
    main()
