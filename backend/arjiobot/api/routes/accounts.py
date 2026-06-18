"""Account/exchange routes."""

from __future__ import annotations

import hashlib

from fastapi import APIRouter

from arjiobot.api.dependencies import get_state, now_iso, save_settings
from arjiobot.api.errors import api_error
from arjiobot.api.schemas.common import ok
from arjiobot.exchange.account_vault import CredentialVaultError, decrypt_credentials, encrypt_credentials, encryption_key_status, save_local_encryption_key, save_vault
from arjiobot.exchange.bitget_environment import EnvironmentLockError
from arjiobot.exchange.credential_models import CredentialPermission, ExchangeCredentialInput
from arjiobot.exchange.exchange_errors import ExchangeAdapterError

router = APIRouter(prefix="/api/accounts", tags=["accounts"])


def _credentials(payload: dict[str, object]) -> ExchangeCredentialInput:
    permissions = tuple(CredentialPermission(value) for value in payload.get("permissions", ["READ"]))
    return ExchangeCredentialInput(
        account_name=str(payload["account_name"]),
        api_key=str(payload["api_key"]),
        api_secret=str(payload["api_secret"]),
        passphrase=str(payload["passphrase"]),
        permissions=permissions,
    )


@router.post("")
def create_account(payload: dict[str, object]):
    account = get_state().exchange_adapter.create_exchange_account(_credentials(payload))
    return ok(account.to_safe_record())


@router.get("")
def list_accounts():
    return ok(tuple(get_state().live_accounts.values()))


@router.get("/active")
def get_active_account():
    state = get_state()
    account = state.live_accounts.get(state.active_live_account_id or "")
    if account is None:
        return ok({"account_id": None, "connection_status": "NO ACTIVE ACCOUNT SELECTED", "live_trading_blocked": True})
    return ok(account)


@router.get("/vault-key")
def get_vault_key_status():
    return ok(encryption_key_status())


@router.post("/vault-key")
def setup_vault_key(payload: dict[str, object]):
    try:
        return ok(save_local_encryption_key(str(payload.get("encryption_key") or "")))
    except CredentialVaultError as exc:
        raise api_error(400, "CREDENTIAL_VAULT_KEY_INVALID", str(exc)) from exc


@router.post("/vault-key/generate")
def generate_vault_key(payload: dict[str, object] | None = None):
    try:
        return ok(save_local_encryption_key())
    except CredentialVaultError as exc:
        raise api_error(400, "CREDENTIAL_VAULT_KEY_INVALID", str(exc)) from exc


@router.post("/bitget/test-and-save")
def test_and_save_bitget_account(payload: dict[str, object]):
    state = get_state()
    nickname = str(payload.get("nickname") or payload.get("account_name") or "Primary Bitget").strip()
    api_key = str(payload.get("api_key") or "").strip()
    api_secret = str(payload.get("api_secret") or "").strip()
    passphrase = str(payload.get("passphrase") or "").strip()
    if not nickname:
        raise api_error(400, "BITGET_ACCOUNT_NICKNAME_REQUIRED", "nickname is required")
    for field_name, value in {"api_key": api_key, "api_secret": api_secret, "passphrase": passphrase}.items():
        if not value or "*" in value:
            raise api_error(400, "BITGET_CREDENTIAL_FIELD_INVALID", f"{field_name} is empty or masked")
    try:
        encrypted = encrypt_credentials(api_key, api_secret, passphrase)
        state.bitget_environment.save_credentials(
            {
                "mode": "LIVE",
                "api_key": api_key,
                "api_secret": api_secret,
                "passphrase": passphrase,
                "environment": "LIVE",
            }
        )
    except CredentialVaultError as exc:
        raise api_error(400, "CREDENTIAL_STORAGE_BLOCKED", str(exc)) from exc
    except (ValueError, EnvironmentLockError) as exc:
        raise api_error(400, "BITGET_ACCOUNT_SAVE_FAILED", str(exc)) from exc
    account_id = _live_account_id(api_key, nickname)
    account = {
        "account_id": account_id,
        "account_name": nickname,
        "exchange": "BITGET",
        "account_type": "REAL",
        "credential_type": "LIVE",
        "api_key": _mask_key(api_key),
        "permissions": ["READ", "TRADE"],
        "is_active": bool(not state.live_accounts or state.active_live_account_id is None),
        "verification_status": "NEEDS_VERIFICATION",
        "connection_status": "NEEDS_VERIFICATION",
        "environment_lock": "PASSED",
        "trading_enabled": False,
        "is_default": not bool(state.live_accounts) or state.active_live_account_id is None,
        "balance": "N/A",
        "available_margin": "N/A",
        "last_successful_api_ping_time": "None",
        "last_failed_check_time": "None",
        "last_error_code": "None",
        "last_error": "Saved locally. Click Test to verify Bitget private API access.",
    }
    if account["is_default"]:
        for existing in state.live_accounts.values():
            existing["is_default"] = False
            existing["is_active"] = False
        state.active_live_account_id = account_id
    state.live_accounts[account_id] = account
    state.encrypted_live_credentials[account_id] = encrypted
    _persist_live_accounts()
    return ok(account)


