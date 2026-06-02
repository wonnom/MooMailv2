# Milestone 2 Task Map

Milestone 2 goal: understand MooMoo/OpenD data availability and build a read-only current portfolio pipeline before final SQL schema design.

Run Milestone 2 commands with the project venv:

```bash
.venv/bin/python scripts/check_opend.py --env-file config/local.env
.venv/bin/python scripts/explore_opend_fields.py --env-file config/local.env --output reports/opend/field-report.json
```

Official docs used for this milestone:

- OpenD quote connection uses `OpenQuoteContext(host='127.0.0.1', port=11111, is_encrypt=None)`.
- Optional encryption uses an RSA private key configured through the SDK and OpenD.
- Trading/account context exposes read-only account, funds, and position queries.
- Market snapshots are retrieved through `get_market_snapshot(code_list)`.

## Exit Criteria

1. Current holdings, cash, and quotes can be retrieved through `moomail-opend-mcp` or its local adapter scaffold.
2. OpenD field availability is documented.
3. The Portfolio Agent can analyze current portfolio state from live OpenD data.
4. No trading capability exists anywhere in the MCP server or adapter.

## Dependency Graph

```text
A. OpenD connection research
   ├── B. OpenD config contract and env example
   │   ├── C. Read-only OpenD adapter interface
   │   │   ├── D. Connection check script
   │   │   ├── E. Field exploration script
   │   │   └── F. Live account/position/quote retrieval
   │   │       ├── G. Normalize OpenD records into internal schemas
   │   │       │   └── H. Portfolio Agent OpenD mode
   │   │       └── I. Recorded/mocked integration tests
   │   └── J. Secret/config documentation
   ├── K. Capability denylist / no-trading review
   │   └── L. Tests proving no trade methods are exposed
   └── M. Field availability report template
       └── N. Fill report from real OpenD run
           └── O. SQL schema design in Milestone 3
```

## Task Breakdown by Exit Criteria

### EC1: Current holdings, cash, and quotes retrievable

| Task | Description | Depends on | Status |
| --- | --- | --- | --- |
| A | Verify official OpenD connection/auth requirements | None | Done |
| B | Add OpenD config model and env example | A | Done |
| C | Add read-only adapter interface | B | Done |
| D | Add connection check script | C | Done |
| F | Implement account, funds, positions, and quote calls | C | Done |
| G | Normalize records into internal schemas | F | Done |
| I | Add mocked adapter tests | C, F | Done |

### EC2: OpenD field availability documented

| Task | Description | Depends on | Status |
| --- | --- | --- | --- |
| M | Add field report model/template | B | Done |
| E | Add field exploration script | C, M | Done |
| N | Run against real OpenD and save report | E, real OpenD access | Done |
| O | Use report to design SQL schema | N | Deferred to Milestone 3 |

### EC3: Portfolio Agent analyzes live OpenD data

| Task | Description | Depends on | Status |
| --- | --- | --- | --- |
| G | Normalize OpenD records into portfolio snapshot schema | F | Done |
| H | Add Portfolio Agent mode using live OpenD packet | G | Done, live export not run |
| I | Add recorded/mocked integration tests | H | Done |

### EC4: No trading capability exists

| Task | Description | Depends on | Status |
| --- | --- | --- | --- |
| K | Keep adapter method surface read-only | C | Done |
| L | Add tests proving no order/trade mutation methods exist | K | Done |

## Free Tasks Started First

These tasks were free of live OpenD dependencies and are safe to implement immediately:

- A: Official OpenD connection research
- B: OpenD config model and env example
- C: Read-only adapter interface
- D: Connection check script
- E: Field exploration script
- I: Mocked adapter tests
- J: Secret/config documentation
- K/L: No-trading surface tests
- M: Field report model/template

## Local Setup Summary

OpenD does not use a normal REST API key in this design. The local process connects to the OpenD gateway by host and port. Account access depends on the local OpenD session being logged in and authorized.

