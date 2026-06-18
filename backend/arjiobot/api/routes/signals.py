"""Signal routes."""

from __future__ import annotations

from fastapi import APIRouter

from arjiobot.api.dependencies import get_state
from arjiobot.api.errors import api_error
from arjiobot.api.schemas.common import ok
from arjiobot.strategy.strategy_models import SignalStatus, signal_to_record

router = APIRouter(prefix="/api/signals", tags=["signals"])


@router.get("")
def list_signals():
    return ok(tuple(signal_to_record(signal) for signal in get_state().signals.values()))


@router.get("/rejected")
def rejected_signals():
    return ok(tuple(signal_to_record(signal) for signal in get_state().signals.values() if signal.status is SignalStatus.REJECTED))


@router.get("/{signal_id}")
def get_signal(signal_id: str):
    signal = get_state().signals.get(signal_id)
    if signal is None:
        raise api_error(404, "SIGNAL_NOT_FOUND", "signal not found")
    return ok(signal_to_record(signal))


@router.post("/generate/{setup_id}")
def generate_signal(setup_id: str, payload: dict[str, object] | None = None):
    state = get_state()
    setup = state.setups.get(setup_id)
    if setup is None:
        raise api_error(404, "SETUP_NOT_FOUND", "setup not found")
    signal = state.strategy_engine.generate_signal_from_setup(setup)
    state.signals[signal.signal_id] = signal
    return ok(signal_to_record(signal))
