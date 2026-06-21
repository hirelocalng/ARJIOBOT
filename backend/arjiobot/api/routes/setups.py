"""Setup routes."""

from __future__ import annotations

from fastapi import APIRouter

from arjiobot.api.dependencies import get_state
from arjiobot.api.errors import api_error
from arjiobot.api.routes.radar import radar_record
from arjiobot.api.schemas.common import ok
from arjiobot.setup_tracker.setup_models import SetupState, SetupStatus

router = APIRouter(prefix="/api/setups", tags=["setups"])

# COMPLETED is the attempt-tracker's own "reached 100% via this swing" marker
# (live_setup_detection.py's _apply_one_attempt_trace); ENTRY_READY is the
# separate, real tradable setup live automation actually acts on
# (_setup_from_trade). Both represent "finished successfully", so both belong
# in the Setup Radar's COMPLETED tab.
_COMPLETED_STATUSES = (SetupStatus.ENTRY_READY, SetupStatus.COMPLETED)
_INVALIDATED_STATUSES = (SetupStatus.INVALIDATED, SetupStatus.EXPIRED)
MAX_TRACKED_INVALIDATED_RETURNED = 100


@router.get("")
def list_setups():
    return ok(tuple(radar_record(setup) for setup in get_state().setups.values()))


@router.get("/entry-ready")
def entry_ready():
    return ok(tuple(radar_record(setup) for setup in get_state().setups.values() if setup.current_state is SetupState.ENTRY_READY))


@router.get("/in-progress")
def in_progress():
    """Active attempts, every one of them - not deduplicated per symbol, since
    a pair can legitimately have more than one concurrent attempt (e.g. a
    bearish and a bullish swing forming at once)."""
    setups = sorted(
        (setup for setup in get_state().setups.values() if setup.status is SetupStatus.ACTIVE),
        key=lambda setup: setup.progress_percent,
        reverse=True,
    )
    return ok(tuple(radar_record(setup) for setup in setups))


@router.get("/completed")
def completed():
    setups = sorted(
        (setup for setup in get_state().setups.values() if setup.status in _COMPLETED_STATUSES),
        key=lambda setup: setup.updated_at,
        reverse=True,
    )
    return ok(tuple(radar_record(setup) for setup in setups))


@router.get("/invalidated")
def invalidated():
    setups = sorted(
        (setup for setup in get_state().setups.values() if setup.status in _INVALIDATED_STATUSES),
        key=lambda setup: setup.invalidated_at or setup.updated_at,
        reverse=True,
    )
    return ok(tuple(radar_record(setup) for setup in setups[:MAX_TRACKED_INVALIDATED_RETURNED]))


@router.get("/progress/{percent}")
def progress(percent: str):
    threshold = float(percent)
    return ok(tuple(radar_record(setup) for setup in get_state().setups.values() if setup.progress_percent >= threshold))


@router.get("/{setup_id}")
def get_setup(setup_id: str):
    setup = get_state().setups.get(setup_id)
    if setup is None:
        raise api_error(404, "SETUP_NOT_FOUND", "setup not found")
    return ok(radar_record(setup))


@router.get("/{setup_id}/history")
def history(setup_id: str):
    return ok(get_state().setup_history.get(setup_id, []))
