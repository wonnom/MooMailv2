# V3 Task Maps

Status: planned iteration. V3.0 design boundary is complete as of 2026-06-17;
V3.1 through V3.4 are not implemented.

V3 turns the V2 MCP-shaped runtime into a real backend MCP runtime. The main
change is conceptual as much as technical: MCP becomes shared backend
infrastructure for deterministic app flows and agentic analysis flows, not only
an LLM tool surface.

## V3 Goal

```text
V2 MCP-shaped modules and custom stdio wrapper
  -> FastMCP servers
  -> backend-owned MCP client/gateway
  -> deterministic portfolio data lane
  -> Portfolio Agent and V2 Investment Agent using the same gateway
```

## Non-Goals

- Do not build Neo4j GraphRAG in this V3 iteration.
- Do not add Pinecone memory.
- Do not redesign the portfolio-history SQL schema.
- Do not add trading, order preparation, trade unlock, or executable trade
  tooling.
- Do not let the frontend call MCP directly.
- Do not make every agent fully autonomous as part of this runtime migration.

## Core Architecture Decision

OpenD MCP is a backend infrastructure boundary.

It must support both:

- deterministic backend refresh/status flows for the web dashboard
- agent/subagent tool calls for analytical queries

The frontend calls backend APIs. The backend owns the MCP host/client runtime
and calls MCP servers through a gateway.

```text
Frontend dashboard
  -> Backend API
      -> Deterministic Portfolio Data Service
          -> MCPToolGateway
              -> OpenD MCP
              -> Finance Metrics MCP
              -> Portfolio SQL MCP

Chat or CLI analytical query
  -> Backend API
      -> V2 Investment Agent
          -> Portfolio Agent
              -> MCPToolGateway
                  -> OpenD MCP
                  -> Finance Metrics MCP
                  -> Portfolio SQL MCP
          -> Sentiment Agent stub
```

## Task Files

| Task | File | Purpose |
| --- | --- | --- |
| V3.0 | [TASK_0_MCP_BACKEND_BOUNDARY.md](TASK_0_MCP_BACKEND_BOUNDARY.md) | Complete. Define MCP as backend infrastructure for deterministic app flows and agentic flows. |
| V3.1 | [TASK_1_FASTMCP_SERVER_MIGRATION.md](TASK_1_FASTMCP_SERVER_MIGRATION.md) | Preserve business logic, replace the custom stdio server with FastMCP servers, and define the gateway contract. |
| V3.2 | [TASK_2_GATEWAY_MODES.md](TASK_2_GATEWAY_MODES.md) | Implement DirectToolGateway for parity tests and StdioMCPToolGateway for production-ish local runtime. |
| V3.3 | [TASK_3_DETERMINISTIC_PORTFOLIO_DATA_LANE.md](TASK_3_DETERMINISTIC_PORTFOLIO_DATA_LANE.md) | Implement the deterministic backend and frontend portfolio data lane without invoking agents. |
| V3.4 | [TASK_4_AGENT_GATEWAY_MIGRATION.md](TASK_4_AGENT_GATEWAY_MIGRATION.md) | Move Portfolio Agent and V2 Investment Agent to the gateway and update docs/tests. |

## Cross-Task Dependency Map

```text
V3.0. MCP backend boundary
  ├── V3.1. FastMCP server migration and gateway contract
  │   ├── V3.2. Gateway modes
  │   │   ├── V3.3. Deterministic portfolio data lane implementation
  │   │   └── V3.4. Agent gateway migration
  │   └── FastMCP parity tests
  └── backend API contract for dashboard refresh/status/snapshot

V3.3. Deterministic portfolio data lane
  ├── depends on V3.2 StdioMCPToolGateway
  ├── adds PortfolioDataService/API/frontend refresh flow
  └── proves dashboard refresh does not invoke agents or LLMs

V3.4. Agent gateway migration
  ├── depends on V3.2 StdioMCPToolGateway
  ├── depends on V3.3 dashboard data lane remaining separate
  ├── depends on DirectToolGateway parity tests
  └── closes old in-process MCP runtime usage
```

## Old Or Replaced Code To Review After V3

Do not delete these before V3 parity is proven. They currently protect the V2
working path.

