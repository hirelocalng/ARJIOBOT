"""Credential and multi-account models for exchange adapters."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from arjiobot.market_data.candle_models import ensure_utc


class ExchangeName(str, Enum):
    BITGET = "BITGET"


class CredentialPermission(str, Enum):
    READ = "READ"
    TRADE = "TRADE"


class VerificationStatus(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    VERIFIED = "VERIFIED"
    FAILED = "FAILED"


def build_account_id(exchange: ExchangeName | str, account_name: str, created_at: datetime) -> str:
    """Build deterministic account ID for replayable tests and imports."""
    exchange_value = exchange.value if isinstance(exchange, ExchangeName) else str(exchange).upper()
    raw = f"{exchange_value}|{account_name}|{ensure_utc(created_at).isoformat()}"
    return f"acct_{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:24]}"


def mask_api_key(api_key: str) -> str:
    """Mask API key for display without exposing the full value."""
    if len(api_key) <= 6:
        return "*" * len(api_key)
    return f"{api_key[:3]}****{api_key[-3:]}"


@dataclass(frozen=True, slots=True)
class ExchangeCredentialInput:
    account_name: str
    api_key: str
    api_secret: str
    passphrase: str
    permissions: tuple[CredentialPermission, ...] = (CredentialPermission.READ,)
    exchange: ExchangeName = ExchangeName.BITGET
    trading_enabled: bool = False
    is_default: bool = False
    created_at: datetime | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "exchange", ExchangeName(self.exchange))
        object.__setattr__(self, "permissions", tuple(CredentialPermission(permission) for permission in self.permissions))
        if not self.account_name:
            raise ValueError("account_name is required")
        if not self.api_key:
            raise ValueError("api_key is required")
        if not self.api_secret:
            raise ValueError("api_secret is required")
        if not self.passphrase:
            raise ValueError("passphrase is required")


def credential_input_from_env(account_name: str = "Env Bitget Account") -> ExchangeCredentialInput | None:
    """Build credential input from optional BITGET_* environment variables."""
    api_key = os.getenv("BITGET_API_KEY")
    api_secret = os.getenv("BITGET_API_SECRET")
    passphrase = os.getenv("BITGET_API_PASSPHRASE")
    if not api_key or not api_secret or not passphrase:
        return None
    return ExchangeCredentialInput(
        account_name=account_name,
        api_key=api_key,
        api_secret=api_secret,
        passphrase=passphrase,
        permissions=(CredentialPermission.READ,),
    )


@dataclass(frozen=True, slots=True)
class ExchangeAccount:
    account_id: str
    account_name: str
    exchange: ExchangeName
    api_key: str
    api_secret_encrypted: str
    passphrase_encrypted: str
    permissions: tuple[CredentialPermission, ...]
    is_active: bool
    is_default: bool
    trading_enabled: bool
    created_at: datetime
    updated_at: datetime
    last_verified_at: datetime | None = None
    verification_status: VerificationStatus = VerificationStatus.UNVERIFIED
    metadata: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "exchange", ExchangeName(self.exchange))
        object.__setattr__(self, "permissions", tuple(CredentialPermission(permission) for permission in self.permissions))
        object.__setattr__(self, "created_at", ensure_utc(self.created_at))
        object.__setattr__(self, "updated_at", ensure_utc(self.updated_at))
        if self.last_verified_at is not None:
            object.__setattr__(self, "last_verified_at", ensure_utc(self.last_verified_at))
        object.__setattr__(self, "verification_status", VerificationStatus(self.verification_status))
        if not self.account_id:
            raise ValueError("account_id is required")
        if CredentialPermission.TRADE not in self.permissions and self.trading_enabled:
            raise ValueError("trading requires TRADE permission")

    @property
    def masked_api_key(self) -> str:
        return mask_api_key(self.api_key)

    def to_safe_record(self) -> dict[str, Any]:
        """Serialize account without exposing secret material."""
        return {
            "account_id": self.account_id,
            "account_name": self.account_name,
            "exchange": self.exchange.value,
            "api_key": self.masked_api_key,
            "permissions": tuple(permission.value for permission in self.permissions),
            "is_active": self.is_active,
            "is_default": self.is_default,
            "trading_enabled": self.trading_enabled,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "last_verified_at": self.last_verified_at,
            "verification_status": self.verification_status.value,
        }