@router.post("/bitget/test")
def test_bitget_connection(payload: dict[str, object] | None = None):
    """Test whichever Bitget credentials are currently resolvable - a
    dashboard-saved account, or BITGET_API_KEY/SECRET/PASSPHRASE environment
    variables as a fallback - without requiring an account to be created or
    selected via the dashboard first. Always returns 200; check `connected`."""
    payload = payload or {}
    symbol = str(payload.get("symbol") or "BTCUSDT").upper()
    state = get_state()
    diagnostics = state.bitget_environment.credential_diagnostics()
    if not diagnostics["available"]:
        missing = diagnostics["missing_env_vars"]
        message = (
            f"No Bitget credentials found. Missing environment variable(s): {', '.join(missing)}."
            if missing
            else "No Bitget credentials found, and the environment variables that are set could not be used."
        )
        return ok({"connected": False, "credential_source": "NONE", "error": message})
    try:
        result = state.bitget_environment.test_connection(symbol=symbol)
    except (EnvironmentLockError, CredentialVaultError) as exc:
        return ok({"connected": False, "credential_source": diagnostics["source"], "error": str(exc)})
    return ok(
        {
            "connected": True,
            "credential_source": diagnostics["source"],
            "available_balance": result.get("available_balance"),
            "available_margin": result.get("available_margin"),
            "account_payload": result.get("account_payload"),
        }
    )


@router.post("/select-active")
def select_active_account(payload: dict[str, object]):
    state = get_state()
    account_id = str(payload.get("account_id") or "")
    account = state.live_accounts.get(account_id)
    if account is None:
        raise api_error(404, "BITGET_ACCOUNT_NOT_FOUND", "account not found")
    for existing in state.live_accounts.values():
        existing["is_default"] = False
        existing["is_active"] = False
    account["is_default"] = True
    account["is_active"] = True
    state.active_live_account_id = account_id
    state.settings["active_account_id"] = account_id
    save_settings(state.settings)
    try:
        _activate_account_credentials(account_id)
    except CredentialVaultError as exc:
        account["connection_status"] = "NEEDS_RECONNECT"
        account["verification_status"] = "NEEDS_RECONNECT"
        account["last_error"] = str(exc)
    _persist_live_accounts()
    return ok(account)


@router.get("/{account_id}")
def get_account(account_id: str):
    live_account = get_state().live_accounts.get(account_id)
    if live_account is not None:
        return ok(live_account)
    account = get_state().exchange_adapter.credential_store.require_account(account_id)
    return ok(account.to_safe_record())


@router.patch("/{account_id}")
def update_account(account_id: str, payload: dict[str, object]):
    account = get_state().exchange_adapter.update_exchange_account(account_id, _credentials(payload))
    return ok(account.to_safe_record())


