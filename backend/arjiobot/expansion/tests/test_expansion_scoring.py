"""Scoring, integration, and report tests for Expansion Engine."""

from __future__ import annotations

from decimal import Decimal

from arjiobot.market_data.candle_models import Timeframe
from arjiobot.expansion.demo_expansion import build_validation_report
from arjiobot.expansion.expansion_scorer import DefaultExpansionStrengthScorer


def test_default_scorer_returns_bounded_nonzero_score() -> None:
    """Default scoring uses ratio, displacement, and timeframe weighting."""
    scorer = DefaultExpansionStrengthScorer()

    score, displacement_strength = scorer.score(
        expansion_ratio=3.0,
        displacement_distance=Decimal("10"),
        expansion_size=Decimal("40"),
        timeframe=Timeframe(30),
    )

    assert 0.0 < score <= 100.0
    assert displacement_strength == 25.0


def test_timeframe_weighting_increases_score() -> None:
    """Higher timeframe expansions receive more default timeframe weight."""
    scorer = DefaultExpansionStrengthScorer()
    low_score, _ = scorer.score(
        expansion_ratio=3.0,
        displacement_distance=Decimal("10"),
        expansion_size=Decimal("40"),
        timeframe=Timeframe(1),
    )
    high_score, _ = scorer.score(
        expansion_ratio=3.0,
        displacement_distance=Decimal("10"),
        expansion_size=Decimal("40"),
        timeframe=Timeframe(60),
    )

    assert high_score > low_score


def test_validation_report_generates_html_and_png() -> None:
    """Final validation report artifacts are generated."""
    report = build_validation_report()
    html_path = report["html_path"]
    png_path = report["png_path"]

    assert html_path.exists()
    assert png_path.exists()
    assert "Expansion Engine Validation Report" in html_path.read_text(encoding="utf-8")
    assert png_path.read_bytes().startswith(b"\x89PNG")