| Candidate | Current role | V3 replacement | Delete or narrow after |
| --- | --- | --- | --- |
| `src/moomail_finance_ai/mcp/stdio.py` | Custom minimal stdio JSON-RPC server wrapper. | FastMCP server runtime. | All three FastMCP servers pass deterministic and live smoke tests. |
| `scripts/mcp_opend_server.py` | Starts custom OpenD stdio wrapper. | FastMCP OpenD server entrypoint, likely rewritten in place or replaced by a new entrypoint. | FastMCP OpenD server is the only supported server script. |
| `scripts/mcp_portfolio_sql_server.py` | Starts custom portfolio SQL stdio wrapper. | FastMCP portfolio SQL server entrypoint. | FastMCP SQL server is the only supported server script. |
| `scripts/mcp_finance_metrics_server.py` | Starts custom metrics stdio wrapper. | FastMCP metrics server entrypoint. | FastMCP metrics server is the only supported server script. |
| `RegisteredMCPModule` in `mcp/registry.py` | In-process tool registry used by agents and custom tests. | FastMCP tool registration plus DirectToolGateway parity adapter. | Agents no longer receive in-process modules and parity tests no longer need this registry. |
| `MCPModule` protocol in `mcp/registry.py` | Type contract for in-process module calls. | `MCPToolGateway` contract. | Portfolio Agent and tests no longer type against `MCPModule`. |
| `MCPToolSpec`, `MCPResourceSpec`, `MCPToolCallResult` | Custom MCP-shaped models. | FastMCP/native MCP schemas and gateway result models. | FastMCP/gateway tests cover tool metadata and structured results. |
| `src/moomail_finance_ai/mcp/agent_access.py` | In-process allowlist manifest builder. | Gateway/server permission config used by backend services and agents. | Gateway allowlist tests replace manifest tests. |
| Direct module injection in `portfolio_agent.py` | Agent receives `opend_mcp`, `finance_metrics_mcp`, and `portfolio_sql_mcp` modules. | Agent receives a permissioned gateway or tool client. | Portfolio Agent tests are migrated to gateway fakes. |
| Direct module builders in `build_default_portfolio_agent` | Creates in-process MCP modules. | Uses backend/gateway factory. | Chat, CLI, and tests all use gateway construction. |
| `_MCPStdioClient` helpers in tests | Custom JSON-RPC subprocess client. | Official MCP client session test helper. | FastMCP stdio round-trip tests are stable. |
| `tests/test_mcp_stdio_round_trips.py` | Verifies custom stdio wrapper. | FastMCP stdio round-trip tests. | New tests prove equivalent server behavior. |
| `tests/test_mcp_servers.py::test_mcp_stdio_adapter_exposes_tools_and_resources` | Unit test for custom wrapper. | FastMCP metadata and gateway tests. | Custom wrapper is removed. |
| Direct-module portions of `tests/test_mcp_tool_contracts.py` | Verifies tool behavior through `RegisteredMCPModule`. | Domain tests plus DirectToolGateway/FastMCP parity tests. | Parity tests prove the same structured content over FastMCP. |
| Direct-module construction in `tests/test_portfolio_agent.py`, `tests/test_v2_portfolio_planner.py`, and `tests/live/test_portfolio_agent_live.py` | Builds agents with in-process modules. | Gateway fake or StdioMCPToolGateway test fixtures. | Agent constructors no longer accept MCP modules. |
| Custom MCP live smoke portions of `tests/live/test_connector_targets.py` | Starts custom server scripts. | Official MCP client live smoke tests against FastMCP servers. | FastMCP live smoke tests pass against local OpenD. |

Also clean generated `__pycache__` directories before committing if they are
still present in the working tree. They are not part of V3 design and should
not be versioned.

## Suggested V3 Closeout Gate

The exact commands will be finalized during implementation, but V3 closeout
should include:

```bash
.venv/bin/python -m pytest tests --ignore=tests/live -q
.venv/bin/python -m pytest tests/test_mcp_fastmcp_servers.py -q
.venv/bin/python -m pytest tests/test_mcp_gateway.py -q
.venv/bin/python -m pytest tests/test_dashboard_portfolio_data_lane.py -q
```

Optional live gate:

```bash
MOOMAIL_RUN_LIVE_CONNECTOR_TESTS=1 .venv/bin/python -m pytest tests/live -q -k "opend or mcp"
```

## Free Tasks

These can start immediately:

- V3.0-A: Document deterministic portfolio data lane contracts.
- V3.0-B: Define backend-owned MCP gateway responsibilities.
- V3.0-C: Update the retirement inventory as implementation reveals more
  custom runtime code.
- V3.1-A: Audit current OpenD, SQL, and metrics business logic boundaries.

Do not start V3.3 until V3.2 has a working gateway with parity coverage. Do not
start V3.4 until V3.3 proves dashboard refresh is deterministic and independent
from agent runs.
