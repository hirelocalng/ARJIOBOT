# Live Trading Control Flow Fix Report

## Summary

The control flow now separates configured pairs/accounts from proven operational state.

The UI should no longer show `CONNECTED`, `ACTIVE`, `MONITORING`, or live-ready state merely because a pair/account exists. Those states now require backend proof.

Frozen strategy profiles and swing/FVG/retrace/entry logic were not changed.

## Files Changed

- `backend/arjiobot/api/dependencies.py`
- `backend/arjiobot/api/routes/accounts.py`
- `backend/arjiobot/api/routes/control_plane.py`
- `backend/arjiobot/api/routes/live_trading.py`
- `backend/arjiobot/api/routes/monitoring.py`
- `backend/arjiobot/api/routes/pairs.py`
- `backend/arjiobot/api/routes/radar.py`
- `backend/arjiobot/api/routes/system.py`
- `backend/arjiobot/api/routes/__init__.py`
- `backend/arjiobot/api/tests/test_accounts_routes.py`
- `backend/arjiobot/api/tests/test_live_control_flow_routes.py`
- `frontend/src/api/accounts.ts`
- `frontend/src/api/liveTrading.ts`
- `frontend/src/api/pairs.ts`
- `frontend/src/pages/AccountManager.tsx`
- `frontend/src/pages/PairManager.tsx`
- `frontend/src/pages/Settings.tsx`
- `frontend/src/types/accounts.ts`
- `frontend/src/types/controlPlane.ts`

## Account Flow Fixed

Added:

```text
POST /api/accounts/bitget/test-and-save
POST /api/accounts/select-active
```

Accounts are only added to the account list after a signed Bitget live account check succeeds.

If the signed check fails:

- account is not saved as connected
- account list remains empty
- control plane shows `NOT CONNECTED`
- live trading stays blocked

The Accounts page now uses `TEST & SAVE BITGET ACCOUNT`.

## Monitoring Flow Added

Added:

```text
POST /api/monitoring/start
POST /api/monitoring/stop
GET /api/monitoring/status
GET /api/pairs/status
```

Enabled pairs are not treated as monitored pairs.

Monitoring only becomes `ACTIVE` after:

- monitoring session starts
- real Bitget contract config loads
- real Bitget ticker loads
- real Bitget candles load

If public market data fails, the pair shows `ERROR` or `NOT MONITORING`, with `N/A` prices.

## Setup Radar Bound To Live Monitoring

Added:

```text
GET /api/radar/live
```

If monitoring is not active, live radar returns:

```text
NO ACTIVE LIVE SETUPS
```

Stopping monitoring clears live setup rows.

## Live Trading Toggle Added

Added:

```text
POST /api/live-trading/toggle
GET /api/live-trading/status
```

Settings now includes:

- `LIVE TRADING: ON`
- `LIVE TRADING: OFF`
- real-funds confirmation checkbox
- confirmation text `ENABLE LIVE`

Live trading ON is blocked unless:

- connected live Bitget account exists
- monitoring is active
- market data is fresh
- risk settings exist
- kill switch is off
- environment lock passes

## Global State Synchronization

Added:

```text
GET /api/system/control-state
```

The existing control plane is now the source for:

- active account
- monitoring state
- pair polling state
- live trading state
- environment lock
- risk readiness
- setup radar readiness

## Fake State Removed

The active UI/API path no longer uses:

- simulated prices
- fake timestamps
- account connected while account list is empty
- enabled pair equals monitored pair
- placeholder setup rows

`SIMULATED` no longer appears in active frontend pages or active API routes.

## Validation

Executed:

```text
python -m pytest backend/arjiobot/api/tests/test_control_plane_routes.py backend/arjiobot/api/tests/test_accounts_routes.py backend/arjiobot/api/tests/test_bitget_environment_routes.py backend/arjiobot/api/tests/test_live_control_flow_routes.py -q -p no:cacheprovider
npm run build
```

Results:

```text
Focused backend tests: 17 passed
Frontend build: PASS
```

## Known Limitation

This machine still cannot complete TLS to `https://api.bitget.com`. Until the network/VPS path is fixed, real Bitget account and public market checks will correctly fail instead of showing fake operational status.

## Final Statement

Accounts, pair monitoring, Setup Radar, and Live Trading toggle now use real backend/Bitget state and no longer show fake operational status: YES
