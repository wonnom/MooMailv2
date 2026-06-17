# Task V3.2: Gateway Modes

Status: planned.

## Goal

Implement the backend MCP gateway modes that both deterministic services and
agents will use.

V3 uses two modes:

- `DirectToolGateway`: test/dev parity adapter only. It wraps current in-process
  tool handlers so tests can compare old and new behavior.
- `StdioMCPToolGateway`: production-ish local runtime. It uses the official MCP
  client to launch/connect to local FastMCP stdio servers.

`DirectToolGateway` is not the production app runtime and is not the target MCP
runtime boundary.

## Target Shape

```text
Backend startup
  -> create GatewayManager
  -> start/connect FastMCP stdio servers
  -> validate tool/resource capabilities
  -> expose gateway to deterministic services and agents

Backend request
  -> service or agent calls gateway.call_tool(...)
  -> gateway checks consumer allowlist
  -> gateway calls target MCP server
  -> gateway returns structured result and trace metadata

Backend shutdown
  -> gateway closes MCP sessions/processes
```

## Exit Criteria

1. `MCPToolGateway` contract is implemented with structured results, sanitized
   errors, timeouts, and trace metadata.
2. `DirectToolGateway` supports fast deterministic parity tests only.
3. `StdioMCPToolGateway` uses the official MCP client to call FastMCP servers
   over stdio.
4. Gateway permissions support deterministic backend consumers and agent
   consumers.
5. Gateway lifecycle is reusable by chat backend, CLI scripts, and future
   dashboard APIs.

## Dependency Graph

```text
V3.1. FastMCP server migration and gateway contract
  ├── A. Gateway result and config models
  │   ├── B. Permission profiles
  │   ├── C. DirectToolGateway
  │   └── D. StdioMCPToolGateway
  │       ├── E. GatewayManager lifecycle
  │       └── F. Trace/error handling
  └── G. Gateway tests
      ├── H. Deterministic portfolio data lane can use gateway
      ├── V3.3. Deterministic portfolio data lane can be implemented
      └── V3.4. Agents can move to gateway
```

## Task Breakdown By Exit Criteria

### EC1: Gateway contract is implemented

| Task | Description | Depends on | Test or check |
| --- | --- | --- | --- |
| A | Add `MCPToolGateway` protocol or abstract base. | V3.1-F | Type/unit test. |
| A1 | Add gateway config models for server name, command, args, env, cwd, timeout, and startup mode. | A | Config validation test. |
| A2 | Add gateway result model with `server_name`, `tool_name`, `structured_content`, `content`, `is_error`, `duration_ms`, and sanitized error fields. | A | Result validation test. |
| A3 | Add gateway exception hierarchy for denied tool, timeout, server unavailable, protocol error, and tool error. | A | Error mapping tests. |
| A4 | Add `list_tools` and `read_resource` methods if needed by permissions and health checks. | A | Metadata tests. |

### EC2: DirectToolGateway supports parity tests only

| Task | Description | Depends on | Test or check |
| --- | --- | --- | --- |
| C | Implement `DirectToolGateway` over current tool handlers or `RegisteredMCPModule` builders. | A | Direct gateway tests. |
| C1 | Ensure DirectToolGateway returns the same gateway result model as StdioMCPToolGateway. | C | Shared contract tests. |
| C2 | Mark DirectToolGateway as test/dev only in docs and code comments. | C | Docs review. |
| C3 | Use DirectToolGateway for parity tests against FastMCP output. | C, V3.1-H1 | Parity tests. |
| C4 | Avoid wiring DirectToolGateway as the default app runtime. | C | Backend factory test. |

### EC3: StdioMCPToolGateway uses official MCP client

| Task | Description | Depends on | Test or check |
| --- | --- | --- | --- |
| D | Implement `StdioMCPToolGateway` using the official MCP Python client/session APIs. | V3.1 FastMCP servers | Stdio gateway round-trip test. |
| D1 | Launch or connect to `opend-mcp`, `portfolio-sql-mcp`, and `finance-metrics-mcp` server processes. | D | Startup test with recorded/temp mode. |
| D2 | Reuse sessions across multiple calls instead of spawning per tool call. | D1 | Call-count/lifecycle test. |
| D3 | Close sessions/processes cleanly on shutdown. | D1 | Shutdown test. |
| D4 | Support recorded OpenD report mode and temp SQLite path for deterministic tests. | D1 | Test fixture. |
| D5 | Support live OpenD config only in opt-in live tests or manual runs. | D1 | Live test skip behavior. |

### EC4: Gateway permissions support all consumers

| Task | Description | Depends on | Test or check |
| --- | --- | --- | --- |
| B | Define permission profiles for `dashboard_refresh`, `portfolio_agent`, `investment_agent`, and `sentiment_agent`. | V3.0-G | Permission tests. |
| B1 | Allow `dashboard_refresh` to call OpenD status/context, metrics snapshot, and SQL update tools. | B | Allow test. |
| B2 | Allow `portfolio_agent` to call OpenD, SQL, and metrics tools needed for portfolio analysis. | B | Allow test. |
| B3 | Deny direct OpenD tools to `investment_agent` by default. | B | Deny test. |
| B4 | Deny trade/order tools globally even if a future server accidentally exposes them. | B | Deny test with fake tool list. |
| B5 | Include permission decisions in sanitized trace metadata. | B | Trace test. |

### EC5: Gateway lifecycle is reusable

| Task | Description | Depends on | Test or check |
| --- | --- | --- | --- |
| E | Add `GatewayManager` or backend factory that owns gateway startup/shutdown. | D | Lifecycle test. |
| E1 | Support chat/backend startup with StdioMCPToolGateway. | E | Backend factory tests in V3.3 and V3.4. |
| E2 | Support CLI script startup with StdioMCPToolGateway. | E | CLI smoke test in V3.4. |
| E3 | Support deterministic dashboard refresh service with the same gateway. | E | Data lane test. |
| F | Standardize gateway trace/error events. | A3, E | Trace tests. |
| F1 | Sanitize errors before returning to frontend. | F | Error response test. |
| F2 | Include server/tool/duration/status in backend trace. | F | Trace event test. |

## Tests To Add During Implementation

- `tests/test_mcp_gateway.py`
  - result model
  - permission allow/deny
  - sanitized error mapping
  - DirectToolGateway mode
- `tests/test_mcp_stdio_gateway.py`
  - starts FastMCP servers in recorded/temp mode
  - calls tools through official MCP client
  - reuses sessions and shuts down cleanly
- `tests/test_mcp_gateway_permissions.py`
  - consumer-specific allowlists
  - direct Investment Agent OpenD denial
  - global trade/order denial
- `tests/test_dashboard_portfolio_data_lane.py`
  - fake gateway sequence for status, refresh, metrics, SQL update

## Deletion Candidates After This Task

These become real deletion candidates only after V3.2, V3.3, and V3.4 are green:

- `_MCPStdioClient` helper classes in deterministic and live tests
- `src/moomail_finance_ai/mcp/stdio.py`
- direct `module.call_tool(...)` helper paths in agents
- `agent_access.py` if gateway permission config replaces it fully

Keep `DirectToolGateway` while it is useful for parity tests. Remove or quarantine
it later if it becomes a tempting production shortcut.

## Risks

- A gateway that starts a server per tool call will be slow and brittle. Reuse
  sessions.
- A gateway with broad permissions will recreate the "central bucket of tools"
  problem. Permission profiles must be tested.
- DirectToolGateway is useful during migration but dangerous as a permanent
  runtime default. Keep it clearly test/dev only.
