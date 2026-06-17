"""Bitget client wrapper boundary.

v1 intentionally performs no network calls. The wrapper exists so future live
or read-only HTTP clients can replace these methods behind the adapter.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from arjiobot.exchange.exchange_errors import ExchangeAdapterError, ExchangeErrorCode
from arjiobot.exchange.exchange_models import (
    ExchangeBalance,
    ExchangeMarketInfo,
    ExchangeMode,
    ExchangeOrderResult,
    ExchangeOrderSide,
    ExchangeOrderStatus,
    ExchangeOrderType,
    ExchangePosition,
    MarketType,
    build_client_order_id,
)
from arjiobot.market_data.candle_models import Candle, Timeframe


class BitgetClient:
    """No-network Bitget USDT-M Futures client boundary."""

    def __init__(self, *, mode: ExchangeMode = ExchangeMode.MOCK) -> None:
        self.mode = ExchangeMode(mode)

    def fetch_balance(self, account_id: str) -> tuple[ExchangeBalance, ...]:
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        return (ExchangeBalance(account_id=account_id, asset="USDT", total=Decimal("10000"), available=Decimal("9500"), locked=Decimal("500"), captured_at=now),)

    def fetch_positions(self, account_id: str) -> tuple[ExchangePosition, ...]:
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        return (ExchangePosition(account_id=account_id, symbol="BTCUSDT", side=ExchangeOrderSide.SELL, size=Decimal("0.1"), entry_price=Decimal("65000"), unrealized_pnl=Decimal("25"), leverage=Decimal("3"), captured_at=now),)

    def fetch_market_info(self, symbol: str) -> ExchangeMarketInfo:
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        return ExchangeMarketInfo(symbol=symbol, market_type=MarketType.USDT_M_FUTURES, base_asset=symbol.upper().replace("USDT", ""), quote_asset="USDT", min_order_size=Decimal("0.001"), price_precision=2, size_precision=3, captured_at=now)

    def fetch_ohlcv(self, account_id: str, symbol: str, timeframe: str = "1M", limit: int = 10) -> tuple[Candle, ...]:
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        tf = Timeframe.parse(timeframe)
        return tuple(
            Candle(symbol=symbol, timeframe=tf, timestamp=start + tf.duration * index, open=100 + index, high=101 + index, low=99 + index, close=100 + index, volume=10)
            for index in range(limit)
        )

    def reject_live_trading(self, *, account_id: str, symbol: str, side: str, order_type: str, size: Decimal, client_order_id: str | None = None) -> ExchangeOrderResult:
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        return ExchangeOrderResult(
            exchange_order_id=None,
            client_order_id=client_order_id or build_client_order_id(account_id=account_id, symbol=symbol, side=side, order_type=order_type, created_at=now),
            account_id=account_id,
            symbol=symbol,
            side=ExchangeOrderSide(side),
            order_type=ExchangeOrderType(order_type),
            status=ExchangeOrderStatus.REJECTED,
            requested_size=size,
            filled_size=Decimal("0"),
            average_fill_price=None,
            submitted_at=now,
            updated_at=now,
            raw_response={"mode": self.mode.value},
            error_message=ExchangeErrorCode.LIVE_TRADING_DISABLED.value,
        )

    def place_live_order(self, *args, **kwargs) -> ExchangeOrderResult:
        raise ExchangeAdapterError(ExchangeErrorCode.LIVE_TRADING_DISABLED, "live Bitget order placement is not implemented in v1")
