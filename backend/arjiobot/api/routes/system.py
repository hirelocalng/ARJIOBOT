"""System-wide control state route."""

from __future__ import annotations

from fastapi import APIRouter

from arjiobot.api.routes.control_plane import control_plane_snapshot

router = APIRouter(prefix="/api/system", tags=["system"])


@router.get("/control-state")
def control_state():
    return control_plane_snapshot()
