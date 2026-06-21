# Python Environment

Use the project-local virtual environment for all Python commands. This avoids the interpreter mismatch where `pip install` succeeds in one Python installation but scripts run with another.

## Created Environment

The local environment is:

```text
.venv/
```

It was created with:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev,opend]'
```

Installed project extras:

- `dev`: pytest and test tooling
- `opend`: MooMoo OpenAPI SDK and its dependencies

The official MCP SDK is a normal project dependency as of V3.1. The local MCP
server scripts run through FastMCP over stdio. V3.2/V3.3 add a backend MCP
gateway and deterministic dashboard APIs to the local chat server.

## Recommended Command Style

Either activate the environment:

```bash
source .venv/bin/activate
```

Then run:

```bash
python -m pytest
python scripts/run_prototype.py "Review my portfolio"
python scripts/check_opend.py --env-file config/local.env
python scripts/explore_opend_fields.py --env-file config/local.env --output reports/opend/field-report.json
python scripts/portfolio_agent_review.py --env-file config/local.env --llm-provider gemini
python scripts/serve_chat.py --env-file config/local.env --default-agent portfolio
```

Or call the venv interpreter directly:

```bash
.venv/bin/python -m pytest
.venv/bin/python scripts/run_prototype.py "Review my portfolio"
.venv/bin/python scripts/check_opend.py --env-file config/local.env
.venv/bin/python scripts/explore_opend_fields.py --env-file config/local.env --output reports/opend/field-report.json
.venv/bin/python scripts/portfolio_agent_review.py --env-file config/local.env --llm-provider gemini
.venv/bin/python scripts/serve_chat.py --env-file config/local.env --default-agent portfolio
```

The second style is more explicit and avoids accidental shell interpreter drift.

## Verify Interpreter

Use these commands if imports behave strangely:

```bash
.venv/bin/python -c 'import sys; print(sys.executable)'
.venv/bin/python -c 'import pydantic; print(pydantic.__version__); print(pydantic.__file__)'
.venv/bin/python -c 'import pytest; print(pytest.__version__)'
```

Expected interpreter:

```text
/Users/weesi/Documents/MooMailV2/.venv/bin/python
```

Pydantic should resolve inside:

```text
/Users/weesi/Documents/MooMailV2/.venv/lib/python3.12/site-packages/pydantic
```

## OpenD Notes

OpenD must be manually opened and logged in before live checks can succeed.

The venv includes `moomoo-api`, but the SDK connects through the local OpenD gateway. It does not use a normal REST API key.

Create local config:

```bash
cp config/example.env config/local.env
```

Then edit:

```env
MOOMAIL_OPEND_HOST=127.0.0.1
MOOMAIL_OPEND_PORT=11111
```

Use the API port configured in OpenD.

For FUTUSG securities accounts, the local env usually needs:

```env
MOOMAIL_MOOMOO_SECURITY_FIRM=FUTUSG
MOOMAIL_MOOMOO_TRADE_ENV=REAL
MOOMAIL_MOOMOO_TRADE_MARKET=US
MOOMAIL_MOOMOO_BASE_CURRENCY=USD
```

If your MooMoo cash is automatically invested into a USD money-market fund and
OpenD exposes that amount only through account-level `fund_assets`, enable:

```env
MOOMAIL_MOOMOO_TREAT_FUND_ASSETS_AS_CASH_SWEEP=true
```

This is disabled by default because `fund_assets` can also represent ordinary
fund exposure in other accounts. When enabled, the agent treats it as
cash-equivalent purchasing power that can be auto-redeemed/auto-invested, not as
idle cash.

Optional RSA configuration goes here only if OpenD encryption is configured:

```env
MOOMAIL_OPEND_RSA_PRIVATE_KEY_PATH=/path/to/conn_key.txt
```

There is intentionally no trade unlock password setting.

Diagnose account funds and positions:

```bash
.venv/bin/python scripts/debug_opend_trade_calls.py --env-file config/local.env
```

Run the full read-only OpenD health gate:

```bash
.venv/bin/python scripts/opend_health_report.py \
  --env-file config/local.env \
  --expected-holdings-count <your-current-position-count> \
  --output reports/opend/health-report.json
```

The health report checks connection, account list, funds, positions, quote
snapshots, and the normalized portfolio summary. It exits `1` only on `fail`.
Unsupported OTC quote rows and other partial quote gaps are `warn` when the
position rows still normalize. Use recorded mode when you want the same report
without calling OpenD:

```bash
.venv/bin/python scripts/opend_health_report.py \
  --from-report reports/opend/field-report.json
```

## Portfolio History DB

The canonical local portfolio-history database is:

```text
data/portfolio-history.sqlite
```

Terminal reviews, `scripts/serve_chat.py`, and `scripts/mcp_portfolio_sql_server.py`
use this same DB by default. Pass `--db <temporary-path>` only for isolated tests
or demos.

When `scripts/serve_chat.py` is running, the deterministic portfolio dashboard
lane is available at:

```text
GET  /api/portfolio/status
GET  /api/portfolio/dashboard
POST /api/portfolio/refresh
```

These endpoints use backend MCP gateway calls and do not start agent runs.

## Portfolio Agent LLM

The Portfolio Agent LLM evaluator is provider-neutral. The current default is
Gemini, but OpenAI can be selected through env or CLI.

Gemini:

```env
MOOMAIL_PORTFOLIO_AGENT_LLM_PROVIDER=gemini
MOOMAIL_GEMINI_API_KEY=...
MOOMAIL_GEMINI_MODEL=...
```

OpenAI:

```env
MOOMAIL_PORTFOLIO_AGENT_LLM_PROVIDER=openai
MOOMAIL_OPENAI_API_KEY=...
MOOMAIL_OPENAI_MODEL=...
```

CLI override:

```bash
.venv/bin/python scripts/portfolio_agent_review.py --llm-provider openai
```

## Updating Packages

When dependencies change:

```bash
.venv/bin/python -m pip install -e '.[dev,opend]'
```

Do not use plain `pip install` unless the venv is activated. Prefer:

```bash
.venv/bin/python -m pip install package-name
```

## Live Connector Tests

Live connector tests are opt-in and are skipped during normal test runs.

```bash
MOOMAIL_RUN_LIVE_CONNECTOR_TESTS=1 .venv/bin/python -m pytest tests/live -q
```

See [CONNECTOR_TESTS.md](CONNECTOR_TESTS.md) for required environment variables and one-connector-at-a-time commands.
