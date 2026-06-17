"""Progress scoring for the Setup Tracker."""

from __future__ import annotations

from typing import Protocol

from arjiobot.setup_tracker.setup_models import Setup, clamp_progress


DEFAULT_PROGRESS_WEIGHTS: dict[str, float] = {
    "htf_fvg_id": 15.0,
    "swing_16m_id": 20.0,
    "expansion_16m_id": 15.0,
    "fvg_16m_id": 15.0,
    "fvg_12m_id": 10.0,
    "fvg_8m_id": 10.0,
    "retrace_tap_candle_id": 5.0,
    "one_minute_swing_id": 5.0,
    "one_minute_fvg_ids": 3.0,
    "entry_fvg_id": 2.0,
}


class SetupProgressScorer(Protocol):
    """Progress scoring protocol."""

    def score(self, setup: Setup) -> float:
        """Return progress percent."""


class DefaultSetupProgressScorer:
    """Default additive progress scorer."""

    def __init__(self, weights: dict[str, float] | None = None) -> None:
        self.weights = weights or DEFAULT_PROGRESS_WEIGHTS

    def score(self, setup: Setup) -> float:
        """Score progress from populated milestone fields."""
        total = 0.0
        for field_name, weight in self.weights.items():
            value = getattr(setup, field_name)
            if value:
                total += weight
        return clamp_progress(total)