Use [config/example.env](../../../config/example.env) as the template for local settings. Create your own ignored file:

```bash
cp config/example.env config/local.env
```

Do not commit the local file.

Important fields:

- `MOOMAIL_OPEND_HOST`: default `127.0.0.1`
- `MOOMAIL_OPEND_PORT`: default `11111`
- `MOOMAIL_OPEND_CONNECTION_TIMEOUT_SECONDS`: default `2.0`
- `MOOMAIL_OPEND_IS_ENCRYPT`: `auto`, `true`, or `false`
- `MOOMAIL_OPEND_RSA_PRIVATE_KEY_PATH`: optional RSA private key path if OpenD encryption is configured
- `MOOMAIL_PROTOBUF_IMPLEMENTATION`: default `python`, used for local `moomoo-api` / `protobuf` compatibility
- `MOOMAIL_MOOMOO_SECURITY_FIRM`: default `FUTUINC`
- `MOOMAIL_MOOMOO_TRADE_MARKET`: default `US`
- `MOOMAIL_MOOMOO_TRADE_ENV`: default `REAL`
- `MOOMAIL_MOOMOO_ACCOUNT_ID`: optional real account id once discovered
- `MOOMAIL_MOOMOO_ACCOUNT_INDEX`: fallback account index, default `0`
- `MOOMAIL_MOOMOO_BASE_CURRENCY`: default `USD`
- `MOOMAIL_MOOMOO_TREAT_FUND_ASSETS_AS_CASH_SWEEP`: optional, default `false`

There is intentionally no trade unlock password setting in v1.

## Current Live OpenD Status

OpenD connection is working on `127.0.0.1:11111`.

The `FUTUSG` configuration exposes real account metadata, funds, positions, and quote snapshots. One OTC holding is returned by positions but is not supported by the OpenD market snapshot API, so the adapter retries quote requests per symbol and records unsupported quote symbols as warnings.

Use this read-only diagnostic when account lists work but funds or positions do
not:

```bash
.venv/bin/python scripts/debug_opend_trade_calls.py --env-file config/local.env
```

It probes `get_acc_list`, `accinfo_query`, and `position_list_query` separately
with cached/refresh variants. It never calls trade unlock or order APIs.

Use this as the V1 live health gate after OpenD is logged in:

```bash
.venv/bin/python scripts/opend_health_report.py \
  --env-file config/local.env \
  --expected-holdings-count <your-current-position-count> \
  --output reports/opend/health-report.json
```

The command reads only connection, accounts, funds, positions, and quotes, then
builds a normalized portfolio summary. Unsupported OTC quotes are warnings, not
failures, as long as the holding is still present in positions.

OpenD `fund_assets` is an account-level aggregate. It is treated as
auto-invested money-market fund assets/effective cash-equivalent purchasing
power only when explicitly enabled in local config.

See [OPEND_FIELD_SUMMARY.md](../OPEND_FIELD_SUMMARY.md) for the redacted field summary.

The ignored raw reports are:

```text
reports/opend/field-report.json
reports/opend/portfolio-packet.json
```

`portfolio-packet.json` is only created when the local normalized portfolio packet script is run.

## Recorded Mode

Use recorded mode for local development and tests that should not keep calling OpenD.

Capture once from live OpenD:

```bash
.venv/bin/python scripts/explore_opend_fields.py \
  --env-file config/local.env \
  --output reports/opend/field-report.json
```

Then build normalized portfolio packets from the saved report without touching OpenD:

```bash
.venv/bin/python scripts/opend_portfolio_snapshot.py \
  --from-report reports/opend/field-report.json \
  --output reports/opend/portfolio-packet.json
```

Run the same health gate against the saved report:

```bash
.venv/bin/python scripts/opend_health_report.py \
  --from-report reports/opend/field-report.json
```

This acts as a temporary local API response while the schema and Portfolio Agent normalization are still being designed.
