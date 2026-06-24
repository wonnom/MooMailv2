# V1.3 Task Maps

Status: complete iteration. V1.3.0 through V1.3.4 are complete.

V1.3 turns the V1.2 MCP-shaped runtime into a real backend MCP runtime. The main
change is conceptual as much as technical: MCP becomes shared backend
infrastructure for deterministic app flows and agentic analysis flows, not only
an LLM tool surface.

## V1.3 Goal

```text
V1.2 MCP-shaped modules and custom stdio wrapper
  -> FastMCP servers
  -> backend-owned MCP client/gateway
  -> deterministic portfolio data lane
  -> Portfolio Agent and V1.2 Investment Agent using the same gateway
```

## Non-Goals

- Do not build Neo4j GraphRAG in this V1.3 iteration.
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
      -> V1.2 Investment Agent
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
| V1.3.0 | [TASK_0_MCP_BACKEND_BOUNDARY.md](TASK_0_MCP_BACKEND_BOUNDARY.md) | Complete. Define MCP as backend infrastructure for deterministic app flows and agentic flows. |
| V1.3.1 | [TASK_1_FASTMCP_SERVER_MIGRATION.md](TASK_1_FASTMCP_SERVER_MIGRATION.md) | Complete. Preserve business logic, replace the custom stdio server scripts with FastMCP servers, and define the gateway contract. |
| V1.3.2 | [TASK_2_GATEWAY_MODES.md](TASK_2_GATEWAY_MODES.md) | Complete. Implement DirectToolGateway for parity tests and StdioMCPToolGateway for production-ish local runtime. |
| V1.3.3 | [TASK_3_DETERMINISTIC_PORTFOLIO_DATA_LANE.md](TASK_3_DETERMINISTIC_PORTFOLIO_DATA_LANE.md) | Complete. Implement the deterministic backend and frontend portfolio data lane without invoking agents. |
| V1.3.4 | [TASK_4_AGENT_GATEWAY_MIGRATION.md](TASK_4_AGENT_GATEWAY_MIGRATION.md) | Complete. Move Portfolio Agent and V1.2 Investment Agent to the gateway and update docs/tests. |

## Cross-Task Dependency Map

```text
V1.3.0. MCP backend boundary
  ├── V1.3.1. FastMCP server migration and gateway contract
  │   ├── V1.3.2. Gateway modes
  │   │   ├── V1.3.3. Deterministic portfolio data lane implementation
  │   │   └── V1.3.4. Agent gateway migration
  │   └── FastMCP parity tests
  └── backend API contract for dashboard refresh/status/snapshot

V1.3.3. Deterministic portfolio data lane
  ├── uses V1.3.2 StdioMCPToolGateway by default
  ├── adds PortfolioDataService/API/frontend refresh flow
  └── proves dashboard refresh does not invoke agents or LLMs

V1.3.4. Agent gateway migration
  ├── depends on V1.3.2 StdioMCPToolGateway
  ├── depends on V1.3.3 dashboard data lane remaining separate
  ├── depends on DirectToolGateway parity tests
  └── closes old in-process MCP runtime usage for Portfolio Agent and V1.2 Investment Agent
```

## Old Or Replaced Code To Review After V1.3

V1.3 parity is proven for the Portfolio Agent and V1.2 Investment Agent gateway
path. The items below are now either migrated, legacy/test-only, or still
deliberately kept as domain/tool-registry support.

