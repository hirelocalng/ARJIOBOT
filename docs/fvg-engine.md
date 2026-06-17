# FVG Engine Specification v1.0 - Frozen

Status: frozen after audit and ambiguity review.

This document is the source of truth for the FVG Engine. Implementation,
tests, reports, and downstream integrations must conform to this specification
unless this document is updated and approved.

## Purpose

The FVG Engine is the authoritative Fair Value Gap service for ArjioBot.

It consumes:

- Market Data candles
- Swing objects from the Swing Engine
- Expansion objects from the Expansion Engine

It produces:

- Generic FVG objects
- Strategy-qualified FVG objects
- FVG lifecycle state
- Tap metadata
- Replay-safe FVG records
- Queryable FVG data for Strategy Engine and Backtester

Downstream modules must never perform independent FVG scans.

## Audit Findings And Amendments

The request defines the generic three-candle FVG rules clearly, but several
strategy and lifecycle areas require v1 amendments:

- Equality is rejected for both bullish and bearish FVGs.
- Generic detection scans candle windows only to identify FVG geometry.
- Strategy qualification requires a related Swing object and related Expansion
  object. The Expansion object must be marked `is_fvg_candidate=True`.
- The request mentions `is_strategy_expansion`; the frozen Expansion Engine
  exposes `is_fvg_candidate`, so v1 uses that field as the integration contract.
- C2 of the FVG window is the displacement candle. For strategy FVGs, C2 must
  match the related Expansion object's timestamp.
- `status` and `lifecycle_state` are both stored for downstream compatibility.
  In v1 they are kept in sync through service methods.
- Generic touch means any candle range intersects the FVG zone, including
  boundary equality.
- Tap updates are centralized through the service API.
- A bearish tap close above `upper_boundary` invalidates the setup. A close
  inside or below the zone remains valid.
- The second high rule is tracked by counting new highs formed inside the FVG
  zone during the confirmation phase.
- A third high inside the zone invalidates the setup as consolidation.
- HTF single-touch behavior is represented by reusable tap/high-count rules;
  full Strategy Engine orchestration is intentionally out of scope.
- Location validation for 12M and 8M strategy FVGs is exposed as a helper using
  the 16M swing high and 16M completion candle low.
- Historical replay must not use wall-clock time. FVG timestamps and IDs are
  derived from candle and relationship data.

## Generic FVG Definition

C1 = first candle
C2 = middle candle / displacement candle
C3 = third candle

Bearish FVG:

```text
Low(C1) > High(C3)
```

Bullish FVG:

```text
High(C1) < Low(C3)
```

Equality does not count.

## Boundaries

For bearish FVG:

```text
upper_boundary = Low(C1)
lower_boundary = High(C3)
```

For bullish FVG:

```text
lower_boundary = High(C1)
upper_boundary = Low(C3)
```

The zone is inclusive for tap checks after the FVG exists.

## Object Fields

Every FVG must store:

- `fvg_id`
- `symbol`
- `timeframe`
- `direction`
- `timestamp`
- `confirmed_at`
- `c1_id`
- `c2_id`
- `c3_id`
- `c1_timestamp`
- `c2_timestamp`
- `c3_timestamp`
- `upper_boundary`
- `lower_boundary`
- `gap_size`
- `gap_size_percent`
- `status`
- `lifecycle_state`
- `touched`
- `touch_count`
- `first_touched_at`
- `last_touched_at`
- `invalidated_at`
- `invalidation_reason`
- `related_swing_id`
- `related_expansion_id`
- `is_strategy_fvg`
- `is_htf_fvg`
- `is_entry_fvg`
- `is_target_fvg`
- `strength_score`
- `created_at`
- `updated_at`
- `fvg_completion_candle_low`

## Lifecycle States

Supported states:

- `ACTIVE`
- `TAPPED`
- `PARTIALLY_FILLED`
- `FILLED`
- `INVALIDATED`
- `EXPIRED`

Default:

- `ACTIVE`

Transitions must happen only through FVG service methods.

## Strategy Rules

Generic FVG does not automatically mean tradeable FVG.

A strategy-qualified bearish FVG requires:

- Valid strict FVG boundaries
- Correct direction
- Related swing exists
- Related expansion exists
- Related expansion has `is_fvg_candidate=True`
- FVG forms in the correct strategy leg
- No equality boundary
- No invalid tap behavior
- No consolidation invalidation

For bearish 12M tap behavior:

- First 1M candle that enters the 12M bearish FVG is the tap candle.
- The candle before the tap is C1 of the 1M swing confirmation structure.
- The tap candle is C2.
- The candle after tap is C3.
- Swing Engine must validate whether the three-candle structure is a 1M swing
  high.
- A tap candle close inside or below the FVG remains valid.
- A tap candle close above the FVG invalidates the setup.
- A second high inside the FVG remains valid only if it closes inside or below
  the FVG.
