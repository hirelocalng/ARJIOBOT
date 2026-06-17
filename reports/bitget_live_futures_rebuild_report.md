# Bitget Live Futures Rebuild Report

## Scope

Rebuilt the exchange connection and execution boundary for Bitget live futures only.

Frozen strategy profiles and swing/FVG/retrace/entry logic were not changed.

## Files Changed

- `backend/arjiobot/exchange/bitget_environment.py`
- `backend/arjiobot/api/routes/bitget.py`
- `backend/arjiobot/api/routes/control_plane.py`
- `backend/arjiobot/api/routes/settings.py`
- `backend/arjiobot/api/dependencies.py`
- `backend/arjiobot/exchange/bitget_adapter.py`
- `backend/arjiobot/api/tests/test_bitget_environment_routes.py`
- `backend/arjiobot/api/tests/test_frontend_contracts.py`
- `frontend/src/api/bitget.ts`
- `frontend/src/types/settings.ts`
- `frontend/src/types/controlPlane.ts`
- `frontend/src/pages/Settings.tsx`
- `frontend/src/pages/MobileControl.tsx`
- `frontend/src/pages/TradingControlCenter.tsx`
- `frontend/src/pages/SetupRadar.tsx`

## Demo Removed Or Quarantined

Removed from active Bitget exchange/API/frontend surfaces:

- DEMO trading mode
- demo credentials
- demo REST base URL
- demo connection route
- demo order route
- `paptrading` header logic
- demo/live toggle wording
- old `ENABLE_LIVE_BITGET_TRADING` confirmation

Active modes are now:

- `OFF`
- `DRY_RUN_PREVIEW`
- `LIVE`

## Official Bitget Futures Endpoints Implemented

REST base:

- `https://api.bitget.com`

WebSocket metadata:

- public: `wss://ws.bitget.com/v2/ws/public`
- private: `wss://ws.bitget.com/v2/ws/private`

Private account:

- `GET /api/v2/mix/account/account`

Public market data:

- `GET /api/v2/mix/market/contracts`
- `GET /api/v2/mix/market/ticker`
- `GET /api/v2/mix/market/candles`

Account/margin/leverage/order:

- `POST /api/v2/mix/account/set-margin-mode`
- `POST /api/v2/mix/account/set-leverage`
- `POST /api/v2/mix/order/place-order`

Defaults:

- product type: `USDT-FUTURES`
- margin coin: `USDT`
- margin mode: `isolated`

## Signed Auth

Implemented Bitget signature construction:

- millisecond timestamp
- query-aware prehash
- JSON body prehash for POST
- HMAC SHA256
- Base64 signature
- required headers:
  - `ACCESS-KEY`
  - `ACCESS-SIGN`
  - `ACCESS-TIMESTAMP`
  - `ACCESS-PASSPHRASE`
  - `Content-Type: application/json`
  - `locale: en-US`

Secrets are not returned in API responses, reports, or frontend state.

## Account Diagnostics

The account check now uses a real signed request to:

```text
GET /api/v2/mix/account/account
```

The control plane exposes:

- connection status
- account type `REAL`
- product type
- margin coin
- available balance
- available margin
- last successful account check
- private API auth status
- last error

The UI must not show connected unless signed auth succeeds.

## Market Monitoring

Pair monitoring now requires successful real public Bitget market requests:

- contract config loaded
- ticker fetched
- 1m candles fetched

Pair rows expose:

- product type
- contract config loaded
- symbol status
- minTradeNum
- minTradeUSDT
- max leverage
- last price
- bid
- ask
- mark price
- market update time
- monitoring status

If market data is not available, monitoring remains `NOT MONITORING`.

## Dry-Run Preview

Added:

```text
POST /api/bitget/orders/dry-run-preview
```

Dry-run:

- uses real public market data
- loads contract config
- validates profile/risk/exchange locks
- calculates isolated margin size
- rounds size using contract config
- enforces min trade and leverage constraints
- builds the exact sanitized order payload
- does not submit a real order

## Live Execution Guard

Live order route remains guarded:

```text
POST /api/bitget/orders/live
```

Requires:

- mode `LIVE`
- live armed
- confirmation text `ENABLE LIVE`
- recent successful dry-run preview
- non-stale account/market data
- profile lock passed
- risk lock passed
- exchange lock passed

## Validation

Executed:

```text
python -m py_compile backend/arjiobot/exchange/bitget_environment.py backend/arjiobot/api/routes/bitget.py backend/arjiobot/api/routes/control_plane.py backend/arjiobot/api/routes/settings.py
python -m pytest backend/arjiobot/api/tests/test_bitget_environment_routes.py backend/arjiobot/api/tests/test_control_plane_routes.py backend/arjiobot/api/tests/test_frontend_contracts.py -q -p no:cacheprovider
npm run build
```

Results:

```text
Backend compile: PASS
Focused backend tests: 13 passed
Frontend build: PASS
```

## No Fake Monitoring Proof

Scan of active Bitget/API/frontend surfaces shows no active:

- demo route
- demo mode
- `paptrading`
- `/orders/test-demo`
- `/connection/demo`
- old demo/live UI wording

Remaining `demo` reference in active API routes is the existing risk route helper import, which was not changed because this task explicitly excluded frozen strategy/risk behavior.

## Known Limitation

This machine still cannot complete TLS to `https://api.bitget.com`.

Until the machine/VPS/network can pass:

```text
curl.exe -I https://api.bitget.com
```

real account and market checks will correctly remain blocked.

## Final Statement

ArjioBot is now aligned with the official Bitget Futures API, live-account only, using real market data, real account diagnostics, isolated margin order planning, dry-run preview, and guarded live execution: YES
