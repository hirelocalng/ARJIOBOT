"""Credential store tests."""

from __future__ import annotations

from arjiobot.exchange.credential_models import CredentialPermission, ExchangeCredentialInput, VerificationStatus
from arjiobot.exchange.credential_store import InMemoryCredentialStore
from arjiobot.exchange.exchange_errors import ExchangeAdapterError, ExchangeErrorCode


def make_credentials(name: str = "Main", *, permissions=(CredentialPermission.READ,)) -> ExchangeCredentialInput:
    return ExchangeCredentialInput(account_name=name, api_key=f"{name}_api_key", api_secret=f"{name}_secret", passphrase=f"{name}_passphrase", permissions=permissions)


def test_account_add_update_delete_and_default_selection() -> None:
    store = InMemoryCredentialStore()
    first = store.create_exchange_account(make_credentials("First"))
    second = store.create_exchange_account(make_credentials("Second"))
    updated = store.update_exchange_account(first.account_id, make_credentials("Updated"))
    default = store.set_default_exchange_account(second.account_id)

    assert first.is_default
    assert updated.account_name == "Updated"
    assert default.is_default
    assert len(store.list_exchange_accounts()) == 2
    store.delete_exchange_account(second.account_id)
    assert len(store.list_exchange_accounts()) == 1


def test_trading_enable_disable_requires_trade_permission() -> None:
    store = InMemoryCredentialStore()
    read_only = store.create_exchange_account(make_credentials("ReadOnly"))

    try:
        store.enable_trading(read_only.account_id)
    except ExchangeAdapterError as error:
        assert error.code is ExchangeErrorCode.PERMISSION_DENIED
    else:
        raise AssertionError("read-only account should not enable trading")

    trade = store.create_exchange_account(make_credentials("Trade", permissions=(CredentialPermission.READ, CredentialPermission.TRADE)))
    enabled = store.enable_trading(trade.account_id)
    disabled = store.disable_trading(trade.account_id)

    assert enabled.trading_enabled
    assert not disabled.trading_enabled


def test_secret_values_are_encrypted_and_decryptable() -> None:
    store = InMemoryCredentialStore()
    account = store.create_exchange_account(make_credentials("Main"))

    assert account.api_secret_encrypted != "Main_secret"
    assert account.passphrase_encrypted != "Main_passphrase"
    assert store.decrypt_api_secret(account.account_id) == "Main_secret"
    assert store.decrypt_passphrase(account.account_id) == "Main_passphrase"


def test_connection_verification_status() -> None:
    store = InMemoryCredentialStore()
    account = store.create_exchange_account(make_credentials("Main"))
    verified = store.mark_verified(account.account_id)

    assert verified.verification_status is VerificationStatus.VERIFIED
    assert verified.last_verified_at is not None
