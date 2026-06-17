"""Radar API schemas."""

from __future__ import annotations

from pydantic import BaseModel


class RadarItem(BaseModel):
    setup_id: str
    symbol: str
    direction: str
    current_state: str
    progress_percent: float
    missing_requirements: list[str]
    invalidation_reason: str | None
    time_remaining: str | None
    stop_reference: str | None
    target_reference: str | None
