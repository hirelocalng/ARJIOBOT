"""Integration/report tests for Strategy Engine."""

from __future__ import annotations

from arjiobot.strategy.demo_strategy import build_validation_report, make_entry_ready_setup
from arjiobot.strategy.signal_service import SignalService
from arjiobot.strategy.strategy_models import SignalRejectionReason


def test_integration_with_setup_tracker_object() -> None:
    setup = make_entry_ready_setup()
    service = SignalService()
    signal = service.generate_signal_from_setup(setup)

    assert signal.setup_id == setup.setup_id
    assert signal.htf_fvg_id == setup.htf_fvg_id
    assert service.get_generated_signals("BTCUSDT") == (signal,)


def test_rejected_query_by_reason() -> None:
    service = SignalService()
    setup = make_entry_ready_setup()
    service.generate_signal_from_setup(setup)
    duplicate = service.generate_signal_from_setup(setup)

    assert service.get_rejected_signals("BTCUSDT", SignalRejectionReason.DUPLICATE_SIGNAL) == (duplicate,)


def test_validation_report_generation() -> None:
    report = build_validation_report()
    html_path = report["html_path"]
    png_path = report["png_path"]

    assert html_path.exists()
    assert png_path.exists()
    assert "Strategy Engine Validation Report" in html_path.read_text(encoding="utf-8")
    assert png_path.read_bytes().startswith(b"\x89PNG")

