"""Mock adapter tests."""

from __future__ import annotations

from arjiobot.exchange.exchange_models import ExchangeOrderStatus
from arjiobot.exchange.mock_adapter import MockBitgetAdapter


def locked_order_payload() -> dict[str, str]:
    return {
        "selected_starting_balance": "500",
        "selected_fixed_risk_amount": "10",
        "risk_amount": "10",
        "trade_type": "ISOLATED_MARGIN",
        "margin_mode": "isolated",
        "entry_price": "100",
        "stop_loss": "101",
        "selected_max_leverage": "100",
        "max_allowed_leverage": "100",
        "quantity": "10",
        "applied_leverage": "100",
        "risk_lock_status": "PASSED",
        "environment_lock_status": "PASSED",
        "exchange_lock_status": "PASSED",
        "profile_lock_status": "PASSED",
    }


def test_mock_balance_positions_and_market_data() -> None:
    adapter = MockBitgetAdapter()

    assert adapter.fetch_balance("acct")[0].asset == "USDT"
    assert adapter.fetch_positions("acct")[0].symbol == "BTCUSDT"
    assert adapter.fetch_market_info("btcusdt").symbol == "BTCUSDT"
    assert len(adapter.fetch_ohlcv("acct", "BTCUSDT", "1M", 3)) == 3


def test_mock_order_placement_is_deterministic_and_filled() -> None:
    adapter = MockBitgetAdapter()
    first = adapter.place_market_order(account_id="acct", symbol="BTCUSDT", side="SELL", position_size="10", leverage="100", **locked_order_payload())
    second = adapter.place_market_order(account_id="acct", symbol="BTCUSDT", side="SELL", position_size="10", leverage="100", **locked_order_payload())

    assert first.status is ExchangeOrderStatus.FILLED
    assert first.exchange_order_id == second.exchange_order_id
    assert first.filled_size == first.requested_size
    assert first.raw_response["applied_margin_amount"] == "10"
    assert first.raw_response["expected_loss_at_sl"] in {"10", "1E+1"}


def test_mock_order_blocks_missing_fixed_risk_amount() -> None:
    adapter = MockBitgetAdapter()
    result = adapter.place_market_order(account_id="acct", symbol="BTCUSDT", side="SELL", position_size="10", leverage="100")

    assert result.status is ExchangeOrderStatus.REJECTED
    assert "margin mode must be isolated" in str(result.error_message)
