"""Operator-triggered maintenance routes.

Protected by the same dashboard-auth middleware as every other /api/* route
(main.py's public_paths allowlist does not include /api/admin/*).
"""

from __future__ import annotations

from fastapi import APIRouter

from arjiobot.api.dependencies import get_state
from arjiobot.api.schemas.common import ok
from arjiobot.setup_tracker.setup_history_store import clear_setup_history

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.post("/clear-setup-history")
def clear_setup_history_endpoint():
    """Manually clear completed_setups/invalidated_setups in memory AND
    delete the persisted setup_history_store.json from disk, simultaneously -
    for an operator to trigger on demand (e.g. from the Railway console)
    without waiting for a restart. IN PROGRESS (state.setups) is never
    touched, and this has no effect on adapter_mode/live_trading_enabled/
    trading_mode/live_armed or any risk/margin/lock check - it only clears
    Setup Radar's COMPLETED/INVALIDATED display history.
    """
    completed_count, invalidated_count = clear_setup_history(get_state())
    return ok(
        {
            "cleared_completed_count": completed_count,
            "cleared_invalidated_count": invalidated_count,
            "message": "completed_setups and invalidated_setups cleared in memory and on disk.",
        }
    )