| Candidate | Current role | V1.3 replacement | Delete or narrow after |
| --- | --- | --- | --- |
| `src/moomail_finance_ai/mcp/stdio.py` | Legacy custom minimal stdio JSON-RPC server wrapper used by registry tests only. | FastMCP server runtime. | Remove after registry tests no longer need custom wrapper coverage. |
| `scripts/mcp_opend_server.py` | FastMCP OpenD server entrypoint as of V1.3.1. | Keep stable CLI while gateway modes are added. | Gateway/live tests prove this is the only supported OpenD server path. |
| `scripts/mcp_portfolio_sql_server.py` | FastMCP portfolio SQL server entrypoint as of V1.3.1. | Keep stable CLI while gateway modes are added. | Gateway tests prove this is the only supported SQL server path. |
| `scripts/mcp_finance_metrics_server.py` | FastMCP metrics server entrypoint as of V1.3.1. | Keep stable CLI while gateway modes are added. | Gateway tests prove this is the only supported metrics server path. |
| `RegisteredMCPModule` in `mcp/registry.py` | In-process tool registry underneath FastMCP and DirectToolGateway tests. Agents no longer receive these modules. | FastMCP tool registration plus DirectToolGateway parity adapter. | Keep while business handlers are registered this way. |
| `MCPModule` protocol in `mcp/registry.py` | Type contract for registry/FastMCP adapter and DirectToolGateway. | `MCPToolGateway` is the agent runtime contract. | Keep while registry adapter exists. |
| `MCPToolSpec`, `MCPResourceSpec`, `MCPToolCallResult` | Custom MCP-shaped models. | FastMCP/native MCP schemas and gateway result models. | FastMCP/gateway tests cover tool metadata and structured results. |
| `src/moomail_finance_ai/mcp/agent_access.py` | In-process allowlist manifest builder. | Gateway/server permission config used by backend services and agents. | Gateway allowlist tests replace manifest tests. |
| Direct module injection in `portfolio_agent.py` | Removed in V1.3.4. | Agent receives a permissioned gateway. | Complete. |
| Direct module builders in `build_default_portfolio_agent` | Removed as the default runtime path in V1.3.4. DirectToolGateway remains test/dev parity support. | Uses backend/gateway factory. | Complete. |
| `_MCPStdioClient` helpers in tests | Custom JSON-RPC subprocess client. | Official MCP client session test helper. | FastMCP stdio round-trip tests are stable. |
| `tests/test_mcp_stdio_round_trips.py` | Verifies custom stdio wrapper. | FastMCP stdio round-trip tests. | New tests prove equivalent server behavior. |
| `tests/test_mcp_servers.py::test_mcp_stdio_adapter_exposes_tools_and_resources` | Unit test for custom wrapper. | FastMCP metadata and gateway tests. | Custom wrapper is removed. |
| Direct-module portions of `tests/test_mcp_tool_contracts.py` | Verifies tool behavior through `RegisteredMCPModule`. | Domain tests plus DirectToolGateway/FastMCP parity tests. | Parity tests prove the same structured content over FastMCP. |
| Direct-module construction in `tests/test_portfolio_agent.py`, `tests/test_portfolio_planner.py`, and `tests/live/test_portfolio_agent_live.py` | Removed in V1.3.4. | DirectToolGateway/recording gateway fixtures. | Complete. |
| Custom MCP live smoke portions of `tests/live/test_connector_targets.py` | Starts custom server scripts. | Official MCP client live smoke tests against FastMCP servers. | FastMCP live smoke tests pass against local OpenD. |

Also clean generated `__pycache__` directories before committing if they are
still present in the working tree. They are not part of V1.3 design and should
not be versioned.

## V1.3 Closeout Gate

V1.3 closeout includes:

```bash
.venv/bin/python -m pytest tests --ignore=tests/live -q
.venv/bin/python -m pytest tests/test_mcp_gateway.py tests/test_mcp_stdio_gateway.py tests/test_mcp_gateway_contract.py -q
.venv/bin/python -m pytest tests/test_portfolio_data_service.py tests/test_chat_app.py -q
```

Latest V1.3.4 closeout result:

```text
.venv/bin/python -m pytest tests --ignore=tests/live -q
183 passed, 1 warning
```

The warning is the existing LangGraph dependency deprecation warning.

Optional live gate:

```bash
MOOMAIL_RUN_LIVE_CONNECTOR_TESTS=1 .venv/bin/python -m pytest tests/live -q -k "opend or mcp"
```

## Free Tasks

## Remaining Work

V1.3 is complete for the MCP runtime migration targeted in this iteration. Keep
legacy registry/custom-stdio tests only while they protect still-used registry
behavior. Future work should move to V1.4 planning, GraphRAG, memory, or richer
planner/synthesis work.
