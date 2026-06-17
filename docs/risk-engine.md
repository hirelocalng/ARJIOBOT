# Risk Engine Specification v1.0 - Frozen

Status: frozen after audit and ambiguity review.

The Risk Engine converts Strategy Engine trade signals into risk-approved or
risk-rejected trade plans. It does not place orders, call Bitget, build the
Execution Engine, or mutate Strategy Engine signals.

## Purpose

The Risk Engine consumes:

- TradeSignal objects from Strategy Engine
- Account/equity snapshots
- User risk configuration
- Open trade/position state where available
- Backtest-compatible simulated balance data where live account data is
  unavailable

It produces:

- RiskAssessment objects
- PositionSize objects
- LeveragePlan objects
- TradePlan objects
- Risk rejection reasons
- Risk analytics metadata

## Audit Findings And Amendments

- v1 supports bearish `MARKET_SELL_READY` signals first.
- Risk amount is maximum intended loss at stop. It is not margin, position size,
  notional, or leverage.
- Risk Engine requires `entry_reference_price` in v1.
- Risk Engine must not recalculate `stop_reference_price` or
  `final_target_price`.
- For bearish setups, `stop_reference_price` must come from the 16M swing high.
- For bearish setups, `final_target_price` must come from Setup Tracker and be
  the lower of the 16M FVG completion candle low and the lowest low among the
  first 3 completed 8M candles after the 16M FVG forms.
- Future bullish setups will use the 16M swing low for stop and the higher
  target equivalent.
- Risk Engine validates these references and uses them for sizing only.
- Backtester compatibility uses synthetic account snapshots and open risk state.
- No wall-clock time is required; callers provide `evaluated_at`.

## Core Principle

`risk_amount_per_trade` is the maximum intended loss if stop loss is hit.

For bearish v1:

```text
risk_distance = stop_reference_price - entry_reference_price
position_size = risk_amount_per_trade / risk_distance
notional_value = position_size * entry_reference_price
```

## Required Inputs

TradeSignal fields:

- `signal_id`
- `setup_id`
- `symbol`
- `direction`
- `action`
- `entry_reference_price`
- `stop_reference_price`
- `final_target_price`

RiskConfig fields:

- `account_currency`
- `account_equity`
- `risk_amount_per_trade`
- `max_leverage`
- `max_open_trades`
- `max_daily_loss`
- `max_weekly_loss`
- `min_position_size`
- `max_position_size`
- `max_symbol_exposure`
- `allow_multiple_positions_same_symbol`
- `fee_rate_buffer`
- `slippage_buffer_bps`
- `minimum_rr_ratio`

OpenRiskState fields:

- `open_trade_count`
- `open_symbol_exposure`
- `current_daily_pnl`
- `current_weekly_pnl`
- `reserved_risk_amount`

## Rejection Reasons

Supported:

- `MISSING_ENTRY_REFERENCE_PRICE`
- `INVALID_STOP_RELATIONSHIP`
- `INVALID_TARGET_RELATIONSHIP`
- `RISK_DISTANCE_ZERO_OR_NEGATIVE`
- `RR_TOO_LOW`
- `LEVERAGE_EXCEEDS_MAX`
- `MAX_OPEN_TRADES_REACHED`
- `DAILY_LOSS_LIMIT_REACHED`
- `WEEKLY_LOSS_LIMIT_REACHED`
- `POSITION_SIZE_TOO_SMALL`
- `POSITION_SIZE_TOO_LARGE`
- `SAME_SYMBOL_EXPOSURE_BLOCKED`
- `SYMBOL_EXPOSURE_LIMIT_REACHED`
- `ACCOUNT_EQUITY_TOO_LOW`
- `INVALID_RISK_CONFIG`
- `UNSUPPORTED_SIGNAL_ACTION`
- `UNKNOWN_RISK_ERROR`

## Service API

Expose:

- `assess_signal(signal, risk_config, account_snapshot, open_risk_state)`
- `create_trade_plan(signal, risk_config, account_snapshot, open_risk_state)`
- `get_assessment_by_id(assessment_id)`
- `get_trade_plan_by_id(trade_plan_id)`
- `get_trade_plan_by_signal_id(signal_id)`
- `get_approved_trade_plans(symbol=None)`
- `get_rejected_trade_plans(symbol=None, reason=None)`
- `update_trade_plan_status(trade_plan_id, status, changed_at, reason=None)`

## Known Limitations

- v1 supports bearish `MARKET_SELL_READY` only.
- v1 does not call Bitget or place orders.
- v1 does not implement Execution Engine behavior.
- v1 uses deterministic in-memory stores behind service APIs.

## Final Validation Report

Model Tests: PASS

Position Sizing Tests: PASS

Leverage Tests: PASS

Loss-Limit Tests: PASS

Exposure Tests: PASS

Signal Risk Validation Tests: PASS

Risk Engine Service Tests: PASS

Integration Tests: PASS

Report Generation Output: PASS

Reports Generated:

- `arjiobot/risk/reports/risk_validation_report.html`
- `arjiobot/risk/reports/risk_validation_report.png`

Tests Executed: 18

Tests Passed: 18

Position Sizing Validation: PASS. Position size is calculated from
`risk_amount_per_trade` and bearish stop distance.

Leverage Validation: PASS. Required leverage is calculated from notional and
available margin, then capped by `max_leverage`.

Loss-Limit Validation: PASS. Daily, weekly, and reserved-risk capacity checks
reject plans that exceed configured limits.

Exposure Validation: PASS. Same-symbol exposure and symbol exposure cap checks
reject invalid plans.

Trade Plan Validation: PASS. Approved plans carry forward
`stop_reference_price` as `stop_loss_price` and `final_target_price` as
`take_profit_price` from the Strategy Engine signal.

Stop / Target Contract Validation: PASS. The Risk Engine does not recalculate
stop or target references. It only validates that bearish stop is above entry
and bearish target is below entry.

Backtester Compatibility Validation: PASS. Risk Engine accepts deterministic
account snapshots and open risk state without depending on live exchange data.

Execution Compatibility Validation: PASS. Approved TradePlan objects include
execution-relevant fields, but Risk Engine does not submit orders.

Benchmark Results: PASS. Benchmark helper reports signal count, duration in
milliseconds, and signals per second.

Known Limitations:

- v1 supports bearish `MARKET_SELL_READY` only.
- v1 requires `entry_reference_price`; missing entry references are rejected.
- v1 does not call Bitget or place orders.
- v1 does not implement Execution Engine behavior.
- v1 uses deterministic in-memory stores behind service APIs.

Ready For Integration: YES

Recommendation: freeze the Risk Engine and integrate it as the authoritative
risk-assessment and trade-plan service for future Execution Engine consumers.
Execution modules must consume approved TradePlan objects and must not
recalculate strategy stop/target references independently.
