# ArjioBot

ArjioBot is a modular strategy research and execution-planning system for the
Arjio trading workflow.

Current mode:

- Adapter mode: `MOCK`
- Execution mode: `PAPER ONLY`
- Live trading enabled: `NO`
- Real Bitget order placement: `NO`

## Built Modules

- Market Data Layer
- Swing Engine
- Expansion Engine
- FVG Engine
- Setup Tracker
- Strategy Engine
- CSV Backtester
- Risk Engine
- Paper Execution Engine
- Bitget Exchange Adapter
- Backend API Routes
- Frontend Dashboard/UI
- JSON metadata storage layer
- Local app runners and smoke validation

## Install Python Dependencies

From the repository root:

```bat
python -m pip install -r requirements.txt
```

If using a shared workspace venv one level above this project:

```bat
..\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## Run Backend

```bat
scripts\run_backend.bat
```

This starts the compatible local API server at:

```text
http://127.0.0.1:8000
```

## Run Frontend

Install Node.js LTS first. Then:

```bat
scripts\run_frontend.bat
```

In PowerShell, use `npm.cmd` instead of `npm` if script execution policy blocks
`npm.ps1`.

The frontend expects:

```text
VITE_API_BASE_URL=http://127.0.0.1:8000
```

## Run Tests

```bat
scripts\run_tests.bat
```

## Run CSV Backtest

```bat
scripts\run_backtest_demo.bat
scripts\run_backtest_csv.bat data\sample_ohlcv.csv BTCUSDT
```

Sample data:

```text
data\sample_ohlcv.csv
```

## Add Bitget API Account Safely

Use the dashboard Accounts page or Backend API account routes. API secret and
passphrase values are accepted for account creation but are never returned in
safe responses. Credentials are masked for display.

Do not enable live trading until the future live-trading enablement pass.

## Manage Pairs

Use the dashboard Pairs page or API routes to add, remove, enable, disable, and
bulk-import monitored symbols.

Default demo pairs:

- BTCUSDT
- ETHUSDT
- SOLUSDT

## Manage Risk Settings

Use the Risk Settings page. Risk amount per trade means maximum loss if the stop
loss is hit. It is not margin, leverage, or position size.

## Production Safety Gates

- Dashboard authentication is supported when `ARJIOBOT_DASHBOARD_PASSWORD` is set.
- Live trading routes exist, but live mode is off by default and blocked until
  account, market-data, risk, environment, and confirmation checks pass.
- Real Bitget order placement must remain guarded behind the live toggle and
  account verification flow.
- Use `DATABASE_URL` and `ARJIOBOT_CREDENTIAL_ENCRYPTION_KEY` for durable
  production settings and encrypted saved account credentials.

## Next Steps

1. Run historical CSV backtests.
2. Review backtest reports.
3. Paper trade through the dashboard.
4. Prepare VPS hosting.
5. Enable live trading later through a separate safety-gated pass.

## Readiness Reports

- `reports\strategy_compliance_audit.html`
- `reports\live_trading_safety_audit.html`
- `reports\final_backtesting_readiness_report.html`
- `reports\application_integration_validation_report.html`

VPS preparation:

- `docs\hosting-vps-quickstart.md`
