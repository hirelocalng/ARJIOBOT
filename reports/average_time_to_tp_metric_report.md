# Average Time To Hit TP Validation

Status: PASS

## Scope

Added reporting-only Average Time To Hit TP metrics for backtest outputs. No strategy logic, profile rules, entry rules, or risk rules were changed.

## Metrics Added

- average_time_to_hit_tp_seconds
- average_time_to_hit_tp_minutes
- average_time_to_hit_tp_human
- fastest_time_to_hit_tp
- slowest_time_to_hit_tp
- median_time_to_hit_tp

## Inclusion Rules

- Includes only trades with outcome WIN.
- Includes only trades whose exit reason indicates TP was reached.
- Requires entry and exit timestamps.
- Ignores losses, breakeven/manual exits, SL exits, unresolved trades, missing timestamps, and invalid timestamps.
- Returns null values and N/A human text when no eligible winning TP trades exist.

## Output Surfaces

- JSON backtest report performance_summary: PASS
- HTML backtest report Performance Summary table: PASS
- Frontend Backtest Details Performance Summary panel: PASS
- TP optimization CSV/export summary fields: PASS

## Validation

- Backtesting tests: 39 passed
- Frontend production build: PASS

Average Time To Hit TP is now included in backtest reports: YES
