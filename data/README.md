# Historical CSV Data

Place historical OHLCV CSV files in this directory for local backtesting.

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

The included `sample_ohlcv.csv` is a tiny deterministic file for smoke testing
the CSV loader and demo backtest flow. It is not intended to represent a full
market session and may not produce realistic strategy behavior.
