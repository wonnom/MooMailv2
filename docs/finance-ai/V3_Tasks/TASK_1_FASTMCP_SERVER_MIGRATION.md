# Task V3.1: FastMCP Server Migration

Status: complete as of 2026-06-17.

## Goal

Preserve OpenD, SQL, and metrics business logic as plain Python code while
replacing the custom `JsonRpcMCPServer` runtime with real FastMCP servers.

This task creates the server side of the V3 runtime. It should not move agents
or build frontend refresh behavior yet. V3.3 implements the deterministic
portfolio data lane after gateway modes are ready; agents move in V3.4.

## Target Shape

```text
Domain logic
  -> OpenD adapter and normalization
  -> PortfolioSqlStore
  -> metrics functions

FastMCP server layer
  -> opend-mcp
  -> portfolio-sql-mcp
  -> finance-metrics-mcp

Gateway contract
  -> MCPToolGateway.call_tool(server, tool, args)
  -> same structured payloads as V2 where possible
```

## Exit Criteria

1. OpenD, SQL, and metrics business logic remains callable and testable outside
   FastMCP.
2. `moomail-opend-mcp`, `moomail-portfolio-sql-mcp`, and
   `moomail-finance-metrics-mcp` have FastMCP server entrypoints.
3. FastMCP tool names, argument schemas, resources, and structured outputs
   preserve V2 contracts unless deliberately changed and documented.
4. A gateway contract exists, even if V3.2 implements the concrete modes.
5. Deterministic parity tests prove FastMCP servers return the same payload
   shapes as the old custom module path for representative calls.

## Completion Notes

Implemented:

- Added `src/moomail_finance_ai/mcp/fastmcp.py`.
- Rewired `scripts/mcp_finance_metrics_server.py` to run FastMCP over stdio.
- Rewired `scripts/mcp_opend_server.py` to run FastMCP over stdio.
- Rewired `scripts/mcp_portfolio_sql_server.py` to run FastMCP over stdio.
- Promoted `mcp>=1,<2` to a normal project dependency in `pyproject.toml`.
- Added `src/moomail_finance_ai/mcp/gateway.py` with `MCPToolGateway`,
  `MCPGatewayResult`, and gateway error types for V3.2.
- Updated deterministic and live MCP stdio tests to use the official MCP client
  instead of the custom `_MCPStdioClient`.
- Added FastMCP parity tests.

Reality checks:

- Business logic still lives in `opend.py`, `opend_portfolio.py`,
  `sql_store.py`, `metrics.py`, and the existing thin MCP tool modules.
- `RegisteredMCPModule` still exists and still owns tool registration under the
  adapter. It is now the shared source for direct-module tests and FastMCP
  server exposure.
- `JsonRpcMCPServer` still exists for legacy/custom wrapper coverage, but the
  three MCP server scripts no longer use it.
- Agents still call in-process modules. Gateway runtime modes and agent
  migration are V3.2 and V3.4 work.
- FastMCP `initialize` reports the SDK implementation version, not the
  MooMail module version. MooMail versions remain exposed in module resources
  and payloads where already available.

## Dependency Graph

```text
A. Audit current tool handlers and domain logic
   ├── B. Extract or confirm domain service functions
   │   ├── C. Build FastMCP finance metrics server
   │   ├── D. Build FastMCP portfolio SQL server
   │   └── E. Build FastMCP OpenD server
   ├── F. Define MCPToolGateway protocol/result shape
   └── G. Add parity tests
       ├── H. Update server scripts/docs
       └── I. Mark custom runtime as pending retirement
```

## Task Breakdown By Exit Criteria

### EC1: Business logic remains plain Python

| Task | Description | Depends on | Test or check |
| --- | --- | --- | --- |
| A | Audit current domain logic in `opend.py`, `opend_portfolio.py`, `sql_store.py`, and `metrics.py`. | V3.0 | Done. Existing adapter/store/metric tests remain separate. |
| A1 | Identify logic currently embedded in `mcp/opend_mcp.py`, `mcp/portfolio_sql_mcp.py`, or `mcp/finance_metrics_mcp.py` that should become reusable service functions. | A | Done. No broad extraction needed for V3.1; wrappers stay thin. |
| B | Keep tool handlers thin: parse args, call domain/service function, return structured data. | A1 | Done via FastMCP adapter over existing modules. |
| B1 | Avoid putting non-trivial finance logic inside FastMCP decorators. | B | Done. FastMCP adapter delegates to existing handlers. |
| B2 | Keep `PortfolioSqlStore` as the database implementation, not a FastMCP-only class. | B | Done. |

### EC2: FastMCP servers exist

