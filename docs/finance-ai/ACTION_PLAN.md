# Action Plan

## Current Reality

The project currently has a local v1-shaped prototype, not the final connected architecture.

Implemented locally:

- Mock Investment Agent prototype.
- Recorded/live-capable read-only OpenD adapter.
- OpenD portfolio normalization.
- Local SQLite portfolio history store.
- Deterministic Python metric functions.
- Local file-backed memory stand-in.
- Local deterministic research store and Sentiment Agent fixtures.
- Full local Investment Agent flow over recorded OpenD data.
- MCP-backed Portfolio Agent that calls OpenD, portfolio SQL, and finance metrics MCP modules.
- Provider-neutral portfolio-only evaluator behind a structured LLM adapter,
  currently verified with Gemini and prepared for OpenAI.
- Local chat frontend with streaming status, report panels, trace output,
  bottom composer, Send button, resizable chat rail, and hide/show controls.
- Local MCP-facing modules and stdio server scripts for OpenD, portfolio SQL, and finance metrics.
- Focused OpenD diagnostic script for account list, funds, and position reads.

Actually connected at least once:

- OpenD was connected live for the `FUTUSG` securities account path.
- SQLite is real and stores local snapshots, metrics, audit summaries, and run records.
- The local frontend can call the local Python backend.
- MCP server scripts round-trip locally for finance metrics, OpenD recorded mode, and portfolio SQL.
- The OpenD MCP live connector smoke test passes when OpenD is available and live connector tests are enabled.
- Gemini live connector smoke tests pass when Gemini credentials are present and live connector tests are enabled.
- The Portfolio Agent live test calls the configured LLM evaluator after running recorded OpenD data through the three MCP modules.
- Live normalized OpenD portfolio summaries build with unsupported OTC quotes
  captured as warnings.

Still not real integrations:

- The full Investment Agent still calls local Python implementations directly rather than acting as an MCP client.
- The Portfolio Agent uses in-process MCP modules, not yet an official MCP transport client.
- No Pinecone memory is connected.
- No Neo4j graph store is connected.
- No vector DB or embedding pipeline is connected.
- No LangGraph runtime is connected.
- No proprietary SQL database is connected.
- No real research document ingestion pipeline exists yet.
- Crypto holdings are not yet read through `OpenCryptoTradeContext`.
- OTC quote fallback outside OpenD is not yet implemented.

## Current Priority: V1 Finalization

The connector validation spike has served its purpose for OpenD, local MCP
modules, SQLite, and LLM adapters. The next objective is to stabilize the first
usable Portfolio Agent version rather than broadening integrations.

See [V1_FINALIZATION_PLAN.md](V1_FINALIZATION_PLAN.md) for the release gate.

Immediate sequence:

1. Harden live OpenD portfolio reads and document the exact env setup.
2. Freeze the Portfolio Agent output contract consumed by terminal and web UI.
3. Keep cash-sweep handling explicit through
   `MOOMAIL_MOOMOO_TREAT_FUND_ASSETS_AS_CASH_SWEEP`.
4. Add a recorded fixture covering OTC quote failure and cash-equivalent handling.
5. Verify terminal and web reviews against the same live OpenD data.
6. Run deterministic tests and live OpenD-only tests before calling v1 done.

## Deferred Connector Validation

Goal: prove every major connector class with one thin, inspectable round trip before deeper integration. This is intentionally not the final architecture. It is a fail-early iteration so assumptions about auth, SDKs, network access, schemas, and operational friction surface while the system is still small.

Minimum outcome before resuming this deferred connector track:

- At least one LLM call is wired into one agent path.
- At least one MCP server is running locally and called by the agent layer.
- At least one live OpenD read is run through the full local review path, not only recorded mode.
- At least one memory connector is tested beyond local file memory.
- At least one research connector is tested beyond in-process fixtures.
- The app can still run locally with graceful fallbacks when optional connectors are unavailable.

### Connector Targets

| Connector | Current state | Next proof | User setup needed | Done when |
| --- | --- | --- | --- | --- |
| LLM provider | Gemini and OpenAI adapters exist; Portfolio Agent currently defaults to Gemini | Run OpenAI live path once credentials are configured | Add provider API key/model to local ignored env file | A local command calls the model, returns structured output, and tests can mock the provider |
| MCP | Portfolio Agent calls OpenD, portfolio SQL, and finance metrics through MCP modules | Move from in-process module calls to official MCP transport/client when needed | None beyond venv, unless the official MCP SDK runtime is installed | Agent/tool code receives OpenD, SQL, and metric output through MCP rather than direct function calls |
| OpenD | Adapter works, recorded data exists | Add explicit live mode to full review and chat server | OpenD open, logged in, API port configured in `config/local.env` | Full review can run from live OpenD with no recorded report input |
| SQL | Local SQLite connected | Keep SQLite as working local store; design adapter seam for future proprietary SQL | Provide proprietary SQL connection details later, not required for spike | Snapshot, metrics, and audit summary are stored through a storage interface |
| Memory | Local JSON file only | Add one Pinecone health/upsert/query spike, or clearly choose local vector fallback if Pinecone is deferred | Pinecone API key, index name, and environment/project config if using Pinecone | A non-sensitive memory record can be written and retrieved through the memory interface |
| Research graph | In-process local fixtures only | Add one Neo4j connection spike with a tiny company/document/claim graph | Neo4j URI, username, password, and database name | A test query can create/read a small graph fixture and return structured graph context |
| Vector retrieval | No embedding/vector connector | Add a minimal embedding/vector round trip, either Pinecone namespace or local vector store | Provider key if using hosted embeddings | A sample document chunk can be embedded/upserted/retrieved |

