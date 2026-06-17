"""Live-only Bitget Futures routes."""

from __future__ import annotations

from fastapi import APIRouter

from arjiobot.api.dependencies import get_state, save_settings
from arjiobot.api.errors import api_error
from arjiobot.api.schemas.common import ok
from arjiobot.exchange.account_vault import CredentialVaultError, decrypt_credentials
from arjiobot.exchange.bitget_environment import EnvironmentLockError, LIVE_CONFIRMATION_TEXT, TradeMode

router = APIRouter(prefix="/api/bitget", tags=["bitget"])


@router.get("/mode")
def get_mode():
    _activate_selected_account_credentials(fail=False)
    return ok(get_state().bitget_environment.mode_status())


@router.post("/mode")
def switch_mode(payload: dict[str, object]):
    service = get_state().bitget_environment
    _activate_selected_account_credentials(fail=False)
    try:
        result = service.switch_mode(str(payload.get("mode") or "OFF"), live_confirmation=payload.get("live_confirmation"))
    except (ValueError, EnvironmentLockError) as exc:
        raise api_error(400, "BITGET_MODE_SWITCH_BLOCKED", str(exc)) from exc
    state = get_state()
    state.settings["trading_mode"] = result["trading_mode"]
    state.settings["environment_lock_verified"] = result["environment_lock_verified"]
    state.settings["live_trading_enabled"] = result["trading_mode"] == "LIVE" and result.get("live_armed") == "YES"
    save_settings(state.settings)
    return ok(result)


@router.post("/credentials")
def save_credentials(payload: dict[str, object]):
    try:
        record = get_state().bitget_environment.save_credentials(payload)
    except (ValueError, EnvironmentLockError) as exc:
        raise api_error(400, "BITGET_CREDENTIALS_INVALID", str(exc)) from exc
    return ok(record)


@router.get("/credentials/status")
def credential_status():
    return ok(get_state().bitget_environment.credential_status())


@router.post("/connection/live")
def test_live_connection(payload: dict[str, object] | None = None):
    payload = payload or {}
    symbol = str(payload.get("symbol") or "BTCUSDT").upper()
    try:
        _activate_selected_account_credentials(fail=True)
        return ok(get_state().bitget_environment.test_connection(symbol=symbol))
    except (EnvironmentLockError, CredentialVaultError) as exc:
        raise api_error(400, "BITGET_LIVE_CONNECTION_BLOCKED", str(exc)) from exc


@router.get("/market/contracts/{symbol}")
def get_contract_config(symbol: str, product_type: str = "USDT-FUTURES"):
    try:
        return ok(get_state().bitget_environment.fetch_contract_config(symbol, product_type=product_type))
    except EnvironmentLockError as exc:
        raise api_error(400, "BITGET_CONTRACT_CONFIG_FAILED", str(exc)) from exc


@router.get("/market/ticker/{symbol}")
def get_ticker(symbol: str, product_type: str = "USDT-FUTURES"):
    try:
        return ok(get_state().bitget_environment.fetch_ticker(symbol, product_type=product_type))
    except EnvironmentLockError as exc:
        raise api_error(400, "BITGET_TICKER_FAILED", str(exc)) from exc


@router.get("/market/candles/{symbol}")
def get_candles(symbol: str, granularity: str = "1m", limit: int = 100, product_type: str = "USDT-FUTURES"):
    try:
        return ok(get_state().bitget_environment.fetch_candles(symbol, granularity=granularity, limit=limit, product_type=product_type))
    except EnvironmentLockError as exc:
        raise api_error(400, "BITGET_CANDLES_FAILED", str(exc)) from exc


@router.post("/orders/dry-run-preview")
def dry_run_preview(payload: dict[str, object]):
    try:
        return ok(get_state().bitget_environment.dry_run_preview(payload))
    except EnvironmentLockError as exc:
        return ok(_blocked_preview(payload, str(exc)))
    except Exception as exc:  # Defensive: preview failures must not crash the dashboard.
        return ok(_blocked_preview(payload, str(exc) or exc.__class__.__name__))


@router.post("/orders/live")
def place_live_order(payload: dict[str, object]):
    if payload.get("live_confirmation") != LIVE_CONFIRMATION_TEXT:
        raise api_error(400, "BITGET_LIVE_CONFIRMATION_REQUIRED", "Live order route requires confirmation text: ENABLE LIVE.")
    try:
        return ok(get_state().bitget_environment.place_order(payload, required_mode=TradeMode.LIVE))
    except EnvironmentLockError as exc:
        raise api_error(400, "BITGET_LIVE_ORDER_BLOCKED", str(exc)) from exc


@router.get("/orders")
def list_orders():
    service = get_state().bitget_environment
    return ok(
        {
            "orders": tuple(service.orders),
            "blocked_orders": tuple(service.blocked_orders),
            "mode_events": tuple(service.mode_events),
            "last_dry_run_preview": service.last_dry_run_preview,
        }
    )


def _activate_selected_account_credentials(*, fail: bool) -> None:
    state = get_state()
    account_id = state.active_live_account_id or str(state.settings.get("active_account_id") or "")
    encrypted = state.encrypted_live_credentials.get(account_id)
    if encrypted:
        state.bitget_environment.runtime_credentials = decrypt_credentials(encrypted)
        return
    if fail:
        raise CredentialVaultError("no connected active Bitget account selected")


def _blocked_preview(payload: dict[str, object], reason: str) -> dict[str, object]:
    selected_profile = str(payload.get("selected_profile_id") or payload.get("selected_strategy_profile") or "")
    applied_profile = str(payload.get("applied_profile_id") or payload.get("profile_id") or "")
    return {
        "would_place_order": "NO",
        "network_submitted": False,
        "blocked_reason": reason,
        "exchange_lock_status": "FAILED",
        "risk_lock_status": "FAILED",
        "profile_lock_status": str(payload.get("profile_lock_status") or "UNKNOWN"),
        "selected_trade_mode": get_state().bitget_environment.mode.value,
        "selected_profile_id": selected_profile,
        "applied_profile_id": applied_profile,
        "symbol": str(payload.get("symbol") or "").upper(),
        "side": str(payload.get("side") or "").upper(),
        "entry_price": str(payload.get("entry_price") or payload.get("entry_reference_price") or ""),
        "stop_loss": str(payload.get("stop_loss") or payload.get("stop_loss_price") or ""),
        "take_profit": str(payload.get("take_profit") or payload.get("take_profit_price") or ""),
        "sanitized_payload": {},
    }
