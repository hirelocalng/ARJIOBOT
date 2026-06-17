"""Data models for deterministic ArjioBot backtesting."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from arjiobot.market_data.candle_models import ensure_utc, to_decimal
from arjiobot.setup_tracker.setup_models import SetupDirection


class SameCandleResolutionPolicy(str, Enum):
    """Policies for candles that hit TP and SL."""

    CONSERVATIVE_STOP_FIRST = "CONSERVATIVE_STOP_FIRST"
    OPTIMISTIC_TP_FIRST = "OPTIMISTIC_TP_FIRST"
    SKIP_TRADE = "SKIP_TRADE"
    MARK_AMBIGUOUS = "MARK_AMBIGUOUS"


class SlippageModelType(str, Enum):
    """Supported slippage models."""

    FIXED_BPS = "FIXED_BPS"


class BacktestStatus(str, Enum):
    """Backtest run statuses."""

    CREATED = "CREATED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class TradeStatus(str, Enum):
    """Simulated trade statuses."""

    ENTERED = "ENTERED"
    CLOSED = "CLOSED"
    SKIPPED_TARGET_ALREADY_REACHED = "SKIPPED_TARGET_ALREADY_REACHED"
    SKIPPED_NO_ENTRY_CANDLE = "SKIPPED_NO_ENTRY_CANDLE"
    AMBIGUOUS = "AMBIGUOUS"
    OPEN = "OPEN"


class TradeExitReason(str, Enum):
    """Simulated trade exit reasons."""

    TAKE_PROFIT = "TAKE_PROFIT"
    STOP_LOSS = "STOP_LOSS"
    AMBIGUOUS = "AMBIGUOUS"
    TARGET_ALREADY_REACHED = "TARGET_ALREADY_REACHED"
    NO_ENTRY_CANDLE = "NO_ENTRY_CANDLE"
    END_OF_DATA = "END_OF_DATA"


@dataclass(frozen=True, slots=True)
class SlippageConfig:
    """Fixed-bps slippage configuration."""

    model_type: SlippageModelType = SlippageModelType.FIXED_BPS
    fixed_bps: Decimal = Decimal("0")

    def __post_init__(self) -> None:
        object.__setattr__(self, "fixed_bps", to_decimal(self.fixed_bps))
        if self.fixed_bps < Decimal("0"):
            raise ValueError("fixed_bps cannot be negative")


@dataclass(frozen=True, slots=True)
class BacktestConfig:
    """Backtest configuration."""

    run_id: str
    symbols: tuple[str, ...]
    start_time: datetime
    end_time: datetime
    initial_balance: Decimal | None = None
    risk_per_trade: Decimal | None = None
    fixed_risk_amount: Decimal | None = None
    selected_rr_profile: str = "RR_1_5"
    max_open_trades: int = 1
    fee_rate: Decimal = Decimal("0.0006")
    slippage_model: SlippageConfig = field(default_factory=SlippageConfig)
    spread_model: str = "NONE"
    timeframe_profile: tuple[int, ...] = (1, 8, 12, 16, 30, 60)
    allow_multiple_signals_per_symbol: bool = False
    same_candle_resolution_policy: SameCandleResolutionPolicy = SameCandleResolutionPolicy.CONSERVATIVE_STOP_FIRST
    random_seed: int = 0
    notes: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbols", tuple(symbol.upper() for symbol in self.symbols))
        object.__setattr__(self, "start_time", ensure_utc(self.start_time))
        object.__setattr__(self, "end_time", ensure_utc(self.end_time))
        if self.initial_balance is None:
            raise ValueError("initial_balance is required; no hidden default is allowed")
        if self.risk_per_trade is None and self.fixed_risk_amount is None:
            raise ValueError("fixed_risk_amount is required; no hidden default is allowed")
        object.__setattr__(self, "initial_balance", to_decimal(self.initial_balance))
        if self.risk_per_trade is not None:
            object.__setattr__(self, "risk_per_trade", to_decimal(self.risk_per_trade))
        if self.fixed_risk_amount is not None:
            object.__setattr__(self, "fixed_risk_amount", to_decimal(self.fixed_risk_amount))
        object.__setattr__(self, "fee_rate", to_decimal(self.fee_rate))
        if not self.run_id:
            raise ValueError("run_id is required")
        if not self.symbols:
            raise ValueError("symbols are required")
        if self.start_time >= self.end_time:
            raise ValueError("start_time must be before end_time")
        if self.initial_balance <= Decimal("0"):
            raise ValueError("initial_balance must be positive")
        fixed_risk = self.fixed_risk_amount if self.fixed_risk_amount is not None else self.risk_per_trade
        object.__setattr__(self, "fixed_risk_amount", fixed_risk)
        object.__setattr__(self, "risk_per_trade", fixed_risk)
        object.__setattr__(self, "selected_rr_profile", self.selected_rr_profile.strip().upper())
        if self.fixed_risk_amount <= Decimal("0"):
            raise ValueError("fixed_risk_amount must be positive")
        if self.max_open_trades < 1:
            raise ValueError("max_open_trades must be positive")
        if self.fee_rate < Decimal("0"):
            raise ValueError("fee_rate cannot be negative")
        if 1 not in self.timeframe_profile:
            raise ValueError("timeframe_profile must include 1M")


@dataclass(frozen=True, slots=True)
class SimulatedTrade:
    """Replay-safe simulated trade."""

    trade_id: str
    signal_id: str
    setup_id: str
    symbol: str
    direction: SetupDirection
    entry_time: datetime | None
    entry_price: Decimal | None
    stop_loss_price: Decimal
    take_profit_price: Decimal
    exit_time: datetime | None
    exit_price: Decimal | None
    exit_reason: TradeExitReason
    risk_amount: Decimal
    position_size: Decimal
    gross_pnl: Decimal
    fees_paid: Decimal
    slippage_paid: Decimal
    net_pnl: Decimal
    r_multiple: Decimal
    status: TradeStatus
    metadata: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbol", self.symbol.upper())
        if self.entry_time is not None:
            object.__setattr__(self, "entry_time", ensure_utc(self.entry_time))
        if self.exit_time is not None:
            object.__setattr__(self, "exit_time", ensure_utc(self.exit_time))
        for field_name in (
            "entry_price",
            "stop_loss_price",
            "take_profit_price",
            "exit_price",
            "risk_amount",
            "position_size",
            "gross_pnl",
            "fees_paid",
            "slippage_paid",
            "net_pnl",
            "r_multiple",
        ):
            value = getattr(self, field_name)
            if value is not None:
                object.__setattr__(self, field_name, to_decimal(value))
        if not self.trade_id:
            raise ValueError("trade_id is required")
        if not self.signal_id:
            raise ValueError("signal_id is required")
        if self.stop_loss_price <= self.take_profit_price and self.direction is not SetupDirection.BEARISH:
            raise ValueError("unsupported stop/target relationship")


@dataclass(frozen=True, slots=True)
class BacktestMetrics:
    """Backtest performance metrics."""

    total_trades: int
    wins: int
    losses: int
    skipped_trades: int
    ambiguous_trades: int
    win_rate: float
    gross_profit: Decimal
    gross_loss: Decimal
    net_profit: Decimal
    profit_factor: float
    average_r: float
    expectancy: float
    max_drawdown: Decimal
    max_drawdown_percent: float
    ending_balance: Decimal
    equity_curve: tuple[tuple[datetime, Decimal], ...]
    largest_win: Decimal
    largest_loss: Decimal
    average_win: Decimal
    average_loss: Decimal
    setup_conversion: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class BacktestRun:
    """Backtest run record."""

    run_id: str
    symbols: tuple[str, ...]
    start_time: datetime
    end_time: datetime
    created_at: datetime
    config: BacktestConfig
    total_candles_processed: int = 0
    total_setups_detected: int = 0
    total_signals_generated: int = 0
    total_trades_simulated: int = 0
    metrics: BacktestMetrics | None = None
    status: BacktestStatus = BacktestStatus.CREATED
    errors: tuple[str, ...] = ()
    reports: dict[str, str] = field(default_factory=dict)
    metadata: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbols", tuple(symbol.upper() for symbol in self.symbols))
        object.__setattr__(self, "start_time", ensure_utc(self.start_time))
        object.__setattr__(self, "end_time", ensure_utc(self.end_time))
        object.__setattr__(self, "created_at", ensure_utc(self.created_at))


def build_trade_id(signal_id: str, entry_time: datetime | None, exit_reason: TradeExitReason) -> str:
    """Build deterministic trade ID."""
    raw = "|".join((signal_id, ensure_utc(entry_time).isoformat() if entry_time else "NO_ENTRY", exit_reason.value))
    return f"trd_{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:24]}"


def build_run_id(symbols: tuple[str, ...], start_time: datetime, end_time: datetime, seed: int = 0) -> str:
    """Build deterministic run ID."""
    raw = "|".join((*tuple(symbol.upper() for symbol in symbols), ensure_utc(start_time).isoformat(), ensure_utc(end_time).isoformat(), str(seed)))
    return f"bt_{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:24]}"


def trade_to_record(trade: SimulatedTrade) -> dict[str, Any]:
    """Return storage/export friendly trade record."""
    return {
        "trade_id": trade.trade_id,
        "signal_id": trade.signal_id,
        "setup_id": trade.setup_id,
        "symbol": trade.symbol,
        "direction": trade.direction.value,
        "entry_time": trade.entry_time,
        "entry_price": trade.entry_price,
        "entry": trade.entry_price,
        "sl": trade.stop_loss_price,
        "tp": trade.take_profit_price,
        "exit_time": trade.exit_time,
        "exit_price": trade.exit_price,
        "exit": trade.exit_price,
        "exit_reason": trade.exit_reason.value,
        "fixed_risk_amount": trade.metadata.get("fixed_risk_amount", str(trade.risk_amount)),
        "selected_starting_balance": trade.metadata.get("selected_starting_balance", ""),
        "applied_starting_balance": trade.metadata.get("applied_starting_balance", ""),
        "selected_fixed_risk_amount": trade.metadata.get("selected_fixed_risk_amount", str(trade.risk_amount)),
        "applied_margin_amount": trade.metadata.get("applied_margin_amount", ""),
        "risk_amount": trade.risk_amount,
        "trade_type": trade.metadata.get("trade_type", "ISOLATED_MARGIN"),
        "margin_mode": trade.metadata.get("margin_mode", "isolated"),
        "entry_price": trade.entry_price,
        "stop_loss": trade.stop_loss_price,
        "take_profit": trade.take_profit_price,
        "price_risk_percent": trade.metadata.get("price_risk_percent", ""),
        "required_leverage": trade.metadata.get("required_leverage", ""),
        "applied_leverage": trade.metadata.get("applied_leverage", ""),
        "max_allowed_leverage": trade.metadata.get("max_allowed_leverage", ""),
        "notional_position_size": trade.metadata.get("notional_position_size", ""),
        "quantity": trade.metadata.get("quantity", str(trade.position_size)),
        "expected_loss_at_sl": trade.metadata.get("expected_loss_at_sl", ""),
        "exchange": trade.metadata.get("exchange", "BACKTEST"),
        "trade_mode": trade.metadata.get("trade_mode", "BACKTEST"),
        "risk_lock_status": trade.metadata.get("risk_lock_status", ""),
        "environment_lock_status": trade.metadata.get("environment_lock_status", ""),
        "exchange_lock_status": trade.metadata.get("exchange_lock_status", ""),
        "profile_lock_status": trade.metadata.get("profile_lock_status", ""),
        "selected_rr_profile": trade.metadata.get("selected_rr_profile", ""),
        "selected_rr_value": trade.metadata.get("selected_rr_value", ""),
        "target_reward_amount": trade.metadata.get("target_reward_amount", ""),
        "position_size": trade.position_size,
        "actual_risk_amount": trade.metadata.get("actual_risk_amount", ""),
        "expected_reward_amount": trade.metadata.get("expected_reward_amount", ""),
        "actual_rr": trade.metadata.get("actual_rr", ""),
        "net_pnl": trade.net_pnl,
        "r_multiple": trade.r_multiple,
        "status": trade.status.value,
    }
