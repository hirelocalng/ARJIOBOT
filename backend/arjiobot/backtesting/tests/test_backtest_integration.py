"""Backtester integration/report tests."""

from __future__ import annotations

from arjiobot.backtesting.demo_backtester import build_validation_report


def test_validation_report_generation() -> None:
    report = build_validation_report()
    html_path = report["html_path"]
    png_path = report["png_path"]

    assert html_path.exists()
    assert png_path.exists()
    assert "Backtest Validation Report" in html_path.read_text(encoding="utf-8")
    assert png_path.read_bytes().startswith(b"\x89PNG")

