# STRICT_PROFILE Specification

**Profile ID:** `STRICT_PROFILE`
**Label:** Strict Profile - original Arjio strategy
**Production Safe:** Yes
**Inherited Base Profile:** `STRICT_PROFILE`
**Status:** Active — selectable production strategy

---

## 1. Profile Definition

**File:** `backend/arjiobot/backtesting/research_profiles.py`
**Variable:** `STRICT_PROFILE` (line 53)
**Dataclass:** `StrategyProfile` (line 13)
**Selector function:** `get_profile("STRICT_PROFILE")` (line 112)
**Profile registry:** `PRODUCTION_PROFILES` (line 103), `_PROFILE_MAP` (line 105)

---

## 2. Expansion Candle Detection

**Rule:** C3 is the expansion candle. It is the right candle of a three-candle swing formation (C1=left, C2=middle/extremum, C3=right/confirmation).

**Active:** Yes
**Profile F override:** No (same candle definition)

**File:** `scripts/backtest_csv.py`
**Function:** `_build_strategy_funnel()` (line 346) — passes `profile.expansion_ratio_min` / `profile.expansion_ratio_max`
**Engine:** `ExpansionDetectionEngine` (internal)

---

## 3. Expansion Ratio

**Rule:** `C3.range_size / ((C1.range_size + C2.range_size) / 2)`
**Minimum:** `2.0` (engine default, retained by STRICT_PROFILE)
**Maximum:** `4.0` (engine default, retained by STRICT_PROFILE)

**Active:** Yes
**Profile F override:** Yes — Profile F uses 1.0 min / 3.0 max

**Field:** `expansion_ratio_min = 2.0`, `expansion_ratio_max = 4.0`
**File:** `backend/arjiobot/backtesting/research_profiles.py` (lines 58–59)

---

## 4. Swing Formation (C1/C2/C3 Definition)

**Rule:** Three-candle swing. Swing high: `C2.high > C1.high AND C2.high > C3.high`. C2 is the extremum, C3 is the confirmation candle and the expansion candle.

**Active:** Yes
**Profile F override:** No

**File:** `backend/arjiobot/swings/swings.py`
**Engine:** `SwingDetectionEngine.detect_all_swings()`

---

## 5. Bearish Displacement Check

**Rule:** After expansion ratio passes, displacement must be confirmed: `C2.low - C3.close > 0` (bearish). The C3 close must be below C2 low.

**Active:** Yes (enforced by engine, not profile)
**Profile F override:** No

**File:** `scripts/backtest_csv.py` — `_build_strategy_funnel()` (line 346)

---

## 6. Entry Mode: Full 1M Confirmation Chain

**Rule:** After the 16M expansion is confirmed, entry requires the full 1M confirmation chain:
1. 1M bearish swing high forms
2. 1M bearish expansion candle
3. 1M bearish FVG forms on the expansion
4. 1M FVG is retested (price returns into the FVG)

**Active:** Yes
**Profile F override:** Yes — Profile F uses direct 12M FVG retrace instead

**Field:** `direct_12m_retrace_entry_enabled = False`
**File:** `backend/arjiobot/backtesting/research_profiles.py` (line 62)
**Enforcement function:** `_classify_1m_confirmation()` in `scripts/backtest_csv.py` (line 1303)
**Trigger:** When `direct_12m_retrace_entry_enabled is False`, the funnel calls `_classify_1m_confirmation()` instead of the direct 12M retrace path.

---

## 7. 1M Swing High Confirmation

**Rule:** A 1M swing high must form after the 16M expansion. This is step 1 of the 1M confirmation chain.

**Active:** Yes (enforced structurally — part of `_classify_1m_confirmation()`)
**Profile F override:** Yes — not required in Profile F

**Field:** `require_1m_swing_confirmation = True`
**File:** `backend/arjiobot/backtesting/research_profiles.py` (line 64)