### Deferred Connector Work Plan

1. Connector configuration
   - Create a single ignored local connector env file or extend existing local env handling.
   - Document required variables without committing secrets.
   - Add a `scripts/check_connectors.py` health check that reports `available`, `missing_config`, or `failed`.

2. LLM spike
   - Status: Gemini adapter is implemented for portfolio-only evaluation.
   - Add OpenAI provider parity if needed after Gemini behavior is stable.
   - Keep structured output validation.
   - Keep deterministic tests using a fake LLM.

3. MCP agent binding
   - Status: Portfolio Agent uses OpenD, portfolio SQL, and finance metrics MCP modules.
   - Keep the local MCP server scripts for OpenD, portfolio SQL, and finance metrics.
   - Add official MCP client/host transport only after the in-process tool path is stable.
   - Keep direct Python tool calls available as fallback until the MCP client path is stable.
   - Confirm no trading tools are exposed through either direct modules or MCP.

4. Live OpenD path
   - Add explicit `--live` / `--recorded` modes to terminal and chat server scripts.
   - Refuse ambiguous mode selection.
   - Run live OpenD through the same normalization, SQL storage, metrics, audit, and report path.

5. Memory connector spike
   - Keep local file memory as fallback.
   - Add one remote memory connector proof if Pinecone credentials are available.
   - Store only non-sensitive test memories during the spike.
   - Confirm IPS/current portfolio/source data still outrank memory.

6. Research connector spike
   - Add one Neo4j graph connection proof with tiny synthetic data.
   - Do not migrate the whole local research store yet.
   - Confirm the Sentiment Agent can consume graph context from an interface rather than direct fixtures.

7. App-level validation
   - Run one local terminal review.
   - Run one local frontend review.
   - Record which connectors were live, which were mocked, and which fell back.
   - Save a redacted connector validation report under `docs/finance-ai/` or an ignored `reports/` path.

### Connector Spike Exit Criteria

- `check_connectors` shows clear status for LLM, MCP, OpenD, SQL, memory, research graph, and vector retrieval.
- One agent path uses a real LLM call and still validates structured output.
- One tool call crosses an MCP boundary.
- Live OpenD mode can run without relying on `reports/opend/field-report.json`.
- SQLite persistence remains working.
- At least one non-sensitive memory round trip is proven through the selected memory connector.
- At least one research graph round trip is proven through Neo4j or an explicitly chosen fallback.
- Tests still pass without requiring live external services.
- Secrets remain in ignored local env files only.

Live connector pytest coverage now exists under `tests/live/`. See [CONNECTOR_TESTS.md](CONNECTOR_TESTS.md).

### What The User Needs To Provide

- OpenD running locally, logged in, with API enabled and port known.
- `config/local.env` populated with the correct OpenD port, security firm, account selection, and trade environment.
- LLM provider API key.
- Pinecone credentials if Pinecone memory is part of the next spike.
- Neo4j connection details if Neo4j is part of the next spike.
- A decision on whether vector retrieval should use Pinecone, another hosted vector DB, or a local vector store for the spike.

### What The Code Should Avoid In This Iteration

- Do not rewrite the whole agent as LangGraph yet.
- Do not migrate all local research fixtures into Neo4j yet.
- Do not replace all direct tool calls with MCP until one agent path has a stable MCP client fallback.
- Do not build autonomous recommendations around the LLM.
- Do not add trading tools.
- Do not store raw portfolio values in remote memory/vector stores.

## Milestone 1: Static Agent Prototype

Goal: prove the orchestration and output contracts without real external integrations.

Use the project-local Python environment from [ENVIRONMENT.md](ENVIRONMENT.md) for all commands.

Work:

- Define Pydantic models for agent state, portfolio snapshots, sentiment packets, citations, guardrail results, and final reports.
- Build the Investment Agent LangGraph skeleton.
- Mock MCP tool responses.
- Mock Portfolio Agent and Sentiment Agent outputs.
- Print final structured reports to terminal.
- Validate final output schemas.
- Create guardrail node with no-trading and citation checks.

Exit criteria:

