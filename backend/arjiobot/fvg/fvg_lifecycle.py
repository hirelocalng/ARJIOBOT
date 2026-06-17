"""Lifecycle helpers for FVG objects."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime

from arjiobot.market_data.candle_models import ensure_utc
from arjiobot.fvg.fvg_models import FVGLifecycleState, FairValueGap


def transition_fvg(
    fvg: FairValueGap,
    state: FVGLifecycleState,
    *,
    changed_at: datetime | None = None,
    reason: str | None = None,
) -> FairValueGap:
    """Return a new FVG with synchronized lifecycle fields."""
    updated_at = ensure_utc(changed_at or fvg.updated_at)
    values = {
        "status": state,
        "lifecycle_state": state,
        "updated_at": updated_at,
    }
    if state is FVGLifecycleState.INVALIDATED:
        values["invalidated_at"] = updated_at
        values["invalidation_reason"] = reason or "invalidated"
    return replace(fvg, **values)
