# PROFILE_RECOVERED_HIGH_WINRATE Recovery Report

Generated: 2026-06-19

## Recovery Source

- Source artifact: `reports/backtests/research_comparison_bt_624f5cc97f161f27c9eaebb8.json`
- Recovered former profile id: `RESEARCH_PROFILE_F_DIRECT_12M_RETRACE_ENTRY`
- Recovered dataset/window: BTCUSDT March 2025
- Recovery method: artifact recovery from existing JSON report. Repository history was not available in this workspace.

## Recovered Profile Definition

- New profile id: `PROFILE_RECOVERED_HIGH_WINRATE`
- Classification: research-only
- Timeframe stack: `PROFILE_15_10_5`
- Expansion ratio: `1.0` to `3.0`
- Retrace window: `3` completed retrace-window candles
- Entry model: direct 10M/12M retrace-style FVG entry, no extra 1M confirmation chain
- TP model: `LEG_TARGET_RESEARCH`
- Risk model: fixed-risk position sizing from entry to swing stop
- FVG detection: unlinked raw detection for the main timeframe
- Main FVG association: `LEGACY_EXPANSION_OR_NEXT_CANDLE`
- Main FVG association window: expansion candle through the next same-timeframe candle
- One trade per retrace FVG: enabled

## Recovered Result

The regenerated report is:

- JSON: `ArjioBot/reports/backtests/bt_624f5cc97f161f27c9eaebb8.json`
- HTML: `ArjioBot/reports/backtests/bt_624f5cc97f161f27c9eaebb8.html`

Recovered output:

- Trades: `45`
- Wins: `34`
- Losses: `11`
- Win rate: `75.55555555555556`
- Net PnL: `861.2824168938263920965503726`
- Profit factor: `1.782984015358023992815045794`
- Max drawdown: `200.00000000000000000000000`
- Passed expansion: `417`
- Passed main FVG: `116`
- Passed retrace: `45`
- Direct entries: `45`

## Exact Match Check

Compared old artifact trades against regenerated `PROFILE_RECOVERED_HIGH_WINRATE` trades using:

- `entry_timestamp`
- `entry_price`
- `stop_loss`
- `take_profit`
- `outcome`
- `net_pnl`

Result:

- Old trades: `45`
- New trades: `45`
- Mismatches: `0`

## Current Broken Comparison

Current `PROFILE_F_VOLUME` on the same BTCUSDT March 2025 dataset and `PROFILE_15_10_5` timeframe stack produced:

- Trades: `39`
- Wins: `18`
- Losses: `21`
- Win rate: `46.15384615384615`
- Net PnL: `600.0000000000000000000000000`
- Profit factor: `1.285714285714285714285714286`
- Passed expansion: `200`
- Passed main FVG: `83`
- Direct entries: `39`

## Root Cause

The good profile was removed from the selectable registry and its behavior was replaced by newer Profile F behavior. The important differences were:

- The old profile used the `15M/10M/5M` stack.
- The old profile used expansion ratio `1.0` to `3.0`.
- The old profile used variable structural leg targets, not fixed 1.5R TP.
- The old profile did not require the stricter current C3 expansion filter.
- The old profile did not use linked strategy FVG detection for the main timeframe.
- The old profile associated a bearish main-timeframe FVG when it formed on the expansion candle or the next same-timeframe candle. The stricter current matcher required the FVG C2 timestamp to equal the expansion timestamp, reducing main FVG passes from `116` to `83`.

## Files Updated

- `backend/arjiobot/backtesting/research_profiles.py`
- `scripts/backtest_csv.py`
- `backend/arjiobot/api/routes/backtesting.py`
- `frontend/src/api/backtesting.ts`
- `frontend/src/pages/Backtesting.tsx`
- `frontend/src/utils/constants.ts`
- `backend/arjiobot/backtesting/tests/test_strategy_profiles.py`
- `backend/arjiobot/backtesting/tests/test_csv_backtest_runner.py`
- `backend/arjiobot/api/tests/test_backtesting_routes.py`
- `backend/arjiobot/api/tests/test_frontend_contracts.py`

## Final Statement

Recovered profile is selectable and actively drives backtest logic: YES
