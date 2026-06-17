# Task V3.0: MCP Backend Boundary

Status: planned.

## Goal

Define MCP as backend infrastructure, not only an LLM agent tool surface.

OpenD MCP must become the standardized backend boundary for MooMoo/OpenD data
access. Deterministic app features and agents should share the same read-only,
permissioned, tested data interface.

## Intent

Two lanes will use MCP:

```text
Deterministic portfolio data lane
  -> app startup, page load, or manual refresh
  -> backend service calls MCP gateway
  -> connection status, funds, positions, normalized snapshot, metrics
  -> SQL history update
  -> dashboard response

Agentic analysis lane
  -> user asks analytical query
  -> Investment Agent decides what context is needed
  -> Portfolio Agent calls gateway for current or historical portfolio context
  -> Sentiment/fundamental tools may be invoked when relevant
```

The frontend must never call MCP directly. It calls backend APIs. The backend
owns MCP server lifecycle, permissions, timeouts, traces, and errors.

## Exit Criteria

1. Architecture docs distinguish deterministic portfolio data lane from
   agentic analysis lane.
2. Backend API contracts exist for portfolio connection status, dashboard
   snapshot, manual refresh, and last-updated metadata.
3. MCP gateway responsibility is documented for both backend services and
   agents.
4. Permission boundaries identify which consumer can call which MCP servers and
   tools.
5. The old "MCP is mainly an agent tool surface" wording is removed or marked as
   historical.

## Dependency Graph

```text
A. Audit current app and agent consumers
   ├── B. Define backend portfolio data lane contracts
   │   ├── C. Define dashboard API response shape
   │   └── D. Define refresh/status error semantics
   ├── E. Define MCP gateway ownership and lifecycle
   │   └── F. Define consumer permission profiles
   └── G. Update architecture/reality docs
       └── H. Add documentation tests or checklist coverage
```

## Task Breakdown By Exit Criteria

### EC1: Deterministic and agentic lanes are distinct

| Task | Description | Depends on | Test or check |
| --- | --- | --- | --- |
| A | Audit `chat_api.py`, `portfolio_agent.py`, `v2_investment_agent.py`, and frontend dashboard assumptions for current portfolio data access. | None | Notes in this task doc or `ARCHITECTURE.md`. |
| A1 | Identify which current calls are infrastructure refresh calls rather than analytical agent calls. | A | Review checklist. |
| B | Define "deterministic portfolio data lane" in `ARCHITECTURE.md` and V3 docs. | A1 | Docs mention page load, manual refresh, OpenD status, snapshot, metrics, SQL update. |
| B1 | Define "agentic analysis lane" in `ARCHITECTURE.md` and V3 docs. | A1 | Docs state Investment Agent owns analysis routing. |
| B2 | State that OpenD MCP serves both lanes. | B, B1 | Docs check. |

### EC2: Backend API contracts are defined

| Task | Description | Depends on | Test or check |
| --- | --- | --- | --- |
| C | Define a backend endpoint or service method for connection status. Suggested shape: `PortfolioConnectionStatus`. | B | Contract/schema test once implemented. |
| C1 | Include OpenD reachable status, configured host/port summary, selected account metadata, and sanitized error. | C | Unit test with fake gateway connection failure. |
| C2 | Ensure no credentials or account secrets leak to frontend. | C1 | Security assertion in response tests. |
| D | Define a backend endpoint or service method for dashboard snapshot. Suggested shape: `PortfolioDashboardSnapshot`. | B | Contract/schema test once implemented. |
| D1 | Include `as_of`, `last_updated_at`, `freshness_status`, funds/balances, holdings, cash-equivalent handling, metrics, and warnings. | D | Snapshot fixture test. |
| D2 | Include unsupported quote warnings and cash sweep assumptions as displayable warnings. | D1 | Fixture test with OTC and fund-assets assumptions. |
| E | Define manual refresh semantics. | C, D | Refresh service test once implemented. |
| E1 | Refresh should check OpenD, retrieve latest funds/positions/context, calculate metrics, update SQL, and return dashboard snapshot. | E | Fake gateway verifies tool sequence. |
| E2 | Failed refresh should return structured error and preserve last-known dashboard state if available. | E | Fake gateway failure test. |

### EC3: Backend owns MCP gateway lifecycle

| Task | Description | Depends on | Test or check |
| --- | --- | --- | --- |
| F | Define the backend as the MCP host/client owner. | B | Architecture docs. |
| F1 | Define startup behavior: create gateway, launch or connect to MCP servers, validate capabilities. | F | Gateway lifecycle test in V3.2. |
| F2 | Define shutdown behavior: close MCP sessions/processes cleanly. | F | Gateway lifecycle test in V3.2. |
| F3 | Define per-request behavior: reuse existing sessions and emit trace/status events. | F | Gateway call trace test in V3.2. |
| F4 | State that frontend talks only to backend APIs. | F | Docs check and frontend code review. |

### EC4: Permission profiles exist

| Task | Description | Depends on | Test or check |
| --- | --- | --- | --- |
| G | Define gateway consumer identities. Suggested identities: `dashboard_refresh`, `portfolio_agent`, `investment_agent`, `sentiment_agent`. | F | Permission config test in V3.2. |
| G1 | `dashboard_refresh` can call OpenD status/context, metrics snapshot, and SQL update tools. | G | Deny/allow test. |
| G2 | `portfolio_agent` can call OpenD, metrics, and SQL tools needed for analysis. | G | Deny/allow test. |
| G3 | `investment_agent` should not directly call OpenD unless explicitly approved later; it should call Portfolio Agent for portfolio retrieval. | G | Deny test. |
| G4 | `sentiment_agent` keeps finance metrics only until research MCP exists. | G | Deny test. |

### EC5: Old wording is corrected

| Task | Description | Depends on | Test or check |
| --- | --- | --- | --- |
| H | Update `ACTION_PLAN.md`, `ARCHITECTURE.md`, and `MCP_SERVERS.md` to describe MCP as backend infrastructure. | B through G | Documentation review. |
| H1 | Mark V2's in-process module runtime as historical/current reality, not target V3 architecture. | H | Documentation review. |
| H2 | Add docs regression checks if the project keeps using doc tests. | H | New or updated docs test. |

## Tests To Add During Implementation

- `tests/test_portfolio_data_lane_contracts.py`
  - validates dashboard status/snapshot response schemas
  - confirms frontend-safe redaction
  - covers refresh success, partial failure, and stale last-known state
- `tests/test_mcp_gateway_permissions.py`
  - verifies consumer allowlists
  - verifies denied OpenD access for direct Investment Agent calls
- Documentation test, if desired:
  - confirms V3 docs mention deterministic lane, agentic lane, backend-owned
    gateway, and no frontend direct MCP calls

## Deletion Candidates After This Task

None from code yet. This is a design boundary task.

After this task, old docs that imply "MCP equals agent tools only" should be
rewritten or marked historical. Do not remove runtime code in V3.0.

## Risks

- If this task is skipped, FastMCP migration may accidentally optimize only for
  agent calls and leave the dashboard with a separate OpenD data path.
- If frontend calls MCP directly, credentials, connection lifecycle, and error
  handling will leak into the wrong layer.
- If permission profiles are vague, the gateway can become a centralized tool
  bucket instead of a controlled backend boundary.
