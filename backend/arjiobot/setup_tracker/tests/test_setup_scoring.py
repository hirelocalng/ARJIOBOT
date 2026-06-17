"""Progress scoring tests."""

from __future__ import annotations

from arjiobot.setup_tracker.setup_scoring import DefaultSetupProgressScorer
from arjiobot.setup_tracker.tests.test_setup_models import make_setup


def test_progress_scoring_adds_milestones() -> None:
    setup = make_setup(
        progress_percent=0.0,
        swing_16m_id="swg",
        expansion_16m_id="exp",
        fvg_16m_id="fvg16",
        fvg_12m_id="fvg12",
        fvg_8m_id="fvg8",
        retrace_tap_candle_id="cndl",
        one_minute_swing_id="swg1",
        one_minute_fvg_ids=("fvg1",),
        entry_fvg_id="fvg1",
    )

    assert DefaultSetupProgressScorer().score(setup) == 100.0


def test_progress_scoring_partial_setup() -> None:
    setup = make_setup(progress_percent=0.0, swing_16m_id="swg")

    assert DefaultSetupProgressScorer().score(setup) == 35.0