| Task | Description | Depends on | Test or check |
| --- | --- | --- | --- |
| C | Add or rewrite finance metrics FastMCP server entrypoint. | B | Done. |
| C1 | Register `calculate_cash_weight`, `calculate_position_weights`, `calculate_single_position_concentration`, `calculate_asset_type_allocation`, `calculate_benchmark_reference`, `calculate_snapshot_metrics`, and `list_metric_definitions`. | C | Done. |
| C2 | Expose metric definitions/version resource or equivalent MCP resource. | C | Done. |
| D | Add or rewrite portfolio SQL FastMCP server entrypoint. | B | Done. |
| D1 | Support `--db-path` or equivalent server config for local SQLite path. | D | Done. |
| D2 | Preserve lean schema tools and schema/status resources. | D | Done. |
| E | Add or rewrite OpenD FastMCP server entrypoint. | B | Done. |
| E1 | Support `--env-file` for live local OpenD config. | E | Done in script; opt-in live test updated but not run by default. |
| E2 | Support recorded report mode to avoid unnecessary live pulls during tests. | E | Done. |
| E3 | Preserve read-only tool surface and no trade/order tools. | E | Done. |

### EC3: Tool contracts preserve V2 shapes

| Task | Description | Depends on | Test or check |
| --- | --- | --- | --- |
| G | Build a parity fixture matrix for representative calls. | C, D, E | Done. |
| G1 | Compare old direct module output and FastMCP server output for metrics calls. | C, G | Done in `tests/test_mcp_fastmcp_parity.py`. |
| G2 | Compare old direct module output and FastMCP output for SQL initialize, value snapshot store, latest state, and schema/status resource. | D, G | Done with representative SQL calls. |
| G3 | Compare old direct module output and FastMCP output for OpenD recorded connection, positions, funds, normalized snapshot, and context. | E, G | Done with recorded normalized snapshot. |
| G4 | Document any intentional shape changes and update V2/V3 schemas if needed. | G1 through G3 | Done. No structured payload shape change found for representative calls. |

### EC4: Gateway contract exists

| Task | Description | Depends on | Test or check |
| --- | --- | --- | --- |
| F | Define `MCPToolGateway` protocol with `call_tool(server_name, tool_name, arguments, consumer=...)`. | V3.0 | Done in `src/moomail_finance_ai/mcp/gateway.py`. |
| F1 | Define result shape: structured content, textual content if needed, `is_error`, server/tool metadata, duration, and sanitized error. | F | Done in `MCPGatewayResult`. |
| F2 | Define resource methods if needed: `list_tools`, `read_resource`, and health/capability checks. | F | Done at protocol level. |
| F3 | Define timeout, retry, and error policy at contract level. | F | Partially done through gateway error classes; concrete timeout/retry behavior remains V3.2. |

### EC5: Parity tests exist

| Task | Description | Depends on | Test or check |
| --- | --- | --- | --- |
| H | Add FastMCP deterministic server tests. | C, D, E | Done by updating `tests/test_mcp_stdio_round_trips.py` to official MCP client. |
| H1 | Add FastMCP parity tests against old direct module outputs. | G | Done in `tests/test_mcp_fastmcp_parity.py`. |
| H2 | Keep old custom stdio tests until new FastMCP tests cover equivalent behavior. | H | Done. Custom wrapper unit coverage remains in `tests/test_mcp_servers.py`; scripts now use FastMCP. |
| H3 | Update `TESTING.md` with old/new MCP test responsibilities. | H2 | Done. |

## Tests Added During Implementation

- `tests/test_mcp_stdio_round_trips.py`
  - starts each FastMCP server in recorded/temp mode
  - lists tools/resources
  - calls one or more representative tools
- `tests/test_mcp_fastmcp_parity.py`
  - compares current module path against FastMCP server path
  - focuses on structured content shape, not incidental JSON ordering
- `tests/test_mcp_gateway_contract.py`
  - captures the gateway result/error contract V3.2 will implement
- updated `tests/live/test_connector_targets.py`
  - opt-in OpenD live connection through FastMCP server
  - no hosted LLM required

## Deletion Candidates After This Task

Do not delete these during V3.1 unless all V3.1 parity tests and V3.2 gateway
tests are already green:

- `src/moomail_finance_ai/mcp/stdio.py`
- `tests/test_mcp_stdio_round_trips.py`
- the custom stdio test in `tests/test_mcp_servers.py`

The three server scripts were rewritten in place so CLI names remain stable.
Remove `JsonRpcMCPServer` only once no tests or docs depend on it.

## Risks

- FastMCP decorator code could accidentally become the only place business
  logic lives. Keep the domain logic separate.
- Tool output shape drift can silently break the Portfolio Agent and frontend.
  Use parity tests before migration.
- OpenD live calls can become slow or flaky. Keep recorded report mode as the
  default deterministic test path.
