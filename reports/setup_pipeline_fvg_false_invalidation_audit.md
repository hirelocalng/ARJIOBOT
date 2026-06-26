# Setup Pipeline False Invalidation Audit

Date: 2026-06-26

## Scope

Audited the live setup path from 16M swing detection through expansion, 16M FVG, 12M FVG, 8M FVG, retrace, and entry creation.

Primary files traced:

- `backend/arjiobot/live_setup_detection.py`
- `backend/scripts/backtest_csv.py`
- `backend/arjiobot/api/routes/radar.py`
- `backend/arjiobot/fvg/fvg.py`

## Root Cause Found

`FVG_16M_NOT_FOUND` could be emitted by the setup attempt tracer after the 1M source clock had advanced past the expected 16M confirmation close, even when the actual synthesized 16M candle dataset being scanned did not yet contain the required C3 confirmation candle.

That created an internal mismatch:

- Setup Radar/dashboard could show stage progress from a later or real `Setup` object.
- Attempt diagnostics could still carry `FVG_16M_NOT_FOUND`, `FVG_16M_WINDOW_CLOSED_WITHOUT_MATCH`, or `FVG_16M_PENDING_CONFIRMATION_WINDOW_OPEN` from a trace object whose 16M scan dataset was not equivalent to the dashboard row being displayed.

The problem was not a strategy-rule failure. It was a data-source and timing consistency failure between:

- source 1M candle freshness,
- synthesized 16M candle availability,
- attempt trace invalidation timing,
- dashboard display state derived from stored setup progress.

## Pipeline Trace

1. Swing creation
   - `detect_live_setups_for_symbol()` snapshots `state.live_candles[symbol]`.
   - `build_timeframe_profile()` builds synthetic 16M/12M/8M candles.
   - `SwingDetectionEngine().detect_all_swings()` detects candidate swings from the configured swing timeframe.

2. Expansion confirmation
   - `_research_expansions()` derives expansion objects from detected swings.
   - `_profile_valid_expansions()` filters by the active profile expansion ratio and C3 requirements.

3. 16M FVG search
   - `FVGDetectionEngine.detect_fvgs()` scans the synthesized 16M candles.
   - `_one_fvg_matches_expansion()` matches FVGs to the expansion.
   - The bug was in `_main_fvg_lookup_still_open()`: it only used latest 1M close to decide whether the 16M FVG window was fully knowable.

4. 12M FVG search
   - `_fvgs_inside_leg()` searches same-direction 12M FVGs after the 16M FVG confirmation inside the approved leg.
   - Existing pending logic keeps this open until the retrace FVG confirmation window can close.

5. 8M FVG search
   - `_fvgs_inside_leg()` repeats the leg check for internal 8M FVGs.
   - Existing pending logic keeps this open until the internal FVG confirmation window can close.

6. Retrace
   - `_first_1m_retrace_into_12m_fvg_within_8m_window()` searches 1M candles within the 8M retrace window.

7. Entry
   - Direct 12M retrace profiles create a real trade candidate.
   - `_setup_from_trade()` converts that candidate into the executable `ENTRY_READY` setup.

## Changes Made

- Passed the actual synthesized main FVG candle dataset into the shared funnel from live detection.
- Updated `_main_fvg_lookup_still_open()` so `FVG_16M_NOT_FOUND` is not emitted unless the required synthesized main-timeframe C3 candle exists and the full confirmation window has been scanned.
- Added structured `[SETUP_PIPELINE_AUDIT]` logs per setup trace with swing id, timestamps, candle indexes, FVG ids, FVG boundaries, rejection reason, and data source.
- Added radar diagnostics fields so the dashboard/API can expose the same audit context.
- Added a regression test for the false-terminal condition where 1M data is ahead but the synthesized 16M scan lacks the required C3 candle.

## Stale Cache Check

`FVGDetectionEngine` is cached per symbol/timeframe in live detection, but `detect_fvgs()` still rescans the supplied candle sequence and returns the detected FVGs for that scan. The cache is used to dedupe repeated log noise, not to return stale FVG results.

No stale FVG result cache was found as the primary cause.

## Dashboard Consistency Check

The dashboard stage columns are derived from `Setup.progress_percent` in `radar_record()`. Attempt traces and real executable setups are separate objects until `_setup_from_trade()` reclaims a tracked attempt row by swing id.

That means the dashboard can show a newer confirmed setup state while older trace diagnostics still appear unless the trace metadata is tied to the exact candle dataset and swing id. The new audit fields make that join explicit.

## Verification

Passed:

```text
pytest backend/arjiobot/backtesting/tests/test_csv_backtest_runner.py -q --basetemp=.pytest-tmp
42 passed
```

Passed syntax compile:

```text
python -m py_compile backend/scripts/backtest_csv.py backend/arjiobot/live_setup_detection.py backend/arjiobot/api/routes/radar.py backend/arjiobot/backtesting/tests/test_csv_backtest_runner.py
```

Blocked by missing local dependency:

```text
pytest backend/arjiobot/api/tests/test_radar_routes.py backend/arjiobot/tests/test_setup_radar_attempts.py -q --basetemp=.pytest-tmp
ModuleNotFoundError: No module named 'sqlalchemy'
```

## Runtime Report Format

On the next live evaluation, each setup trace logs one `[SETUP_PIPELINE_AUDIT]` JSON record containing:

- `setup_id`
- `swing_id`
- `swing_timestamp`
- `stage`
- `expansion_16m_id`
- `fvg_16m_id`, `fvg_12m_id`, `fvg_8m_id`
- FVG boundaries
- candle indexes
- rejection reason
- failure detail
- data source
- main FVG dataset fingerprint

Those records are the per-setup rejection report requested; they identify the exact candle index and dataset used for each rejection.