- A `review my portfolio` query runs end to end against mocked data.
- The Investment Agent calls mock Portfolio and Sentiment agents.
- The final output contains portfolio analysis, research context, missing data, and source references.
- The guardrail node can block or revise unsafe outputs.

## Milestone 2: OpenD Exploration and Read-Only Portfolio Pipeline

Goal: understand MooMoo/OpenD data availability before designing the final SQL schema.

OpenD must be manually opened and logged in by the user before live connection or field exploration commands can succeed. Run scripts with `.venv/bin/python`.

Work:

- Implement `moomail-opend-mcp` connection checks.
- Inspect account, position, balance, cash, quote, transaction, and order-history fields available through OpenD.
- Confirm US equity symbol formats, account identifiers, quote timestamps, and currency fields.
- Build read-only current portfolio retrieval.
- Add freshness metadata and warnings.
- Normalize OpenD outputs into internal structured models.
- Add integration tests with recorded or mocked OpenD responses.

Exit criteria:

- Current holdings, cash, and quotes can be retrieved through `moomail-opend-mcp`.
- OpenD field availability is documented.
- The Portfolio Agent can analyze current portfolio state from live OpenD data.
- No trading capability exists anywhere in the MCP server.

## Milestone 3: Portfolio History and Metrics

Goal: persist portfolio history and calculate deterministic metrics.

Work:

- Design SQL schema based on OpenD exploration.
- Implement `moomail-portfolio-sql-mcp`.
- Store on-demand portfolio snapshots when a review runs.
- Store captured quotes used during runs.
- Store calculated metrics with version metadata.
- Store audit records and simple output summaries.
- Implement `moomail-finance-metrics-mcp` with tested Python calculations.
- Add benchmark comparison, defaulting to `SPY` or `VTI`.

Exit criteria:

- A portfolio review can use live OpenD data and persisted SQL snapshots.
- Metrics are deterministic, tested, and versioned.
- The system detects missing or stale portfolio history.
- SQL stores run metadata and concise summaries, not hidden reasoning or full final responses.

## Milestone 4: Research GraphRAG and Sentiment Agent

Goal: retrieve curated source-backed research for held portfolio stocks.

Work:

- Define document metadata requirements.
- Build manual ingestion for filings, earnings transcripts, shareholder letters, annual reports, quarterly reports, and curated research.
- Store graph entities and relationships in Neo4j.
- Store semantic chunks in a vector store.
- Implement `research-rag-mcp`.
- Build Sentiment Agent retrieval and synthesis.
- Require contradictory evidence search for major thesis claims.
- Return chunk-level citations with parent document metadata.

Exit criteria:

- For a held ticker, Sentiment Agent returns thesis, developments, risks, catalysts, contradictions, stance, citations, and missing research.
- Empty retrieval produces an explicit warning instead of invented analysis.
- Source quality is ranked and visible in structured output.

## Milestone 5: Full Investment Agent With Memory and Guardrails

Goal: combine portfolio diagnostics, research retrieval, long-term memory, and policy checks into a complete portfolio review.

Work:

- Implement `memory-mcp` backed by Pinecone.
- Store and retrieve allowed memory types.
- Add IPS loading from local canonical config.
- Enforce IPS precedence over memory.
- Add memory write proposals for preference and thesis changes.
- Add routine agent-generated review summaries where appropriate.
- Finalize guardrail node.
- Store guardrail failures in audit logs.
- Produce terminal-rendered final reports for review.

Exit criteria:

- `review my portfolio` runs end to end with live OpenD data, SQL history, curated RAG documents, deterministic metrics, memory retrieval, guardrail review, citations, and saved audit summaries.
- No trading tools or executable order paths exist.
- Missing critical data blocks recommendations when necessary.
- Non-critical missing data appears in a clear missing-data section.

## Milestone 6: TypeScript Chat Frontend

Goal: build the user interface only after backend formats and requirements are stable.

Work:

- Build chat interface.
- Render structured report panels from backend JSON.
- Stream operational status events.
- Add citation drawer.
- Add technical trace drawer.
- Add saved report browsing.
- Design future markdown/PDF export.

Exit criteria:

- The UI can run the same portfolio review workflow as the terminal flow.
- The UI shows what the agent is doing in real time without exposing hidden reasoning.
- Citations open source snippets or document metadata.

## Suggested Build Order From Here

1. Finalize live OpenD Portfolio Agent V1.
2. Freeze the terminal and frontend output contract.
3. Add the recorded OpenD fixture covering OTC quote failure and cash-sweep handling.
4. Run terminal and web reviews against the same live account data.
5. Harden frontend warning/failure rendering without changing the backend contract.
6. Add the V1 release gate commands to the runbook.
7. Resume deferred connectors one at a time: OTC quote fallback, crypto context,
   Pinecone memory, Neo4j research GraphRAG, then official MCP SDK transport if
   it still improves the architecture.
