# Backtester Specification v1.0 - Frozen

Status: frozen after audit and ambiguity review.

The Backtester replays historical candles through the frozen ArjioBot pipeline
and simulates deterministic trade outcomes. It does not place orders, connect
to Bitget, mutate production services, or build the Risk Engine.

## Purpose

The Backtester consumes:

- Historical candle data
- Market Data Layer candles
- Swing Engine outputs
- Expansion Engine outputs
- FVG Engine outputs
- Setup Tracker outputs
- Strategy Engine signals

It produces:

- BacktestRun objects
- SimulatedTrade objects
- Trade outcomes
- Performance metrics
- Equity curve
- Drawdown report
- Strategy-stage analytics
- Setup conversion analytics
- Replay-safe reports

## Audit Findings And Amendments

- v1 supports bearish signal backtesting first.
- Data structures include direction/status enums so bullish support can be added
  later without redesign.
- Historical candles must be closed, sorted chronologically per symbol, and
  duplicate timestamps per symbol/timeframe are invalid.
- No wall-clock time is used. Run, trade, and replay timestamps come from config
  and historical events.
- Synthetic timeframe generation is represented by configurable timeframe
  profiles. v1 validates the profile and keeps replay order deterministic.
- Entry uses the next available 1M candle open after signal generation.
- If the final target is reached before entry, the trade is skipped.
- Same-candle stop/take-profit ambiguity uses configurable policy. Default is
  `CONSERVATIVE_STOP_FIRST`.
- Fee model defaults to `0.0006` and applies to entry and exit notional.
- Slippage model defaults to fixed `0.0` bps. For bearish sells, entry is
  worsened lower and exits are worsened higher.
- Simplified risk sizing is allowed only for simulation:
  `position_size = risk_amount / abs(stop_loss_price - entry_price)`.
- Leverage, live risk checks, exchange routing, and order placement are out of
  scope and belong to future modules.

## Replay Pipeline

```text
1M historical candles
Market Data synthetic timeframes
Swing Engine
Expansion Engine
FVG Engine
Setup Tracker
Strategy Engine
Backtester trade simulation
```

Replay must process candles chronologically and must not expose future candles
to past decisions.

## BacktestConfig

Stores:

- `run_id`
- `symbols`
- `start_time`
- `end_time`
- `initial_balance`
- `risk_per_trade`
- `max_open_trades`
- `fee_rate`
- `slippage_model`
- `spread_model`
- `timeframe_profile`
- `allow_multiple_signals_per_symbol`
- `same_candle_resolution_policy`
- `random_seed`
- `notes`

## Historical CSV Data Source

For v1, the Backtester will use historical OHLCV CSV files as the primary data
source.

Supported CSV sources:

- Bitget historical candles
- Binance historical candles
- Other exchange candle exports

Required CSV columns:

- `timestamp`
- `open`
- `high`
- `low`
- `close`
- `volume`

Optional columns:

- `symbol`
- `timeframe`

The Backtester must include a CSV loader that normalizes imported data into the
project's `Candle` model before replay.

Do not use TradingView Lightweight Charts as a data source.

Chart visualization can be handled later by the Dashboard module.

## Trade Simulation

For `MARKET_SELL_READY`:

- Entry price = next available 1M candle open after signal generation.
- Stop loss = signal stop reference.
- Take profit = signal final target.
- Stop is hit when candle high is greater than or equal to stop.
- Target is hit when candle low is less than or equal to target.

The Backtester consumes `stop_reference_price` and `final_target_price` from
Strategy Engine signals. It does not recalculate Setup Tracker stop/target
references.

## Reports

Generate:

- `arjiobot/backtesting/reports/backtest_validation_report.html`
- `arjiobot/backtesting/reports/backtest_validation_report.png`

Reports must show summary metrics, trade table, equity curve, drawdown, setup
conversion funnel, and PASS / FAIL validation summary.

## Known Limitations

- v1 simulates bearish Strategy Engine signals only.
- v1 does not place orders, call Bitget, calculate leverage, or perform live
  Risk Engine checks.
- v1 may process multiple symbols sequentially.

## Final Validation Report

Model Tests: PASS

Historical Replay Tests: PASS

Trade Simulator Tests: PASS

Fee Tests: PASS

Slippage Tests: PASS

Metrics Tests: PASS

Backtest Engine Tests: PASS

Integration Tests: PASS

Report Generation Output: PASS

Reports Generated:

- `arjiobot/backtesting/reports/backtest_validation_report.html`
- `arjiobot/backtesting/reports/backtest_validation_report.png`

Tests Executed: 22

Tests Passed: 22

Replay Validation: PASS. Historical candles are closed, sorted
chronologically, duplicate-checked per symbol/timeframe, and replayed without
future leakage.

CSV Loader Validation: PASS. Historical OHLCV CSV files are normalized into the
project `Candle` model, required OHLCV columns are enforced, and optional
`symbol` / `timeframe` columns override explicit loader defaults when present.

Trade Simulation Validation: PASS. Bearish signals enter at the next available
1M candle open, simulate stop loss and take profit outcomes, handle
target-before-entry skips, and apply configurable same-candle TP/SL policy.

Fee / Slippage Validation: PASS. Fees apply to entry and exit notional.
Fixed-bps bearish slippage worsens entry and exit prices deterministically.

Metrics Validation: PASS. Metrics include trade counts, wins, losses, skipped
trades, ambiguous trades, win rate, net profit, profit factor, R multiple,
expectancy, equity curve, drawdown, ending balance, win/loss statistics, and
setup conversion analytics.

Setup Conversion Validation: PASS. Conversion analytics track setups created,
progress funnel checkpoints, entry-ready setups, signals generated, trades
entered, wins, losses, invalidation counts, and failure stage placeholder.

Benchmark Results: PASS. Benchmark helper reports candle count, duration in
milliseconds, and candles per second.

Known Limitations:

- v1 simulates bearish Strategy Engine signals only.
- v1 does not place orders, call Bitget, calculate leverage, or perform live
  Risk Engine checks.
- v1 may process multiple symbols sequentially.
- v1 uses simplified risk sizing for simulation only.

Ready For Integration: YES

Recommendation: freeze the Backtester and integrate it as the authoritative
historical simulation service for the frozen ArjioBot pipeline. Do not proceed
to Risk Engine until downstream consumers use BacktestRun, SimulatedTrade, and
BacktestMetrics records instead of ad hoc simulation logic.
