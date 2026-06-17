"""Pluggable scoring for FVG objects."""

from __future__ import annotations

from decimal import Decimal
from typing import Protocol

from arjiobot.expansion.expansion_models import ExpansionCandle
from arjiobot.fvg.fvg_models import FairValueGap, clamp_score
from arjiobot.swings.swing_models import Swing


class FVGStrengthScorer(Protocol):
    """Interface for FVG strength scorers."""

    def score(
        self,
        *,
        fvg: FairValueGap,
        related_expansion: ExpansionCandle | None,
        related_swing: Swing | None,
    ) -> float:
        """Return a bounded strength score."""


class DefaultFVGStrengthScorer:
    """Default FVG strength scorer."""

    def score(
        self,
        *,
        fvg: FairValueGap,
        related_expansion: ExpansionCandle | None,
        related_swing: Swing | None,
    ) -> float:
        """Score using timeframe, gap size, relationships, role, and tap state."""
        timeframe_score = min(20.0, fvg.timeframe.minutes / 60.0 * 20.0)
        reference_price = max(abs(fvg.upper_boundary), Decimal("1"))
        gap_percent = float(fvg.gap_size / reference_price * Decimal("100"))
        gap_score = min(25.0, gap_percent * 5.0)
        expansion_score = (related_expansion.strength_score * 0.25) if related_expansion else 0.0
        swing_score = (related_swing.strength_score * 0.15) if related_swing else 0.0
        role_score = 0.0
        if fvg.is_htf_fvg:
            role_score += 5.0
        if fvg.is_entry_fvg:
            role_score += 5.0
        if fvg.is_target_fvg:
            role_score += 3.0
        tap_score = 5.0 if not fvg.touched else 2.0
        return clamp_score(
            timeframe_score + gap_score + expansion_score + swing_score + role_score + tap_score
        )
