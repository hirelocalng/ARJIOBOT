"""Credential model tests."""

from __future__ import annotations

from datetime import datetime, timezone

from arjiobot.exchange.credential_models import CredentialPermission, ExchangeAccount, ExchangeName, VerificationStatus, build_account_id, mask_api_key


def test_credential_masking_and_safe_record_hide_secrets() -> None:
    created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    account = ExchangeAccount(
        account_id=build_account_id(ExchangeName.BITGET, "Main", created_at),
        account_name="Main",
        exchange=ExchangeName.BITGET,
        api_key="abc123456xyz",
        api_secret_encrypted="enc:v1:not-secret",
        passphrase_encrypted="enc:v1:not-passphrase",
        permissions=(CredentialPermission.READ,),
        is_active=True,
        is_default=True,
        trading_enabled=False,
        created_at=created_at,
        updated_at=created_at,
        verification_status=VerificationStatus.UNVERIFIED,
    )
    record = account.to_safe_record()

    assert mask_api_key("abc123456xyz") == "abc****xyz"
    assert record["api_key"] == "abc****xyz"
    assert "api_secret" not in record
    assert "passphrase" not in record


def test_account_id_is_deterministic() -> None:
    created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)

    assert build_account_id(ExchangeName.BITGET, "Main", created_at) == build_account_id(ExchangeName.BITGET, "Main", created_at)
