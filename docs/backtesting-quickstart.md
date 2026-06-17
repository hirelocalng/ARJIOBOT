# Backtesting Quickstart

ArjioBot v1 uses historical OHLCV CSV files as the primary backtesting data
source.

## CSV Format

Required columns:

- `timestamp`
- `open`
- `high`
- `low`
- `close`
- `volume`

Optional columns:

- `symbol`
- `timeframe`

Place CSV files in `data/`. A tiny smoke-test file is included at
`data/sample_ohlcv.csv`.

## Run Demo Backtest

From the project root:

```bat
scripts\run_backtest_demo.bat
```

Run a specific CSV:

```bat
scripts\run_backtest_csv.bat data\sample_ohlcv.csv BTCUSDT
```

CSV backtest reports are written under:

```text
reports\backtests\
```

The demo generates:

- `backend/arjiobot/backtesting/reports/backtest_validation_report.html`
- `backend/arjiobot/backtesting/reports/backtest_validation_report.png`

## Upload CSV Through API/Dashboard

Start the backend:

```bat
scripts\run_backend.bat
```

Start the frontend after installing Node.js LTS:

```bat
scripts\run_frontend.bat
```

Then open the Backtesting page, upload a CSV, and run a backtest.

## Interpreting Results

Backtest output includes:

- Total candles loaded
- Setups detected
- Signals generated
- Trades simulated
- Wins and losses
- Win rate
- Net profit
- Max drawdown
- Profit factor
- Setup conversion funnel

## Common Errors

- Missing required CSV columns: verify headers match the required column names.
- Invalid timestamp: use ISO timestamps such as `2026-01-01T00:00:00Z`.
- No trades simulated: sample data may not create a valid Arjio strategy trade.
- Frontend will not start: install Node.js LTS and rerun `scripts\run_frontend.bat`.
