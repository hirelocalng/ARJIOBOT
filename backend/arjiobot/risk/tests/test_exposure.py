"""Exposure tests."""

from __future__ import annotations

from decimal import Decimal

from arjiobot.risk.exposure import exposure_after_trade, has_same_symbol_exposure


def test_exposure_helpers() -> None:
    exposure = {"BTCUSDT": Decimal("1000")}
    assert has_same_symbol_exposure(symbol="btcusdt", open_symbol_exposure=exposure)
    assert exposure_after_trade(symbol="BTCUSDT", open_symbol_exposure=exposure, notional_value=500) == Decimal("1500")

