"""Setup routes."""

from __future__ import annotations

from fastapi import APIRouter

from arjiobot.api.dependencies import get_state
from arjiobot.api.errors import api_error
from arjiobot.api.routes.radar import radar_record
from arjiobot.api.schemas.common import ok
from arjiobot.setup_tracker.setup_models import SetupState

router = APIRouter(prefix="/api/setups", tags=["setups"])


@router.get("")
def list_setups():
    return ok(tuple(radar_record(setup) for setup in get_state().setups.values()))


@router.get("/entry-ready")
def entry_ready():
    return ok(tuple(radar_record(setup) for setup in get_state().setups.values() if setup.current_state is SetupState.ENTRY_READY))


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
