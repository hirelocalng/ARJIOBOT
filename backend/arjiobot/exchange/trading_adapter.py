"""Trading adapter interface and guarded v1 implementation."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Protocol

from arjiobot.exchange.bitget_client import BitgetClient
from arjiobot.exchange.credential_models import VerificationStatus
from arjiobot.exchange.credential_store import InMemoryCredentialStore
from arjiobot.exchange.exchange_errors import ExchangeAdapterError, ExchangeErrorCode
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


class TradingAdapterInterface(Protocol):
    def set_leverage(self, account_id: str, symbol: str, leverage: Decimal): ...
    def place_market_order(self, **kwargs) -> ExchangeOrderResult: ...
    def place_stop_loss_order(self, **kwargs) -> ExchangeOrderResult: ...
    def place_take_profit_order(self, **kwargs) -> ExchangeOrderResult: ...
    def cancel_order(self, account_id: str, symbol: str, order_id: str): ...
    def cancel_all_symbol_orders(self, account_id: str, symbol: str): ...


class LiveGuardedTradingAdapter:
    """Guarded interface for future live trading.

    v1 validates safety gates and returns normalized rejections; it does not
    place real Bitget orders.
    """

    def __init__(self, *, mode: ExchangeMode, credential_store: InMemoryCredentialStore, client: BitgetClient | None = None, rate_limiter: RateLimitGuard | None = None) -> None:
        self.mode = ExchangeMode(mode)
        self.credential_store = credential_store
        self.client = client or BitgetClient(mode=self.mode)
        self.rate_limiter = rate_limiter or RateLimitGuard()

    def set_leverage(self, account_id: str, symbol: str, leverage: Decimal):
        self._require_live_enabled(account_id)
        raise ExchangeAdapterError(ExchangeErrorCode.LIVE_TRADING_DISABLED, "live set_leverage is not implemented in v1")

    def place_market_order(
        self,
        *,
        account_id: str,
        symbol: str,
        side: str,
        position_size: Decimal,
        leverage: Decimal,
        client_order_id: str | None = None,
        execution_instruction_approved: bool = False,
        risk_trade_plan_approved: bool = False,
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
            self._require_live_enabled(account_id)
            if not execution_instruction_approved or not risk_trade_plan_approved:
                raise ExchangeAdapterError(ExchangeErrorCode.PERMISSION_DENIED, "approved execution instruction and risk trade plan are required")
            raise ExchangeAdapterError(ExchangeErrorCode.LIVE_TRADING_DISABLED, "live Bitget order placement is not implemented in v1")
        except OrderSizingGuardError as error:
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
                raw_response={"mode": self.mode.value, "guard": "ISOLATED_MARGIN"},
                error_message=str(error),
            )
        except ExchangeAdapterError as error:
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
                raw_response={"mode": self.mode.value, **sizing},
                error_message=error.code.value,
            )

    def place_stop_loss_order(self, **kwargs) -> ExchangeOrderResult:
        return self._reject_order(kwargs, ExchangeOrderType.STOP_LOSS)

    def place_take_profit_order(self, **kwargs) -> ExchangeOrderResult:
        return self._reject_order(kwargs, ExchangeOrderType.TAKE_PROFIT)

    def cancel_order(self, account_id: str, symbol: str, order_id: str):
        self._require_live_enabled(account_id)
        raise ExchangeAdapterError(ExchangeErrorCode.LIVE_TRADING_DISABLED, "live cancel_order is not implemented in v1")

    def cancel_all_symbol_orders(self, account_id: str, symbol: str):
        self._require_live_enabled(account_id)
        raise ExchangeAdapterError(ExchangeErrorCode.LIVE_TRADING_DISABLED, "live cancel_all_symbol_orders is not implemented in v1")

    def _require_live_enabled(self, account_id: str) -> None:
        if self.mode is not ExchangeMode.LIVE_ENABLED:
            raise ExchangeAdapterError(ExchangeErrorCode.LIVE_TRADING_DISABLED, "adapter mode is not LIVE_ENABLED")
        account = self.credential_store.require_account(account_id)
        if not account.trading_enabled:
            raise ExchangeAdapterError(ExchangeErrorCode.LIVE_TRADING_DISABLED, "account trading is disabled")
        if account.verification_status is not VerificationStatus.VERIFIED:
            raise ExchangeAdapterError(ExchangeErrorCode.INVALID_CREDENTIALS, "account credentials are not verified")
        self.rate_limiter.acquire(account_id)

    def _reject_order(self, kwargs: dict[str, object], order_type: ExchangeOrderType) -> ExchangeOrderResult:
        timestamp = ensure_utc(kwargs.get("submitted_at") or datetime(2026, 1, 1, tzinfo=timezone.utc))
        account_id = str(kwargs["account_id"])
        symbol = str(kwargs["symbol"])
        side = str(kwargs.get("side", ExchangeOrderSide.BUY.value))
        size = to_decimal(kwargs.get("position_size", kwargs.get("size", Decimal("0"))))
        client_order_id = str(kwargs.get("client_order_id") or build_client_order_id(account_id=account_id, symbol=symbol, side=side, order_type=order_type.value, created_at=timestamp))
        return ExchangeOrderResult(
            exchange_order_id=None,
            client_order_id=client_order_id,
            account_id=account_id,
            symbol=symbol,
            side=ExchangeOrderSide(side),
            order_type=order_type,
            status=ExchangeOrderStatus.REJECTED,
            requested_size=size,
            filled_size=Decimal("0"),
            average_fill_price=None,
            submitted_at=timestamp,
            updated_at=timestamp,
            raw_response={"mode": self.mode.value},
            error_message=ExchangeErrorCode.LIVE_TRADING_DISABLED.value,
        )
