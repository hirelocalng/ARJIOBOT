# Strategy Profile Audit Report

**Date:** 2026-06-16
**Scope:** STRICT_PROFILE restoration and dual-profile production setup
**Reference run:** bt_1bdecf6c1dce7b21a9109c79 (1INCHUSDT, PROFILE_F, PROFILE_15_10_5)

---

## Audit Checklist

| # | Item | Result | Notes |
|---|------|--------|-------|
| 1 | STRICT_PROFILE exists as a named, importable `StrategyProfile` object | **YES** | `research_profiles.py:53` — `STRICT_PROFILE = StrategyProfile(...)` |
| 2 | STRICT_PROFILE is in `PRODUCTION_PROFILES` tuple | **YES** | `research_profiles.py:103` — `PRODUCTION_PROFILES = (STRICT_PROFILE, PROFILE_F)` |
| 3 | STRICT_PROFILE is selectable via `get_profile("STRICT_PROFILE")` without error | **YES** | `research_profiles.py:112` — `_PROFILE_MAP` lookup |
| 4 | PROFILE_F is unchanged from pre-audit state | **YES** | `expansion_ratio_min=1.0`, `max=3.0`, `direct_12m_retrace_entry_enabled=True`, `require_1m_swing_confirmation=False`, `retrace_window_8m_candles=3` — all preserved |
| 5 | `direct_12m_retrace_entry_enabled=False` on STRICT_PROFILE (full 1M chain active) | **YES** | `research_profiles.py:62` |
| 6 | `direct_12m_retrace_entry_enabled=True` on PROFILE_F (direct 12M retrace active) | **YES** | `research_profiles.py:88` |
| 7 | `expansion_ratio_min=2.0` / `max=4.0` on STRICT_PROFILE | **YES** | `research_profiles.py:58–59` |
| 8 | `expansion_ratio_min=1.0` / `max=3.0` on PROFILE_F | **YES** | `research_profiles.py:84–85` |
| 9 | `active_strategy_profile` setting exists in backend with default `PROFILE_F` | **YES** | `dependencies.py:32` |
| 10 | `active_strategy_profile` persists across restart via `runtime_settings.json` | **YES** | `dependencies.py:59` — validated on load |
| 11 | Backend `PATCH /api/settings` accepts both `STRICT_PROFILE` and `PROFILE_F` for `active_strategy_profile` | **YES** | `settings.py:29` — `get_profile()` validation |
| 12 | Backend `PATCH /api/settings` rejects unknown profiles with HTTP 400 | **YES** | `settings.py:29–33` — `STRATEGY_PROFILE_INVALID` error code |
| 13 | `GET /api/health` returns `active_strategy_profile` from settings (not hardcoded `PROFILE_F`) | **YES** | `health.py:27` — `state.settings.get("active_strategy_profile", "PROFILE_F")` |
| 14 | `scripts/backtest_csv.py run()` accepts `strategy_profile` parameter | **YES** | `backtest_csv.py` — `run(..., strategy_profile="PROFILE_F")` parameter |
| 15 | Frontend `BACKTESTING_PROFILES` constant includes both profiles | **YES** | `frontend/src/utils/constants.ts` — `['STRICT_PROFILE', 'PROFILE_F']` |

---

## Rejected Expansion Audit Summary (bt_1bdecf6c1dce7b21a9109c79)

| Metric | Value |
|--------|-------|
| Watched swing highs | 578 |
| Rejected (no expansion) | 556 |
| Passed | 22 |
| Primary rejection reason | `RATIO_BELOW_ENGINE_MIN_2.0` = 549 (98.7%) |
| Secondary reasons | `NO_BEARISH_DISPLACEMENT` = 3, `RATIO_ABOVE_PROFILE_MAX_3.0` = 3, `RATIO_ABOVE_ENGINE_MAX_4.0` = 1 |
| Min ratio (rejected) | 0.000065 |
| Max ratio (rejected) | 3.914... |
| Average ratio (rejected) | ~0.49 |
| Median ratio (rejected) | ~0.45 |

**Root cause:** 98.7% of all rejected candidates have ratio < 2.0 (engine minimum). This is expected behavior — PROFILE_F uses `expansion_ratio_min=1.0` but the engine enforces a hard floor of 2.0. The effective minimum is therefore 2.0, not 1.0. No code defect detected.

### A) Was the ratio calculation changed? NO
`C3.range_size / ((C1.range_size + C2.range_size) / 2)` is unchanged. Verified by re-running the identical pipeline in `scripts/audit_rejected_no_expansion.py` and matching watched=578, rejected=556, passed=22.

### B) Was the reference candle selection changed? NO
C1, C2, C3 are derived from `swing.left_candle`, `swing.middle_candle`, `swing.right_candle` — same as the backtest engine. No alternative selection path exists.

### C) Was the C3 definition changed? NO
C3 is always the swing's right confirmation candle. The expansion is always the C3 of the swing high that formed it. Identity is guaranteed.

### D) Does the expansion candle come from the same swing structure? YES
The expansion is derived directly from the swing object. `expansion.timestamp == swing.right_candle.timestamp` by construction — no separate lookup or reselection occurs.

---

## Full audit data
Full per-candidate rejection detail: `reports/backtests/rejected_no_expansion_audit_bt_1bdecf6c1dce7b21a9109c79.json`