- A third high inside the FVG invalidates immediately.

For bearish HTF tap behavior:

- The 16M swing high must tap a 30M or 1H bearish FVG.
- The tap must be single-touch before displacement.
- Consolidation, repeated higher highs, close above the HTF FVG, or more than
  two highs inside the HTF FVG invalidates the setup.

For bearish 12M and 8M FVG location:

- The FVG must exist inside the leg between the 16M swing high and the low of
  the 16M FVG completion candle.

## Query API

Expose:

- `get_fvg_by_id(fvg_id)`
- `get_latest_fvg(symbol, timeframe, direction=None)`
- `get_active_fvgs(symbol=None, timeframe=None, direction=None)`
- `get_fvgs_between(symbol, timeframe, start, end, direction=None, status=None)`
- `get_strategy_fvgs(symbol=None, timeframe=None, direction=None)`
- `get_htf_fvgs(symbol, direction=None)`
- `get_entry_fvgs(symbol, direction=None)`
- `get_tapped_fvgs(symbol=None, timeframe=None)`
- `get_untapped_fvgs(symbol=None, timeframe=None)`

## Update API

Expose:

- `mark_tapped(fvg_id, candle, touched_at)`
- `update_lifecycle_state(fvg_id, state, reason=None)`
- `mark_strategy_fvg(fvg_id, is_strategy=True)`
- `invalidate_fvg(fvg_id, reason, invalidated_at)`
- `increment_touch_count(fvg_id, candle)`

## Validation Requirements

Tests must cover:

- Valid bearish FVG
- Valid bullish FVG
- Equality boundary rejected
- No FVG false positives
- HTF FVG detection
- Strategy FVG qualification
- 12M FVG tap rule
- First tap candle close inside FVG
- First tap candle close below FVG
- First tap candle close above FVG invalidates
- Second high rule
- Third high invalidation
- Consolidation invalidation
- Touch count tracking
- Lifecycle transitions
- Query APIs
- Historical scan
- Live processing
- Replay consistency
- Benchmark behavior

## Reports

Generate:

- `arjiobot/fvg/reports/fvg_validation_report.html`
- `arjiobot/fvg/reports/fvg_validation_report.png`

Reports must show candlesticks, FVG zones, tapped FVGs, untapped FVGs,
strategy FVGs, related swing IDs, related expansion IDs, and PASS / FAIL
summary.

## Known Limitations

- v1 implements FVG detection, strategy qualification primitives, and tap
  validation helpers, but not full Setup Tracker orchestration.
- v1 stores FVGs in memory behind a deterministic service API.
- v1 HTF tap validation is rule-based and reusable; complete multi-timeframe
  strategy sequencing belongs to the future Strategy Engine.

## Final Validation Report

Model Tests: PASS

Detection Tests: PASS

Scoring Tests: PASS

Tap Rule Tests: PASS

Lifecycle Tests: PASS

Integration Tests: PASS

Historical Scan Behavior: PASS

Incremental / Live Behavior: PASS

False Positive Behavior: PASS

Equality Boundary Rejection: PASS

HTF FVG Detection: PASS

Strategy FVG Qualification: PASS

FVG Candidate Integration: PASS

Report Generation Output: PASS

Reports Generated:

- `arjiobot/fvg/reports/fvg_validation_report.html`
- `arjiobot/fvg/reports/fvg_validation_report.png`

Tests Executed: 33

Tests Passed: 33

Detection Accuracy: PASS for the frozen validation dataset.

Boundary Rule Validation: PASS. Strict bearish and bullish FVG boundaries reject
equality and accept only valid three-candle imbalance geometry.

Strategy Rule Validation: PASS.

Strategy Qualification Validation: PASS. Strategy FVGs require valid FVG
geometry, a related Swing object, a related Expansion object, and an Expansion
object marked `is_fvg_candidate=True`.

Tap Rule Validation: PASS. Bearish 12M tap behavior invalidates any 1M
confirmation-phase candle that intersects the FVG zone and closes above the FVG
upper boundary. Closes inside or below the FVG remain valid.

Benchmark Results: PASS. Benchmark helper reports processed candle count,
detected FVG count, duration in milliseconds, and candles per second.

Known Limitations:

- v1 does not implement Setup Tracker orchestration.
- v1 storage is in-memory behind deterministic service APIs.
- v1 HTF behavior is exposed as reusable validation rules.
- v1 uses the frozen Expansion Engine `is_fvg_candidate` field as the strategy
  expansion qualification contract.

Ready For Integration: YES

Recommendation: freeze the FVG Engine and integrate it as the authoritative FVG
source for future Setup Tracker, Strategy Engine, and Backtester consumers.
Downstream modules must consume FVG service queries and must not scan candles
independently for FVGs.
