# Swing Detection Engine Specification

Status: frozen after approval.

This document is the source of truth for all Swing Detection Engine
implementation work. Future code changes, tests, and downstream integrations
must conform to this specification unless this document is updated and approved.

## Purpose

The Swing Detection Engine is the first market structure and validation layer of
the Arjio strategy.

It is responsible for detecting, storing, updating, and exposing swing highs and
swing lows across all monitored timeframes. It must preserve enough information
for downstream strategy modules to make deterministic decisions without
rescanning candles.

This module is a foundational dependency for:

- Expansion candle validation
- FVG validation
- Setup tracking
- Strategy execution
- Analytics
- Backtesting
- Replay

Accuracy and replay correctness are more important than feature count.

## Ownership

This module is responsible for:

- Detecting swing highs
- Detecting swing lows
- Storing swing objects
- Tracking swing lifecycle state
- Tracking swing strength
- Tracking relative structure metadata
- Tracking strategy validation flags
- Exposing market structure query APIs
- Supporting historical scans
- Supporting incremental live processing
- Acting as the authoritative market structure service

This module is not responsible for:

- Detecting FVGs
- Detecting expansion candles
- Creating trade entries
- Creating trade exits
- Scoring complete trade setups
- Risk management
- Order execution

Downstream systems must consume swing objects from this engine. They must not
perform independent swing scans or maintain parallel swing state.

## System Flow

```text
Market Data Layer
Swing Detection Engine
Expansion Candle Engine
FVG Engine
Setup Tracker
Strategy Engine
Risk Engine
Execution Engine
```

## Files

The Swing Detection Engine lives in:

```text
arjiobot/
  swings/
    swing_models.py
    swings.py
    demo_swings.py
    tests/
      test_swings.py
```

## Candle Input

Input candles come from the Market Data Layer.

The engine must support:

- 1 minute
- 8 minute
- 12 minute
- 16 minute
- 30 minute
- 1 hour
- Any future timeframe

The engine must never hardcode timeframe values.

Input candle validation requirements:

- Candles in a detection window must share the same symbol.
- Candles in a detection window must share the same timeframe.
- Candles must be strictly ordered by timestamp for detection.
- Duplicate candle timestamps are invalid.
- Historical scans may sort input before detection.
- Live processing must process closed candles in arrival order per symbol and
  timeframe.

## Swing High Definition

A swing high consists of three consecutive candles.

- C1 = left candle
- C2 = middle candle
- C3 = right candle

A swing high is valid when:

```text
High(C2) > High(C1)
High(C2) > High(C3)
```

If both conditions are true, create a `SwingHigh` object.

## Swing Low Definition

A swing low consists of three consecutive candles.

- C1 = left candle
- C2 = middle candle
- C3 = right candle

A swing low is valid when:

```text
Low(C2) < Low(C1)
Low(C2) < Low(C3)
```

If both conditions are true, create a `SwingLow` object.

## Confirmation Timing

A swing is not confirmed until C3 closes.

Every swing must store:

- `candidate_detected_at`
- `confirmed_at`

Definitions:

- `candidate_detected_at`: timestamp of the middle candle, C2.
- `confirmed_at`: timestamp at which C3 is closed and the swing becomes known.

The system must never allow future candles after C3 to influence swing
confirmation. No lookahead bias is allowed.

Backtests and replay must only expose a swing after `confirmed_at`.

## Swing Object Fields

Every detected swing must store:

- `swing_id: str`
- `symbol: str`
- `timeframe: Timeframe`
- `timestamp: datetime`
- `candidate_detected_at: datetime`
- `confirmed_at: datetime`
- `swing_type: SwingType`
- `price: Decimal`
- `candle_index: int`
- `left_candle: Candle`
- `middle_candle: Candle`
- `right_candle: Candle`
- `source_candle_ids: tuple[str, str, str]`
- `status: SwingStatus`
- `strength_score: float`
- `previous_swing_high_id: str | None`
- `previous_swing_low_id: str | None`
- `structure_label: StructureLabel | None`
- `parent_swing_id: str | None`
- `is_strategy_candidate: bool`
- `touched_htf_fvg: bool`
- `valid_for_strategy: bool`
- `expansion_confirmed: bool`
- `created_at: datetime`
- `updated_at: datetime`
- `status_updated_at: datetime | None`
- `broken_at: datetime | None`
- `broken_by_candle_id: str | None`
- `metadata: dict[str, str]`

Field definitions:

