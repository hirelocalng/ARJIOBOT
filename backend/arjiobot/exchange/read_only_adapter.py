"""Read-only exchange adapter."""

from __future__ import annotations

from decimal import Decimal

from arjiobot.exchange.bitget_client import BitgetClient
from arjiobot.exchange.exchange_errors import ExchangeAdapterError, ExchangeErrorCode
from arjiobot.exchange.exchange_models import ExchangeMode
from arjiobot.exchange.mock_adapter import MockBitgetAdapter
from arjiobot.exchange.rate_limits import RateLimitGuard


class ReadOnlyBitgetAdapter(MockBitgetAdapter):
    """Adapter that permits safe reads and rejects all trading operations."""

    def __init__(self, *, client: BitgetClient | None = None, rate_limiter: RateLimitGuard | None = None) -> None:
        super().__init__(client=client or BitgetClient(mode=ExchangeMode.READ_ONLY), rate_limiter=rate_limiter)
        self.mode = ExchangeMode.READ_ONLY

    def place_market_order(self, **kwargs):
        raise ExchangeAdapterError(ExchangeErrorCode.TRADING_NOT_ALLOWED_IN_READ_ONLY_MODE, "read-only mode cannot place orders")

    def set_leverage(self, account_id: str, symbol: str, leverage: Decimal):
        raise ExchangeAdapterError(ExchangeErrorCode.TRADING_NOT_ALLOWED_IN_READ_ONLY_MODE, "read-only mode cannot set leverage")

    def place_stop_loss_order(self, **kwargs):
        raise ExchangeAdapterError(ExchangeErrorCode.TRADING_NOT_ALLOWED_IN_READ_ONLY_MODE, "read-only mode cannot place stop-loss orders")

    def place_take_profit_order(self, **kwargs):
        raise ExchangeAdapterError(ExchangeErrorCode.TRADING_NOT_ALLOWED_IN_READ_ONLY_MODE, "read-only mode cannot place take-profit orders")

    def cancel_order(self, account_id: str, symbol: str, order_id: str):
        raise ExchangeAdapterError(ExchangeErrorCode.TRADING_NOT_ALLOWED_IN_READ_ONLY_MODE, "read-only mode cannot cancel orders")

    def cancel_all_symbol_orders(self, account_id: str, symbol: str):
        raise ExchangeAdapterError(ExchangeErrorCode.TRADING_NOT_ALLOWED_IN_READ_ONLY_MODE, "read-only mode cannot cancel orders")
