# Setup Tracker Specification v1.0 - Frozen

Status: frozen after audit and ambiguity review.

The Setup Tracker is the authoritative setup-state service for ArjioBot. It
tracks setup state, progress, lifecycle, timing, invalidation, and
analytics-ready metadata. It does not place trades, calculate risk, execute
orders, or implement the Strategy Engine.

## Purpose

The Setup Tracker consumes:

- Market Data candles
- Swing objects from the Swing Engine
- Expansion objects from the Expansion Engine
- FVG objects from the FVG Engine

It produces:

- Setup objects
- Setup lifecycle state
- Setup progress percentage
- Setup invalidation reason
- Setup timing metadata
- Setup analytics metadata
- Queryable setup radar data

Downstream modules must not independently reconstruct setup state.

## Audit Findings And Amendments

- v1 implements bearish setup tracking first with `direction = BEARISH`.
- Data structures use a direction enum so bullish setup tracking can be added
  later without redesign.
- Setup progress uses the requested additive milestone weights and is clamped
  to `0.0 - 100.0`.
- State transitions are deterministic and service-owned.
- Historical replay consumes ordered events and uses event timestamps only.
- No wall-clock time is used for setup IDs or replay state.
- Retracement window checks the first three completed 8M candles after 16M FVG
  formation.
- The FVG Engine remains authoritative for FVG tap geometry. Setup Tracker uses
  the FVG service/rules rather than reimplementing generic FVG detection.
- Any 1M candle intersecting the 12M bearish FVG and closing above its upper
  boundary invalidates with `CLOSE_ABOVE_12M_FVG`.
- More than two 1M new highs inside the 12M FVG invalidates with
  `THIRD_HIGH_INSIDE_12M_FVG` or `CONSOLIDATION_INSIDE_12M_FVG`.
- Entry ready is a tracked state only. No order, risk, or execution behavior is
  included.

## Bearish Setup Flow

The Setup Tracker tracks this sequence:

1. HTF FVG exists
2. 16M swing high forms inside/tapping HTF FVG
3. 16M expansion candle validates the swing
4. 16M bearish FVG forms
5. 12M bearish FVG exists within the valid 16M leg
6. 8M bearish FVG exists within the valid 16M leg
7. Price retraces into the 12M FVG within the next 3 completed 8M candles
8. 1M confirmation phase begins
9. 1M swing high forms inside the 12M FVG reaction zone
10. 1M bearish FVG forms
11. Price returns to the first or second 1M bearish FVG
12. Entry Ready

## State Model

Supported states:

- `WATCHING_HTF_FVG`
- `HTF_FVG_TAPPED`
- `SWING_16M_CONFIRMED`
- `EXPANSION_16M_CONFIRMED`
- `FVG_16M_CONFIRMED`
- `FVG_12M_CONFIRMED`
- `FVG_8M_CONFIRMED`
- `WAITING_FOR_12M_RETRACE`
- `ONE_MINUTE_CONFIRMATION_ACTIVE`
- `ONE_MINUTE_SWING_CONFIRMED`
- `ONE_MINUTE_FVG_CONFIRMED`
- `ENTRY_READY`
- `INVALIDATED`
- `EXPIRED`
- `COMPLETED`

## Progress Scoring

Milestone weights:

- HTF FVG found: 15%
- 16M swing high: 20%
- 16M expansion: 15%
- 16M FVG: 15%
- 12M FVG: 10%
- 8M FVG: 10%
- Retracement into 12M FVG: 5%
- 1M swing high: 5%
- 1M FVG: 3%
- Entry ready: 2%

Total: 100%.

The scoring system is pluggable.

## Setup Object Fields

Every setup stores:

- `setup_id`
- `symbol`
- `direction`
- `current_state`
- `progress_percent`
- `status`
- `created_at`
- `updated_at`
- `invalidated_at`
- `invalidation_reason`
- `completed_at`
- `htf_fvg_id`
- `swing_16m_id`
- `expansion_16m_id`
- `fvg_16m_id`
- `fvg_12m_id`
- `fvg_8m_id`
- `retrace_tap_candle_id`
- `one_minute_swing_id`
- `one_minute_fvg_ids`
- `entry_fvg_id`
- `stop_reference_price`
- `target_a_price`
- `target_b_price`
- `final_target_price`
- `time_remaining`
- `state_history`
- `watched_timeframes`
- `metadata`

## State History

Every transition records:

- `from_state`
- `to_state`
- `changed_at`
- `reason`
- `triggering_object_type`
- `triggering_object_id`

## Invalidation Reasons

Supported reasons:

- `HTF_FVG_INVALID`
- `SWING_NOT_CONFIRMED`
- `EXPANSION_NOT_CONFIRMED`
- `FVG_16M_NOT_FOUND`
- `FVG_12M_NOT_FOUND`
- `FVG_8M_NOT_FOUND`
- `FVG_OUTSIDE_16M_LEG`
- `RETRACE_WINDOW_EXPIRED`
- `CLOSE_ABOVE_12M_FVG`
- `THIRD_HIGH_INSIDE_12M_FVG`
- `CONSOLIDATION_INSIDE_12M_FVG`
- `PRICE_REACHED_TARGET_BEFORE_ENTRY`
- `SETUP_EXPIRED`
- `MANUAL_INVALIDATION`

## Query API

Expose:

- `get_setup_by_id(setup_id)`
- `get_active_setups(symbol=None)`
- `get_setups_by_state(state, symbol=None)`
- `get_setups_above_progress(progress, symbol=None)`
- `get_entry_ready_setups(symbol=None)`
- `get_invalidated_setups(symbol=None, reason=None)`
- `get_setup_radar(symbol=None)`
- `get_setups_between(start, end, symbol=None, status=None)`
- `get_state_history(setup_id)`

## Update API

Expose:

- `create_setup()`
- `advance_setup_state()`
- `invalidate_setup()`
- `expire_setup()`
- `mark_entry_ready()`
- `update_progress()`
- `record_state_transition()`
- `update_target_references()`
- `update_stop_reference()`

## Reports

Generate:

- `arjiobot/setup_tracker/reports/setup_tracker_validation_report.html`
- `arjiobot/setup_tracker/reports/setup_tracker_validation_report.png`

Reports must show setup lifecycle timeline, progress percentages, state
transitions, invalidation examples, entry-ready example, radar table, and PASS /
FAIL summary.

## Known Limitations

- v1 tracks setup state and readiness but does not implement Strategy Engine
  trade decisions.
- v1 stores setup state in memory behind deterministic service APIs.
- v1 implements bearish setup validation first; bullish support is represented
  in the model but not yet orchestrated.

## Stop And Target Reference Contract

For bearish setups:

- `stop_reference_price` comes from the 16M swing high.
- `final_target_price` is computed by the Setup Tracker.
- `final_target_price` is the lower of:
  - low of the 16M FVG completion candle
  - lowest low among the first 3 completed 8M candles after the 16M FVG forms

For future bullish setups:

- `stop_reference_price` will come from the 16M swing low.
- `final_target_price` will be the higher target equivalent:
  - high of the 16M FVG completion candle
  - highest high among the first 3 completed 8M candles after the 16M FVG forms

## Final Validation Report

Model Tests: PASS

State Machine Tests: PASS

Progress Scoring Tests: PASS

Invalidation Tests: PASS

Timing Tests: PASS

Service / Query Tests: PASS

Integration Tests: PASS

Historical Replay Support: PASS

Live Incremental Update Support: PASS

Report Generation Output: PASS

Reports Generated:

- `arjiobot/setup_tracker/reports/setup_tracker_validation_report.html`
- `arjiobot/setup_tracker/reports/setup_tracker_validation_report.png`

Tests Executed: 23

Tests Passed: 23

Report Note: `Tests Executed` and `Tests Passed` are a static validation
summary in the demo report. Live pytest output is produced by the test runner.

State Transition Validation: PASS. Setup transitions are service-owned and
record deterministic state history entries.

Progress Scoring Validation: PASS. Milestone weights add to 100% and are
clamped to `0.0 - 100.0`.

Invalidation Validation: PASS. Retrace window expiration, close above 12M FVG,
third high inside 12M FVG, manual invalidation, and price-target-before-entry
paths are represented.

Radar Validation: PASS. Radar output includes setup ID, symbol, direction,
state, progress, missing requirements, invalidation reason, time remaining,
watched timeframes, target reference, and stop reference.

Replay Validation: PASS. Ordered replay events produce deterministic setup IDs
and states without wall-clock time.

Benchmark Results: PASS. Benchmark helper reports setup count, duration in
milliseconds, and setups per second.

Known Limitations:

- v1 tracks bearish setups first.
- v1 does not implement Strategy Engine trade decisions.
- v1 does not calculate risk or execute orders.
- v1 persistence is in-memory behind deterministic service APIs.

Ready For Integration: YES

Recommendation: freeze the Setup Tracker and integrate it as the authoritative
setup-state source for future Strategy Engine, Analytics, Backtester, and radar
dashboard consumers. Do not let downstream modules reconstruct setup state
independently.