- `swing_id`: stable deterministic identifier for the swing.
- `symbol`: market symbol, normalized uppercase.
- `timeframe`: timeframe of the three source candles.
- `timestamp`: timestamp of the middle candle, C2.
- `candidate_detected_at`: same market timestamp as C2.
- `confirmed_at`: timestamp when C3 is closed and the swing can be used.
- `swing_type`: `HIGH` or `LOW`.
- `price`: high of C2 for swing highs, low of C2 for swing lows.
- `candle_index`: index of C2 within the processed candle sequence.
- `left_candle`: C1 snapshot.
- `middle_candle`: C2 snapshot.
- `right_candle`: C3 snapshot.
- `source_candle_ids`: stable IDs for C1, C2, and C3.
- `status`: lifecycle state.
- `strength_score`: pluggable strength score from `0.0` to `100.0`.
- `previous_swing_high_id`: previous swing high for same symbol/timeframe, if any.
- `previous_swing_low_id`: previous swing low for same symbol/timeframe, if any.
- `structure_label`: optional future label: `HH`, `LH`, `HL`, or `LL`.
- `parent_swing_id`: optional parent swing for hierarchy or higher timeframe links.
- `is_strategy_candidate`: default `False`.
- `touched_htf_fvg`: default `False`.
- `valid_for_strategy`: default `False`.
- `expansion_confirmed`: default `False`.
- `created_at`: when the swing record was created.
- `updated_at`: when the swing record was last updated.
- `status_updated_at`: when lifecycle status last changed.
- `broken_at`: market timestamp when the swing became broken.
- `broken_by_candle_id`: candle ID that caused the break.
- `metadata`: extension field for non-critical future data.

## Swing Lifecycle

Every swing must maintain a lifecycle state in `status`.

Allowed values:

- `ACTIVE`
- `BROKEN`
- `MITIGATED`

Default:

- `ACTIVE`

### Broken State

A swing high becomes `BROKEN` when the high of a later candle exceeds the swing
high price.

A swing low becomes `BROKEN` when the low of a later candle breaches below the
swing low price.

Broken state uses wick breach. Candle close is not required.

When a swing becomes broken, store:

- `broken_at`
- `broken_by_candle_id`
- `status_updated_at`

### Mitigated State

Mitigation is not currently used by the strategy.

The engine must support the `MITIGATED` state, but mitigation transition rules
must remain configurable. Do not hardcode mitigation behavior in the base swing
definition.

### State Ownership

Status transition rules are owned by the Swing Engine as the authoritative
market structure service. Downstream modules may request status changes through
the service API, but they must not mutate swing state directly.

The design must support future state transitions without modifying downstream
modules.

## Swing Strength

Every swing must include:

```text
strength_score: float
```

Range:

```text
0.0 - 100.0
```

The score must be clamped to this range.

The scorer must be pluggable.

The initial implementation must not always return `0.0`. Initial score should
consider:

- Timeframe weight
- Distance from previous swing
- Candle range
- Displacement size

Future versions may also use:

- Volatility
- Structure significance
- Higher timeframe confirmation
- Liquidity context
- Arjio-specific validation layers

The swing model must not assume one permanent scoring formula.

## Relative Structure Metadata

Every swing must support:

- `previous_swing_high_id`
- `previous_swing_low_id`
- `structure_label`
- `parent_swing_id`

These fields support future market structure analysis:

- Higher High (`HH`)
- Lower High (`LH`)
- Higher Low (`HL`)
- Lower Low (`LL`)

Using IDs avoids repeated rescans. If a previous swing or parent swing does not
exist, the relevant field must be `None`.

`structure_label` may initially be `None` until structure classification is
implemented.

## Strategy Validation Flags

Every swing must support:

- `is_strategy_candidate: bool`
- `touched_htf_fvg: bool`
- `valid_for_strategy: bool`
- `expansion_confirmed: bool`

Defaults:

- `is_strategy_candidate = False`
- `touched_htf_fvg = False`
- `valid_for_strategy = False`
- `expansion_confirmed = False`

These flags will later be populated by:

- Expansion Engine
- FVG Engine
- Strategy Engine

The Swing object must be capable of carrying strategy state without requiring a
parallel object hierarchy.

Downstream modules must update these flags through the Swing Engine service API.

## Detection Engine Requirements

The engine must provide historical detection:

- `detect_swing_highs(candles)`
- `detect_swing_lows(candles)`
- `detect_all_swings(candles)`

The engine must provide incremental detection:

- `process_closed_candle(candle)`

Historical scans may process a full candle sequence.

Live streaming updates must avoid rescanning the entire candle history whenever
a new candle closes. The architecture must evaluate only the newly formed
window and maintain enough rolling context per `(symbol, timeframe)`.

For the three-candle swing definition, a live swing is confirmed only after the
right candle arrives and closes.

## Query API

The Swing Engine must expose a stable service contract:

- `get_swing_by_id(swing_id)`
- `get_latest_swing_high(symbol, timeframe)`
- `get_latest_swing_low(symbol, timeframe)`
- `get_active_swings(symbol=None, timeframe=None)`
- `get_swings_between(symbol, timeframe, start, end, swing_type=None, status=None)`
- `get_swings_for_timeframe(symbol, timeframe, swing_type=None, status=None, limit=None)`

