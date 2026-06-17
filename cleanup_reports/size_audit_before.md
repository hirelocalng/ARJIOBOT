# ArjioBot Size Audit Before Cleanup

Generated: 2026-06-17

## Safety / Branch Status

- Requested branch: `cleanup/reduce-project-size`
- Branch creation status: **BLOCKED**
- Reason: `git` is not available in this PowerShell session (`Get-Command git` returned no command).
- Cleanup mode: audit first, quarantine uncertain artifacts, test before permanent removal.

## Total Size

- Total project size: **3,479,063,882 bytes**
- Approx total: **3.24 GiB / 3.48 GB**

## Largest Top-Level Folders

| Folder | Size |
|---|---:|
| `reports` | 2,802.35 MB |
| `data` | 392.96 MB |
| `frontend` | 117.83 MB |
| `backend` | 4.27 MB |
| `scripts` | 0.37 MB |
| `docs` | 0.09 MB |

## Largest Remaining Sources Of Bloat

### `reports/backtests`

- Size: **2,800.36 MB**
- File count: **1,130**
- Type breakdown:
  - `.csv`: 951 files, **2,727.58 MB**
  - `.json`: 90 files, **42.50 MB**
  - `.html`: 89 files, **30.28 MB**
- Pattern: repeated generated `api_upload_*.csv` upload copies and generated `bt_*.json/html` reports.

### Duplicate Generated CSVs

- Duplicate SHA256 groups in `reports/backtests/*.csv`: **55**
- Examples:
  - 56 identical files, 336.77 MB total, sample `api_upload_csv_0001_c3d6cc0dbc1d_09a35523.csv`
  - 37 identical files, 198.88 MB total, sample `api_upload_csv_0001_a26daa70617e_227b68f7.csv`
  - 35 identical files, 208.43 MB total, sample `api_upload_csv_0001_3ae9b4893c04_0a440cf1.csv`
  - 30 identical files, 174.40 MB total, sample `api_upload_csv_0001_7fffa234c144_12e26854.csv`
  - 28 identical files, 173.71 MB total, sample `api_upload_csv_0001_6c385ecb7538_a6eccb82.csv`

## Largest Files Observed

| File | Size |
|---|---:|
| `data/2023.csv` | 19.44 MB |
| `frontend/node_modules/@esbuild/win32-x64/esbuild.exe` | 10.13 MB |
| `frontend/node_modules/typescript/lib/typescript.js` | 8.69 MB |
| Many `reports/backtests/api_upload_*.csv` files | ~6.4-6.7 MB each |
| `data/BTCUSDT-1m-2025-03.csv` | 6.64 MB |
| `data/BTCUSDT-1m-2026-05.csv` | 6.58 MB |
| `data/ETHUSDT-1m-2026-05.csv` | 6.48 MB |

## Generated / Cache Folders Found

- `frontend/node_modules`
- `frontend/node_modules/.vite`
- `frontend/dist`
- `backend/.pytest_cache`
- Multiple `__pycache__` folders under `backend/arjiobot/**`
- `scripts/__pycache__`
- `.pytest_tmp`

## Initial Classification

| Path / Pattern | Classification | Planned Action |
|---|---|---|
| `reports/backtests/api_upload_*.csv` | Generated upload copies | Quarantine old copies under `_cleanup_quarantine/reports_old/backtests/` |
| `reports/backtests/bt_*.json` / `bt_*.html` | Generated backtest reports | Quarantine old reports, keep latest small proof artifacts if needed |
| `frontend/dist` | Generated build output | Remove after build can recreate it |
| `frontend/node_modules/.vite` | Generated Vite cache | Remove |
| `backend/.pytest_cache` | Generated pytest cache | Remove |
| `**/__pycache__` | Generated Python bytecode cache | Remove |
| `.pytest_tmp` | Generated test temp folder | Remove if empty or stale |
| `frontend/node_modules` | Dependency install output | Candidate for quarantine/removal after confirming package lock/build can reinstall; may be kept if offline build is required |
| `data/*.csv` | Source/test market datasets | Keep unless confirmed duplicate/unused |
| `profiles.lock.json` and profile freeze files | Protected | Keep unchanged |

## Notes

- No source deletion has been performed at this stage.
- No profile strategy/freeze files should be touched by this cleanup.
- Reports are the main cleanup target, not strategy code.
