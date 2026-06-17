# Live Execution Readiness Confirmation

## Scope

This was a verification audit. Frozen strategy profiles and strategy rules were not modified.

Profiles not modified:

- `PROFILE_RECOVERED_HIGH_WINRATE`
- `PROFILE_2`
- profile freeze files
- swing/FVG/retrace/entry rules

## Files Checked

- `backend/arjiobot/exchange/bitget_environment.py`
- `backend/arjiobot/risk/isolated_margin.py`
- `backend/arjiobot/exchange/order_sizing_guard.py`
- `backend/arjiobot/api/routes/bitget.py`
- `backend/arjiobot/api/routes/live_trading.py`
- `backend/arjiobot/api/routes/control_plane.py`
- `backend/arjiobot/api/routes/account_status.py`
- `frontend/src/pages/TradingControlCenter.tsx`

## Files Changed

- `backend/arjiobot/exchange/bitget_environment.py`
- `backend/arjiobot/api/routes/control_plane.py`
- `backend/arjiobot/api/tests/test_bitget_environment_routes.py`
- `backend/arjiobot/api/tests/test_control_plane_routes.py`
- `backend/arjiobot/api/tests/test_live_control_flow_routes.py`
- `frontend/src/types/controlPlane.ts`
- `frontend/src/pages/TradingControlCenter.tsx`

## Bug Found And Fixed

The dry-run preview was blocking when the user-selected max leverage was greater than the exchange max leverage, even when the trade's required leverage fit inside the exchange cap.

Fix:

- `effective_max_leverage = min(selected_max_leverage, exchange_max_leverage)`
- sizing is validated against `effective_max_leverage`
- trade blocks only when required leverage exceeds the effective cap

## Risk Amount Trace Proof

Dry-run order preview now records:

- `selected_fixed_risk_amount`
- `applied_fixed_risk_amount`
- `applied_margin_amount`
- `margin_amount`
- `risk_amount`
- `expected_loss_at_sl_excluding_fees`
- `expected_loss_at_sl`

Assertions added for risk values:

- selected risk `10` produces margin `10` and expected SL loss `10`
- selected risk `25` produces margin `25` and expected SL loss `25`
- selected risk `100` produces margin `100` and expected SL loss `100`

No hidden `100` risk or hidden `10000` balance is used by the dry-run order sizing path.

## Position Size Formula Proof

Validated formula path:

- `price_risk_percent = abs(entry_price - stop_loss) / entry_price`
- `required_leverage = 1 / price_risk_percent`
- `notional_position_size = fixed_risk_amount * required_leverage`
- `quantity = notional_position_size / entry_price`
- `expected_loss_at_sl = abs(entry_price - stop_loss) * rounded_quantity`

If Bitget size rounding changes risk beyond tolerance, order preview blocks with:

- `RISK_SIZE_ROUNDING_MISMATCH`

## Leverage Formula Proof

Dry-run preview now reports:

- `selected_max_leverage`
- `exchange_max_leverage`
- `effective_max_leverage`
- `required_leverage`
- `applied_leverage`

If required leverage exceeds the effective cap, preview blocks with:

- `BLOCKED_REQUIRED_LEVERAGE_EXCEEDS_MAX`

## Fees And Slippage Warning

Dry-run preview now reports:

- `expected_loss_at_sl_excluding_fees`
- `estimated_fee`
- `estimated_slippage_buffer`
- `estimated_total_worst_case_loss`
- `risk_within_limit`

If estimated worst-case loss exceeds the selected fixed risk by more than the allowed tolerance, preview blocks with:

- `ESTIMATED_TOTAL_RISK_EXCEEDS_ALLOWED_TOLERANCE`

## Account And Margin Confirmation

Account health is read from signed Bitget Futures account checks. The dashboard readiness checklist blocks live readiness when:

- account is not connected
- signed account check is not confirmed
- isolated margin is not confirmed
- account data is stale

## Setup Radar Readiness Proof

The control-plane snapshot now includes:

- `LIVE EXECUTION READINESS CHECKLIST`
- `Setup Radar Ready`
- `setup_radar_source`
- exact blockers for missing live market data, stale market data, missing profile lock, or monitoring not active

If no live setup exists, readiness remains separate from fake setup rows.

## BUY / SELL Trigger Proof

Dry-run tests verify:

- BUY preview maps to Bitget `side=buy`
- SELL preview maps to Bitget `side=sell`
- both paths use the same locked risk sizing and profile lock validation
- live order placement remains blocked unless the LIVE route receives explicit `ENABLE LIVE` confirmation and all live gates pass

## Live Order Gate Proof

Verified live gates include:

- live mode / live armed
- account connected
- environment lock
- profile lock
- risk lock
- isolated margin
- market data available
- recent dry-run preview
- kill switch
- repeated API error guard
- max risk / daily loss / max trades / max open positions

If any gate fails, order preview or live order returns an exact blocked reason.

## Dashboard Checklist

The Trading Control Center now displays:

- Account Ready
- Market Data Ready
- Setup Radar Ready
- BUY Trigger Ready
- SELL Trigger Ready
- Risk Engine Ready
- Margin Mode Ready
- Leverage Ready
- Order Preview Ready
- Live Trading Armed
- Overall Status: `READY` / `BLOCKED`

Each `NO` includes an exact reason.

## Test Results

- `python -m py_compile ArjioBot\backend\arjiobot\exchange\bitget_environment.py ArjioBot\backend\arjiobot\api\routes\control_plane.py`: PASS
- `python -m pytest ArjioBot\backend\arjiobot\api\tests\test_live_control_flow_routes.py ArjioBot\backend\arjiobot\api\tests\test_bitget_environment_routes.py ArjioBot\backend\arjiobot\api\tests\test_control_plane_routes.py ArjioBot\backend\arjiobot\api\tests\test_account_status_routes.py -q -p no:cacheprovider`: 25 passed
- `cd ArjioBot\frontend && npm run build`: PASS

## Current Readiness Conclusion

The code path is safer and the dry-run validation path is verified. Actual live readiness still depends on runtime state:

- connected Bitget live account
- successful signed account refresh
- isolated margin confirmed
- live market monitoring active
- fresh market data
- recent dry-run preview
- explicit LIVE arming

## Final Statement

Risk amount, trade sizing, Setup Radar, BUY trigger, SELL trigger, and live execution gates have been verified and are ready: YES, subject to runtime account/market/live-arm gates passing before any real order.
