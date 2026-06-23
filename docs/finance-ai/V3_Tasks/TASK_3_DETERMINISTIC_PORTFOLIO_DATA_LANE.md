# Task V3.3: Deterministic Portfolio Data Lane

Status: complete.

## Goal

Implement the deterministic portfolio data lane as a real backend and frontend
flow.

The dashboard should be able to show current portfolio state, OpenD connection
status, latest balances, holdings, metrics, warnings, and last-updated metadata
without asking Portfolio Agent or Investment Agent to decide whether OpenD data
is needed.

This task proves the non-agent MCP consumer path before moving agents to the
gateway in V3.4.

Implemented files:

- `src/moomail_finance_ai/portfolio_data_service.py`
- `src/moomail_finance_ai/chat_api.py`
- `scripts/serve_chat.py`
- `web/index.html`
- `web/static/app.ts` / `web/static/app.js`
- `web/static/portfolio_api.ts` / `web/static/portfolio_api.js`
- `tests/test_portfolio_data_service.py`
- `tests/test_chat_app.py`

## Target Shape

```text
Frontend page load or manual refresh
  -> Backend dashboard/status/refresh API
      -> PortfolioDataService
          -> MCPToolGateway as consumer="dashboard_refresh"
              -> moomail-opend-mcp
              -> moomail-finance-metrics-mcp
              -> moomail-portfolio-sql-mcp
      -> frontend-safe dashboard state

Chat analytical query
  -> Investment Agent / Portfolio Agent path
  -> not involved in dashboard refresh
```

## Exit Criteria

1. Complete. Backend has a deterministic `PortfolioDataService` for
   connection status, latest dashboard snapshot, and manual refresh.
2. Complete. The service uses `MCPToolGateway` with the `dashboard_refresh` consumer and
   does not call Portfolio Agent, Investment Agent, an LLM, or agent planner.
3. Complete. Backend API routes expose connection status, latest dashboard snapshot, and
   manual refresh result to the frontend.
4. Complete. Frontend dashboard/page-load flow uses those backend APIs and shows refresh
   progress, errors, last-updated metadata, balances, holdings, metrics, and
   warnings without starting an agent run.
5. Complete. Refresh updates the canonical SQL portfolio-history DB through portfolio SQL
   MCP and preserves a last-known stale snapshot when refresh fails.
6. Complete. Tests prove the deterministic lane, frontend behavior, and no-agent/no-LLM
   boundary.

Implemented routes:

- `GET /api/portfolio/status`
- `GET /api/portfolio/dashboard`
- `POST /api/portfolio/refresh`

Current route behavior:

- Status checks OpenD through the backend service and returns a connected or
  disconnected status with sanitized errors.
- Dashboard reads the latest SQL portfolio state and calculates metrics from
  that reconstructed snapshot. It does not call OpenD.
- Refresh checks OpenD, retrieves a normalized current portfolio context,
  calculates metrics, stores the observation in canonical SQL history, and
  returns dashboard-ready state.
- On refresh failure, the service returns the last-known SQL dashboard snapshot
  when available and includes the sanitized refresh error.

## Dependency Graph

```text
V3.0. MCP backend boundary
  └── V3.1. FastMCP servers and gateway contract
      └── V3.2. Gateway modes and permissions
          ├── A. Backend response models
          ├── B. PortfolioDataService
          │   ├── C. Connection status flow
          │   ├── D. Dashboard snapshot flow
          │   ├── E. Manual refresh flow
          │   └── F. Last-known stale state/error flow
          ├── G. Backend API routes
          ├── H. Frontend dashboard refresh UI
          └── I. Tests and docs
              └── V3.4. Agent gateway migration
```

## Task Breakdown By Exit Criteria

### EC1: Backend deterministic service exists

| Task | Description | Depends on | Test or check |
| --- | --- | --- | --- |
| A | Add response models for `PortfolioConnectionStatus`, `PortfolioDashboardSnapshot`, and `PortfolioRefreshResult`. | V3.0 | Schema/unit tests. |
| A1 | Ensure models include `as_of`, `last_updated_at`, `freshness_status`, warnings, errors, and source summary. | A | Model validation tests. |
| A2 | Ensure models are frontend-safe and exclude secrets, raw account IDs, API keys, credentials, tokens, and hidden backend config. | A | Redaction/security tests. |
| B | Add `PortfolioDataService` or equivalent backend service. | A, V3.2 | Service tests with fake gateway. |
| B1 | Inject a gateway dependency and canonical portfolio/db config. | B | Construction test. |
| B2 | Expose service methods for `connection_status()`, `latest_snapshot()`, and `refresh()`. | B | Method tests. |

### EC2: Service uses gateway and avoids agents/LLMs

| Task | Description | Depends on | Test or check |
| --- | --- | --- | --- |
| C | Implement connection status flow through `moomail-opend-mcp:opend_check_connection` and sanitized config/resource data if needed. | B | Fake gateway verifies tool call and consumer. |
| C1 | Use `consumer="dashboard_refresh"` on all gateway calls. | C | Gateway fake assertion. |
| C2 | Return structured disconnected/degraded status on OpenD or gateway failure. | C | Failure test. |
| D | Implement latest dashboard snapshot flow from SQL latest state and/or last-known cached refresh state. | B | Latest snapshot test. |
| D1 | Do not call OpenD during a pure latest-snapshot read unless explicit refresh is requested. | D | Fake gateway call-count test. |
| E | Implement manual refresh flow. | B, C | Refresh success test. |
| E1 | Call OpenD context retrieval, finance metrics calculation, SQL upsert/store tools, and return dashboard snapshot. | E | Tool sequence test. |
| E2 | Do not instantiate or call `MCPPortfolioAgent`, `V2InvestmentAgent`, LLM evaluator, or sentiment agent. | E | Fake/spies prove no agent/LLM calls. |

