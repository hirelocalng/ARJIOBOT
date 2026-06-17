"""Normalized exchange errors."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from arjiobot.market_data.candle_models import ensure_utc


class ExchangeErrorCode(str, Enum):
    AUTHENTICATION_FAILED = "AUTHENTICATION_FAILED"
    INVALID_CREDENTIALS = "INVALID_CREDENTIALS"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    INSUFFICIENT_BALANCE = "INSUFFICIENT_BALANCE"
    SYMBOL_NOT_SUPPORTED = "SYMBOL_NOT_SUPPORTED"
    RATE_LIMITED = "RATE_LIMITED"
    NETWORK_ERROR = "NETWORK_ERROR"
    ORDER_REJECTED = "ORDER_REJECTED"
    LIVE_TRADING_DISABLED = "LIVE_TRADING_DISABLED"
    TRADING_NOT_ALLOWED_IN_READ_ONLY_MODE = "TRADING_NOT_ALLOWED_IN_READ_ONLY_MODE"
    UNKNOWN_EXCHANGE_ERROR = "UNKNOWN_EXCHANGE_ERROR"


@dataclass(frozen=True, slots=True)
class ExchangeErrorRecord:
    code: ExchangeErrorCode
    message: str
    account_id: str | None
    symbol: str | None
    created_at: datetime
    metadata: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "created_at", ensure_utc(self.created_at))
        if self.symbol is not None:
            object.__setattr__(self, "symbol", self.symbol.upper())


class ExchangeAdapterError(RuntimeError):
    """Raised when an exchange adapter operation is rejected."""

    def __init__(self, code: ExchangeErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code


def normalize_exchange_error(error: Exception, *, account_id: str | None = None, symbol: str | None = None, created_at: datetime) -> ExchangeErrorRecord:
    """Convert arbitrary errors into a normalized exchange error record."""
    code = error.code if isinstance(error, ExchangeAdapterError) else ExchangeErrorCode.UNKNOWN_EXCHANGE_ERROR
    return ExchangeErrorRecord(code=code, message=str(error), account_id=account_id, symbol=symbol, created_at=created_at)
