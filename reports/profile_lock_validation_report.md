# Profile Lock Validation Report

Generated: 2026-06-19

## Goal

Ensure the frontend-selected backtesting profile remains the only profile used by the API route, backend runner, strategy funnel, trade simulator, cache key, JSON report, HTML report, and frontend details panel.

## Profile Selection Flow

1. Frontend `Backtesting.tsx` sends `profile_id` and `selected_strategy_profile` from the dropdown.
2. API `/api/backtesting/run` rejects missing or invalid profile values.
3. API resolves the selected profile with `get_profile(profile_id)`.
4. API applies only explicit research overrides to that same resolved profile.
5. API passes the resolved profile id to `scripts/backtest_csv.py`.
6. CSV runner rejects a missing profile and verifies selected id equals resolved id before running.
7. Strategy funnel and trade simulator stamp every trade with selected/applied profile metadata.
8. Runner verifies all trades before writing reports.
9. API verifies the returned report and all trades again before storing the run.
10. Frontend displays `Profile Lock Verification` in Backtest Details.

## Enforcement Added

- Missing selected profile: rejected.
- Invalid selected profile: rejected.
- Selected/resolved mismatch: rejected.
- Trade-level selected/applied mismatch: rejected.
- Cache key includes selected profile, profile parameters, timeframe profile, dataset hash, risk, fees, and slippage.
- JSON and HTML reports include `PROFILE LOCK VERIFICATION`.

## Selectable Profiles Checked

Regression test `test_all_selectable_profiles_stay_profile_locked` runs:

- `STRICT_PROFILE`
- `PROFILE_F_VOLUME`
- `PROFILE_F_BALANCED`
- `PROFILE_F_SELECTIVE`
- `PROFILE_G_CODEX_OPTIMIZED`
- `PROFILE_RECOVERED_HIGH_WINRATE`

For every profile:

- `profile_id` equals selected profile.
- `selected_profile_id` equals selected profile.
- `applied_profile_id` equals selected profile.
- `profile_lock_status` equals `PASSED`.
- `selected_profile_actively_used_by_backend` equals `YES`.

## Validation Run

Regenerated real recovered-profile report:

- JSON: `ArjioBot/reports/backtests/bt_624f5cc97f161f27c9eaebb8.json`
- HTML: `ArjioBot/reports/backtests/bt_624f5cc97f161f27c9eaebb8.html`

Profile lock result:

- Frontend selected profile: `PROFILE_RECOVERED_HIGH_WINRATE`
- API selected profile: `PROFILE_RECOVERED_HIGH_WINRATE`
- Backend resolved profile: `PROFILE_RECOVERED_HIGH_WINRATE`
- Strategy applied profile: `PROFILE_RECOVERED_HIGH_WINRATE`
- Trades checked: `45`
- Mismatched trades count: `0`
- Profile lock status: `PASSED`
- Selected profile actively used by backend: `YES`

## Tests

- Backend/API/frontend contract regression: `81 passed`
- Frontend production build: `PASSED`

## Final Statement

Profile locking is enforced across frontend, API, backend, strategy engine, trade simulator, cache, and reports: YES
