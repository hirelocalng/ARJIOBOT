"""Live automation routes."""

from __future__ import annotations

from fastapi import APIRouter

from arjiobot.api.dependencies import get_state
from arjiobot.api.schemas.common import ok
from arjiobot.live_automation import live_automation_status, run_live_automation_once

router = APIRouter(prefix="/api/live-automation", tags=["live-automation"])


@router.get("/status")
def status():
    return ok(live_automation_status(get_state()))


@router.post("/run-once")
def run_once(payload: dict[str, object] | None = None):
    return ok(run_live_automation_once(get_state(), source="API_RUN_ONCE"))
