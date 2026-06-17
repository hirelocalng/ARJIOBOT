"""In-memory credential store with an encryption-ready interface."""

from __future__ import annotations

import base64
from dataclasses import replace
from datetime import datetime, timezone
from typing import Protocol, Sequence

from arjiobot.exchange.credential_models import (
    CredentialPermission,
    ExchangeAccount,
    ExchangeCredentialInput,
    ExchangeName,
    VerificationStatus,
    build_account_id,
)
from arjiobot.exchange.exchange_errors import ExchangeAdapterError, ExchangeErrorCode
from arjiobot.market_data.candle_models import ensure_utc


class CredentialCipher(Protocol):
    """Replaceable credential cipher boundary."""

    def encrypt(self, value: str) -> str: ...
    def decrypt(self, value: str) -> str: ...


class Base64CredentialCipher:
    """Development-only reversible cipher for in-memory v1 storage."""

    prefix = "enc:v1:"

    def encrypt(self, value: str) -> str:
        encoded = base64.urlsafe_b64encode(value[::-1].encode("utf-8")).decode("ascii")
        return f"{self.prefix}{encoded}"

    def decrypt(self, value: str) -> str:
        if not value.startswith(self.prefix):
            raise ExchangeAdapterError(ExchangeErrorCode.INVALID_CREDENTIALS, "credential value is not encrypted")
        decoded = base64.urlsafe_b64decode(value[len(self.prefix) :].encode("ascii")).decode("utf-8")
        return decoded[::-1]


class InMemoryCredentialStore:
    """Multi-account in-memory credential store."""

    def __init__(self, *, cipher: CredentialCipher | None = None) -> None:
        self.cipher = cipher or Base64CredentialCipher()
        self._accounts: dict[str, ExchangeAccount] = {}

    def create_exchange_account(self, credentials: ExchangeCredentialInput, created_at: datetime | None = None) -> ExchangeAccount:
        timestamp = ensure_utc(created_at or credentials.created_at or datetime.now(timezone.utc))
        account = ExchangeAccount(
            account_id=build_account_id(credentials.exchange, credentials.account_name, timestamp),
            account_name=credentials.account_name,
            exchange=credentials.exchange,
            api_key=credentials.api_key,
            api_secret_encrypted=self.cipher.encrypt(credentials.api_secret),
            passphrase_encrypted=self.cipher.encrypt(credentials.passphrase),
            permissions=credentials.permissions,
            is_active=True,
            is_default=credentials.is_default or not self._accounts,
            trading_enabled=False,
            created_at=timestamp,
            updated_at=timestamp,
        )
        if account.is_default:
            self._clear_default()
        self._accounts[account.account_id] = account
        return account

    def update_exchange_account(self, account_id: str, credentials: ExchangeCredentialInput, updated_at: datetime | None = None) -> ExchangeAccount:
        existing = self.require_account(account_id)
        timestamp = ensure_utc(updated_at or datetime.now(timezone.utc))
        updated = replace(
            existing,
            account_name=credentials.account_name,
            exchange=ExchangeName(credentials.exchange),
            api_key=credentials.api_key,
            api_secret_encrypted=self.cipher.encrypt(credentials.api_secret),
            passphrase_encrypted=self.cipher.encrypt(credentials.passphrase),
            permissions=credentials.permissions,
            trading_enabled=False,
            updated_at=timestamp,
            last_verified_at=None,
            verification_status=VerificationStatus.UNVERIFIED,
        )
        self._accounts[account_id] = updated
        return updated

    def delete_exchange_account(self, account_id: str) -> None:
        self.require_account(account_id)
        was_default = self._accounts[account_id].is_default
        del self._accounts[account_id]
        if was_default and self._accounts:
            first = next(iter(self._accounts.values()))
            self._accounts[first.account_id] = replace(first, is_default=True)

    def set_default_exchange_account(self, account_id: str) -> ExchangeAccount:
        account = self.require_account(account_id)
        self._clear_default()
        updated = replace(account, is_default=True, updated_at=datetime.now(timezone.utc))
        self._accounts[account_id] = updated
        return updated

    def enable_trading(self, account_id: str) -> ExchangeAccount:
        account = self.require_account(account_id)
        if CredentialPermission.TRADE not in account.permissions:
            raise ExchangeAdapterError(ExchangeErrorCode.PERMISSION_DENIED, "account lacks TRADE permission")
        updated = replace(account, trading_enabled=True, updated_at=datetime.now(timezone.utc))
        self._accounts[account_id] = updated
        return updated

    def disable_trading(self, account_id: str) -> ExchangeAccount:
        account = self.require_account(account_id)
        updated = replace(account, trading_enabled=False, updated_at=datetime.now(timezone.utc))
        self._accounts[account_id] = updated
        return updated

    def mark_verified(self, account_id: str, verified_at: datetime | None = None) -> ExchangeAccount:
        account = self.require_account(account_id)
        timestamp = ensure_utc(verified_at or datetime.now(timezone.utc))
        updated = replace(account, verification_status=VerificationStatus.VERIFIED, last_verified_at=timestamp, updated_at=timestamp)
        self._accounts[account_id] = updated
        return updated

    def mark_failed(self, account_id: str, verified_at: datetime | None = None) -> ExchangeAccount:
        account = self.require_account(account_id)
        timestamp = ensure_utc(verified_at or datetime.now(timezone.utc))
        updated = replace(account, verification_status=VerificationStatus.FAILED, last_verified_at=timestamp, updated_at=timestamp)
        self._accounts[account_id] = updated
        return updated

    def list_exchange_accounts(self) -> tuple[ExchangeAccount, ...]:
        return tuple(self._accounts.values())

    def list_safe_accounts(self) -> tuple[dict[str, object], ...]:
        return tuple(account.to_safe_record() for account in self._accounts.values())

    def require_account(self, account_id: str) -> ExchangeAccount:
        try:
            return self._accounts[account_id]
        except KeyError as exc:
            raise ExchangeAdapterError(ExchangeErrorCode.INVALID_CREDENTIALS, "exchange account not found") from exc

    def decrypt_api_secret(self, account_id: str) -> str:
        return self.cipher.decrypt(self.require_account(account_id).api_secret_encrypted)

    def decrypt_passphrase(self, account_id: str) -> str:
        return self.cipher.decrypt(self.require_account(account_id).passphrase_encrypted)

    def _clear_default(self) -> None:
        for account in tuple(self._accounts.values()):
            if account.is_default:
                self._accounts[account.account_id] = replace(account, is_default=False)
