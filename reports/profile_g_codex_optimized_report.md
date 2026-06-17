# Profile G Codex Optimized Research Report

Generated: 2026-06-18

## Profile Name

`PROFILE_G_CODEX_OPTIMIZED`

Classification: `RESEARCH ONLY`

Production impact: `STRICT_PROFILE` unchanged. Profile F variants unchanged. Profile G is additive and selectable for backtesting only unless promoted later.

## Full Logic Definition

Profile G keeps the core Arjio structure:

- Swing displacement
- C3 expansion tied to the swing formation
- 16M bearish FVG formed by the same displacement leg
- 12M FVG on the same leg used as the retracement zone
- 8M FVG on the same leg required
- 1M candle retrace into the 12M FVG
- One trade per 12M FVG
- No fake or synthesized trades

Default parameters:

- Timeframe set: `DEFAULT_16_12_8`
- Swing timeframe: `16M`
- Main FVG timeframe: `16M`
- Retrace FVG timeframe: `12M`
- Internal FVG timeframe: `8M`
- Entry timeframe: `1M`
- Expansion min: `1.0`
- Expansion max: `4.0`
- Retracement window: `3` completed 8M candles
- Entry model: `DIRECT_12M_RETRACE`
- TP model: `RR_1_0_RESEARCH`
- Stop source: 16M swing high/low
- Fixed risk sizing: enabled

## Why This Profile Was Selected

Existing diagnostics showed two major blockers:

- Strict produced high selectivity but too few entries.
- Profile F Volume generated the best frequency, but the 1.5R target increased losses from immediate adverse reaction and weak expansions.

The TP optimization report showed the best frequency plus validation stability came from the Profile F Volume structure with a 1R research TP:

- 37 total trades
- Positive net PnL
- Positive validation PnL
- Lower drawdown than the 1.5R run
- More stable validation than wider TP variants

Profile G saves that discovered configuration as a real selectable research profile.

## Fresh Backtest Result

Dataset: `ArjioBot/data/SOLUSDT-1m-2026-04.csv`

Result:

- Profile: `PROFILE_G_CODEX_OPTIMIZED`
- Trades: `37`
- Closed trades: `36`
- Wins: `19`
- Losses: `17`
- Win rate: `52.78%`
- Net PnL: `200`
- Profit factor: `1.1176`
- Max drawdown: `500`
- Expectancy: `5.56`
- Validation status: profitable in prior train/validation optimization split

Report outputs:

- JSON: `ArjioBot/reports/backtests/bt_b7b935523bca7ad60b56795d.json`
- HTML: `ArjioBot/reports/backtests/bt_b7b935523bca7ad60b56795d.html`

## Comparison Against Existing Profiles

Best known existing candidates from generated optimization reports:

- `PROFILE_F_VOLUME + RR_1_5_CURRENT`: 37 trades, 44.44% win rate, net PnL 400, profit factor 1.20, validation net PnL -100.
- `PROFILE_F_VOLUME + RR_1_0`: 37 trades, 52.78% win rate, net PnL 200, profit factor 1.1176, validation net PnL 100.
- `PROFILE_F_SELECTIVE + RR_1_5_CURRENT`: 10 trades, 50.00% win rate, net PnL 250, profit factor 1.50, validation net PnL 200.
- `PROFILE_F_VOLUME + 16M_FVG_BOUNDARY`: 9 trades, 88.89% win rate, net PnL 159.7, profit factor 2.597, too few trades.

Profile G does not claim the highest profit factor in isolation. It was selected because it produced the strongest balance of trade count, validation profitability, and realistic execution from the available sample.

## Target Check

- Minimum 25 trades per month: `YES`
- Around 70% win rate: `NO`
- Positive net PnL: `YES`
- Profit factor above all existing profiles: `NO`
- Controlled drawdown: `PARTIAL`
- No fake/synthesized trades: `YES`

## Frontend Tunable Variables

Profile G exposes these backtesting-only controls:

- Expansion min
- Expansion max
- Retrace window in completed 8M candles
- TP model: `RR_1_0_RESEARCH` or `RR_1_5`
- Timeframe profile selector, including `DEFAULT_16_12_8`, `PROFILE_15_10_5`, `PROFILE_30_16_8`, `PROFILE_12_8_4`, and `PROFILE_8_4_2`

The backend validates Profile G overrides and rejects invalid ranges.

## Final Recommendation

`PROFILE_G_CODEX_OPTIMIZED` is ready for research backtesting and frontend selection.

It is not ready for production promotion yet because the 70% win-rate and profit-factor targets were not achieved on the current SOLUSDT April dataset. Use it as the new tunable research baseline for broader multi-month, multi-symbol validation.
