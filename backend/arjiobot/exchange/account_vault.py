"""Persistent encrypted Bitget account storage."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
from pathlib import Path
from typing import Any

from arjiobot.exchange.bitget_environment import BitgetCredentialConfig

ROOT = Path(__file__).resolve().parents[3]
VAULT_PATH = ROOT / "data" / "bitget_accounts.vault.json"
LOCAL_KEY_PATH = ROOT / "data" / ".credential_encryption_key"
KEY_ENV = "ARJIOBOT_CREDENTIAL_ENCRYPTION_KEY"


class CredentialVaultError(RuntimeError):
    """Raised when encrypted credential persistence is unavailable."""


def load_vault() -> tuple[dict[str, dict[str, object]], dict[str, dict[str, str]], str | None]:
    if not VAULT_PATH.exists():
        return {}, {}, None
    try:
        payload = json.loads(VAULT_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}, {}, None
    accounts: dict[str, dict[str, object]] = {}
    encrypted: dict[str, dict[str, str]] = {}
    for row in payload.get("accounts", []):
        if not isinstance(row, dict):
            continue
        account_id = str(row.get("account_id") or "")
        if not account_id:
            continue
        safe = {key: value for key, value in row.items() if key != "encrypted_credentials"}
        safe["connection_status"] = "NEEDS_VERIFICATION"
        safe["verification_status"] = "NEEDS_VERIFICATION"
        safe["trading_enabled"] = False
        safe.setdefault("last_error", "Needs verification after backend restart.")
        accounts[account_id] = safe
        cipher = row.get("encrypted_credentials")
        if isinstance(cipher, dict):
            encrypted[account_id] = {str(key): str(value) for key, value in cipher.items()}
    active_account_id = str(payload.get("active_account_id") or "") or None
    return accounts, encrypted, active_account_id


def save_vault(accounts: dict[str, dict[str, object]], encrypted: dict[str, dict[str, str]], active_account_id: str | None) -> None:
    VAULT_PATH.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for account_id, account in accounts.items():
        row = _public_account_record(account)
        if account_id in encrypted:
            row["encrypted_credentials"] = encrypted[account_id]
        rows.append(row)
    VAULT_PATH.write_text(json.dumps({"active_account_id": active_account_id, "accounts": rows}, indent=2), encoding="utf-8")


def encrypt_credentials(api_key: str, api_secret: str, passphrase: str) -> dict[str, str]:
    key = _key()
    plaintext = json.dumps({"api_key": api_key, "api_secret": api_secret, "passphrase": passphrase}, separators=(",", ":")).encode("utf-8")
    nonce = os.urandom(16)
    cipher = _xor_stream(plaintext, key, nonce)
    mac = hmac.new(key, nonce + cipher, hashlib.sha256).digest()
    return {
        "nonce": base64.b64encode(nonce).decode("ascii"),
        "ciphertext": base64.b64encode(cipher).decode("ascii"),
        "mac": base64.b64encode(mac).decode("ascii"),
    }


def decrypt_credentials(payload: dict[str, str]) -> BitgetCredentialConfig:
    key = _key()
    try:
        nonce = base64.b64decode(payload["nonce"])
        cipher = base64.b64decode(payload["ciphertext"])
        mac = base64.b64decode(payload["mac"])
    except (KeyError, ValueError) as exc:
        raise CredentialVaultError("credential payload is corrupt") from exc
    expected = hmac.new(key, nonce + cipher, hashlib.sha256).digest()
    if not hmac.compare_digest(mac, expected):
        raise CredentialVaultError("credential decryption failed")
    try:
        raw = json.loads(_xor_stream(cipher, key, nonce).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CredentialVaultError("credential payload is corrupt") from exc
    return BitgetCredentialConfig(api_key=str(raw.get("api_key") or ""), api_secret=str(raw.get("api_secret") or ""), passphrase=str(raw.get("passphrase") or ""), source="VAULT")


def encryption_key_available() -> bool:
    return bool(_secret_value(fail=False))


def encryption_key_status() -> dict[str, object]:
    if os.getenv(KEY_ENV):
        return {"configured": True, "source": "ENVIRONMENT", "secret_returned": False}
    if LOCAL_KEY_PATH.exists() and LOCAL_KEY_PATH.read_text(encoding="utf-8").strip():
        return {"configured": True, "source": "LOCAL_BACKEND_FILE", "secret_returned": False}
    return {"configured": False, "source": "NONE", "secret_returned": False}


def save_local_encryption_key(secret: str | None = None) -> dict[str, object]:
    value = (secret or "").strip() or generate_encryption_key()
    if len(value) < 24:
        raise CredentialVaultError("encryption key must be at least 24 characters")
    LOCAL_KEY_PATH.parent.mkdir(parents=True, exist_ok=True)
    LOCAL_KEY_PATH.write_text(value, encoding="utf-8")
    try:
        os.chmod(LOCAL_KEY_PATH, 0o600)
    except OSError:
        pass
    return encryption_key_status()


def generate_encryption_key() -> str:
    return secrets.token_urlsafe(48)


def _key() -> bytes:
    secret = _secret_value()
    return hashlib.sha256(secret.encode("utf-8")).digest()


def _secret_value(*, fail: bool = True) -> str:
    secret = os.getenv(KEY_ENV)
    if not secret and LOCAL_KEY_PATH.exists():
        secret = LOCAL_KEY_PATH.read_text(encoding="utf-8").strip()
    if not secret:
        if not fail:
            return ""
        raise CredentialVaultError("CREDENTIAL STORAGE BLOCKED: encryption key missing")
    return secret


def _xor_stream(data: bytes, key: bytes, nonce: bytes) -> bytes:
    output = bytearray()
    counter = 0
    while len(output) < len(data):
        block = hmac.new(key, nonce + counter.to_bytes(8, "big"), hashlib.sha256).digest()
        output.extend(block)
        counter += 1
    return bytes(item ^ mask for item, mask in zip(data, output))


def _public_account_record(account: dict[str, object]) -> dict[str, Any]:
    blocked = {"api_secret", "passphrase", "encrypted_credentials"}
    return {key: value for key, value in account.items() if key not in blocked and not key.startswith("_")}
