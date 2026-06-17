"""Loss limit tests."""

from __future__ import annotations

from decimal import Decimal

from arjiobot.risk.loss_limits import daily_loss_capacity_remaining, weekly_loss_capacity_remaining


def test_loss_capacity_calculations() -> None:
    assert daily_loss_capacity_remaining(max_daily_loss=500, current_daily_pnl=-100, reserved_risk_amount=50) == Decimal("350")
    assert daily_loss_capacity_remaining(max_daily_loss=500, current_daily_pnl=100, reserved_risk_amount=50) == Decimal("450")
    assert weekly_loss_capacity_remaining(max_weekly_loss=1000, current_weekly_pnl=-200, reserved_risk_amount=50) == Decimal("750")

