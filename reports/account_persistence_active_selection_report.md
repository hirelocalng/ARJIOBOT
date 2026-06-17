# Account Persistence And Active Selection Report

## Scope

Fixed Bitget account persistence, active account selection, reconnect flow, and Settings integration. Frozen strategy profiles and strategy logic were not modified.

## Files Changed

- `backend/arjiobot/exchange/account_vault.py`
- `backend/arjiobot/api/dependencies.py`
- `backend/arjiobot/api/routes/accounts.py`
- `backend/arjiobot/api/routes/account_status.py`
- `backend/arjiobot/api/routes/live_trading.py`
- `backend/arjiobot/api/tests/test_accounts_routes.py`
- `backend/arjiobot/api/tests/test_account_status_routes.py`
- `backend/arjiobot/api/tests/test_live_control_flow_routes.py`
- `frontend/src/api/accounts.ts`
- `frontend/src/types/accounts.ts`
- `frontend/src/types/settings.ts`
- `frontend/src/pages/AccountManager.tsx`
- `frontend/src/pages/Settings.tsx`
- `frontend/src/App.tsx`
- `frontend/src/components/layout/Topbar.tsx`

## Persistent Account Storage

Implemented encrypted local account vault:

- path: `data/bitget_accounts.vault.json`
- metadata remains visible after restart
- credentials are encrypted at rest
- full API key, API secret, and passphrase are never returned to the frontend

Required environment variable:

- `ARJIOBOT_CREDENTIAL_ENCRYPTION_KEY`

If the key is missing, account save/reconnect is blocked with:

- `CREDENTIAL STORAGE BLOCKED: encryption key missing`

## Account Lifecycle

Accounts page now owns credential entry and management:

- add new Bitget account
- test and save account
- reconnect existing account
- refresh account status
- select active account
- delete account
- view saved accounts list

Settings no longer asks for API key, secret, or passphrase.

## Active Account Source Of Truth

Added global active account state:

- `active_live_account_id` in backend state
- persisted active account in the vault
- `active_account_id` in runtime settings

The selected account is used by:

- account diagnostics
- Account Status page
- Trading Control Center
- live trading toggle
- readiness checks
- Bitget credential activation before refresh/live checks

## Backend Endpoints

Implemented/fixed:

- `POST /api/accounts/bitget/test-and-save`
- `GET /api/accounts`
- `GET /api/accounts/active`
- `GET /api/accounts/{account_id}`
- `POST /api/accounts/{account_id}/refresh`
- `POST /api/accounts/{account_id}/reconnect`
- `DELETE /api/accounts/{account_id}`
- `POST /api/accounts/select-active`

## Restart Behavior

On backend restart:

- saved accounts are loaded from the vault
- accounts remain visible
- status becomes `NEEDS_VERIFICATION`
- account is not deleted just because verification is pending
- active account id is restored

If credentials cannot be decrypted or are missing, account remains visible and becomes `NEEDS_RECONNECT`.

## Live Trading Dependency

Live trading now blocks when:

- no active account is selected
- selected account is not connected
- selected account has an error

Exact no-account blocker:

- `LIVE BLOCKED: no connected active Bitget account selected`

## UI Changes

Accounts page:

- added reconnect mode
- added refresh status action
- added active account selection
- shows masked key, status, balance, last success, last failed, and last error

Settings page:

- removed Bitget credential fields
- added `Active Bitget Account` dropdown
- added apply active account button
- shows current active account and status

Topbar:

- shows active account name
- shows account connection status

## Security Verification

API responses do not expose:

- full API key
- API secret
- passphrase
- decrypted credential payload

Only masked API key and safe account metadata are returned.

## Test Results

- `python -m py_compile ...`: PASS
- `python -m pytest ArjioBot\backend\arjiobot\api\tests\test_accounts_routes.py ArjioBot\backend\arjiobot\api\tests\test_account_status_routes.py ArjioBot\backend\arjiobot\api\tests\test_live_control_flow_routes.py ArjioBot\backend\arjiobot\api\tests\test_control_plane_routes.py -q -p no:cacheprovider`: 20 passed
- `cd ArjioBot\frontend && npm run build`: PASS

## Final Statement

Bitget accounts are now saved persistently, selectable from Settings, reusable after restart, and live trading only uses the selected connected account: YES
