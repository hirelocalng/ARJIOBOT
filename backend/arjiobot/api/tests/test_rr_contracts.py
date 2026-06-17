"""RR profile request/response contract checks."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]


def test_frontend_does_not_send_selectable_rr_payload() -> None:
    source = (ROOT / "frontend" / "src" / "pages" / "Backtesting.tsx").read_text(encoding="utf-8")

    assert "fixed_risk_amount: risk" in source
    assert "rr_profile: " + "rr" + "Profile" not in source
    assert "custom" + "_rr" + "_value" not in source
    assert "RR_" + "PROFILES" not in source