@router.delete("/{account_id}")
def delete_account(account_id: str):
    state = get_state()
    if account_id in state.live_accounts:
        state.live_accounts.pop(account_id, None)
        state.encrypted_live_credentials.pop(account_id, None)
        if state.active_live_account_id == account_id:
            state.active_live_account_id = None
            state.settings["active_account_id"] = ""
            state.bitget_environment.runtime_credentials = None
            save_settings(state.settings)
        _persist_live_accounts()
        return ok({"deleted": True})
    get_state().exchange_adapter.delete_exchange_account(account_id)
    return ok({"deleted": True})


@router.post("/{account_id}/default")
def set_default(account_id: str, payload: dict[str, object] | None = None):
    state = get_state()
    if account_id in state.live_accounts:
        for existing in state.live_accounts.values():
            existing["is_default"] = False
            existing["is_active"] = False
        state.live_accounts[account_id]["is_default"] = True
        state.live_accounts[account_id]["is_active"] = True
        state.active_live_account_id = account_id
        return ok(state.live_accounts[account_id])
    return ok(get_state().exchange_adapter.set_default_exchange_account(account_id).to_safe_record())


@router.post("/{account_id}/test-connection")
def test_connection(account_id: str, payload: dict[str, object] | None = None):
    state = get_state()
    if account_id in state.live_accounts:
        try:
            _activate_account_credentials(account_id)
            connection = state.bitget_environment.test_connection(symbol="BTCUSDT")
        except EnvironmentLockError as exc:
            state.live_accounts[account_id]["connection_status"] = "ERROR"
            state.live_accounts[account_id]["verification_status"] = "FAILED"
            state.live_accounts[account_id]["last_failed_check_time"] = now_iso()
            state.live_accounts[account_id]["last_error_code"] = "BITGET_ACCOUNT_TEST_FAILED"
            state.live_accounts[account_id]["last_error"] = str(exc)
            _persist_live_accounts()
            raise api_error(400, "BITGET_ACCOUNT_TEST_FAILED", str(exc)) from exc
        except CredentialVaultError as exc:
            state.live_accounts[account_id]["connection_status"] = "NEEDS_RECONNECT"
            state.live_accounts[account_id]["verification_status"] = "NEEDS_RECONNECT"
            state.live_accounts[account_id]["last_failed_check_time"] = now_iso()
            state.live_accounts[account_id]["last_error_code"] = "CREDENTIAL_DECRYPT_FAILED"
            state.live_accounts[account_id]["last_error"] = str(exc)
            _persist_live_accounts()
            raise api_error(400, "BITGET_ACCOUNT_NEEDS_RECONNECT", str(exc)) from exc
        account = state.live_accounts[account_id]
        account["connection_status"] = "CONNECTED"
        account["verification_status"] = "VERIFIED"
        account["environment_lock"] = "PASSED"
        account["balance"] = connection.get("available_balance", "N/A")
        account["available_margin"] = connection.get("available_margin", "N/A")
        account["last_successful_api_ping_time"] = connection.get("last_successful_verification_time", now_iso())
        account["last_failed_check_time"] = "None"
        account["last_error_code"] = "None"
        account["last_error"] = "None"
        _persist_live_accounts()
        return ok(account)
    try:
        return ok(get_state().exchange_adapter.test_connection(account_id).to_safe_record())
    except ExchangeAdapterError as exc:
        raise api_error(400, exc.code.value, str(exc)) from exc


@router.post("/{account_id}/enable-trading")
def enable_trading(account_id: str, payload: dict[str, object] | None = None):
    state = get_state()
    if account_id in state.live_accounts:
        state.live_accounts[account_id]["trading_enabled"] = True
        return ok(state.live_accounts[account_id])
    try:
        return ok(get_state().exchange_adapter.enable_trading(account_id).to_safe_record())
    except Exception as exc:
        raise api_error(400, getattr(getattr(exc, "code", None), "value", "ACCOUNT_ERROR"), str(exc))


