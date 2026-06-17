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
..\.venv\Scripts\python.exe -m pip install pytest
```

If using the shared workspace venv from this project:

```bat
..\.venv\Scripts\python.exe -m pytest --version
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

## Not Enabled Yet

- Live trading
- Real Bitget order placement
- Production database
- Authentication/login
- Multi-user SaaS features

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
