"""Risk validation tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal

from arjiobot.risk.demo_risk import default_context, make_signal
from arjiobot.risk.risk_models import AccountSnapshot, OpenRiskState, RiskConfig, RiskRejectionReason
from arjiobot.risk.risk_validation import validate_signal_risk


def risk_config(**overrides):
    return RiskConfig(account_equity=Decimal("10000"), fixed_risk_amount=Decimal("100"), **overrides)


def reasons_for(signal, config=None, state=None, snapshot=None):
    config_, snapshot_, state_ = default_context()
    return validate_signal_risk(signal=signal, risk_config=config or config_, account_snapshot=snapshot or snapshot_, open_risk_state=state or state_)[0]


def test_valid_bearish_signal_passes() -> None:
    assert reasons_for(make_signal()) == ()


def test_missing_entry_and_invalid_stop_target() -> None:
    signal = make_signal()
    assert RiskRejectionReason.MISSING_ENTRY_REFERENCE_PRICE in reasons_for(replace(signal, entry_reference_price=None))
    assert RiskRejectionReason.INVALID_STOP_RELATIONSHIP in reasons_for(replace(signal, stop_reference_price=Decimal("80")))
    assert RiskRejectionReason.INVALID_TARGET_RELATIONSHIP not in reasons_for(replace(signal, final_target_price=Decimal("100")))


def test_rr_too_low_and_insufficient_available_margin() -> None:
    signal = make_signal()
    assert RiskRejectionReason.RR_TOO_LOW in reasons_for(signal, config=risk_config(minimum_rr_ratio=Decimal("2")))
    scarce_margin_snapshot = AccountSnapshot(account_currency="USDT", account_equity=Decimal("10000"), available_margin=Decimal("1"), captured_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    assert RiskRejectionReason.INSUFFICIENT_AVAILABLE_MARGIN in reasons_for(signal, snapshot=scarce_margin_snapshot)


def test_trade_count_loss_limits_reserved_and_exposure() -> None:
    signal = make_signal()
    assert RiskRejectionReason.MAX_OPEN_TRADES_REACHED in reasons_for(signal, state=OpenRiskState(open_trade_count=1))
    assert RiskRejectionReason.DAILY_LOSS_LIMIT_REACHED in reasons_for(signal, state=OpenRiskState(current_daily_pnl=Decimal("-450"), reserved_risk_amount=Decimal("0")))
    assert RiskRejectionReason.WEEKLY_LOSS_LIMIT_REACHED in reasons_for(signal, state=OpenRiskState(current_weekly_pnl=Decimal("-1450"), reserved_risk_amount=Decimal("0")))
    assert RiskRejectionReason.DAILY_LOSS_LIMIT_REACHED in reasons_for(signal, state=OpenRiskState(reserved_risk_amount=Decimal("450")))
    assert RiskRejectionReason.SAME_SYMBOL_EXPOSURE_BLOCKED in reasons_for(signal, state=OpenRiskState(open_symbol_exposure={"BTCUSDT": Decimal("1")}))
    assert RiskRejectionReason.SYMBOL_EXPOSURE_LIMIT_REACHED in reasons_for(signal, config=risk_config(max_symbol_exposure=Decimal("10"), allow_multiple_positions_same_symbol=True))


def test_position_size_limits() -> None:
    signal = make_signal()
    assert RiskRejectionReason.POSITION_SIZE_TOO_SMALL in reasons_for(signal, config=risk_config(min_position_size=Decimal("10")))
    assert RiskRejectionReason.POSITION_SIZE_TOO_LARGE in reasons_for(signal, config=risk_config(max_position_size=Decimal("1")))
