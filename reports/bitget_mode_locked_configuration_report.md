# Bitget Demo/Live Mode-Locked Configuration Report

## Summary

Bitget REST and WebSocket configuration is now mode-managed by the backend.

The user is no longer asked for a Bitget Demo REST Base URL in normal setup.

## REST Rules

- LIVE REST base URL: `https://api.bitget.com`
- DEMO REST base URL: `https://api.bitget.com`
- DEMO credentials are stored separately from LIVE credentials.
- DEMO REST requests apply request header `paptrading: 1`.
- LIVE REST requests do not apply `paptrading: 1`.
- Runtime credential payloads cannot override the Bitget REST base URL.
- Environment lock verification fails if the resolved credential/environment is mismatched.

## WebSocket Rules

- DEMO mode auto-selects Bitget WebSocket endpoint metadata.
- LIVE mode auto-selects Bitget WebSocket endpoint metadata.
- The normal Settings UI does not ask for manual WebSocket URLs.

## UI Changes

Settings now shows:

- REST Base URL
- Demo REST Header
- Credential Type
- Connection Status
- Last Account Check
- Last Market Price Fetch

Removed from normal Bitget setup:

- Demo Base URL input
- Live Base URL input
- frontend credential payload `base_url`

## Backend Changes

- `BitgetCredentialConfig` normalizes all DEMO/LIVE credentials to `https://api.bitget.com`.
- DEMO signed account probes include `paptrading: 1`.
- LIVE signed account probes do not include `paptrading: 1`.
- DEMO market ticker fetches include `paptrading: 1`.
- LIVE market ticker fetches do not include `paptrading: 1`.
- Environment lock records now expose REST/header/WebSocket mode metadata.

## Validation

Executed:

```text
python -m py_compile backend/arjiobot/exchange/bitget_environment.py backend/arjiobot/api/routes/control_plane.py
python -m pytest backend/arjiobot/api/tests/test_bitget_environment_routes.py backend/arjiobot/api/tests/test_control_plane_routes.py -q -p no:cacheprovider
npm run build
```

Results:

```text
Backend compile: PASS
Backend Bitget/control-plane tests: 10 passed
Frontend build: PASS
```

Final scan:

- No active `https://api.bitget.com/demo` REST base URL remains.
- No normal frontend Bitget `baseUrl`/`setBaseUrl` credential field remains.
- Remaining `api_base_url` field is the frontend-to-local-backend URL setting, not a Bitget REST setting.

## Final Statement

Bitget demo/live REST and WebSocket configuration is mode-locked and no longer requires manual demo base URL input: YES
