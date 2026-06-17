"""Trading adapter interface tests."""

from __future__ import annotations

from arjiobot.exchange.credential_models import CredentialPermission, ExchangeCredentialInput
from arjiobot.exchange.credential_store import InMemoryCredentialStore
from arjiobot.exchange.exchange_errors import ExchangeErrorCode
from arjiobot.exchange.exchange_models import ExchangeMode, ExchangeOrderStatus
from arjiobot.exchange.trading_adapter import LiveGuardedTradingAdapter, TradingAdapterInterface


def make_store() -> tuple[InMemoryCredentialStore, str]:
    store = InMemoryCredentialStore()
    account = store.create_exchange_account(
        ExchangeCredentialInput(account_name="Live", api_key="api_key_123456", api_secret="secret", passphrase="pass", permissions=(CredentialPermission.READ, CredentialPermission.TRADE))
    )
    return store, account.account_id


def locked_order_payload() -> dict[str, str]:
    return {
        "selected_starting_balance": "1000",
        "selected_fixed_risk_amount": "25",
        "risk_amount": "25",
        "trade_type": "ISOLATED_MARGIN",
        "margin_mode": "isolated",
        "entry_price": "100",
        "stop_loss": "101",
        "selected_max_leverage": "100",
        "max_allowed_leverage": "100",
        "quantity": "25",
        "applied_leverage": "100",
        "risk_lock_status": "PASSED",
        "environment_lock_status": "PASSED",
        "exchange_lock_status": "PASSED",
        "profile_lock_status": "PASSED",
    }


def test_trading_interface_methods_exist() -> None:
    method_names = set(TradingAdapterInterface.__dict__)

    assert {"set_leverage", "place_market_order", "place_stop_loss_order", "place_take_profit_order", "cancel_order", "cancel_all_symbol_orders"} <= method_names


def test_live_disabled_rejects_order_submission() -> None:
    store, account_id = make_store()
    adapter = LiveGuardedTradingAdapter(mode=ExchangeMode.LIVE_DISABLED, credential_store=store)
    result = adapter.place_market_order(account_id=account_id, symbol="BTCUSDT", side="SELL", position_size="25", leverage="100", **locked_order_payload())

    assert result.status is ExchangeOrderStatus.REJECTED
    assert result.error_message == ExchangeErrorCode.LIVE_TRADING_DISABLED.value


def test_live_enabled_requires_account_trading_and_verified_credentials() -> None:
    store, account_id = make_store()
    adapter = LiveGuardedTradingAdapter(mode=ExchangeMode.LIVE_ENABLED, credential_store=store)
    result = adapter.place_market_order(account_id=account_id, symbol="BTCUSDT", side="SELL", position_size="25", leverage="100", execution_instruction_approved=True, risk_trade_plan_approved=True, **locked_order_payload())

    assert result.status is ExchangeOrderStatus.REJECTED
    assert result.error_message == ExchangeErrorCode.LIVE_TRADING_DISABLED.value


def test_live_enabled_requires_approved_execution_and_risk_inputs() -> None:
    store, account_id = make_store()
    store.enable_trading(account_id)
    store.mark_verified(account_id)
    adapter = LiveGuardedTradingAdapter(mode=ExchangeMode.LIVE_ENABLED, credential_store=store)
    result = adapter.place_market_order(account_id=account_id, symbol="BTCUSDT", side="SELL", position_size="25", leverage="100", **locked_order_payload())

    assert result.status is ExchangeOrderStatus.REJECTED
    assert result.error_message == ExchangeErrorCode.PERMISSION_DENIED.value


def test_live_order_blocks_missing_isolated_margin_payload_before_live_checks() -> None:
    store, account_id = make_store()
    adapter = LiveGuardedTradingAdapter(mode=ExchangeMode.LIVE_ENABLED, credential_store=store)
    result = adapter.place_market_order(account_id=account_id, symbol="BTCUSDT", side="SELL", position_size="25", leverage="100", execution_instruction_approved=True, risk_trade_plan_approved=True)

    assert result.status is ExchangeOrderStatus.REJECTED
    assert "margin mode must be isolated" in str(result.error_message)
