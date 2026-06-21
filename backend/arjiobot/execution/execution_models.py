"""Data models for the Execution Engine."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from arjiobot.market_data.candle_models import ensure_utc, to_decimal


class OrderSide(str, Enum):
    SELL = "SELL"
    BUY = "BUY"


class OrderType(str, Enum):
    MARKET = "MARKET"
    STOP = "STOP"
    TAKE_PROFIT = "TAKE_PROFIT"


class TimeInForce(str, Enum):
    IOC = "IOC"
    GTC = "GTC"


class ExecutionStatus(str, Enum):
    CREATED = "CREATED"
    VALIDATED = "VALIDATED"
    SUBMITTED = "SUBMITTED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    PROTECTIVE_ORDERS_PLANNED = "PROTECTIVE_ORDERS_PLANNED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    FAILED = "FAILED"


class ExecutionRejectionReason(str, Enum):
    TRADE_PLAN_NOT_APPROVED = "TRADE_PLAN_NOT_APPROVED"
    MISSING_REQUIRED_FIELD = "MISSING_REQUIRED_FIELD"
    UNSUPPORTED_ACTION = "UNSUPPORTED_ACTION"
    INVALID_POSITION_SIZE = "INVALID_POSITION_SIZE"
    INVALID_LEVERAGE = "INVALID_LEVERAGE"
    INVALID_STOP_LOSS = "INVALID_STOP_LOSS"
    INVALID_TAKE_PROFIT = "INVALID_TAKE_PROFIT"
    DUPLICATE_EXECUTION = "DUPLICATE_EXECUTION"
    PAPER_EXECUTION_FAILED = "PAPER_EXECUTION_FAILED"
    UNKNOWN_EXECUTION_ERROR = "UNKNOWN_EXECUTION_ERROR"


@dataclass(frozen=True, slots=True)
class OrderInstruction:
    order_instruction_id: str
    trade_plan_id: str
    signal_id: str
    setup_id: str
    symbol: str
    side: OrderSide
    order_type: OrderType
    position_size: Decimal
    leverage: Decimal
    entry_reference_price: Decimal
    stop_loss_price: Decimal
    take_profit_price: Decimal
    trade_type: str
    margin_mode: str
    margin_amount: Decimal
    risk_amount: Decimal
    required_leverage: Decimal
    max_allowed_leverage: Decimal
    notional_position_size: Decimal
    expected_loss_at_sl: Decimal
    reduce_only: bool
    time_in_force: TimeInForce
    created_at: datetime
    metadata: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbol", self.symbol.upper())
        object.__setattr__(self, "created_at", ensure_utc(self.created_at))
        for field_name in (
            "position_size",
            "leverage",
            "entry_reference_price",
            "stop_loss_price",
            "take_profit_price",
            "margin_amount",
            "risk_amount",
            "required_leverage",
            "max_allowed_leverage",
            "notional_position_size",
            "expected_loss_at_sl",
        ):
            object.__setattr__(self, field_name, to_decimal(getattr(self, field_name)))
        if not self.order_instruction_id:
            raise ValueError("order_instruction_id is required")
        if self.position_size <= Decimal("0"):
            raise ValueError("position_size must be positive")
        if self.leverage < Decimal("1"):
            raise ValueError("leverage must be at least 1")
        if self.trade_type != "ISOLATED_MARGIN" or self.margin_mode != "isolated":
            raise ValueError("orders must use isolated margin")
        if self.margin_amount <= Decimal("0") or self.required_leverage <= Decimal("0"):
            raise ValueError("isolated margin amount must be derived from notional and required leverage")
        implied_margin = self.notional_position_size / self.required_leverage
        if abs(implied_margin - self.margin_amount) > max(Decimal("0.00000001"), self.margin_amount * Decimal("0.000001")):
            raise ValueError("isolated margin amount must match notional position size divided by required leverage")


@dataclass(frozen=True, slots=True)
class ProtectiveOrderPlan:
    protective_order_id: str
    execution_id: str
    trade_plan_id: str
    symbol: str
    side: OrderSide
    order_type: OrderType
    trigger_price: Decimal
    position_size: Decimal
    reduce_only: bool
    created_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbol", self.symbol.upper())
        object.__setattr__(self, "trigger_price", to_decimal(self.trigger_price))
        object.__setattr__(self, "position_size", to_decimal(self.position_size))
        object.__setattr__(self, "created_at", ensure_utc(self.created_at))


@dataclass(frozen=True, slots=True)
class ExecutionRecord:
    execution_id: str
    trade_plan_id: str
    signal_id: str
    setup_id: str
    symbol: str
    status: ExecutionStatus
    order_instruction_id: str | None
    created_at: datetime
    submitted_at: datetime | None = None
    filled_at: datetime | None = None
    cancelled_at: datetime | None = None
    rejected_at: datetime | None = None
    fill_price: Decimal | None = None
    filled_size: Decimal | None = None
    stop_loss_price: Decimal | None = None
    take_profit_price: Decimal | None = None
    exchange_order_id: str | None = None
    paper_execution: bool = True
    rejection_reason: ExecutionRejectionReason | None = None
    protective_orders: tuple[ProtectiveOrderPlan, ...] = ()
    metadata: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbol", self.symbol.upper())
        object.__setattr__(self, "created_at", ensure_utc(self.created_at))
        for field_name in ("submitted_at", "filled_at", "cancelled_at", "rejected_at"):
            value = getattr(self, field_name)
            if value is not None:
                object.__setattr__(self, field_name, ensure_utc(value))
        for field_name in ("fill_price", "filled_size", "stop_loss_price", "take_profit_price"):
            value = getattr(self, field_name)
            if value is not None:
                object.__setattr__(self, field_name, to_decimal(value))
        if self.status is ExecutionStatus.REJECTED and self.rejection_reason is None:
            raise ValueError("rejected executions require rejection_reason")


def build_order_instruction_id(trade_plan_id: str, created_at: datetime) -> str:
    raw = f"{trade_plan_id}|{ensure_utc(created_at).isoformat()}|ORDER"
    return f"ord_{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:24]}"


def build_execution_id(trade_plan_id: str, created_at: datetime) -> str:
    raw = f"{trade_plan_id}|{ensure_utc(created_at).isoformat()}|EXEC"
    return f"exe_{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:24]}"


def build_protective_order_id(execution_id: str, order_type: OrderType) -> str:
    raw = f"{execution_id}|{order_type.value}"
    return f"pxo_{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:24]}"


_TERMINAL_EXECUTION_STATUSES = frozenset({ExecutionStatus.CANCELLED, ExecutionStatus.REJECTED, ExecutionStatus.FAILED})


def execution_to_record(execution: ExecutionRecord) -> dict[str, Any]:
    return {
        "execution_id": execution.execution_id,
        "trade_plan_id": execution.trade_plan_id,
        "signal_id": execution.signal_id,
        "setup_id": execution.setup_id,
        "symbol": execution.symbol,
        "status": execution.status.value,
        # A trade is "active" once submitted/filled and stays that way until a
        # terminal status is reached - there is no further fill/close simulation
        # yet, so FILLED has no separate "closed" state to transition into.
        "is_active": execution.status not in _TERMINAL_EXECUTION_STATUSES,
        "fill_price": execution.fill_price,
        "filled_size": execution.filled_size,
        "stop_loss_price": execution.stop_loss_price,
        "take_profit_price": execution.take_profit_price,
        "exchange_order_id": execution.exchange_order_id,
        "paper_execution": execution.paper_execution,
        "rejection_reason": execution.rejection_reason.value if execution.rejection_reason else None,
        "created_at": execution.created_at.isoformat(),
        "submitted_at": execution.submitted_at.isoformat() if execution.submitted_at else None,
        "filled_at": execution.filled_at.isoformat() if execution.filled_at else None,
        "cancelled_at": execution.cancelled_at.isoformat() if execution.cancelled_at else None,
        "rejected_at": execution.rejected_at.isoformat() if execution.rejected_at else None,
        "metadata": execution.metadata,
    }
