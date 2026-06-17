# Bitget Exchange Adapter Specification v1.0 - Frozen

Status: frozen after audit and ambiguity review.

The Bitget Exchange Adapter connects ArjioBot to Bitget USDT-M Futures through
a safety-first adapter boundary. v1 supports mock execution and read-only
account/market access contracts only. Live trading is never enabled by default.

## Purpose

The adapter consumes approved execution instructions, Risk Engine trade plan
data, API credential records, and account selection settings.

It produces:

- Exchange account snapshots
- Balance records
- Position records
- Market metadata
- Normalized order result records
- Exchange order status
- Normalized exchange error records

## Audit Findings And Amendments

- Default mode is `MOCK`.
- Supported modes are `MOCK`, `READ_ONLY`, `PAPER`, `LIVE_DISABLED`, and
  `LIVE_ENABLED`.
- v1 implements an in-memory credential store with an encryption-ready cipher
  interface.
- Persistent secrets must never be stored in plain text. v1 stores encrypted or
  encoded secret values only.
- Safe account records mask API keys and never expose API secret or passphrase.
- Read-only mode rejects all trading operations.
- Live-disabled mode rejects all trading operations.
- Live-enabled mode still requires account trading enabled, credential
  verification passed, an approved execution instruction, and an approved risk
  trade plan.
- The v1 Bitget client wrapper does not make network calls and does not place
  real orders.
- Withdrawal permissions are not supported.
- USDT-M perpetual futures are the target market type.

## Account Contract

Credential records store:

- `account_id`
- `account_name`
- `exchange`
- `api_key`
- `api_secret_encrypted`
- `passphrase_encrypted`
- `permissions`
- `is_active`
- `is_default`
- `trading_enabled`
- `created_at`
- `updated_at`
- `last_verified_at`
- `verification_status`

## Service API

Expose service-ready backend methods for future frontend use:

- `create_exchange_account(credentials)`
- `update_exchange_account(account_id, credentials)`
- `delete_exchange_account(account_id)`
- `set_default_exchange_account(account_id)`
- `enable_trading(account_id)`
- `disable_trading(account_id)`
- `test_connection(account_id)`
- `get_account_balance(account_id)`
- `get_account_positions(account_id)`
- `list_exchange_accounts()`

## Adapter Operations

Read-only operations:

- `fetch_balance(account_id)`
- `fetch_positions(account_id)`
- `fetch_open_orders(account_id)`
- `fetch_order_status(account_id, order_id)`
- `fetch_market_info(symbol)`
- `fetch_ohlcv(symbol, timeframe, limit)`

Trading interface methods:

- `set_leverage(account_id, symbol, leverage)`
- `place_market_order(...)`
- `place_stop_loss_order(...)`
- `place_take_profit_order(...)`
- `cancel_order(account_id, symbol, order_id)`
- `cancel_all_symbol_orders(account_id, symbol)`

## Error Codes

Supported normalized errors:

- `AUTHENTICATION_FAILED`
- `INVALID_CREDENTIALS`
- `PERMISSION_DENIED`
- `INSUFFICIENT_BALANCE`
- `SYMBOL_NOT_SUPPORTED`
- `RATE_LIMITED`
- `NETWORK_ERROR`
- `ORDER_REJECTED`
- `LIVE_TRADING_DISABLED`
- `TRADING_NOT_ALLOWED_IN_READ_ONLY_MODE`
- `UNKNOWN_EXCHANGE_ERROR`

## Known Limitations

- v1 does not make real Bitget network requests.
- v1 does not place live orders.
- v1 uses in-memory credential storage only.
- v1 credential cipher is replaceable and intended for future production
  encryption integration.
- Dashboard/API routes are not implemented in this module.

## Final Validation Report

Execution date: 2026-06-06

- Tests executed: 21
- Tests passed: 21
- Mock mode validation: PASS
- Read-only safety validation: PASS
- Multi-account validation: PASS
- Credential safety validation: PASS
- Live trading safeguard validation: PASS
- HTML report: `backend/arjiobot/exchange/reports/exchange_adapter_validation_report.html`
- PNG report: `backend/arjiobot/exchange/reports/exchange_adapter_validation_report.png`

Validation confirms:

- Default adapter mode is `MOCK`.
- Mock mode returns deterministic fake balances, positions, market info, OHLCV candles, order IDs, and order results.
- Read-only mode permits safe reads and rejects trading operations with `TRADING_NOT_ALLOWED_IN_READ_ONLY_MODE`.
- Live-disabled mode rejects trading operations with `LIVE_TRADING_DISABLED`.
- Live-enabled mode requires account trading enabled, verified credentials, an approved execution instruction, and an approved risk trade plan.
- API secret and passphrase values are stored through the credential cipher interface and are not exposed in safe account records.
- API keys are masked for display.
- Multiple Bitget accounts can be created, updated, deleted, selected as default, verified, and toggled for trading permission.
- Rate-limit behavior is enforced per account and testable without Bitget calls.
- No Dashboard, frontend UI, API routes, live Bitget order placement, or API key storage service was implemented.

Ready For Integration: YES