**Note:** This flag is metadata only. The actual gate is `direct_12m_retrace_entry_enabled = False`, which routes execution to `_classify_1m_confirmation()`. The `require_1m_swing_confirmation` flag documents the intent but is not checked as an individual gate in the funnel.

---

## 8. 1M Bearish Expansion Confirmation

**Rule:** After the 1M swing high, a 1M bearish expansion candle must form. This is step 2 of the 1M confirmation chain.

**Active:** Yes (enforced structurally — part of `_classify_1m_confirmation()`)
**Profile F override:** Yes — not required in Profile F

**Field:** `require_1m_bearish_expansion = False`
**Note:** Field is False because the funnel code does not gate on this flag individually. The full `_classify_1m_confirmation()` path enforces all steps unconditionally when `direct_12m_retrace_entry_enabled = False`. This flag is metadata documenting that the step exists in the chain.

---

## 9. 1M Bearish FVG Confirmation

**Rule:** After the 1M bearish expansion, a 1M bearish FVG must form. This is step 3 of the 1M confirmation chain.

**Active:** Yes (enforced structurally — part of `_classify_1m_confirmation()`)
**Profile F override:** Yes — not required in Profile F

**Field:** `require_1m_bearish_fvg = False`
**Note:** Same as `require_1m_bearish_expansion` — enforced by the confirmation path, not individually gated.

---

## 10. 1M FVG Retest Confirmation

**Rule:** The 1M bearish FVG must be retested (price returns into the 1M FVG) before entry. This is step 4 of the 1M confirmation chain.

**Active:** Yes (enforced structurally — part of `_classify_1m_confirmation()`)
**Profile F override:** Yes — not required in Profile F

**Field:** `require_1m_fvg_retest = False`
**Note:** Same pattern — enforced by the confirmation path.

---

## 11. 16M FVG Formation

**Rule:** A 16M bearish FVG must exist on the expansion leg. The expansion candle (C3) must form an FVG.

**Active:** Yes
**Profile F override:** No

**File:** `scripts/backtest_csv.py` — `_build_strategy_funnel()` (line 346)

---

## 12. 12M FVG Formation

**Rule:** A 12M bearish FVG must exist on the same price leg as the 16M FVG. This is the FVG that price retraces into.

**Active:** Yes
**Profile F override:** No (both profiles require 12M FVG)

**File:** `scripts/backtest_csv.py` — `_build_strategy_funnel()` (line 346)

---

## 13. 8M Retrace Window

**Rule:** After the 16M expansion is confirmed, the retrace must occur within a window of `retrace_window_8m_candles` completed 8M candles measured from the 16M FVG confirmation time.

**Value:** `3` completed 8M candles
**Active:** Yes
**Profile F override:** No (both profiles use 3)

**Field:** `retrace_window_8m_candles = 3`
**File:** `backend/arjiobot/backtesting/research_profiles.py` (line 60)

**Note:** The original STRICT_PROFILE window value is uncertain (no git history). 3 matches Profile F and the user explicitly requested not to reintroduce a 4-candle window.

---

## 14. One Trade Per 12M FVG

**Rule:** Once a trade is taken from a 12M FVG, that FVG cannot generate a second trade even if price retraces into it again.

**Active:** Yes
**Profile F override:** No (both profiles enforce this)

**Field:** `one_trade_per_12m_fvg = True`
**File:** `backend/arjiobot/backtesting/research_profiles.py` (line 63)

---

## 15. Stop-Loss Source

**Rule:** Stop-loss is placed at the 16M swing high (for bearish trades) or 16M swing low (for bullish trades).

**Active:** Yes
**Profile F override:** No

**File:** `scripts/backtest_csv.py` — `_simulate_bearish_trade()` (line 896), `_simulate_bullish_trade()` (line 1055)

---

## 16. Risk/Reward Profile

**Rule:** Fixed 1:1.5 RR. Take-profit is placed at `entry + (entry - stop_loss) * 1.5` for bearish trades.

**Active:** Yes
**Profile F override:** No (both profiles use RR_1_5)

