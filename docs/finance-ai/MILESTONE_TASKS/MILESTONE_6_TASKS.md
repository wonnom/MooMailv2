# Milestone 6 Task Map

Milestone 6 goal: provide a TypeScript chat frontend over the local full Investment Agent workflow.

## Scope

The frontend is local and dependency-light:

- Python stdlib HTTP server.
- Static HTML/CSS.
- TypeScript source checked in under `web/static/app.ts`.
- Browser-ready JavaScript checked in under `web/static/app.js` because npm/TypeScript tooling is not required for tests.
- Streaming status uses a newline-delimited event stream over `fetch`.
- Stream failures are returned as structured `error` payloads and rendered in
  the chat rail plus technical trace instead of requiring terminal inspection.
- Chat-style input uses a bottom composer with a Send button.
- The chat rail can be resized or hidden for full report inspection.
- Portfolio snapshot rendering shows all returned holdings and cash lines.
- Allocation rendering supports sortable bars and a pie-chart view.

## Exit Criteria

1. The UI can run the same portfolio review workflow as the terminal flow.
2. The UI shows what the agent is doing in real time without exposing hidden reasoning.
3. Citations open source snippets or document metadata.

## Dependency Graph

```text
A. FullInvestmentAgent from Milestone 5
   ├── B. HTTP API server
   │   ├── C. POST /api/chat full JSON endpoint
   │   └── D. POST /api/chat/stream newline-delimited event stream
   ├── E. Static frontend shell
   │   ├── F. TypeScript client source
   │   ├── G. Browser JS companion
   │   ├── H. Structured report panels
   │   └── I. Citation drawer/details
   └── J. Tests and browser verification
```

## Task Breakdown by Exit Criteria

### EC1: UI runs the same workflow as terminal

| Task | Description | Depends on | Status |
| --- | --- | --- | --- |
| A | Full Investment Agent available | Milestone 5 | Done |
| B | Add local HTTP server | A | Done |
| C | Add `/api/chat` endpoint | B | Done |
| E | Add static frontend | B | Done |
| H | Render report panels from backend JSON | E | Done |
| H1 | Add chat-style Send composer | E | Done |
| H2 | Add resizable and hideable chat rail | E | Done |
| H3 | Add holdings/cash table and sortable allocation views | E | Done |
| J | Add API/frontend static tests | B, E | Done |

### EC2: UI shows real-time status without hidden reasoning

| Task | Description | Depends on | Status |
| --- | --- | --- | --- |
| D | Add streaming status endpoint | B | Done |
| F/G | Add streaming client | D | Done |
| J | Test stream emits status and final events | D | Done |
| D1 | Add structured stream error payloads | D | Done |
| F1 | Render backend errors in chat and trace panel | D1, F/G | Done |
| J1 | Test stream error and frontend error contract | D1, F1 | Done |

### EC3: Citations open source snippets or metadata

| Task | Description | Depends on | Status |
| --- | --- | --- | --- |
| I | Add citation details panel | H | Done |
| J | Add static frontend test for citation controls | I | Done |

## Commands

Start the local app:

```bash
.venv/bin/python scripts/serve_chat.py --host 127.0.0.1 --port 8787
```

Then open:

```text
http://127.0.0.1:8787
```

## Verification

Run:

```bash
.venv/bin/python -m pytest
```

Latest focused tests:

```text
tests/test_chat_app.py ....... 7 passed
```

Latest full suite:

```text
77 passed, 10 skipped
```

Local server check:

```bash
curl -sS -X POST http://127.0.0.1:8787/api/chat/stream \
  -H 'Content-Type: application/json' \
  -d '{"query":"Review my portfolio"}'
```

Latest streamed API summary:

- Status events emitted
- Final event emitted
- Error event emitted on backend failure and rendered in the trace panel
- Final report included citations
- Guardrails passed
