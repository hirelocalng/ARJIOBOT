"""Read-only adapter tests."""

from __future__ import annotations

from arjiobot.exchange.exchange_errors import ExchangeAdapterError, ExchangeErrorCode
from arjiobot.exchange.read_only_adapter import ReadOnlyBitgetAdapter


def test_read_only_allows_reads() -> None:
    adapter = ReadOnlyBitgetAdapter()

    assert adapter.fetch_balance("acct")[0].asset == "USDT"


def test_read_only_rejects_trading_operations() -> None:
    adapter = ReadOnlyBitgetAdapter()

    try:
        adapter.place_market_order(account_id="acct", symbol="BTCUSDT", side="SELL", position_size="0.1", leverage="3")
    except ExchangeAdapterError as error:
        assert error.code is ExchangeErrorCode.TRADING_NOT_ALLOWED_IN_READ_ONLY_MODE
    else:
        raise AssertionError("read-only mode should reject trading")
