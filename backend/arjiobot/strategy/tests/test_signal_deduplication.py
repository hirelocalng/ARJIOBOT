"""Deduplication tests."""

from __future__ import annotations

from datetime import timedelta

from arjiobot.strategy.demo_strategy import make_entry_ready_setup
from arjiobot.strategy.signal_deduplication import has_generated_signal_for_setup
from arjiobot.strategy.strategy_engine import StrategyEngine
from arjiobot.strategy.strategy_models import SignalRejectionReason, SignalStatus


def test_duplicate_signal_rejected() -> None:
    setup = make_entry_ready_setup()
    engine = StrategyEngine()
    generated = engine.generate_signal_from_setup(setup)
    duplicate = engine.generate_signal_from_setup(setup, setup.updated_at + timedelta(seconds=1))

    assert generated.status is SignalStatus.GENERATED
    assert duplicate.status is SignalStatus.REJECTED
    assert duplicate.rejection_reason is SignalRejectionReason.DUPLICATE_SIGNAL
    assert engine.get_signal_by_setup_id(setup.setup_id) == generated


def test_deduplication_helper() -> None:
    setup = make_entry_ready_setup()
    signal = StrategyEngine().generate_signal_from_setup(setup)

    assert has_generated_signal_for_setup([signal], setup.setup_id)

