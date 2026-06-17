# Expansion Candle Engine Specification

Status: frozen after audit and amendments.

This document is the source of truth for Expansion Candle Engine implementation
work. Future code changes, tests, reports, and downstream integrations must
conform to this specification unless this document is updated and approved.

## Purpose

The Expansion Candle Engine is the authoritative displacement layer between the
Swing Detection Engine and the FVG Engine.

It consumes:

- Candle data
- Confirmed Swing objects

It produces:

- Expansion Candle objects
- Displacement metrics
- Expansion strength scores

The Expansion Engine does not detect swings, FVGs, entries, exits, or complete
trade setups.

## System Flow

```text
Market Data Layer
Swing Detection Engine
Expansion Candle Engine
FVG Engine
```

## Files

The Expansion Candle Engine lives in:

```text
arjiobot/
  expansion/
    expansion_models.py
    expansion.py
    expansion_service.py
    expansion_scorer.py
    demo_expansion.py
    tests/
      test_expansion_models.py
      test_expansion_detection.py
      test_expansion_scoring.py
    reports/
      expansion_validation_report.html
      expansion_validation_report.png
```

## Audit Findings And Amendments

The initial request establishes the core size rule but leaves several items
ambiguous. These amendments are frozen for v1:

- Direction is derived from swing type: Swing High creates a bearish expansion;
  Swing Low creates a bullish expansion.
- The expansion candle is always C3, the right candle of the confirmed swing.
- Size uses `High(C3) - Low(C3)`.
- Average prior size uses `(Size(C1) + Size(C2)) / 2`.
- `expansion_ratio = Size(C3) / Average(Size(C1), Size(C2))`.
- A valid expansion requires `2.0 <= expansion_ratio <= 4.0`.
- Bearish directional displacement requires `Close(C3) < Low(C2)`.
- Bullish directional displacement requires `Close(C3) > High(C2)`.
- Bearish `displacement_distance = Low(C2) - Close(C3)`.
- Bullish `displacement_distance = Close(C3) - High(C2)`.
- `displacement_percent = displacement_distance / Size(C3) * 100`.
- `displacement_strength` is the same normalized directional component used by
  the scorer and is stored for transparency even though downstream modules use
  `strength_score` as the primary score.
- `is_fvg_candidate` defaults to `False` on the model and is set by the engine
  only when the expansion is valid and its score meets the configured threshold.
- Live processing accepts newly closed candles and the confirmed swings created
  by the Swing Engine for that candle. It evaluates only those new swings.
- Historical processing evaluates each supplied confirmed swing once and must
  not rescan candle history to discover swings.

Performance risks:

- Recomputing swings from candles would duplicate Swing Engine work and produce
  drift. Expansion must consume Swing objects directly.
- Historical validation should use one pass over supplied swings.
- Live processing must keep only indexes and recent IDs, not full candle
  histories.

Downstream risks:

- FVG modules must consume Expansion objects rather than scanning every candle.
- FVG modules must use `is_fvg_candidate` as their first filter.
- FVG modules must not mutate Expansion objects directly.

## Expansion Object Fields

Every expansion must store:

- `expansion_id: str`
- `symbol: str`
- `timeframe: Timeframe`
- `timestamp: datetime`
- `direction: ExpansionDirection`
- `swing_id: str`
- `swing_type: SwingType`
- `size: Decimal`
- `expansion_ratio: float`
- `displacement_distance: Decimal`
- `displacement_percent: float`
- `displacement_strength: float`
- `strength_score: float`
- `is_fvg_candidate: bool`
- `created_at: datetime`
- `updated_at: datetime`

## Detection Rules

Given:

- C1 = left candle from the Swing object
- C2 = middle candle from the Swing object
- C3 = right candle from the Swing object

Calculate:

```text
Size(C1) = High(C1) - Low(C1)
Size(C2) = High(C2) - Low(C2)
Size(C3) = High(C3) - Low(C3)
Average = (Size(C1) + Size(C2)) / 2
Expansion Ratio = Size(C3) / Average
```

A valid expansion requires:

```text
2.0 <= Expansion Ratio <= 4.0
```

For bearish setups:

```text
Swing type = HIGH
Expansion candle = C3
Close(C3) < Low(C2)
```

For bullish setups:

```text
Swing type = LOW
Expansion candle = C3
Close(C3) > High(C2)
```

Size alone is insufficient. A candle with a valid ratio but no directional
close beyond C2 is rejected.

## Scoring

Every expansion must include:

```text
strength_score: float
```

Range:

```text
0.0 - 100.0
```

The score must be clamped to this range.

The scoring architecture must be pluggable. The default scorer uses:

- Expansion ratio
- Displacement magnitude
- Timeframe weighting

## FVG Candidate Flag

Every expansion includes:

```text
is_fvg_candidate: bool
```

Default:

```text
False
```

The Expansion Engine sets `is_fvg_candidate=True` when a valid expansion meets
the configured FVG candidate score threshold. Future FVG modules must consume
these Expansion objects rather than scanning every candle.

## Engine Requirements

The engine must support:

- Historical scans
- Incremental live updates

Historical scans process supplied confirmed swings in one pass.

Live processing must process only newly closed candles and newly confirmed
swings. It must not rescan full histories.

## Query API

The Expansion Engine must expose:

- `get_latest_expansion()`
- `get_expansion_by_id()`
- `get_expansions_for_timeframe()`
- `get_expansions_between()`
- `get_fvg_candidates()`

The query API must return structured Expansion objects, not raw dictionaries.

## Validation Requirements

The module must include:

- Unit tests
- Integration tests
- Historical validation
- Live update validation
- Benchmark tests
- False positive tests
- False negative tests
- Final validation report

The final report must include:

- Tests executed
- Tests passed
- Detection accuracy
- Benchmark results
- Known limitations

The report artifacts must include:

- HTML report
- PNG report

The report must display:

- Candles
- Expansion candles
- Expansion ratios
- Swing references
- PASS / FAIL summary

## Known Limitations

- v1 validates only the strict three-candle Swing Engine structure.
- v1 displacement uses candle close beyond C2, not wick-only displacement.
- v1 storage is in-memory and deterministic; database persistence can be added
  later behind the same service contract.

## Final Validation Report

Model Tests: PASS

Detection Tests: PASS

Scoring Tests: PASS

Historical Scan Behavior: PASS

Incremental / Live Behavior: PASS

False Positive Behavior: PASS

False Negative Boundary Behavior: PASS

FVG Candidate Flag: PASS

Report Generation Output: PASS

Reports Generated:

- `arjiobot/expansion/reports/expansion_validation_report.html`
- `arjiobot/expansion/reports/expansion_validation_report.png`

Tests Executed: 17

Tests Passed: 17

Detection Accuracy: PASS for the frozen validation dataset.

Benchmark Results: PASS. Benchmark helper reports processed swing count,
detected expansion count, duration in milliseconds, and swings per second.

Known Limitations:

- v1 validates confirmed Swing Engine objects only.
- v1 uses close-based directional displacement beyond C2.
- v1 FVG candidate selection is threshold-based and configurable.
- v1 persistence is in-memory behind the stable service API.

Ready For Integration: YES

Recommendation: freeze the Expansion Candle Engine and integrate it as the
authoritative displacement source for the FVG Engine. Do not proceed to FVG
implementation until downstream consumers are wired to consume Expansion
objects and `is_fvg_candidate` rather than scanning candles directly.
