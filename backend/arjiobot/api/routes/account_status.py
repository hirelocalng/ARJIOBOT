"""Bitget account health and execution-setting status routes."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter

from arjiobot.api.dependencies import get_state, now_iso
from arjiobot.api.errors import api_error
from arjiobot.api.schemas.common import ok
from arjiobot.exchange.account_vault import CredentialVaultError, decrypt_credentials, save_vault
from arjiobot.exchange.bitget_environment import DEFAULT_MARGIN_COIN, DEFAULT_PRODUCT_TYPE, EnvironmentLockError, STALE_DATA_SECONDS

router = APIRouter(prefix="/api/account-status", tags=["account-status"])


@router.get("/summary")
def account_status_summary():
    return ok(_summary())


@router.post("/refresh")
def refresh_account_status():
    state = get_state()
    account = _active_account()
    if account is None:
        raise api_error(400, "BITGET_ACCOUNT_NOT_CONNECTED", "No connected Bitget live account is saved.")
    symbol = _active_symbol()
    try:
        _activate_selected_credentials()
        connection = state.bitget_environment.test_connection(symbol=symbol)
    except EnvironmentLockError as exc:
        account["connection_status"] = "ERROR"
        account["verification_status"] = "FAILED"
        account["last_error"] = str(exc)
        account["last_failed_api_ping_time"] = now_iso()
        _persist_accounts()
        raise api_error(400, "BITGET_ACCOUNT_REFRESH_FAILED", str(exc)) from exc
    except CredentialVaultError as exc:
        account["connection_status"] = "NEEDS_RECONNECT"
        account["verification_status"] = "NEEDS_RECONNECT"
        account["last_error"] = str(exc)
        account["last_failed_api_ping_time"] = now_iso()
        _persist_accounts()
        raise api_error(400, "BITGET_ACCOUNT_NEEDS_RECONNECT", str(exc)) from exc
    _apply_connection_to_account(account, connection)
    _persist_accounts()
    return ok(_summary())


@router.get("/balance")
def account_balance():
    return ok(_balance_status())


@router.get("/positions")
def account_positions():
    state = get_state()
    account = _active_account()
    if account is None:
        return ok(_positions_unavailable("NOT CONNECTED"))
    try:
        _activate_selected_credentials()
        record = state.bitget_environment.fetch_positions()
    except EnvironmentLockError as exc:
        account["last_error"] = str(exc)
        account["last_failed_positions_poll_time"] = now_iso()
        raise api_error(400, "BITGET_POSITIONS_REFRESH_FAILED", str(exc)) from exc
    return ok(_positions_status(record))


@router.get("/open-orders")
def account_open_orders():
    state = get_state()
    account = _active_account()
    if account is None:
        return ok(_open_orders_unavailable("NOT CONNECTED"))
    try:
        _activate_selected_credentials()
        record = state.bitget_environment.fetch_open_orders()
    except EnvironmentLockError as exc:
        account["last_error"] = str(exc)
        account["last_failed_open_orders_poll_time"] = now_iso()
        raise api_error(400, "BITGET_OPEN_ORDERS_REFRESH_FAILED", str(exc)) from exc
    return ok(_open_orders_status(record))


@router.get("/margin-mode")
def account_margin_mode():
    return ok(_margin_status())


@router.get("/leverage")
def account_leverage():
    return ok(_leverage_status())


@router.get("/risk-status")
def account_risk_status():
    return ok(_risk_status())


def _summary() -> dict[str, object]:
    return {
        "account_connection": _connection_status(),
        "balance": _balance_status(),
        "margin_mode": _margin_status(),
        "position_mode": _position_mode_status(),
        "order_type_price_type": _order_type_status(),
        "leverage": _leverage_status(),
        "open_positions": _positions_status(get_state().bitget_environment.last_positions),
        "open_orders": _open_orders_status(get_state().bitget_environment.last_open_orders),
        "risk_status": _risk_status(),
        "data_freshness": _freshness_status(),
    }


def _connection_status() -> dict[str, object]:
    state = get_state()
    account = _active_account()
    credentials = state.bitget_environment.credential_status().get("live", {})
    last_connection = state.bitget_environment.last_connection_result or {}
    if account is None:
        return {
            "connection_status": "NO ACTIVE ACCOUNT SELECTED",
            "exchange": "BITGET",
            "credential_present": "YES" if credentials.get("configured") else "NO",
            "credential_type": "LIVE",
            "api_key_masked": credentials.get("api_key_masked", "N/A"),
            "private_api_auth_status": "NOT CONFIRMED",
            "last_successful_api_ping_time": "N/A",
            "last_failed_api_ping_time": "N/A",
            "last_error": state.bitget_environment.last_connection_error or "None",
            "live_execution_status": "BLOCKED",
        }
    return {
        "connection_status": account.get("connection_status", "NOT CONNECTED"),
        "account_id": account.get("account_id", "N/A"),
        "account_name": account.get("account_name", "N/A"),
        "exchange": account.get("exchange", "BITGET"),
        "credential_present": "YES" if credentials.get("configured") else "NO",
        "credential_type": account.get("credential_type", "LIVE"),
        "api_key_masked": account.get("api_key", credentials.get("api_key_masked", "N/A")),
        "private_api_auth_status": last_connection.get("private_api_auth_status", account.get("verification_status", "NOT CONFIRMED")),
        "last_successful_api_ping_time": account.get("last_successful_api_ping_time", "N/A"),
        "last_failed_api_ping_time": account.get("last_failed_api_ping_time", "N/A"),
        "last_error": account.get("last_error", "None"),
        "live_execution_status": _live_execution_status(),
    }


def _balance_status() -> dict[str, object]:
    account = _active_account()
    payload = get_state().bitget_environment.last_account_payload or {}
    if account is None:
        return {
            "status": "NOT CONNECTED",
            "total_equity": "N/A",
            "available_balance": "N/A",
            "available_margin": "N/A",
            "frozen_margin": "N/A",
            "unrealized_pnl": "N/A",
            "margin_coin": DEFAULT_MARGIN_COIN,
        }
    return {
        "status": "AVAILABLE" if payload or account.get("balance") not in {None, "N/A"} else "WAITING",
        "total_equity": payload.get("total_equity", "N/A"),
        "available_balance": payload.get("available_balance", account.get("balance", "N/A")),
        "available_margin": payload.get("available_margin", account.get("available_margin", "N/A")),
        "frozen_margin": payload.get("frozen_margin", "N/A"),
        "unrealized_pnl": payload.get("unrealized_pnl", "N/A"),
        "margin_coin": payload.get("margin_coin", DEFAULT_MARGIN_COIN),
        "last_updated": payload.get("fetched_at", account.get("last_successful_api_ping_time", "N/A")),
    }


def _margin_status() -> dict[str, object]:
    payload = get_state().bitget_environment.last_account_payload or {}
    margin_mode = str(payload.get("margin_mode") or "N/A").upper()
    return {
        "status": "VERIFIED" if margin_mode not in {"", "N/A"} else "NOT CONFIRMED",
        "margin_mode": margin_mode if margin_mode else "N/A",
        "product_type": payload.get("product_type", DEFAULT_PRODUCT_TYPE),
        "margin_coin": payload.get("margin_coin", DEFAULT_MARGIN_COIN),
        "source": "SIGNED_ACCOUNT_ENDPOINT" if margin_mode not in {"", "N/A"} else "UNAVAILABLE",
    }


def _position_mode_status() -> dict[str, object]:
    payload = get_state().bitget_environment.last_account_payload or {}
    position_mode = str(payload.get("position_mode") or payload.get("holdMode") or "N/A").upper()
    return {
        "status": "VERIFIED" if position_mode not in {"", "N/A"} else "NOT CONFIRMED",
        "position_mode": position_mode if position_mode else "N/A",
        "source": "SIGNED_ACCOUNT_ENDPOINT" if position_mode not in {"", "N/A"} else "UNAVAILABLE",
    }


def _order_type_status() -> dict[str, object]:
    settings = get_state().settings
    order_type = str(settings.get("order_type") or "MARKET").upper()
    price_type = str(settings.get("price_type") or ("MARKET_PRICE" if order_type == "MARKET" else "LIMIT_PRICE")).upper()
    return {
        "status": "CONFIGURED",
        "order_type": order_type,
        "price_type": price_type,
        "source": "EXECUTION_SETTINGS",
    }


def _leverage_status() -> dict[str, object]:
    state = get_state()
    setting = str(state.settings.get("max_leverage") or "").strip()
    contract_values = [str(record.get("maxLever") or "N/A") for record in state.bitget_environment.last_contracts.values()]
    return {
        "status": "CONFIGURED" if setting else "NOT CONFIRMED",
        "configured_max_leverage": setting or "N/A",
        "exchange_max_leverage_seen": contract_values[0] if contract_values else "N/A",
        "source": "RISK_SETTINGS_AND_LAST_CONTRACT_FETCH" if setting or contract_values else "UNAVAILABLE",
    }


def _positions_status(record: dict[str, object] | None) -> dict[str, object]:
    if not record:
        return _positions_unavailable("WAITING")
    positions = tuple(record.get("positions", ()))
    return {
        "status": "NO OPEN POSITIONS" if len(positions) == 0 else "OPEN POSITIONS",
        "position_count": len(positions),
        "positions": positions,
        "last_updated": record.get("fetched_at", "N/A"),
    }


def _positions_unavailable(status: str) -> dict[str, object]:
    return {"status": status, "position_count": 0, "positions": (), "last_updated": "N/A"}


def _open_orders_status(record: dict[str, object] | None) -> dict[str, object]:
    if not record:
        return _open_orders_unavailable("WAITING")
    orders = tuple(record.get("orders", ()))
    return {
        "status": "NO OPEN ORDERS" if len(orders) == 0 else "OPEN ORDERS",
        "order_count": len(orders),
        "orders": orders,
        "last_updated": record.get("fetched_at", "N/A"),
    }


def _open_orders_unavailable(status: str) -> dict[str, object]:
    return {"status": status, "order_count": 0, "orders": (), "last_updated": "N/A"}


def _risk_status() -> dict[str, object]:
    state = get_state()
    settings = state.settings
    live_blockers: list[str] = []
    if _active_account() is None:
        live_blockers.append("ACCOUNT_NOT_CONNECTED")
    if _freshness_status()["account_data_status"] == "ACCOUNT DATA STALE":
        live_blockers.append("ACCOUNT_DATA_STALE")
    if state.bitget_environment.emergency_kill_switch:
        live_blockers.append("EMERGENCY_KILL_SWITCH_ACTIVE")
    if not str(settings.get("risk_amount_per_trade") or "").strip():
        live_blockers.append("RISK_AMOUNT_NOT_SET")
    return {
        "live_execution_status": "BLOCKED" if live_blockers else "READY",
        "blockers": tuple(live_blockers),
        "risk_amount_per_trade": settings.get("risk_amount_per_trade") or "N/A",
        "max_daily_loss": settings.get("max_daily_loss") or "N/A",
        "max_weekly_loss": settings.get("max_weekly_loss") or "N/A",
        "max_open_trades": settings.get("max_open_trades") or "N/A",
        "kill_switch": "ACTIVE" if state.bitget_environment.emergency_kill_switch else "INACTIVE",
        "repeated_api_errors": state.bitget_environment.repeated_api_errors,
    }


def _freshness_status() -> dict[str, object]:
    account = _active_account()
    last_account = str(account.get("last_successful_api_ping_time", "")) if account else ""
    account_stale = not last_account or _is_stale(last_account)
    market_times = [str(item.get("fetched_at", "")) for item in get_state().bitget_environment.last_tickers.values()]
    latest_market = max(market_times) if market_times else ""
    market_stale = not latest_market or _is_stale(latest_market)
    return {
        "account_data_status": "ACCOUNT DATA STALE" if account_stale else "FRESH",
        "market_data_status": "MARKET DATA STALE" if market_stale else "FRESH",
        "last_account_refresh": last_account or "N/A",
        "last_market_refresh": latest_market or "N/A",
        "stale_after_seconds": STALE_DATA_SECONDS,
    }


def _live_execution_status() -> str:
    return "BLOCKED" if _risk_status().get("blockers") else "READY"


def _active_account() -> dict[str, object] | None:
    state = get_state()
    if state.active_live_account_id:
        return state.live_accounts.get(state.active_live_account_id)
    for account in state.live_accounts.values():
        if account.get("is_active") or account.get("is_default"):
            return account
    return None


def _active_symbol() -> str:
    for pair in get_state().monitored_pairs.values():
        if pair.get("enabled"):
            return str(pair.get("symbol") or "BTCUSDT").upper()
    return "BTCUSDT"


def _apply_connection_to_account(account: dict[str, object], connection: dict[str, object]) -> None:
    account["connection_status"] = "CONNECTED"
    account["verification_status"] = "VERIFIED"
    account["environment_lock"] = "PASSED"
    account["balance"] = connection.get("available_balance", "N/A")
    account["available_margin"] = connection.get("available_margin", "N/A")
    account["last_successful_api_ping_time"] = connection.get("last_successful_verification_time", now_iso())
    account["last_error"] = "None"


def _activate_selected_credentials() -> None:
    state = get_state()
    account_id = state.active_live_account_id or ""
    encrypted = state.encrypted_live_credentials.get(account_id)
    if not encrypted:
        raise CredentialVaultError("saved credentials are missing; reconnect account")
    state.bitget_environment.runtime_credentials = decrypt_credentials(encrypted)


def _persist_accounts() -> None:
    state = get_state()
    save_vault(state.live_accounts, state.encrypted_live_credentials, state.active_live_account_id)


def _is_stale(value: str) -> bool:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return True
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - parsed).total_seconds() > STALE_DATA_SECONDS
