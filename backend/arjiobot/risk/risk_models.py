"""Data models for the ArjioBot Risk Engine."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from arjiobot.market_data.candle_models import ensure_utc, to_decimal
from arjiobot.setup_tracker.setup_models import SetupDirection
from arjiobot.strategy.strategy_models import SignalAction


class RiskRejectionReason(str, Enum):
    """Risk rejection reasons."""

    MISSING_ENTRY_REFERENCE_PRICE = "MISSING_ENTRY_REFERENCE_PRICE"
    INVALID_STOP_RELATIONSHIP = "INVALID_STOP_RELATIONSHIP"
    INVALID_TARGET_RELATIONSHIP = "INVALID_TARGET_RELATIONSHIP"
    RISK_DISTANCE_ZERO_OR_NEGATIVE = "RISK_DISTANCE_ZERO_OR_NEGATIVE"
    RR_TOO_LOW = "RR_TOO_LOW"
    LEVERAGE_EXCEEDS_MAX = "LEVERAGE_EXCEEDS_MAX"
    REQUIRED_LEVERAGE_EXCEEDS_MAX = "BLOCKED_REQUIRED_LEVERAGE_EXCEEDS_MAX"
    MAX_OPEN_TRADES_REACHED = "MAX_OPEN_TRADES_REACHED"
    DAILY_LOSS_LIMIT_REACHED = "DAILY_LOSS_LIMIT_REACHED"
    WEEKLY_LOSS_LIMIT_REACHED = "WEEKLY_LOSS_LIMIT_REACHED"
    POSITION_SIZE_TOO_SMALL = "POSITION_SIZE_TOO_SMALL"
    POSITION_SIZE_TOO_LARGE = "POSITION_SIZE_TOO_LARGE"
    INVALID_RR_PROFILE = "INVALID_RR_PROFILE"
    INVALID_FIXED_RISK_AMOUNT = "INVALID_FIXED_RISK_AMOUNT"
    FIXED_RISK_VALIDATION_FAILED = "FIXED_RISK_VALIDATION_FAILED"
    SAME_SYMBOL_EXPOSURE_BLOCKED = "SAME_SYMBOL_EXPOSURE_BLOCKED"
    SYMBOL_EXPOSURE_LIMIT_REACHED = "SYMBOL_EXPOSURE_LIMIT_REACHED"
    ACCOUNT_EQUITY_TOO_LOW = "ACCOUNT_EQUITY_TOO_LOW"
    INVALID_RISK_CONFIG = "INVALID_RISK_CONFIG"
    UNSUPPORTED_SIGNAL_ACTION = "UNSUPPORTED_SIGNAL_ACTION"
    UNKNOWN_RISK_ERROR = "UNKNOWN_RISK_ERROR"


class TradePlanStatus(str, Enum):
    """Trade plan approval status."""

    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SENT_TO_EXECUTION = "SENT_TO_EXECUTION"
    CANCELLED = "CANCELLED"


@dataclass(frozen=True, slots=True)
class RiskConfig:
    """User risk configuration."""

    account_currency: str = "USDT"
    account_equity: Decimal | None = None
    risk_amount_per_trade: Decimal | None = None
    fixed_risk_amount: Decimal | None = None
    selected_rr_profile: str = "RR_1_5"
    max_leverage: Decimal = Decimal("10")
    max_open_trades: int = 1
    max_daily_loss: Decimal = Decimal("500")
    max_weekly_loss: Decimal = Decimal("1500")
    min_position_size: Decimal = Decimal("0")
    max_position_size: Decimal = Decimal("1000000")
    max_symbol_exposure: Decimal = Decimal("1000000")
    allow_multiple_positions_same_symbol: bool = False
    fee_rate_buffer: Decimal = Decimal("0")
    slippage_buffer_bps: Decimal = Decimal("0")
    minimum_rr_ratio: Decimal = Decimal("0")
    allocated_margin: Decimal | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "account_equity",
            "risk_amount_per_trade",
            "fixed_risk_amount",
            "max_leverage",
            "max_daily_loss",
            "max_weekly_loss",
            "min_position_size",
            "max_position_size",
            "max_symbol_exposure",
            "fee_rate_buffer",
            "slippage_buffer_bps",
            "minimum_rr_ratio",
            "allocated_margin",
        ):
            value = getattr(self, field_name)
            if value is not None:
                object.__setattr__(self, field_name, to_decimal(value))
        if self.account_equity is None:
            raise ValueError("account_equity is required; no hidden default is allowed")
        if self.risk_amount_per_trade is None and self.fixed_risk_amount is None:
            raise ValueError("fixed_risk_amount is required; no hidden default is allowed")
        if self.account_equity <= Decimal("0"):
            raise ValueError("account_equity must be positive")
        fixed_risk = self.fixed_risk_amount if self.fixed_risk_amount is not None else self.risk_amount_per_trade
        object.__setattr__(self, "fixed_risk_amount", fixed_risk)
        object.__setattr__(self, "risk_amount_per_trade", fixed_risk)
        object.__setattr__(self, "selected_rr_profile", self.selected_rr_profile.strip().upper())
        if self.fixed_risk_amount <= Decimal("0"):
            raise ValueError("fixed_risk_amount must be positive")
        if self.max_leverage < Decimal("1"):
            raise ValueError("max_leverage must be at least 1")


@dataclass(frozen=True, slots=True)
class AccountSnapshot:
    """Account/equity snapshot."""

    account_currency: str
    account_equity: Decimal
    available_margin: Decimal
    captured_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "account_equity", to_decimal(self.account_equity))
        object.__setattr__(self, "available_margin", to_decimal(self.available_margin))
        object.__setattr__(self, "captured_at", ensure_utc(self.captured_at))
        if self.account_equity <= Decimal("0"):
            raise ValueError("account_equity must be positive")
        if self.available_margin <= Decimal("0"):
            raise ValueError("available_margin must be positive")


@dataclass(frozen=True, slots=True)
class OpenRiskState:
    """Current open risk state."""

    open_trade_count: int = 0
    open_symbol_exposure: dict[str, Decimal] = field(default_factory=dict)
    current_daily_pnl: Decimal = Decimal("0")
    current_weekly_pnl: Decimal = Decimal("0")
    reserved_risk_amount: Decimal = Decimal("0")

    def __post_init__(self) -> None:
        object.__setattr__(self, "open_symbol_exposure", {key.upper(): to_decimal(value) for key, value in self.open_symbol_exposure.items()})
        object.__setattr__(self, "current_daily_pnl", to_decimal(self.current_daily_pnl))
        object.__setattr__(self, "current_weekly_pnl", to_decimal(self.current_weekly_pnl))
        object.__setattr__(self, "reserved_risk_amount", to_decimal(self.reserved_risk_amount))


@dataclass(frozen=True, slots=True)
class PositionSize:
    """Position size calculation."""

    risk_amount: Decimal
    risk_distance: Decimal
    position_size: Decimal
    notional_value: Decimal


@dataclass(frozen=True, slots=True)
class LeveragePlan:
    """Leverage calculation."""

    required_leverage: Decimal
    approved_leverage: Decimal
    required_margin: Decimal


@dataclass(frozen=True, slots=True)
class MarginPlanFields:
    """Isolated-margin sizing fields required by execution and reports."""

    trade_type: str = "ISOLATED_MARGIN"
    margin_mode: str = "isolated"
    applied_margin_amount: Decimal = Decimal("0")
    price_risk_percent: Decimal = Decimal("0")
    required_leverage: Decimal = Decimal("0")
    applied_leverage: Decimal = Decimal("0")
    max_allowed_leverage: Decimal = Decimal("0")
    notional_position_size: Decimal = Decimal("0")
    quantity: Decimal = Decimal("0")
    expected_loss_at_sl: Decimal = Decimal("0")


@dataclass(frozen=True, slots=True)
class RiskAssessment:
    """Risk assessment record."""

    assessment_id: str
    signal_id: str
    symbol: str
    evaluated_at: datetime
    validation_passed: bool
    rejection_reasons: tuple[RiskRejectionReason, ...]
    risk_amount: Decimal
    risk_distance: Decimal
    reward_distance: Decimal
    rr_ratio: Decimal
    fixed_risk_amount: Decimal
    selected_rr_profile: str
    selected_rr_value: Decimal
    target_reward_amount: Decimal
    actual_risk_amount: Decimal
    expected_reward_amount: Decimal
    actual_rr: Decimal
    calculated_take_profit_price: Decimal | None
    position_size: Decimal
    notional_value: Decimal
    required_leverage: Decimal
    approved_leverage: Decimal
    required_margin: Decimal
    daily_loss_capacity_remaining: Decimal
    weekly_loss_capacity_remaining: Decimal
    exposure_after_trade: Decimal
    trade_type: str = "ISOLATED_MARGIN"
    margin_mode: str = "isolated"
    applied_margin_amount: Decimal = Decimal("0")
    price_risk_percent: Decimal = Decimal("0")
    max_allowed_leverage: Decimal = Decimal("0")
    quantity: Decimal = Decimal("0")
    expected_loss_at_sl: Decimal = Decimal("0")
    metadata: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbol", self.symbol.upper())
        object.__setattr__(self, "evaluated_at", ensure_utc(self.evaluated_at))


@dataclass(frozen=True, slots=True)
class TradePlan:
    """Risk-approved or rejected trade plan."""

    trade_plan_id: str
    signal_id: str
    setup_id: str
    symbol: str
    direction: SetupDirection
    action: SignalAction
    entry_reference_price: Decimal | None
    stop_loss_price: Decimal | None
    take_profit_price: Decimal | None
    risk_amount: Decimal
    position_size: Decimal
    notional_value: Decimal
    required_margin: Decimal
    leverage: Decimal
    rr_ratio: Decimal
    fixed_risk_amount: Decimal
    selected_rr_profile: str
    selected_rr_value: Decimal
    target_reward_amount: Decimal
    actual_risk_amount: Decimal
    expected_reward_amount: Decimal
    actual_rr: Decimal
    trade_type: str
    margin_mode: str
    applied_margin_amount: Decimal
    price_risk_percent: Decimal
    max_allowed_leverage: Decimal
    quantity: Decimal
    expected_loss_at_sl: Decimal
    fee_buffer: Decimal
    slippage_buffer: Decimal
    approval_status: TradePlanStatus
    rejection_reasons: tuple[RiskRejectionReason, ...]
    created_at: datetime
    updated_at: datetime
    required_leverage: Decimal = Decimal("0")
    metadata: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbol", self.symbol.upper())
        object.__setattr__(self, "created_at", ensure_utc(self.created_at))
        object.__setattr__(self, "updated_at", ensure_utc(self.updated_at))


def build_assessment_id(signal_id: str, evaluated_at: datetime) -> str:
    """Build deterministic assessment ID."""
    raw = f"{signal_id}|{ensure_utc(evaluated_at).isoformat()}"
    return f"rsa_{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:24]}"


def build_trade_plan_id(signal_id: str, evaluated_at: datetime) -> str:
    """Build deterministic trade plan ID."""
    raw = f"{signal_id}|{ensure_utc(evaluated_at).isoformat()}"
    return f"tpl_{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:24]}"


def trade_plan_to_record(plan: TradePlan) -> dict[str, Any]:
    """Return storage-friendly trade plan record."""
    return {
        "trade_plan_id": plan.trade_plan_id,
        "signal_id": plan.signal_id,
        "symbol": plan.symbol,
        "action": plan.action.value,
        "approval_status": plan.approval_status.value,
        "rejection_reasons": tuple(reason.value for reason in plan.rejection_reasons),
        "position_size": plan.position_size,
        "fixed_risk_amount": plan.fixed_risk_amount,
        "selected_rr_profile": plan.selected_rr_profile,
        "selected_tp_model": plan.selected_rr_profile,
        "applied_tp_model": plan.selected_rr_profile,
        "tp_model_lock_status": "UNLOCKED",
        "selected_rr_value": plan.selected_rr_value,
        "actual_risk_amount": plan.actual_risk_amount,
        "expected_reward_amount": plan.expected_reward_amount,
        "actual_rr": plan.actual_rr,
        "trade_type": plan.trade_type,
        "margin_mode": plan.margin_mode,
        "applied_margin_amount": plan.applied_margin_amount,
        "price_risk_percent": plan.price_risk_percent,
        "required_leverage": plan.required_leverage,
        "applied_leverage": plan.leverage,
        "max_allowed_leverage": plan.max_allowed_leverage,
        "notional_position_size": plan.notional_value,
        "quantity": plan.quantity,
        "expected_loss_at_sl": plan.expected_loss_at_sl,
        "leverage": plan.leverage,
        "rr_ratio": plan.rr_ratio,
        "time_exit_enabled": plan.metadata.get("time_exit_enabled", "NO"),
        "time_exit_minutes": plan.metadata.get("time_exit_minutes", ""),
        "planned_time_exit_at": plan.metadata.get("planned_time_exit_at", ""),
        "close_type": plan.metadata.get("time_exit_close_type", ""),
    }
