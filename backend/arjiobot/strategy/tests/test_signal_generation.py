"""Signal generation tests."""

from __future__ import annotations

from datetime import timedelta

from arjiobot.strategy.demo_strategy import make_entry_ready_setup
from arjiobot.strategy.strategy_engine import StrategyEngine
from arjiobot.strategy.strategy_models import SignalAction, SignalRejectionReason, SignalStatus


def test_valid_bearish_signal_generation() -> None:
    setup = make_entry_ready_setup()
    signal = StrategyEngine().generate_signal_from_setup(setup)

    assert signal.status is SignalStatus.GENERATED
    assert signal.action is SignalAction.MARKET_SELL_READY
    assert signal.validation_passed
    assert signal.stop_reference_price > signal.entry_reference_price > signal.final_target_price


def test_rejected_generation_stores_validation_errors() -> None:
    setup = make_entry_ready_setup()
    setup = type(setup)(**{field: getattr(setup, field) for field in setup.__dataclass_fields__} | {"entry_fvg_id": None})
    signal = StrategyEngine().generate_signal_from_setup(setup)

    assert signal.status is SignalStatus.REJECTED
    assert signal.rejection_reason is SignalRejectionReason.MISSING_REQUIRED_FIELD
    assert signal.validation_errors


def test_live_processing_evaluates_once() -> None:
    setup = make_entry_ready_setup()
    engine = StrategyEngine()

    first = engine.process_entry_ready_setups((setup,))
    second = engine.process_entry_ready_setups((setup,))

    assert len(first) == 1
    assert second == ()


def test_service_query_and_status_transition() -> None:
    setup = make_entry_ready_setup()
    engine = StrategyEngine()
    signal = engine.generate_signal_from_setup(setup)
    updated = engine.mark_signal_status(signal.signal_id, SignalStatus.SENT_TO_RISK_ENGINE, setup.updated_at + timedelta(minutes=1), reason="handoff")

    assert engine.get_signal_by_id(signal.signal_id) == updated
    assert updated.metadata["status_reason"] == "handoff"
    assert engine.get_signals_between(setup.created_at, setup.updated_at + timedelta(days=1), symbol="BTCUSDT")

