"""Mock exchange adapter for full-system dry runs."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from decimal import Decimal

from arjiobot.exchange.bitget_client import BitgetClient
from arjiobot.exchange.exchange_models import (
    ExchangeMode,
    ExchangeOrderResult,
    ExchangeOrderSide,
    ExchangeOrderStatus,
    ExchangeOrderType,
    build_client_order_id,
)
from arjiobot.exchange.order_sizing_guard import OrderSizingGuardError, validate_isolated_order_payload
from arjiobot.exchange.rate_limits import RateLimitGuard
from arjiobot.market_data.candle_models import ensure_utc, to_decimal


class MockBitgetAdapter:
    """Deterministic no-network adapter used by default."""

    def __init__(self, *, client: BitgetClient | None = None, rate_limiter: RateLimitGuard | None = None) -> None:
        self.mode = ExchangeMode.MOCK
        self.client = client or BitgetClient(mode=self.mode)
        self.rate_limiter = rate_limiter or RateLimitGuard()

    def fetch_balance(self, account_id: str):
        self.rate_limiter.acquire(account_id)
        return self.client.fetch_balance(account_id)

    def fetch_positions(self, account_id: str):
        self.rate_limiter.acquire(account_id)
        return self.client.fetch_positions(account_id)

    def fetch_open_orders(self, account_id: str) -> tuple[ExchangeOrderResult, ...]:
        self.rate_limiter.acquire(account_id)
        return ()

    def fetch_order_status(self, account_id: str, order_id: str) -> ExchangeOrderResult:
        self.rate_limiter.acquire(account_id)
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        return ExchangeOrderResult(
            exchange_order_id=order_id,
            client_order_id=f"client_{order_id}",
            account_id=account_id,
            symbol="BTCUSDT",
            side=ExchangeOrderSide.SELL,
            order_type=ExchangeOrderType.MARKET,
            status=ExchangeOrderStatus.FILLED,
            requested_size=Decimal("0.1"),
            filled_size=Decimal("0.1"),
            average_fill_price=Decimal("65000"),
            submitted_at=now,
            updated_at=now,
            raw_response={"mock": True},
        )

    def fetch_market_info(self, symbol: str):
        return self.client.fetch_market_info(symbol)

    def fetch_ohlcv(self, account_id: str, symbol: str, timeframe: str = "1M", limit: int = 10):
        self.rate_limiter.acquire(account_id)
        return self.client.fetch_ohlcv(account_id, symbol, timeframe, limit)

    def place_market_order(
        self,
        *,
        account_id: str,
        symbol: str,
        side: str,
        position_size: Decimal,
        leverage: Decimal,
        client_order_id: str | None = None,
        submitted_at: datetime | None = None,
        **order_metadata: object,
    ) -> ExchangeOrderResult:
        timestamp = ensure_utc(submitted_at or datetime(2026, 1, 1, tzinfo=timezone.utc))
        order_client_id = client_order_id or build_client_order_id(account_id=account_id, symbol=symbol, side=side, order_type=ExchangeOrderType.MARKET.value, created_at=timestamp)
        size = to_decimal(position_size)
        try:
            sizing = validate_isolated_order_payload(
                {
                    **order_metadata,
                    "account_id": account_id,
                    "symbol": symbol,
                    "side": side,
                    "position_size": position_size,
                    "quantity": order_metadata.get("quantity", position_size),
                    "leverage": leverage,
                    "client_order_id": order_client_id,
                }
            )
        except OrderSizingGuardError as exc:
            return ExchangeOrderResult(
                exchange_order_id=None,
                client_order_id=order_client_id,
                account_id=account_id,
                symbol=symbol,
                side=ExchangeOrderSide(side),
                order_type=ExchangeOrderType.MARKET,
                status=ExchangeOrderStatus.REJECTED,
                requested_size=size,
                filled_size=Decimal("0"),
                average_fill_price=None,
                submitted_at=timestamp,
                updated_at=timestamp,
                raw_response={"mock": True, "guard": "ISOLATED_MARGIN"},
                error_message=str(exc),
            )
        self.rate_limiter.acquire(account_id)
        exchange_order_id = f"mock_{hashlib.sha256(order_client_id.encode('utf-8')).hexdigest()[:20]}"
        return ExchangeOrderResult(
            exchange_order_id=exchange_order_id,
            client_order_id=order_client_id,
            account_id=account_id,
            symbol=symbol,
            side=ExchangeOrderSide(side),
            order_type=ExchangeOrderType.MARKET,
            status=ExchangeOrderStatus.FILLED,
            requested_size=size,
            filled_size=size,
            average_fill_price=Decimal("65000"),
            submitted_at=timestamp,
            updated_at=timestamp,
            raw_response={"mock": True, "leverage": str(leverage), **sizing},
        )

    def set_leverage(self, account_id: str, symbol: str, leverage: Decimal) -> dict[str, str]:
        self.rate_limiter.acquire(account_id)
        return {"account_id": account_id, "symbol": symbol.upper(), "leverage": str(leverage), "mode": self.mode.value}
