# TP Model / RR Setting Fix Report

Status: PASS

## Source Of Hard Lock

The hard lock was not only UI text.

It came from:

- `frontend/src/pages/Settings.tsx`
- `frontend/src/pages/RiskSettings.tsx`
- `backend/arjiobot/api/dependencies.py`
- `backend/arjiobot/risk/rr_profiles.py`
- `backend/arjiobot/api/routes/backtesting.py`

The backend previously allowed only `RR_1_5` and rejected other TP/RR models through `ALLOWED_RR_PROFILES` and `resolve_rr_value()`.

## Lock Behavior Corrected

Supported selectable TP/RR models now include:

- `RR_1_0`
- `RR_1_0_RESEARCH`
- `RR_1_5`
- `LEG_TARGET_RESEARCH`

Frozen strategy logic remains frozen. TP model selection is now treated as a runtime execution/research parameter when the selected profile allows `tp_model` overrides. If a profile blocks override, the API fails loudly with `TP_MODEL_OVERRIDE_BLOCKED`.

## End-To-End Wiring

- Settings UI saves `selected_rr_profile`.
- Control plane exposes selected/saved/applied TP model.
- Backtesting request sends `selected_tp_model` and `selected_rr_profile`.
- Backend resolves the selected TP model instead of forcing `RR_1_5`.
- Backtest profile overrides apply `tp_model` when allowed.
- Risk validation uses `final_target_price` for `LEG_TARGET_RESEARCH`.
- Trade plan records include selected/applied TP model fields.
- Demo/live environment-locked order records carry selected/applied TP model fields.
- JSON/HTML backtest reports and trade rows include TP model lock fields.

## New Report / Trade Fields

- `selected_tp_model`
- `applied_tp_model`
- `tp_model_lock_status`
- `tp_model_override_allowed`

## Validation

- Settings + backtesting + risk focused tests: 41 passed
- Control plane tests: 2 passed
- Frontend build: PASS

TP model can now be set to LEG_TARGET_RESEARCH and is actively used by the system: YES