These methods will be consumed by:

- Expansion Engine
- FVG Engine
- Setup Tracker
- Analytics
- Backtesting Engine
- Replay Engine

The query API must return structured swing objects, not raw dictionaries.

## Update API

The Swing Engine must expose centralized update methods:

- `update_swing_status(swing_id, status, changed_at, reason=None)`
- `mark_strategy_candidate(swing_id, is_candidate=True)`
- `update_strategy_flags(swing_id, touched_htf_fvg=None, valid_for_strategy=None, expansion_confirmed=None)`
- `update_structure_metadata(swing_id, structure_label=None, parent_swing_id=None)`

Downstream modules must use these methods instead of mutating swing objects
directly.

## Storage Requirements

The store must preserve at minimum:

- `swing_id`
- `symbol`
- `timeframe`
- `timestamp`
- `confirmed_at`
- `swing_type`
- `price`
- `status`
- `strength_score`
- `source_candle_ids`

The engine must not rely only on embedded candle objects.

Backtesting and replay engines must be able to reconstruct swings
deterministically from historical data.

Required indexes or equivalent lookup structures:

- `swing_id`
- `(symbol, timeframe, swing_type, timestamp)`
- `(symbol, timeframe, status)`
- `(symbol, timeframe, confirmed_at)`

## Replay Compatibility

The Swing Engine must support future setup replay.

Every swing should be reproducible from historical data.

Given:

- `symbol`
- `timeframe`
- `timestamp`

The system should be able to reconstruct the exact swing that existed at that
moment in time.

Replay must respect `confirmed_at` and must never expose a swing before it was
known in historical time.

## Performance Requirements

The bot may eventually monitor:

- 10 pairs
- 50 pairs
- 100 pairs

Therefore:

- Historical scans should be O(n).
- Combined high/low detection should happen in one pass where possible.
- Live updates must be incremental.
- Buffers must be keyed by `(symbol, timeframe)`.
- Previous swing references must be maintained without repeated full rescans.
- Query paths must use indexed storage or equivalent efficient lookup
  structures.

## Validation Requirements

The module must include:

- Unit tests
- Integration tests
- Sample datasets
- Demo scripts

Tests must cover:

- Swing high detected correctly
- Swing low detected correctly
- False positives rejected
- Equal highs rejected
- Equal lows rejected
- Historical scans
- Live streaming updates
- Incremental processing
- No lookahead bias
- Confirmation timing
- Query API behavior
- Update API behavior
- Status defaults
- Broken state wick breach rules
- Mitigated state support without hardcoded transition behavior
- Strength score bounds
- Strength score is not always zero
- Previous swing IDs
- Structure metadata defaults
- Strategy validation flag defaults
- Source candle IDs
- Replay reconstruction requirements

## Validation Report

Historical Tests: PASS

Live Processing Tests: PASS

Query Tests: PASS

Previous Swing Linking: PASS

Benchmark Tests: PASS

Replay Consistency: PASS

Ready For Integration: YES

## Freeze And Integration Recommendation

Recommendation: freeze the Swing Detection Engine specification and proceed
with integration into the Expansion Candle Engine.

All required validation areas have passed, including historical detection, live
incremental processing, query behavior, previous swing linking, benchmark
coverage, and replay consistency. The engine is ready to serve as the
authoritative swing source for downstream Expansion Candle Engine validation.

Integration should consume Swing Engine query and update APIs directly. The
Expansion Candle Engine must not perform independent swing scans or mutate swing
objects outside the Swing Engine service API.

## Logging

Include structured logging.

Required events:

- Swing high detected
- Swing low detected
- Number of swings found
- Detection duration
- Incremental candle processed
- Swing status updated
- Strategy flags updated
- Structure metadata updated

## Downstream Compatibility Notes

Expansion Engine needs exact candle references, source candle IDs,
confirmation timing, and strength score.

FVG Engine needs stable swing IDs, timeframe consistency, and no duplicate
market structure scans.

Setup Tracker consumes Swing objects directly and must rely on centralized
status and strategy flag updates.

Backtesting must only expose swings after `confirmed_at` and must reconstruct
the same swing IDs from the same historical candles.

Analytics needs lifecycle timestamps, status transitions, strategy flags, and
structure metadata.

## Future Extensibility

The architecture must support the following without requiring a rewrite:

- 3-candle swings
- 5-candle swings
- Custom swing definitions
- Arjio-specific validation layers
- Higher-timeframe confirmation rules
- Pluggable strength scoring
- Configurable mitigation behavior
- Swing lifecycle extensions
- Market structure classification
- Parent/child swing hierarchy

Use interfaces and clean abstractions where useful.
