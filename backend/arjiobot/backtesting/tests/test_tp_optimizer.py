"""Take-profit optimization research tests."""

from __future__ import annotations

import importlib.util
import sys
from decimal import Decimal
from pathlib import Path


def _load_optimizer():
    root = Path(__file__).resolve().parents[4]
    script_path = root / "scripts" / "optimize_tp_models.py"
    spec = importlib.util.spec_from_file_location("arjiobot_tp_optimizer", script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load optimize_tp_models.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_tp_optimizer_matrix_contains_only_three_profile_f_variants_and_four_tp_models() -> None:
    optimizer = _load_optimizer()

    assert {profile.profile_id for profile in optimizer.PROFILE_VARIANTS} == {
        "PROFILE_F_VOLUME",
        "PROFILE_F_BALANCED",
        "PROFILE_F_SELECTIVE",
    }
    assert set(optimizer.TP_MODELS) == {
        "16M_FVG_BOUNDARY",
        "RR_1_0",
        "8M_PRE_RETRACE_EXTREME",
        "RR_1_5_CURRENT",
    }


def test_rr_tp_models_resolve_without_changing_entry() -> None:
    optimizer = _load_optimizer()
    trade = {
        "direction": "BEARISH",
        "entry_price": "100",
        "stop_loss": "110",
        "entry_timestamp": "2026-01-01T00:00:00+00:00",
        "setup_snapshot": {},
    }

    assert optimizer._resolve_tp(trade, "RR_1_0", "BEARISH", Decimal("100"), Decimal("110")) == Decimal("90")
    assert optimizer._resolve_tp(trade, "RR_1_5_CURRENT", "BEARISH", Decimal("100"), Decimal("110")) == Decimal("85.0")


def test_boundary_and_8m_extreme_tp_models_use_setup_snapshot_sources() -> None:
    optimizer = _load_optimizer()
    trade = {
        "direction": "BEARISH",
        "entry_price": "100",
        "stop_loss": "110",
        "entry_timestamp": "2026-01-01T00:16:00+00:00",
        "setup_snapshot": {
            "fvg_16m": {"lower_boundary": "96", "upper_boundary": "104"},
            "eight_minute_candles_after_16m_fvg": (
                {"timestamp": "2026-01-01T00:00:00+00:00", "low": "94", "high": "103"},
                {"timestamp": "2026-01-01T00:08:00+00:00", "low": "95", "high": "102"},
                {"timestamp": "2026-01-01T00:16:00+00:00", "low": "90", "high": "120"},
            ),
        },
    }

    assert optimizer._resolve_tp(trade, "16M_FVG_BOUNDARY", "BEARISH", Decimal("100"), Decimal("110")) == Decimal("96")
    assert optimizer._resolve_tp(trade, "8M_PRE_RETRACE_EXTREME", "BEARISH", Decimal("100"), Decimal("110")) == Decimal("94")


def test_ranking_prefers_profitable_validation_and_25_trade_requirement() -> None:
    optimizer = _load_optimizer()
    strong = {
        "valid_trades": 25,
        "validation_net_pnl": "100",
        "validation_win_rate": 60.0,
        "validation_profit_factor": "1.5",
        "win_rate": 60.0,
        "profit_factor": "1.5",
        "net_pnl": "200",
        "max_drawdown": "50",
        "expectancy": "8",
        "longest_losing_streak": 2,
    }
    weak = {**strong, "valid_trades": 24, "validation_net_pnl": "-1"}

    assert optimizer._rank_key(strong) > optimizer._rank_key(weak)
