"""Integration and report tests for the FVG Engine."""

from __future__ import annotations

from dataclasses import replace

from arjiobot.expansion.expansion import ExpansionDetectionEngine
from arjiobot.fvg.demo_fvg import build_validation_dataset, build_validation_report
from arjiobot.fvg.fvg import FVGDetectionEngine
from arjiobot.fvg.fvg_models import FVGDirection
from arjiobot.swings.swings import SwingDetectionEngine


def test_strategy_fvg_qualification_links_swing_and_expansion() -> None:
    """Strategy FVGs require Swing and Expansion relationships."""
    candles = build_validation_dataset()[:4]
    swing_result = SwingDetectionEngine().detect_all_swings(candles)
    expansion_result = ExpansionDetectionEngine(fvg_candidate_threshold=0.0).detect_expansions(swing_result.all_swings)
    result = FVGDetectionEngine().detect_fvgs(
        candles,
        swings=swing_result.all_swings,
        expansions=expansion_result.expansions,
    )

    assert result.count == 1
    fvg = result.fvgs[0]
    assert fvg.is_strategy_fvg
    assert fvg.related_swing_id == swing_result.swing_highs[0].swing_id
    assert fvg.related_expansion_id == expansion_result.expansions[0].expansion_id
    assert expansion_result.expansions[0].timestamp == fvg.c2_timestamp


def test_query_apis_return_expected_sets() -> None:
    """Query service returns structured FVGs for downstream modules."""
    engine = FVGDetectionEngine()
    fvg = engine.detect_fvgs(build_validation_dataset()).fvgs[0]

    assert engine.get_fvg_by_id(fvg.fvg_id) == fvg
    assert engine.get_latest_fvg("BTCUSDT", "1M", FVGDirection.BEARISH) == fvg
    assert fvg in engine.get_active_fvgs("BTCUSDT", "1M")
    assert fvg in engine.get_untapped_fvgs("BTCUSDT", "1M")
    assert engine.get_fvgs_between("BTCUSDT", "1M", fvg.c1_timestamp, fvg.confirmed_at)


def test_entry_and_htf_queries() -> None:
    """Role queries expose entry and HTF FVGs."""
    engine = FVGDetectionEngine()
    one_minute = engine.detect_fvgs(build_validation_dataset()).fvgs[0]
    marked = engine.store.replace(replace(one_minute, is_entry_fvg=True))

    assert engine.get_entry_fvgs("BTCUSDT") == (marked,)


def test_report_generation_output() -> None:
    """HTML and PNG report artifacts are generated."""
    report = build_validation_report()
    html_path = report["html_path"]
    png_path = report["png_path"]

    assert html_path.exists()
    assert png_path.exists()
    assert "FVG Engine Validation Report" in html_path.read_text(encoding="utf-8")
    assert png_path.read_bytes().startswith(b"\x89PNG")