### EC3: Backend API routes exist

| Task | Description | Depends on | Test or check |
| --- | --- | --- | --- |
| G | Add backend route for connection status, for example `GET /api/portfolio/status`. | B, C | HTTP test. |
| G1 | Add backend route for latest dashboard snapshot, for example `GET /api/portfolio/dashboard`. | D | HTTP test. |
| G2 | Add backend route for manual refresh, for example `POST /api/portfolio/refresh`. | E | HTTP test. |
| G3 | Return structured errors with non-200 or explicit failure payloads according to the existing chat API style. | G through G2 | HTTP error test. |
| G4 | Ensure API routes reuse backend gateway/session management rather than creating one gateway per frontend poll if a shared manager exists. | V3.2, G | Lifecycle test. |

### EC4: Frontend uses deterministic refresh flow

| Task | Description | Depends on | Test or check |
| --- | --- | --- | --- |
| H | Update frontend page-load behavior to request dashboard/status API instead of running Portfolio Agent by default. | G, G1 | Static/frontend test. |
| H1 | Add or update manual refresh control to call refresh API, show loading state, and update dashboard state on success. | G2, H | Frontend test. |
| H2 | Show connection status, last updated, freshness, balances, holdings, metrics, warnings, and data-quality events. | H1 | Frontend DOM/static test. |
| H3 | Show refresh errors in the dashboard/trace area and preserve stale last-known data when provided. | G3, H1 | Error UI test. |
| H4 | Keep chat input and agent selector separate from dashboard refresh. | H | Frontend test verifies refresh does not submit chat query. |

### EC5: SQL history update and stale-state behavior work

| Task | Description | Depends on | Test or check |
| --- | --- | --- | --- |
| F | Persist refresh observations through portfolio SQL MCP. | E | Fake gateway verifies SQL tools. |
| F1 | Store or update daily value snapshot, position states, weight snapshots, and data-quality events according to current SQL design. | F | Refresh persistence test. |
| F2 | Use `data/portfolio-history.sqlite` by default, with temp DB override in tests. | F | Config/path test. |
| F3 | On refresh failure after prior success, return prior snapshot with stale freshness and structured error. | F | Stale fallback test. |

### EC6: Tests and docs prove the boundary

| Task | Description | Depends on | Test or check |
| --- | --- | --- | --- |
| I | Add `tests/test_portfolio_data_service.py`. | B through F | Service tests. |
| I1 | Add or update HTTP/backend tests for dashboard/status/refresh routes. | G | API tests. |
| I2 | Update `tests/test_chat_app.py` or add frontend static tests for deterministic refresh UI. | H | Frontend tests. |
| I3 | Add a no-agent/no-LLM regression test. | E2 | Test fails if refresh constructs agents or LLM evaluator. |
| I4 | Update `ARCHITECTURE.md`, `MCP_SERVERS.md`, `PROTOCOL.md`, and `TESTING.md` after implementation. | I | Docs review. |

## Tests To Add Or Update During Implementation

- `tests/test_portfolio_data_service.py`
  - connection status success/failure
  - latest snapshot without OpenD refresh
  - manual refresh success
  - refresh failure with stale last-known snapshot
  - no agent/LLM invocation
- `tests/test_portfolio_dashboard_api.py`
  - status endpoint
  - dashboard endpoint
  - refresh endpoint
  - sanitized errors and no secrets
- `tests/test_chat_app.py` or a frontend-specific test
  - page load calls dashboard/status APIs
  - refresh button calls refresh API
  - refresh does not submit a chat query or select an agent
  - error UI renders without hanging
- Opt-in live test, if useful:
  - live OpenD manual refresh through FastMCP/StdioMCPToolGateway
  - still guarded by `MOOMAIL_RUN_LIVE_CONNECTOR_TESTS=1`

Implemented verification:

```bash
.venv/bin/python -m pytest tests/test_portfolio_data_service.py tests/test_chat_app.py -q
```

Latest targeted result during V3.3 implementation:

```text
15 passed
```

## Deletion Candidates After This Task

Review and remove or quarantine any frontend/backend behavior that treats
dashboard refresh as an agent run:

- page-load Portfolio Agent invocation, if any exists
- frontend "run portfolio evaluation" behavior used only to populate dashboard
  state
- backend route code that retrieves current portfolio data by constructing a
  Portfolio Agent when a deterministic service should own it
- duplicated frontend state derived from old portfolio-agent-only responses

Do not remove the Portfolio Agent itself. It remains the analytical subagent for
chat queries and V3.4 migration.

No MCP tools were deleted in V3.3. The deterministic service still uses the
same OpenD, metrics, and SQL MCP surfaces as the agents use through the
gateway. V3.4 later proved the agent path is gateway-backed; the remaining
registry/custom-stdio code is kept only where it still protects the FastMCP
adapter, DirectToolGateway parity mode, or legacy registry behavior.

## Risks

- If dashboard refresh calls an agent, the app will stay slow and confusing:
  data freshness would depend on LLM/agent orchestration.
- If latest snapshot always calls OpenD, page loads may become brittle. Keep
  latest-read and explicit-refresh behavior distinct.
- If frontend state shape is designed only around today's static UI, the future
  React frontend may inherit awkward contracts. Keep backend response models as
  the source of truth.
