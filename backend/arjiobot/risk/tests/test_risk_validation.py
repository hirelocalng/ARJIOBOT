"""Risk validation tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal

from arjiobot.risk.demo_risk import default_context, make_signal
from arjiobot.risk.risk_models import AccountSnapshot, OpenRiskState, RiskConfig, RiskRejectionReason
from arjiobot.risk.risk_validation import calculate_max_safe_leverage, validate_signal_risk


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


# --- calculate_max_safe_leverage -------------------------------------------
#
# Worked example throughout: entry=0.6309, stop=0.6247, R=2.0, k=0.0071
# (maintenance_margin_rate+close_fee_rate - the split between the two doesn't
# matter, only the sum does). Exact math: Q=R/|entry-stop|=2.0/0.0062=
# 322.580645..., N=Q*entry=203.516129... (not the 203.41 a quick mental
# rounding might suggest - 6309/31 worked out exactly confirms 203.52),
# MM_stop=Q*stop*k=1.430765..., M_required=R+MM_stop/T. These intermediate
# values aren't part of calculate_max_safe_leverage's return signature (only
# L_max is), so only L_max is asserted below; the bitget_environment
# [MMR-SAFE] audit log line (test_bitget_environment_routes.py) is what
# surfaces Q/N/MM_stop/M_required for operators.

_WORKED_ENTRY = Decimal("0.6309")
_WORKED_STOP = Decimal("0.6247")
_WORKED_RISK = Decimal("2.0")
_WORKED_MMR_RATE = Decimal("0.0068")
_WORKED_FEE_RATE = Decimal("0.0003")  # _WORKED_MMR_RATE + _WORKED_FEE_RATE == 0.0071 == k


def test_calculate_max_safe_leverage_matches_worked_example() -> None:
    assert calculate_max_safe_leverage(
        _WORKED_ENTRY, _WORKED_STOP, _WORKED_RISK,
        maintenance_margin_rate=_WORKED_MMR_RATE, close_fee_rate=_WORKED_FEE_RATE, target_mmr=Decimal("0.70"),
    ) == 50


def test_calculate_max_safe_leverage_target_mmr_variations() -> None:
    """Same worked example, varying only target_mmr: a looser target (T=1.00,
    MMR allowed to reach 100% at the stop) permits more leverage; a tighter
    target (T=0.50, a bigger safety cushion) permits less."""
    lev_loose = calculate_max_safe_leverage(
        _WORKED_ENTRY, _WORKED_STOP, _WORKED_RISK,
        maintenance_margin_rate=_WORKED_MMR_RATE, close_fee_rate=_WORKED_FEE_RATE, target_mmr=Decimal("1.00"),
    )
    lev_tight = calculate_max_safe_leverage(
        _WORKED_ENTRY, _WORKED_STOP, _WORKED_RISK,
        maintenance_margin_rate=_WORKED_MMR_RATE, close_fee_rate=_WORKED_FEE_RATE, target_mmr=Decimal("0.50"),
    )
    assert lev_loose == 59
    # The exact value floors to 41 (59.32... -> 41.86... as T tightens), not
    # the 42 a quick round() might suggest - calculate_max_safe_leverage is
    # specified to floor, never round, so the most conservative (smaller)
    # integer below the exact 41.86x is what must come out here.
    assert lev_tight == 41
    assert lev_tight < lev_loose, "a tighter target_mmr (bigger safety cushion) must never permit MORE leverage"


def test_calculate_max_safe_leverage_short_trade_sl_above_entry() -> None:
    """Same formula for a short - sl_price is always the stop level, above
    entry for a short instead of below it for a long. abs(entry-sl_price)
    makes the distance identical either way, but N (uses entry_price) and
    MM_stop (uses sl_price) are not symmetric under swapping the two, so this
    is checked against its own independently-derived expected value, not
    against the long-side worked example's result."""
    short_leverage = calculate_max_safe_leverage(
        _WORKED_STOP, _WORKED_ENTRY, _WORKED_RISK,  # entry/stop swapped relative to the long worked example
        maintenance_margin_rate=_WORKED_MMR_RATE, close_fee_rate=_WORKED_FEE_RATE, target_mmr=Decimal("0.70"),
    )
    assert short_leverage == 49
    assert short_leverage >= 1


def test_calculate_max_safe_leverage_sl_extremely_close_to_entry_does_not_crash(caplog) -> None:
    import logging

    with caplog.at_level(logging.WARNING, logger="arjiobot.risk.risk_validation"):
        leverage = calculate_max_safe_leverage(Decimal("100"), Decimal("100"), Decimal("2"))

    assert leverage == 1
    assert any("calculate_max_safe_leverage failed" in record.message for record in caplog.records)


def test_calculate_max_safe_leverage_never_raises_on_garbage_input() -> None:
    assert calculate_max_safe_leverage("not-a-number", "also-not-a-number", "10") == 1
    assert calculate_max_safe_leverage(Decimal("-100"), Decimal("90"), Decimal("10")) == 1
    assert calculate_max_safe_leverage(Decimal("100"), Decimal("90"), Decimal("-10")) == 1
    assert calculate_max_safe_leverage(Decimal("100"), Decimal("90"), Decimal("10"), target_mmr=Decimal("0")) == 1


def test_calculate_max_safe_leverage_is_invariant_to_risk_per_trade() -> None:
    """L_max must depend only on entry/stop/rates/target_mmr, never on
    risk_per_trade - Q, N, and MM_stop all scale linearly with risk_per_trade,
    so the L_max=N/M_required ratio cancels it out exactly. If a future edit
    accidentally hardcoded or mis-scaled risk_per_trade, this is what would
    catch it."""
    leverages = {
        calculate_max_safe_leverage(
            _WORKED_ENTRY, _WORKED_STOP, risk,
            maintenance_margin_rate=_WORKED_MMR_RATE, close_fee_rate=_WORKED_FEE_RATE, target_mmr=Decimal("0.70"),
        )
        for risk in (Decimal("1.0"), Decimal("5.0"), Decimal("10.0"))
    }
    assert leverages == {50}


def test_calculate_max_safe_leverage_default_rate_parameters() -> None:
    """Defaults (maintenance_margin_rate=0.004, close_fee_rate=0.0003,
    target_mmr=0.70) apply when the caller overrides none of them - and
    accept plain floats/ints, not just Decimal, since the documented
    signature uses float defaults."""
    assert calculate_max_safe_leverage(100, 101, 100) == 61
    assert calculate_max_safe_leverage(100.0, 101.0, 100.0) >= 1