@router.post("/{account_id}/disable-trading")
def disable_trading(account_id: str, payload: dict[str, object] | None = None):
    state = get_state()
    if account_id in state.live_accounts:
        state.live_accounts[account_id]["trading_enabled"] = False
        return ok(state.live_accounts[account_id])
    return ok(get_state().exchange_adapter.disable_trading(account_id).to_safe_record())


@router.get("/{account_id}/balance")
def balance(account_id: str):
    account = get_state().live_accounts.get(account_id)
    if account is not None:
        return ok([{"asset": "USDT", "available": account.get("balance", "N/A"), "available_margin": account.get("available_margin", "N/A")}])
    return ok(get_state().exchange_adapter.get_account_balance(account_id))


@router.get("/{account_id}/positions")
def positions(account_id: str):
    if account_id in get_state().live_accounts:
        return ok([])
    return ok(get_state().exchange_adapter.get_account_positions(account_id))


@router.post("/{account_id}/refresh")
def refresh_live_account(account_id: str, payload: dict[str, object] | None = None):
    return test_connection(account_id)


@router.post("/{account_id}/reconnect")
def reconnect_live_account(account_id: str, payload: dict[str, object]):
    state = get_state()
    existing = state.live_accounts.get(account_id)
    if existing is None:
        raise api_error(404, "BITGET_ACCOUNT_NOT_FOUND", "account not found")
    nickname = str(payload.get("nickname") or payload.get("account_name") or existing.get("account_name") or "Primary Bitget").strip()
    api_key = str(payload.get("api_key") or "").strip()
    api_secret = str(payload.get("api_secret") or "").strip()
    passphrase = str(payload.get("passphrase") or "").strip()
    for field_name, value in {"api_key": api_key, "api_secret": api_secret, "passphrase": passphrase}.items():
        if not value or "*" in value:
            raise api_error(400, "BITGET_CREDENTIAL_FIELD_INVALID", f"{field_name} is empty or masked")
    try:
        encrypted = encrypt_credentials(api_key, api_secret, passphrase)
        state.bitget_environment.save_credentials({"mode": "LIVE", "api_key": api_key, "api_secret": api_secret, "passphrase": passphrase, "environment": "LIVE"})
    except CredentialVaultError as exc:
        raise api_error(400, "CREDENTIAL_STORAGE_BLOCKED", str(exc)) from exc
    except (ValueError, EnvironmentLockError) as exc:
        existing["connection_status"] = "ERROR"
        existing["verification_status"] = "FAILED"
        existing["last_failed_check_time"] = now_iso()
        existing["last_error_code"] = "BITGET_RECONNECT_FAILED"
        existing["last_error"] = str(exc)
        _persist_live_accounts()
        raise api_error(400, "BITGET_RECONNECT_FAILED", str(exc)) from exc
    existing.update(
        {
            "account_name": nickname,
            "api_key": _mask_key(api_key),
            "connection_status": "NEEDS_VERIFICATION",
            "verification_status": "NEEDS_VERIFICATION",
            "environment_lock": "PASSED",
            "balance": "N/A",
            "available_margin": "N/A",
            "last_successful_api_ping_time": "None",
            "last_failed_check_time": "None",
            "last_error_code": "None",
            "last_error": "Reconnected locally. Click Test to verify Bitget private API access.",
        }
    )
    state.encrypted_live_credentials[account_id] = encrypted
    _persist_live_accounts()
    return ok(existing)


def _live_account_id(api_key: str, nickname: str) -> str:
    raw = f"BITGET|LIVE|{api_key}|{nickname}"
    return f"bitget_live_{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:16]}"


def _activate_account_credentials(account_id: str) -> None:
    state = get_state()
    encrypted = state.encrypted_live_credentials.get(account_id)
    if not encrypted:
        raise CredentialVaultError("saved credentials are missing; reconnect account")
    state.bitget_environment.runtime_credentials = decrypt_credentials(encrypted)


def _persist_live_accounts() -> None:
    state = get_state()
    save_vault(state.live_accounts, state.encrypted_live_credentials, state.active_live_account_id)


def _mask_key(value: str) -> str:
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}****{value[-4:]}"
