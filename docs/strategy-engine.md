# Strategy Engine Specification v1.0 - Frozen

Status: frozen after audit and ambiguity review.

The Strategy Engine converts fully validated `ENTRY_READY` setups into
deterministic trade signal objects. It does not place trades, calculate
position size, call Bitget, calculate leverage, or inspect account balance.

## Purpose

The Strategy Engine consumes:

- Setup objects from Setup Tracker
- Swing objects from Swing Engine
- Expansion objects from Expansion Engine
- FVG objects from FVG Engine
- Market Data candles only when needed for final validation

It produces:

- TradeSignal objects
- Signal lifecycle state
- Signal validation metadata
- Signal rejection reason
- Replay-safe signal records

The Strategy Engine is the single source of truth for whether a setup becomes a
trade signal.

## Audit Findings And Amendments

- v1 supports bearish signal generation first.
- Data structures include direction/action enums so bullish support can be added
  later without redesign.
- `setup.current_state == ENTRY_READY` and `setup.status == ENTRY_READY` are
  required for signal generation.
- The request says setup status must be active/valid. The frozen Setup Tracker
  marks entry-ready setups with `SetupStatus.ENTRY_READY`; v1 treats that as
  valid for signal generation.
- Rejected attempts are stored as rejected TradeSignal records for analytics.
- Only one generated signal may exist for a `setup_id`.
- A duplicate attempt after a generated signal is stored as a rejected signal
  with `DUPLICATE_SIGNAL`.
- No wall-clock time is used. Signal IDs use setup identity and event
  timestamps.
- If an entry reference price is unavailable, the signal can still be valid as
  long as `stop_reference_price > final_target_price` for bearish setups.
- If an entry reference price is available, bearish validation also requires
  `stop_reference_price > entry_reference_price > final_target_price`.
- If latest relevant price is at or below the final target before signal
  generation, the setup is rejected with `TARGET_ALREADY_REACHED`.

## Responsibility

The Strategy Engine answers only:

```text
Should this ENTRY_READY setup become a trade signal?
```

It must not answer:

- What is the position size?
- What leverage should be used?
- Should Bitget place an order?
- What is the account balance?

## V1 Signal

For bearish v1:

- `direction = BEARISH`
- `action = MARKET_SELL_READY`
- `entry_reference_type = MARKET_SELL`

## Required Validation

Before generating a signal, validate:

1. `setup_id` exists
2. `symbol` exists
3. direction is `BEARISH`
4. setup is `ENTRY_READY`
5. setup is not invalidated
6. setup has `htf_fvg_id`
7. setup has `swing_16m_id`
8. setup has `expansion_16m_id`
9. setup has `fvg_16m_id`
10. setup has `fvg_12m_id`
11. setup has `fvg_8m_id`
12. setup has `one_minute_swing_id`
13. setup has `entry_fvg_id`
14. `stop_reference_price` exists
15. `final_target_price` exists
16. stop reference is above entry reference when entry reference exists
17. final target is below entry reference when entry reference exists
18. price has not already hit final target before signal generation
19. setup has not expired
20. signal has not already been generated for this setup

## Signal Object Fields

Every TradeSignal stores:

- `signal_id`
- `setup_id`
- `symbol`
- `direction`
- `action`
- `status`
- `created_at`
- `updated_at`
- `generated_at`
- `entry_reference_type`
- `entry_reference_price`
- `stop_reference_price`
- `final_target_price`
- `risk_engine_status`
- `execution_status`
- `validation_passed`
- `validation_errors`
- `rejection_reason`
- `source_state`
- `source_progress_percent`
- `htf_fvg_id`
- `swing_16m_id`
- `expansion_16m_id`
- `fvg_16m_id`
- `fvg_12m_id`
- `fvg_8m_id`
- `one_minute_swing_id`
- `entry_fvg_id`
- `metadata`

## Signal Status

Supported:

- `GENERATED`
- `REJECTED`
- `SENT_TO_RISK_ENGINE`
- `RISK_APPROVED`
- `RISK_REJECTED`
- `SENT_TO_EXECUTION`
- `EXECUTED`
- `CANCELLED`
- `EXPIRED`

v1 creates only `GENERATED` or `REJECTED`.

## Rejection Reasons

Supported:

- `SETUP_NOT_ENTRY_READY`
- `SETUP_INVALIDATED`
- `SETUP_EXPIRED`
- `MISSING_REQUIRED_FIELD`
- `INVALID_DIRECTION`
- `DUPLICATE_SIGNAL`
- `TARGET_ALREADY_REACHED`
- `INVALID_STOP_TARGET_RELATIONSHIP`
- `UNSUPPORTED_DIRECTION`
- `UNKNOWN_VALIDATION_ERROR`

## Service API

Expose:

- `generate_signal_from_setup(setup)`
- `validate_setup_for_signal(setup)`
- `get_signal_by_id(signal_id)`
- `get_signal_by_setup_id(setup_id)`
- `get_generated_signals(symbol=None)`
- `get_rejected_signals(symbol=None, reason=None)`
- `get_signals_between(start, end, symbol=None, status=None)`
- `mark_signal_status(signal_id, status, changed_at, reason=None)`

## Reports

Generate:

- `arjiobot/strategy/reports/strategy_validation_report.html`
- `arjiobot/strategy/reports/strategy_validation_report.png`

Reports must show setups evaluated, generated signals, rejected signals,
rejection reasons, signal lifecycle table, and PASS / FAIL summary.

## Known Limitations

- v1 supports bearish signal generation only.
- v1 does not calculate position size, risk, leverage, or execution details.
- v1 stores signals in memory behind deterministic service APIs.

## Stop And Target Reference Contract

The Strategy Engine carries forward `stop_reference_price` and
`final_target_price` from the Setup Tracker. It must not recalculate these
values.

For bearish setups:

- stop loss reference = 16M swing high
- take profit reference = lower of:
  - low of the 16M FVG completion candle
  - lowest low among the first 3 completed 8M candles after the 16M FVG forms

For future bullish setups:

- stop loss reference = 16M swing low
- take profit reference = higher of:
  - high of the 16M FVG completion candle
  - highest high among the first 3 completed 8M candles after the 16M FVG forms

## Final Validation Report

Model Tests: PASS

Signal Validation Tests: PASS

Signal Generation Tests: PASS

Deduplication Tests: PASS

Replay Tests: PASS

Integration Tests: PASS

Live Event Processing Support: PASS

Report Generation Output: PASS

Reports Generated:

- `arjiobot/strategy/reports/strategy_validation_report.html`
- `arjiobot/strategy/reports/strategy_validation_report.png`

Tests Executed: 22

Tests Passed: 22

Signal Validation Result: PASS. The engine accepts only valid bearish
`ENTRY_READY` setups with required references and rejects invalidated, expired,
incomplete, unsupported, target-reached, and invalid stop/target setups.

Deduplication Validation: PASS. Only one generated signal can exist per
`setup_id`; duplicate attempts are stored as rejected signal records with
`DUPLICATE_SIGNAL`.

Replay Validation: PASS. Replaying the same setup sequence with the same event
timestamps produces deterministic signal IDs and outcomes.

Benchmark Results: PASS. Benchmark helper reports setup count, signal count,
duration in milliseconds, and setups per second.

Known Limitations:

- v1 generates bearish `MARKET_SELL_READY` signals only.
- v1 does not calculate position size, risk, leverage, or execution details.
- v1 does not call Bitget or place orders.
- v1 persistence is in-memory behind deterministic service APIs.

Ready For Integration: YES

Recommendation: freeze the Strategy Engine and integrate it as the
authoritative setup-to-signal source for the future Risk Engine. Downstream
modules must consume TradeSignal objects and must not independently decide
whether a setup becomes a signal.
