# ArjioBot VPS Runbook

## Production Start Commands

Backend:

```powershell
.\scripts\run_backend.bat
```

Frontend:

```powershell
.\scripts\run_frontend.bat
```

Linux equivalents:

```bash
./scripts/run_backend.sh
./scripts/run_frontend.sh
```

## Required Configuration

Copy `.env.example` and set real values outside source control.

Live trading defaults to disabled. Keep `LIVE_TRADING_ENABLED=false` until:

- Bitget credentials are added.
- Account connection test passes.
- A default account is verified.
- At least one pair is enabled.
- Timeframe profile is one of `DEFAULT_16_12_8` or `PROFILE_15_10_5`.
- RR is permanently locked to `RR_1_5` (1:1.5) for Profile F.
- Fixed risk amount is positive.

## Health Checks

Basic health:

```text
GET /api/health
```

Deep system status:

```text
GET /api/system-status
```

## Current Readiness Notes

- Backtesting and paper/demo execution use production `PROFILE_F`.
- Live Bitget order placement remains guarded and intentionally disabled in this build.
- Credentials are never returned through frontend-safe account responses.
- Pair settings persist to `data/runtime_pairs.json`.
- Runtime settings persist to `data/runtime_settings.json`.

## Validation

```powershell
..\.venv\Scripts\python.exe -m pytest backend/arjiobot/api/tests backend/arjiobot/risk/tests backend/arjiobot/execution/tests backend/arjiobot/backtesting/tests -q
```

```powershell
cd frontend
npm run build
```
