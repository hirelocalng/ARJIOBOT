"""Exchange adapter integration tests."""

from __future__ import annotations

from arjiobot.exchange.bitget_adapter import BitgetExchangeAdapter
from arjiobot.exchange.credential_models import CredentialPermission, ExchangeCredentialInput
from arjiobot.exchange.demo_exchange import build_validation_report
from arjiobot.exchange.exchange_errors import ExchangeErrorCode, normalize_exchange_error, ExchangeAdapterError
from arjiobot.exchange.exchange_models import ExchangeMode, ExchangeOrderStatus, build_client_order_id
from datetime import datetime, timezone


def make_credentials(name: str = "Main") -> ExchangeCredentialInput:
    return ExchangeCredentialInput(account_name=name, api_key=f"{name}_api_key_123456", api_secret=f"{name}_secret", passphrase=f"{name}_pass", permissions=(CredentialPermission.READ, CredentialPermission.TRADE))


def locked_order_payload() -> dict[str, str]:
    return {
        "selected_starting_balance": "10000",
        "selected_fixed_risk_amount": "100",
        "risk_amount": "100",
        "trade_type": "ISOLATED_MARGIN",
        "margin_mode": "isolated",
        "entry_price": "100",
        "stop_loss": "101",
        "selected_max_leverage": "100",
        "max_allowed_leverage": "100",
        "quantity": "100",
        "applied_leverage": "100",
        "risk_lock_status": "PASSED",
        "environment_lock_status": "PASSED",
        "exchange_lock_status": "PASSED",
        "profile_lock_status": "PASSED",
    }


def test_service_multi_account_switching_and_safe_listing() -> None:
    adapter = BitgetExchangeAdapter()
    first = adapter.create_exchange_account(make_credentials("First"))
    second = adapter.create_exchange_account(make_credentials("Second"))
    adapter.set_default_exchange_account(second.account_id)
    records = adapter.list_exchange_accounts()

    assert records[0]["api_key"].endswith("****456")
    assert not any("secret" in key for record in records for key in record)
    assert records[1]["is_default"]
    assert adapter.get_account_balance(first.account_id)[0].asset == "USDT"


def test_service_read_only_and_live_disabled_rejections() -> None:
    base = BitgetExchangeAdapter()
    account = base.create_exchange_account(make_credentials())
    read_only = BitgetExchangeAdapter(mode=ExchangeMode.READ_ONLY, credential_store=base.credential_store)
    live_disabled = BitgetExchangeAdapter(mode=ExchangeMode.LIVE_DISABLED, credential_store=base.credential_store)

    read_result = read_only.place_market_order(account_id=account.account_id, symbol="BTCUSDT", side="SELL", position_size="100", leverage="100", **locked_order_payload())
    live_result = live_disabled.place_market_order(account_id=account.account_id, symbol="BTCUSDT", side="SELL", position_size="100", leverage="100", **locked_order_payload())

    assert read_result.status is ExchangeOrderStatus.REJECTED
    assert read_result.error_message == ExchangeErrorCode.TRADING_NOT_ALLOWED_IN_READ_ONLY_MODE.value
    assert live_result.error_message == ExchangeErrorCode.LIVE_TRADING_DISABLED.value


def test_deterministic_client_order_ids() -> None:
    created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)

    assert build_client_order_id(account_id="acct", symbol="btcusdt", side="SELL", order_type="MARKET", created_at=created_at) == build_client_order_id(account_id="acct", symbol="BTCUSDT", side="SELL", order_type="MARKET", created_at=created_at)


def test_normalized_error_handling() -> None:
    error = normalize_exchange_error(ExchangeAdapterError(ExchangeErrorCode.NETWORK_ERROR, "network down"), account_id="acct", symbol="btcusdt", created_at=datetime(2026, 1, 1, tzinfo=timezone.utc))

    assert error.code is ExchangeErrorCode.NETWORK_ERROR
    assert error.symbol == "BTCUSDT"


def test_report_generation() -> None:
    report = build_validation_report()
    html_path = report["html_path"]
    png_path = report["png_path"]

    assert html_path.exists()
    assert png_path.exists()
    assert "Bitget Exchange Adapter Validation Report" in html_path.read_text(encoding="utf-8")
    assert png_path.read_bytes().startswith(b"\x89PNG")
