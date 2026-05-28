# Milestone 3 Task Map

Milestone 3 goal: persist portfolio history and calculate deterministic metrics.

## Scope Clarification

The SQL store preserves the full OpenD snapshot because accounting needs the whole account view. V1 analysis metrics default to the `v1_us_equities` scope, so non-US-equity assets such as Bitcoin exposure, money funds, options, margin/cash mechanics, and unsupported quote rows are stored but not treated as v1 equity-analysis problems by default.

## Exit Criteria

1. A portfolio review can use OpenD data and persisted SQL snapshots.
2. Metrics are deterministic, tested, and versioned.
3. The system detects missing or stale portfolio history.
4. SQL stores run metadata and concise summaries, not hidden reasoning or full final responses.

## Dependency Graph

```text
A. OpenD field report from Milestone 2
   ├── B. SQL schema design
   │   ├── C. SQLite portfolio store
   │   │   ├── D. Store normalized portfolio snapshots
   │   │   ├── E. Store raw quote rows used during runs
   │   │   ├── F. Store calculated metric records
   │   │   └── G. Store audit/run summaries
   │   └── H. History freshness/status queries
   ├── I. Deterministic metric contracts
   │   ├── J. Cash, allocation, concentration, and benchmark-reference metrics
   │   ├── K. Metric versioning
   │   └── L. Unit tests with known inputs
   └── M. Recorded OpenD workflow
       ├── N. Build normalized packet from recorded report
       ├── O. Persist packet to SQL
       ├── P. Calculate metrics and persist them
       └── Q. Emit terminal summary for inspection
```

## Task Breakdown by Exit Criteria

### EC1: Portfolio review can use OpenD data and persisted SQL snapshots

| Task | Description | Depends on | Status |
| --- | --- | --- | --- |
| A | Use recorded OpenD field report from Milestone 2 | None | Done |
| B | Design SQLite schema based on OpenD fields | A | Done |
| C | Implement `PortfolioSqlStore` | B | Done |
| D | Store normalized portfolio snapshots | C | Done |
| E | Store raw quote rows used during runs | C | Done |
| N | Build normalized packet from recorded report | A | Done |
| O | Persist recorded packet to SQLite | C, N | Done |

### EC2: Metrics are deterministic, tested, and versioned

| Task | Description | Depends on | Status |
| --- | --- | --- | --- |
| I | Define deterministic metric result contract | None | Done |
| J | Implement v1 US-equity metric calculations | I | Done |
| K | Add metric version metadata | I | Done |
| L | Add unit tests with known inputs | J, K | Done |
| P | Persist calculated metrics to SQL | C, J | Done |

### EC3: Missing or stale portfolio history is detected

| Task | Description | Depends on | Status |
| --- | --- | --- | --- |
| H | Add history status query | C | Done |
| H1 | Detect empty history | H | Done |
| H2 | Detect stale latest snapshot | H | Done |
| H3 | Detect insufficient historical depth | H | Done |

### EC4: SQL stores metadata and concise summaries only

| Task | Description | Depends on | Status |
| --- | --- | --- | --- |
| G | Store agent run metadata and output summary | C | Done |
| G1 | Store tool calls, source ids, assumptions, and guardrail JSON | G | Done |
| G2 | Do not store hidden reasoning or full final responses | G | Done |
| G3 | Add tests for audit storage shape | G | Done |

## Commands

Use recorded mode to avoid repeated OpenD calls:

```bash
.venv/bin/python scripts/portfolio_history_demo.py \
  --from-report reports/opend/field-report.json \
  --db data/portfolio-history.sqlite \
  --output reports/opend/history-summary.json
```

The SQLite database and generated reports are ignored by git.

## Current Status

Milestone 3 is implemented as a local SQLite-backed prototype, now exposed through `moomail-portfolio-sql-mcp` and `moomail-finance-metrics-mcp`.

Latest recorded run:

- Database: `data/portfolio-history.sqlite`
- Summary report: `reports/opend/history-summary.json`
- Portfolio snapshots: 1
- Cash balances: 1
- Position snapshots: 15
- Quote snapshots: 14
- Calculated metrics: 5
- Agent run summaries: 1
- History status: fresh but missing `historical_depth`

The audit table stores concise metadata and `output_summary`; it does not include hidden reasoning or a full final response column.

## Verification

Run:

```bash
.venv/bin/python -m pytest
```

Latest result:

```text
53 passed, 4 skipped
```
