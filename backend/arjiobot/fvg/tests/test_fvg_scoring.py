"""Scoring tests for the FVG Engine."""

from __future__ import annotations

from decimal import Decimal

from arjiobot.fvg.fvg_scorer import DefaultFVGStrengthScorer
from arjiobot.fvg.tests.test_fvg_models import make_fvg


def test_default_scorer_returns_bounded_score() -> None:
    """Default scorer returns a non-zero bounded score."""
    score = DefaultFVGStrengthScorer().score(
        fvg=make_fvg(gap_size=Decimal("10"), upper_boundary=Decimal("100"), lower_boundary=Decimal("90")),
        related_expansion=None,
        related_swing=None,
    )

    assert 0.0 < score <= 100.0


def test_tap_status_changes_score() -> None:
    """Untapped FVGs receive more initial freshness score."""
    scorer = DefaultFVGStrengthScorer()
    untouched = scorer.score(fvg=make_fvg(), related_expansion=None, related_swing=None)
    tapped = scorer.score(
        fvg=make_fvg(touched=True, touch_count=1, first_touched_at=make_fvg().confirmed_at),
        related_expansion=None,
        related_swing=None,
    )

    assert untouched > tapped

