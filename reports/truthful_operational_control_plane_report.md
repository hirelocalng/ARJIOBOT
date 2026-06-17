# Truthful Operational Control Plane Validation

## Scope

The control panel was converted away from cosmetic/demo state toward backend and exchange truth.

No strategy profile logic was changed.

## Files Changed

- `backend/arjiobot/api/dependencies.py`
- `backend/arjiobot/api/routes/accounts.py`
- `backend/arjiobot/api/routes/control_plane.py`
- `backend/arjiobot/api/tests/test_bitget_environment_routes.py`
- `backend/arjiobot/api/tests/test_control_plane_routes.py`
- `backend/arjiobot/api/tests/test_radar_routes.py`
- `backend/arjiobot/exchange/bitget_adapter.py`
- `backend/arjiobot/exchange/bitget_environment.py`
- `frontend/src/components/radar/SetupRadarTable.tsx`
- `frontend/src/pages/PairManager.tsx`
- `frontend/src/pages/SetupRadar.tsx`

## Root Cause

The frontend and API were previously allowed to display optimistic placeholder state:

- seeded demo setup radar candidates
- simulated market prices and timestamps
- mock balance/account verification
- active monitoring labels without a real account connection and market-data poll

This made the UI look operational even when the backend had not verified exchange credentials or received live market data.

## Corrections

- Removed API startup seeding of fake `ENTRY_READY` setup candidates.
- Radar now starts empty unless real backend-tracked setup candidates exist.
- Setup Radar empty state now displays `NO ACTIVE TRACKED SETUPS`.
- Control plane pair monitoring now requires:
  - enabled pair
  - connected account
  - successful market-data poll
- Pair rows now show `NOT MONITORING`, `NO`, and `N/A` instead of simulated price/tick data when no real poll exists.
- MOCK adapter mode now emits `MOCK MODE ACTIVE - NOT REAL EXCHANGE DATA`.
- Pair manager displays the MOCK warning visibly.
- Bitget demo/live connection tests now perform a signed account probe instead of accepting cosmetic credentials.
- Invalid credentials now fail loudly.
- Legacy account adapter no longer marks accounts verified without real exchange verification.

## Backend Truth Rules

- Account connection is `CONNECTED` only after the Bitget environment records a successful signed connection probe.
- Market pair monitoring is `MONITORING` only after a successful live ticker poll.
- Live price and tick time are `N/A` until a real poll succeeds.
- Setup Radar uses real API setup state only.
- System health now exposes last successful market poll, polling interval, active polling job count, and last error.

## Validation

Executed:

```text
python -m pytest backend/arjiobot/api/tests/test_control_plane_routes.py backend/arjiobot/api/tests/test_bitget_environment_routes.py backend/arjiobot/api/tests/test_radar_routes.py -q -p no:cacheprovider
npm run build
```

Results:

```text
Backend focused tests: 11 passed
Frontend build: PASS
```

Final scan confirms there are no active `SIMULATED` or `MOCK_BALANCE` display paths in the control-plane API/frontend paths. Remaining matches are intentional truth-state labels:

- `NO ACTIVE TRACKED SETUPS`
- `NO PAIRS CONFIGURED FOR REAL MONITORING`
- `MOCK MODE ACTIVE - NOT REAL EXCHANGE DATA`

## Known Limitations

- A real Bitget connection requires valid credentials and network access.
- Without a successful signed Bitget probe, the UI correctly remains `NOT CONNECTED`.
- Without a successful market-data poll, pair status correctly remains `NOT MONITORING`.

## Final Statement

UI state now reflects only real backend/exchange truth. No fake monitoring, fake setup radar, or fake connection status remains: YES
