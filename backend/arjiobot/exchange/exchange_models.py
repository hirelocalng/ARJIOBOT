"""Normalized exchange adapter models."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from arjiobot.market_data.candle_models import Candle, ensure_utc, to_decimal


class ExchangeMode(str, Enum):
    MOCK = "MOCK"
    READ_ONLY = "READ_ONLY"
    PAPER = "PAPER"
    LIVE_DISABLED = "LIVE_DISABLED"
    LIVE_ENABLED = "LIVE_ENABLED"


class MarketType(str, Enum):
    USDT_M_FUTURES = "USDT_M_FUTURES"


class ExchangeOrderStatus(str, Enum):
    PLANNED = "PLANNED"
    SUBMITTED = "SUBMITTED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


class ExchangeOrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class ExchangeOrderType(str, Enum):
    MARKET = "MARKET"
    STOP_LOSS = "STOP_LOSS"
    TAKE_PROFIT = "TAKE_PROFIT"


def build_client_order_id(*, account_id: str, symbol: str, side: str, order_type: str, created_at: datetime) -> str:
    """Build deterministic client order ID."""
    raw = f"{account_id}|{symbol.upper()}|{side}|{order_type}|{ensure_utc(created_at).isoformat()}"
    return f"cli_{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:24]}"


@dataclass(frozen=True, slots=True)
class ExchangeBalance:
    account_id: str
    asset: str
    total: Decimal
    available: Decimal
    locked: Decimal
    captured_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "asset", self.asset.upper())
        for field_name in ("total", "available", "locked"):
            object.__setattr__(self, field_name, to_decimal(getattr(self, field_name)))
        object.__setattr__(self, "captured_at", ensure_utc(self.captured_at))


@dataclass(frozen=True, slots=True)
class ExchangePosition:
    account_id: str
    symbol: str
    side: ExchangeOrderSide
    size: Decimal
    entry_price: Decimal
    unrealized_pnl: Decimal
    leverage: Decimal
    captured_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbol", self.symbol.upper())
        object.__setattr__(self, "side", ExchangeOrderSide(self.side))
        for field_name in ("size", "entry_price", "unrealized_pnl", "leverage"):
            object.__setattr__(self, field_name, to_decimal(getattr(self, field_name)))
        object.__setattr__(self, "captured_at", ensure_utc(self.captured_at))


@dataclass(frozen=True, slots=True)
class ExchangeMarketInfo:
    symbol: str
    market_type: MarketType
    base_asset: str
    quote_asset: str
    min_order_size: Decimal
    price_precision: int
    size_precision: int
    captured_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbol", self.symbol.upper())
        object.__setattr__(self, "market_type", MarketType(self.market_type))
        object.__setattr__(self, "base_asset", self.base_asset.upper())
        object.__setattr__(self, "quote_asset", self.quote_asset.upper())
        object.__setattr__(self, "min_order_size", to_decimal(self.min_order_size))
        object.__setattr__(self, "captured_at", ensure_utc(self.captured_at))


@dataclass(frozen=True, slots=True)
class ExchangeOrderResult:
    exchange_order_id: str | None
    client_order_id: str
    account_id: str
    symbol: str
    side: ExchangeOrderSide
    order_type: ExchangeOrderType
    status: ExchangeOrderStatus
    requested_size: Decimal
    filled_size: Decimal
    average_fill_price: Decimal | None
    submitted_at: datetime
    updated_at: datetime
    raw_response: dict[str, Any] = field(default_factory=dict)
    error_message: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbol", self.symbol.upper())
        object.__setattr__(self, "side", ExchangeOrderSide(self.side))
        object.__setattr__(self, "order_type", ExchangeOrderType(self.order_type))
        object.__setattr__(self, "status", ExchangeOrderStatus(self.status))
        object.__setattr__(self, "requested_size", to_decimal(self.requested_size))
        object.__setattr__(self, "filled_size", to_decimal(self.filled_size))
        if self.average_fill_price is not None:
            object.__setattr__(self, "average_fill_price", to_decimal(self.average_fill_price))
        object.__setattr__(self, "submitted_at", ensure_utc(self.submitted_at))
        object.__setattr__(self, "updated_at", ensure_utc(self.updated_at))


@dataclass(frozen=True, slots=True)
class ExchangeAccountSnapshot:
    account_id: str
    balances: tuple[ExchangeBalance, ...]
    positions: tuple[ExchangePosition, ...]
    captured_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "captured_at", ensure_utc(self.captured_at))


@dataclass(frozen=True, slots=True)
class OhlcvResult:
    account_id: str
    symbol: str
    candles: tuple[Candle, ...]
    captured_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbol", self.symbol.upper())
        object.__setattr__(self, "captured_at", ensure_utc(self.captured_at))
