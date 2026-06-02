# Personal Finance AI Design

This folder describes the planned personal multi-agent finance AI, with v1 focused on the Investment Agent branch.

The system is designed for one user's portfolio first. It should analyze actual holdings, current market data, portfolio history, curated research, and long-term investment memory. It must produce source-backed portfolio reviews and investment reasoning without ever placing trades.

## Documents

- [AGENTS.md](AGENTS.md): agent hierarchy, responsibilities, boundaries, and agent-to-agent contracts.
- [ARCHITECTURE.md](ARCHITECTURE.md): system architecture, data stores, MCP servers, orchestration, and deployment shape.
- [ACTION_PLAN.md](ACTION_PLAN.md): implementation milestones and sequencing.
- [PROTOCOL.md](PROTOCOL.md): runtime protocol, state flow, structured events, schemas, and audit records.
- [REQUIREMENTS.md](REQUIREMENTS.md): product, engineering, security, data, and acceptance requirements.
- [ENVIRONMENT.md](ENVIRONMENT.md): project venv, dependency installation, and command conventions.
- [CONNECTOR_TESTS.md](CONNECTOR_TESTS.md): live connector test setup for LLM, MCP, OpenD, SQL, Pinecone, vector retrieval, and Neo4j.
- [MCP_SERVERS.md](MCP_SERVERS.md): local MCP server boundaries, tool/resource lists, agent allowlists, and run commands.
- [TESTING.md](TESTING.md): test responsibility map and why similarly named OpenD, SQL, and MCP tests are not redundant.
- [V1_FINALIZATION_PLAN.md](V1_FINALIZATION_PLAN.md): current first-version finish line, release gate, and v1.1 backlog.
- [MILESTONE_1_TASKS.md](MILESTONE_TASKS/MILESTONE_1_TASKS.md): static prototype task graph.
- [MILESTONE_2_TASKS.md](MILESTONE_TASKS/MILESTONE_2_TASKS.md): OpenD exploration and read-only portfolio pipeline task graph.
- [MILESTONE_3_TASKS.md](MILESTONE_TASKS/MILESTONE_3_TASKS.md): portfolio history and deterministic metrics task graph.
- [MILESTONE_4_TASKS.md](MILESTONE_TASKS/MILESTONE_4_TASKS.md): research retrieval and Sentiment Agent task graph.
- [MILESTONE_5_TASKS.md](MILESTONE_TASKS/MILESTONE_5_TASKS.md): full Investment Agent task graph.
- [MILESTONE_6_TASKS.md](MILESTONE_TASKS/MILESTONE_6_TASKS.md): chat frontend task graph.

## Scope

The target system centers on the Investment Agent branch:

- Investment Agent
- Portfolio Agent
- Sentiment Agent
- Read-only MooMoo/OpenD integration
- Deterministic finance metric tools
- Curated research retrieval through GraphRAG
- Pinecone-backed long-term investment memory
- Guardrail and audit protocol

The current first usable version is narrower: a live OpenD portfolio review
through the Portfolio Agent path, with SQLite persistence, deterministic
metrics, provider-backed portfolio evaluation, guardrails, and the local chat
frontend. Pinecone memory, Neo4j GraphRAG, crypto ingestion, and OTC quote
fallback are deferred until the portfolio output contract is stable.

The future Budgeting, Expenses, and Savings Agent is acknowledged as part of the long-term product, but it is not part of the v1 implementation.

## Architecture Diagram

### Agents
```mermaid
flowchart TD
  UI["Chat / CLI"] --> IA["Investment Agent"]

  IA --> PA["Portfolio Agent"]
  IA --> SA["Sentiment Agent"]
  IA --> MEM["Investment Memory"]

  PA --> OPEND["MCP: OpenD / MooMoo Read-Only"]
  PA --> SQL["MCP: Portfolio SQL History"]
  PA --> METRICS["MCP: Finance Metrics"]

  SA --> RAG["MCP: Research / GraphRAG"]
  SA --> METRICS

  IA --> GUARD["Mandatory Guardrails"]
```



## Core Decisions

- No trade placement, ever.
- Investment branch first; no main finance orchestrator needed in v1.
- Python agent layer using LangGraph and LangChain components.
- Local TypeScript/static chatbot frontend exists with streaming status, report panels, trace output, and a resizable/hideable chat rail.
- MCP servers are the boundary for broker access, portfolio data, metrics, research retrieval, and memory.
- MooMoo/OpenD is the read-only source for current portfolio data.
- OpenD exploration drives the SQL schema and portfolio normalization.
- OpenD unsupported OTC quote snapshots are warnings when positions are still available.
- Account-level `fund_assets` can be treated as effective cash-equivalent purchasing power only when explicitly enabled in local config.
- SQL stores lean portfolio history: daily value snapshots, compact position
  states, allocation weight snapshots, data-quality events, audit logs, and run
  summaries.
- SQL does not store broad raw OpenD blobs, full quote history, hidden
  reasoning, or full final responses in v1.
- Pinecone stores Investment Agent long-term memory, not source-of-truth financial records.
- Neo4j GraphRAG is separate from Pinecone memory.
- Sentiment retrieval starts with portfolio holdings only.
- Outputs must be source-backed, truthful, and clear about missing data.
- No confidence scores. Use explicit uncertainty and limitations instead.

## Local Python Environment

Use the project-local venv for all Python commands:

```bash
source .venv/bin/activate
```

Or call it directly:

```bash
.venv/bin/python -m pytest
.venv/bin/python scripts/run_prototype.py "Review my portfolio"
.venv/bin/python scripts/check_opend.py --env-file config/local.env
.venv/bin/python scripts/debug_opend_trade_calls.py --env-file config/local.env
.venv/bin/python scripts/opend_health_report.py --env-file config/local.env --expected-holdings-count <N>
```

See [ENVIRONMENT.md](ENVIRONMENT.md) for the full setup and verification workflow.
