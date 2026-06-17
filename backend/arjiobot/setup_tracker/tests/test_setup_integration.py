"""Integration/report/replay tests for Setup Tracker."""

from __future__ import annotations

from datetime import datetime, timezone

from arjiobot.setup_tracker.demo_setup_tracker import build_validation_report
from arjiobot.setup_tracker.setup_models import SetupState
from arjiobot.setup_tracker.setup_tracker import SetupTracker


def test_historical_replay_is_deterministic() -> None:
    timestamp = datetime(2026, 1, 1, tzinfo=timezone.utc)
    events = [
        {"type": "create", "symbol": "BTCUSDT", "timestamp": timestamp, "htf_fvg_id": "htf"},
    ]

    first = SetupTracker().process_events(events)[0]
    second = SetupTracker().process_events(events)[0]

    assert first.setup_id == second.setup_id
    assert first.current_state is SetupState.WATCHING_HTF_FVG


def test_validation_report_generation() -> None:
    report = build_validation_report()
    html_path = report["html_path"]
    png_path = report["png_path"]

    assert html_path.exists()
    assert png_path.exists()
    assert "Setup Tracker Validation Report" in html_path.read_text(encoding="utf-8")
    assert png_path.read_bytes().startswith(b"\x89PNG")

