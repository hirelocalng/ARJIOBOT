"""Profile optimization runner tests."""

from __future__ import annotations

import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path

from arjiobot.backtesting.research_profiles import PROFILE_F_BALANCED, PROFILE_F_SELECTIVE, PROFILE_F_VOLUME, STRICT_PROFILE


def _load_optimizer():
    root = Path(__file__).resolve().parents[4]
    script_path = root / "scripts" / "optimize_profiles.py"
    spec = importlib.util.spec_from_file_location("arjiobot_profile_optimizer", script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load optimize_profiles.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_optimizer_builds_research_variants_without_mutating_production_profiles() -> None:
    optimizer = _load_optimizer()
    original_profile_f_volume = PROFILE_F_VOLUME.to_record()
    original_profile_f_balanced = PROFILE_F_BALANCED.to_record()
    original_profile_f_selective = PROFILE_F_SELECTIVE.to_record()
    original_strict = STRICT_PROFILE.to_record()

    variants = tuple(optimizer._build_variants())

    assert variants
    assert {variant.profile_id for variant in variants} == {
        "STRICT_PROFILE",
        "PROFILE_F_VOLUME",
        "PROFILE_F_BALANCED",
        "PROFILE_F_SELECTIVE",
    }
    assert PROFILE_F_VOLUME.to_record() == original_profile_f_volume
    assert PROFILE_F_BALANCED.to_record() == original_profile_f_balanced
    assert PROFILE_F_SELECTIVE.to_record() == original_profile_f_selective
    assert STRICT_PROFILE.to_record() == original_strict
    assert all(variant.retrace_window_8m_candles == 3 for variant in variants)


def test_optimizer_writes_csv_and_html_reports(tmp_path) -> None:
    optimizer = _load_optimizer()
    csv_path = tmp_path / "BTCUSDT-1m-mini.csv"
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rows = ["timestamp,open,high,low,close,volume"]
    for index in range(160):
        timestamp = start + timedelta(minutes=index)
        rows.append(f"{timestamp.isoformat()},100,101,99,100,10")
    csv_path.write_text("\n".join(rows), encoding="utf-8")

    report = optimizer.optimize(csv_path, "BTCUSDT", starting_balance="10000", risk_amount_per_trade="100", max_leverage="100")

    assert report["research_only"] is True
    assert report["production_settings_overwritten"] is False
    assert report["training_candles"] == 112
    assert report["validation_candles"] == 48
    assert report["meets_25_trades_and_70_win_rate"] in {"YES", "NO"}
    assert report["validation_still_profitable"] in {"YES", "NO"}
    assert report["overfitting_risk"] in {"LOW", "MEDIUM", "HIGH"}
    assert Path(report["csv_path"]).exists()
    assert Path(report["html_path"]).exists()

