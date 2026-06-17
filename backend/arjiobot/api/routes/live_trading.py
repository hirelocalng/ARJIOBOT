"""Live trading ON/OFF control routes."""

from __future__ import annotations

from fastapi import APIRouter

from arjiobot.api.dependencies import get_state, save_settings
from arjiobot.api.errors import api_error
from arjiobot.api.schemas.common import ok
from arjiobot.exchange.account_vault import CredentialVaultError, decrypt_credentials
from arjiobot.exchange.bitget_environment import TradeMode

router = APIRouter(prefix="/api/live-trading", tags=["live-trading"])


@router.post("/toggle")
def toggle_live_trading(payload: dict[str, object]):
    state = get_state()
    enabled = bool(payload.get("enabled"))
    if not enabled:
        state.settings["live_trading_enabled"] = False
        state.settings["trading_mode"] = "OFF"
        state.bitget_environment.live_armed = False
        save_settings(state.settings)
        return ok({"live_trading_enabled": False, "message": "LIVE TRADING OFF", "status": "OFF"})
    if payload.get("understand_real_funds") is not True:
        raise api_error(400, "LIVE_CONFIRMATION_CHECKBOX_REQUIRED", "LIVE BLOCKED: confirmation checkbox is required")
    if str(payload.get("confirmation_text") or "") != "ENABLE LIVE":
        raise api_error(400, "LIVE_CONFIRMATION_TEXT_REQUIRED", "LIVE BLOCKED: confirmation text must be ENABLE LIVE")
    blocked = _live_block_reason()
    if blocked != "None":
        raise api_error(400, "LIVE_TRADING_BLOCKED", f"LIVE BLOCKED: {blocked}")
    state.settings["live_trading_enabled"] = True
    state.settings["trading_mode"] = "LIVE"
    state.bitget_environment.mode = TradeMode.LIVE
    state.bitget_environment.live_armed = True
    save_settings(state.settings)
    return ok({"live_trading_enabled": True, "message": "LIVE TRADING ON", "status": "LIVE"})


@router.get("/status")
def live_trading_status():
    return ok({"live_trading_enabled": bool(get_state().settings.get("live_trading_enabled")), "blocked_reason": _live_block_reason()})


def _live_block_reason() -> str:
    state = get_state()
    active_account = state.live_accounts.get(state.active_live_account_id or "")
    if not active_account:
        return "no connected active Bitget account selected"
    if active_account.get("connection_status") != "CONNECTED":
        return str(active_account.get("last_error") or "selected active Bitget account is not connected")
    try:
        encrypted = state.encrypted_live_credentials.get(str(active_account.get("account_id") or ""))
        if encrypted:
            state.bitget_environment.runtime_credentials = decrypt_credentials(encrypted)
        else:
            return "selected active Bitget account credentials are missing"
    except CredentialVaultError as exc:
        return str(exc)
    if not state.monitoring.get("active"):
        return "pair monitoring not active"
    if not any(poll.get("poll_success") == "YES" for poll in state.market_polls.values()):
        return "market data stale"
    if not state.settings.get("risk_amount_per_trade") or not state.settings.get("max_leverage"):
        return "risk settings missing"
    if state.bitget_environment.emergency_kill_switch:
        return "kill switch active"
    if state.bitget_environment.verify_environment_lock(TradeMode.DRY_RUN_PREVIEW, order_environment="DRY_RUN_PREVIEW", fail_on_error=False).lock_status != "PASSED":
        return "environment lock failed"
    return "None"
