# ArjioBot Size Audit After Cleanup Attempt

Generated: 2026-06-17

## Status

**Cleanup blocked / not completed.**

Reason: the required backend test command failed. Per the cleanup instruction, quarantined files were restored and no permanent deletion of the large report dump was performed.

## Size Summary

| Metric | Size |
|---|---:|
| Before cleanup audit | 3,479,063,882 bytes |
| After blocked cleanup attempt | 3,471,619,879 bytes |
| Net reduction while restored | 7,444,003 bytes, about 7.10 MB |

The small reduction is from regenerated cache/build artifact cleanup. The large `reports/backtests` dump was restored after tests failed.

## Largest Remaining Folders

| Folder | Size |
|---|---:|
| `reports` | 2,802.36 MB |
| `data` | 392.96 MB |
| `frontend` | 111.68 MB |
| `backend` | 3.30 MB |
| `scripts` | 0.37 MB |

## Reports Folder Status

`reports/backtests` was restored.

Current breakdown:

| Extension | Count | Size |
|---|---:|---:|
| `.csv` | 971 | 2,727.59 MB |
| `.json` | 90 | 42.50 MB |
| `.html` | 89 | 30.28 MB |

## Files / Folders Quarantined

| Path | Status |
|---|---|
| `reports/backtests/` | Quarantined, then restored because backend tests failed |

## Files / Folders Removed

Generated cache/build folders were removed where Windows permissions allowed:

- Python `__pycache__` directories
- Vite cache directories
- `frontend/dist` before build

Windows denied removal of:

- `.pytest_tmp`
- `backend/.pytest_cache`

The frontend build recreated `frontend/dist`.

## `.gitignore` Updates

Added ignore rules for:

- Python caches and coverage
- frontend `node_modules`, `dist`, `build`, Vite cache
- `reports/backtests`
- `_cleanup_quarantine`
- temp/log files

## Dependency Changes

None. Dependency cleanup was not attempted because the required backend test run failed before that phase.

## Tests / Verification

### Passed

- Profile freeze tests:
  - `python -m pytest backend/arjiobot/profile_freeze/tests -q -p no:cacheprovider`
  - Result: `2 passed`
- Frontend build:
  - `npm run build`
  - Result: passed

### Failed

Backend tests:

Command:

```powershell
python -m pytest backend/arjiobot -q -p no:cacheprovider
```

Result:

- `380 passed`
- `7 failed`

Failures:

- `backend/arjiobot/api/tests/test_execution_routes.py::test_paper_execution_routes_only`
  - `IndexError: list index out of range` because `/api/setups/entry-ready` returned no setup.
- `backend/arjiobot/api/tests/test_health_routes.py::test_health_and_status_routes`
  - Expected `adapter_mode == MOCK`, actual `BITGET_LIVE`.
- `backend/arjiobot/api/tests/test_risk_routes.py::test_risk_assessment_and_trade_plan_routes`
  - `IndexError: list index out of range` because `/api/setups/entry-ready` returned no setup.
- `backend/arjiobot/api/tests/test_rr_contracts.py::test_backend_route_forces_production_rr_and_fixed_risk_to_runner`
  - Expected source string `rr_profile = PRODUCTION_RR_PROFILE`.
- `backend/arjiobot/api/tests/test_signals_routes.py::test_signal_generation_and_error_response`
  - `IndexError: list index out of range` because `/api/setups/entry-ready` returned no setup.
- `backend/arjiobot/exchange/tests/test_exchange_integration.py::test_report_generation`
  - Legacy account adapter raises `ExchangeAdapterError` for real account verification path.
- `backend/arjiobot/tests/test_strategy_compliance_rules.py::test_strategy_risk_execution_and_backtest_safety_rules`
  - Expected take profit to equal signal final target; actual plan used RR-derived target.

## Frozen Profile Proof

- Profile freeze tests passed after cleanup attempt.
- No cleanup action modified `PROFILE_RECOVERED_HIGH_WINRATE`, `PROFILE_2`, profile freeze files, swing/FVG/retrace/entry strategy logic, or active frontend pages.

## Remaining Largest Files / Why Kept

- `reports/backtests/api_upload_*.csv`: restored because backend tests failed and cleanup instructions required restoring quarantine.
- `data/*.csv`: retained as market datasets unless separately confirmed unused.
- `frontend/node_modules`: retained so frontend build can run without network reinstall.

## Final Result

Cleanup did not complete because required tests failed. The large report dump was restored.

Final statement:

“ArjioBot cleanup completed safely, project size reduced, useless files removed/quarantined, and all critical functionality still works: NO”