**File:** `backend/arjiobot/risk/rr_profiles.py`
**Setting:** `selected_rr_profile = "RR_1_5"`

---

## 17. Fixed Risk Amount

**Rule:** Risk amount per trade is fixed in USD (or quote currency), not percentage of balance. Configured via `risk_amount_per_trade` setting.

**Active:** Yes
**Profile F override:** No

**File:** `backend/arjiobot/api/dependencies.py` (line 36), `DEFAULT_SETTINGS["risk_amount_per_trade"]`

---

## 18. FVG Delay

**Rule:** Number of 16M candles after FVG confirmation before the retrace window opens.

**Value:** `0` (no delay — window opens immediately)
**Active:** Yes
**Profile F override:** No (both use 0)

**Field:** `fvg_delay_16m_candles = 0`
**File:** `backend/arjiobot/backtesting/research_profiles.py` (line 61)

---

## 19. Active Strategy Profile Setting

**Rule:** The `active_strategy_profile` backend setting controls which profile governs live/demo execution, radar, signals, and backtesting. Persists across restarts.

**Allowed values:** `STRICT_PROFILE`, `PROFILE_F`
**Default:** `PROFILE_F`

**File:** `backend/arjiobot/api/dependencies.py` (lines 29–33)
**Setting key:** `"active_strategy_profile"`
**Validation:** `load_settings()` rejects unknown values (line 59); `update_settings()` route calls `get_profile()` (settings.py line 29–33)

---

## 20. Profile Selector

**File:** `backend/arjiobot/api/routes/settings.py` — `update_settings()` (line 29)
**Validation:** `get_profile(str(value)).profile_id` — rejects any unknown profile with HTTP 400 `STRATEGY_PROFILE_INVALID`

---

## 21. Backtesting Integration

**File:** `scripts/backtest_csv.py`
**Function:** `run(csv_path, symbol, *, strategy_profile="PROFILE_F", ...)` (accepts profile ID string)
**Resolution:** `active_profile = get_profile(strategy_profile)` at top of `run()`
**Funnel:** `_build_strategy_funnel(profile=active_profile, ...)` (line 346)

---

## 22. Uncertain Rules (Documented)

The following rules are uncertain because STRICT_PROFILE was previously deleted and no git history exists:

| Rule | Uncertainty | Current Value | Source |
|------|-------------|---------------|--------|
| `retrace_window_8m_candles` | Original may have been 4; user confirmed not to reintroduce 4 | 3 | User instruction |
| `require_1m_bearish_expansion` | Always enforced structurally; original flag value unknown | `False` (metadata) | `_classify_1m_confirmation()` structure |
| `require_1m_bearish_fvg` | Always enforced structurally; original flag value unknown | `False` (metadata) | `_classify_1m_confirmation()` structure |
| `require_1m_fvg_retest` | Always enforced structurally; original flag value unknown | `False` (metadata) | `_classify_1m_confirmation()` structure |

---

## 23. Rules NOT in STRICT_PROFILE

The following rules were part of a previous implementation and have been explicitly excluded:

- **HTF two-tap limit** — not in STRICT_PROFILE; user instruction: do not reintroduce
- **4-candle 8M retrace window** — not in STRICT_PROFILE; user instruction: do not reintroduce
- **Second-tap 12M entry logic** — not in STRICT_PROFILE; user instruction: do not reintroduce
- **1:1 RR** — not in STRICT_PROFILE; user instruction: do not reintroduce
- **Custom RR (non-1:1.5)** — not in STRICT_PROFILE; user instruction: do not reintroduce

---

## 24. Profile Separation Guarantee

Both STRICT_PROFILE and PROFILE_F are:

- Independent `StrategyProfile` instances (not aliases)
- Registered in `PRODUCTION_PROFILES` tuple
- Individually resolvable via `get_profile()`
- Independently selectable as `active_strategy_profile` and `default_backtesting_profile`
- Never mixed — setting one does not affect the other

**File:** `backend/arjiobot/backtesting/research_profiles.py` (lines 103–117)
