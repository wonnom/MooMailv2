# OpenD Field Summary

Generated from live OpenD connections on 2026-05-23 and updated after the
2026-05-30 live OpenD normalization checks.

Raw field exploration output is saved locally to:

```text
reports/opend/field-report.json
```

That file is ignored by git because it may contain account identifiers, holdings, balances, or quotes. It is also the temporary local API fixture for offline development.

Normalized portfolio packet output is saved locally to:

```text
reports/opend/portfolio-packet.json
```

That file is also ignored by git.

## Connection

- Host: `127.0.0.1`
- Port: `11111`
- Status: connected
- Gateway: local OpenD
- Security firm: `FUTUSG`
- Trade environment: `REAL`

## Current Findings

### `accounts`

Rows returned: 4

Fields returned:

- `acc_id`
- `acc_status`
- `acc_type`
- `card_num`
- `security_firm`
- `sim_acc_type`
- `trd_env`
- `trdmarket_auth`
- `uni_card_num`

The returned accounts include the active real account plus simulated accounts. Account identifiers and card identifiers are intentionally not copied into this tracked document.

### `funds`

Rows returned: 1

Fields returned:

- `au_avl_withdrawal_cash`
- `au_cash`
- `aud_assets`
- `aud_net_cash_power`
- `available_funds`
- `avl_withdrawal_cash`
- `beginning_dtbp`
- `bond_assets`
- `cash`
- `cn_avl_withdrawal_cash`
- `cn_cash`
- `cnh_assets`
- `cnh_net_cash_power`
- `currency`
- `dt_call_amount`
- `dt_status`
- `frozen_cash`
- `fund_assets`
- `hk_avl_withdrawal_cash`
- `hk_cash`
- `hkd_assets`
- `hkd_net_cash_power`
- `initial_margin`
- `interest_charged_amount`
- `is_pdt`
- `jp_avl_withdrawal_cash`
- `jp_cash`
- `jpy_assets`
- `jpy_net_cash_power`
- `long_mv`
- `maintenance_margin`
- `margin_call_margin`
- `market_val`
- `max_power_short`
- `max_withdrawal`
- `net_cash_power`
- `pdt_seq`
- `pending_asset`
- `power`
- `realized_pl`
- `remaining_dtbp`
- `risk_level`
- `risk_status`
- `securities_assets`
- `sg_avl_withdrawal_cash`
- `sg_cash`
- `sgd_assets`
- `sgd_net_cash_power`
- `short_mv`
- `total_assets`
- `unrealized_pl`
- `us_avl_withdrawal_cash`
- `us_cash`
- `usd_assets`
- `usd_net_cash_power`

### `positions`

Rows returned: 15

Fields returned:

- `average_cost`
- `can_sell_qty`
- `code`
- `cost_price`
- `cost_price_valid`
- `currency`
- `diluted_cost`
- `market_val`
- `nominal_price`
- `pl_ratio`
- `pl_ratio_avg_cost`
- `pl_ratio_valid`
- `pl_val`
- `pl_val_valid`
- `position_market`
- `position_side`
- `qty`
- `realized_pl`
- `stock_name`
- `today_buy_qty`
- `today_buy_val`
- `today_pl_val`
- `today_sell_qty`
- `today_sell_val`
- `today_trd_val`
- `unrealized_pl`

### `quotes`

Rows returned: 14

Fields returned: 142 fields, including:

- `code`
- `name`
- `update_time`
- `last_price`
- `open_price`
- `high_price`
- `low_price`
- `prev_close_price`
- `volume`
- `turnover`
- `ask_price`
- `bid_price`
- `sec_status`
- `equity_valid`
- `option_valid`
- `pe_ratio`
- `pe_ttm_ratio`
- `pb_ratio`
- `dividend_ttm`
- `dividend_ratio_ttm`
- `total_market_val`
- `net_asset`
- `net_profit`
- `earning_per_share`
- `highest52weeks_price`
- `lowest52weeks_price`
- `pre_price`
- `after_price`
- `overnight_price`

Warnings:

```text
One OTC holding was not supported by the OpenD market snapshot API. The adapter now retries quotes per symbol, so supported quote rows are retained and unsupported symbols are recorded as warnings.
```

## Interpretation

The OpenD gateway is reachable and the `FUTUSG` configuration exposes the real account, funds, positions, and most quote snapshots.

The current portfolio includes data types that matter for schema design:

- US-listed equities
- At least one OTC holding where OpenD quote snapshots may fail
- Options positions
- Margin account fields
- Negative cash / financing fields
- Realized and unrealized P&L fields
- Per-currency cash and asset fields
- Account-level `fund_assets`, which may represent a cash sweep in this user's
  setup but is not universally safe to classify as cash

Likely next checks:

- Set `MOOMAIL_MOOMOO_ACCOUNT_ID` in `config/local.env` to the active real account id if multiple accounts cause ambiguity.
- Enable `MOOMAIL_MOOMOO_TREAT_FUND_ASSETS_AS_CASH_SWEEP=true` only if
  `fund_assets` represents the automatic MooMoo money-market cash sweep.
- Decide whether OTC holdings should use a fallback quote provider in a later milestone.
- Explore `OpenCryptoTradeContext` separately for crypto holdings under the
  same account number.
- Preserve option-position fields even if the first Investment Agent scope emphasizes equities.
- Preserve margin and negative-cash fields in the eventual SQL schema.

## Next Field Report Target

The next successful portfolio packet should include:

- Normalized `PortfolioSnapshot`
- Normalized `PortfolioAgentPacket`
- Redacted terminal summary
- Optional ignored full JSON output for local inspection

Status: complete from recorded mode.

Recorded command:

```bash
.venv/bin/python scripts/opend_portfolio_snapshot.py \
  --from-report reports/opend/field-report.json \
  --output reports/opend/portfolio-packet.json
```

Recorded output summary:

- Holdings: 15 in the first recorded report; 16 in the later live summary
- Cash balances: base cash, plus an optional cash-sweep row when enabled
- Candidate issues: 2
- Missing fields: `quotes_for_all_positions`
- Warning: one OTC quote was unsupported by OpenD market snapshots

Live summary after OpenD was fixed:

```text
holdings_count: 16
cash_balances_count: 2 when cash-sweep treatment is enabled
missing_fields: quotes_for_all_positions
warning: US.TCEHY quote query failed because OpenD does not support OTC market data for TCEHY
```
