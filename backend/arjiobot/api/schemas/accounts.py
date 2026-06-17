"""Account API schemas."""

from __future__ import annotations

from pydantic import BaseModel


class AccountCreateRequest(BaseModel):
    account_name: str
    api_key: str
    api_secret: str
    passphrase: str
    permissions: list[str] | None = None


class AccountUpdateRequest(AccountCreateRequest):
    is_active: bool | None = None
