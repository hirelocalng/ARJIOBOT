"""Pluggable scoring for Expansion Candle Engine objects."""

from __future__ import annotations

from decimal import Decimal
from typing import Protocol

from arjiobot.market_data.candle_models import Timeframe
from arjiobot.expansion.expansion_models import clamp_score


class ExpansionStrengthScorer(Protocol):
    """Interface for pluggable expansion strength scorers."""

    def score(
        self,
        *,
        expansion_ratio: float,
        displacement_distance: Decimal,
        expansion_size: Decimal,
        timeframe: Timeframe,
    ) -> tuple[float, float]:
        """Return ``(strength_score, displacement_strength)``."""


class DefaultExpansionStrengthScorer:
    """Default scorer based on ratio quality, displacement, and timeframe."""

    def score(
        self,
        *,
        expansion_ratio: float,
        displacement_distance: Decimal,
        expansion_size: Decimal,
        timeframe: Timeframe,
    ) -> tuple[float, float]:
        """Score a valid expansion from 0.0 to 100.0."""
        ratio_center = 3.0
        ratio_quality = max(0.0, 1.0 - abs(expansion_ratio - ratio_center) / 1.0)
        ratio_score = ratio_quality * 40.0

        displacement_strength = (
            float(displacement_distance / expansion_size) * 100.0
            if expansion_size
            else 0.0
        )
        displacement_score = min(40.0, displacement_strength * 0.8)
        timeframe_score = min(20.0, float(Timeframe.parse(timeframe).minutes) / 60.0 * 20.0)

        score = ratio_score + displacement_score + timeframe_score
        return clamp_score(score), clamp_score(displacement_strength)
