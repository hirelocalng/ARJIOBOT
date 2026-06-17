"""Audit script: per-candidate breakdown of rejected_no_expansion = 556.

Run:  python scripts/audit_rejected_no_expansion.py

Reproduces the exact same pipeline used in bt_1bdecf6c1dce7b21a9109c79 and
captures per-candidate details for every watched swing high that did NOT
produce a valid expansion (the 556 rejections).
"""

from __future__ import annotations

import json
import statistics
import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from arjiobot.backtesting.historical_replay import build_timeframe_profile, load_ohlcv_csv  # noqa: E402
from arjiobot.backtesting.research_profiles import PROFILE_F_VOLUME  # noqa: E402
from arjiobot.backtesting.timeframe_profiles import get_timeframe_profile  # noqa: E402
from arjiobot.swings.swings import SwingDetectionEngine  # noqa: E402
from arjiobot.swings.swing_models import SwingType  # noqa: E402

# ── same settings as bt_1bdecf6c1dce7b21a9109c79 ──────────────────────────
CSV_PATH = ROOT / "data" / "1INCHUSDT-1m-2025-05.csv"
SYMBOL = "1INCHUSDT"
TF_PROFILE_ID = "PROFILE_15_10_5"

# Engine thresholds (from ExpansionDetectionEngine defaults)
ENGINE_MIN_RATIO = 2.0
ENGINE_MAX_RATIO = 4.0

# Profile thresholds (Profile F Volume)
PROFILE_MIN_RATIO = float(PROFILE_F_VOLUME.expansion_ratio_min)
PROFILE_MAX_RATIO = float(PROFILE_F_VOLUME.expansion_ratio_max)

# Effective pass range is intersection: [max(engine, profile)] → [2.0, 3.0]
EFFECTIVE_MIN = max(ENGINE_MIN_RATIO, PROFILE_MIN_RATIO)
EFFECTIVE_MAX = min(ENGINE_MAX_RATIO, PROFILE_MAX_RATIO)


def _classify(swing) -> tuple[float | None, str]:
    """Return (ratio, rejection_reason) for a swing high.

    Returns (ratio, 'PASSED') if the swing would produce a valid expansion.
    """
    c1 = swing.left_candle
    c2 = swing.middle_candle
    c3 = swing.right_candle

    c1_size = float(c1.high - c1.low)
    c2_size = float(c2.high - c2.low)
    c3_size = float(c3.high - c3.low)
    avg_size = (c1_size + c2_size) / 2.0

    if avg_size <= 0.0 or c3_size <= 0.0:
        return None, "ZERO_SIZED_CANDLE"

    ratio = c3_size / avg_size

    # Engine gate 1: ratio bounds
    if ratio < ENGINE_MIN_RATIO:
        return ratio, "RATIO_BELOW_ENGINE_MIN_2.0"
    if ratio > ENGINE_MAX_RATIO:
        return ratio, "RATIO_ABOVE_ENGINE_MAX_4.0"

    # Engine gate 2: displacement (bearish = swing HIGH)
    # displacement = C2.low - C3.close  (must be > 0 for bearish)
    displacement = float(c2.low - c3.close)
    if displacement <= 0.0:
        return ratio, "NO_BEARISH_DISPLACEMENT"

    # Profile gate: ratio above profile max
    if ratio > PROFILE_MAX_RATIO:
        return ratio, "RATIO_ABOVE_PROFILE_MAX_3.0"

    # _expansion_is_swing_c3 identity check (should always pass here)
    # expansion.timestamp == swing.right_candle.timestamp is guaranteed
    # since we derive expansion from swing directly — no separate check needed

    return ratio, "PASSED"


def main() -> None:
    print(f"Loading {CSV_PATH.name} …")
    candles_1m = load_ohlcv_csv(CSV_PATH, default_symbol=SYMBOL)
    tf_profile = get_timeframe_profile(TF_PROFILE_ID)

    required_minutes = {
        tf_profile.swing_timeframe,
        tf_profile.main_fvg_timeframe,
        tf_profile.retrace_fvg_timeframe,
        tf_profile.internal_fvg_timeframe,
        tf_profile.retrace_window_timeframe,
        1,
    }
    profiles = {m: build_timeframe_profile(candles_1m, m) for m in required_minutes}
    swing_candles = profiles[tf_profile.swing_timeframe]

    print(f"Detecting swings on {tf_profile.swing_timeframe}M candles …")
    swing_results = SwingDetectionEngine().detect_all_swings(swing_candles)
    swing_highs = [s for s in swing_results.swing_highs if s.swing_type is SwingType.HIGH]
    print(f"  {len(swing_highs)} bearish swing highs found")

    watched = swing_highs

    rows: list[dict] = []
    for swing in watched:
        c1 = swing.left_candle
        c2 = swing.middle_candle
        c3 = swing.right_candle
        c1_size = float(c1.high - c1.low)
        c2_size = float(c2.high - c2.low)
        c3_size = float(c3.high - c3.low)
        avg_size = (c1_size + c2_size) / 2.0
        ratio, reason = _classify(swing)
        rows.append(
            {
                "timestamp": c3.timestamp.isoformat(),
                "pair": SYMBOL,
                "c3_size": round(c3_size, 8),
                "c1_size": round(c1_size, 8),
                "c2_size": round(c2_size, 8),
                "avg_size": round(avg_size, 8),
                "ratio": round(ratio, 6) if ratio is not None else None,
                "reason": reason,
            }
        )

    rejected = [r for r in rows if r["reason"] != "PASSED"]
    passed = [r for r in rows if r["reason"] == "PASSED"]

    print(f"\n{'-'*70}")
    print(f"AUDIT: rejected_no_expansion for bt_1bdecf6c1dce7b21a9109c79")
    print(f"{'-'*70}")
    print(f"  Watched swing highs : {len(watched)}")
    print(f"  Rejected            : {len(rejected)}")
    print(f"  Passed              : {len(passed)}")
    print()

    # ── Rejection reason breakdown ────────────────────────────────────────
    reason_counts: dict[str, int] = {}
    for r in rejected:
        reason_counts[r["reason"]] = reason_counts.get(r["reason"], 0) + 1
    print("Rejection reason breakdown:")
    for reason, count in sorted(reason_counts.items(), key=lambda x: -x[1]):
        pct = count / len(rejected) * 100 if rejected else 0
        print(f"  {reason:<38} {count:>4}  ({pct:.1f}%)")

    # ── Ratio stats for rejected candidates (those that have a ratio) ─────
    rejected_ratios = [r["ratio"] for r in rejected if r["ratio"] is not None]
    if rejected_ratios:
        print(f"\nRejected candidates with a computed ratio: {len(rejected_ratios)}")
        print(f"  Min ratio    : {min(rejected_ratios):.6f}")
        print(f"  Max ratio    : {max(rejected_ratios):.6f}")
        print(f"  Average ratio: {statistics.mean(rejected_ratios):.6f}")
        print(f"  Median ratio : {statistics.median(rejected_ratios):.6f}")
    else:
        print("\nNo rejected candidates have a computed ratio (all zero-sized).")

    # ── Histogram ─────────────────────────────────────────────────────────
    bins = [
        (0.0, 0.5), (0.5, 1.0), (1.0, 1.5), (1.5, 2.0),
        (2.0, 2.5), (2.5, 3.0), (3.0, 4.0), (4.0, float("inf")),
    ]
    bin_labels = [
        "0.0-0.5", "0.5-1.0", "1.0-1.5", "1.5-2.0",
        "2.0-2.5", "2.5-3.0", "3.0-4.0", "4.0+   ",
    ]
    all_ratios = [r["ratio"] for r in rows if r["ratio"] is not None]
    print(f"\nHistogram -- expansion ratio (ALL {len(all_ratios)} candidates with non-zero candles):")
    print(f"  {'Bin':<10} {'Count':>6}  Bar")
    max_count = max((sum(1 for v in all_ratios if lo <= v < hi) for lo, hi in bins), default=1)
    for (lo, hi), label in zip(bins, bin_labels):
        count = sum(1 for v in all_ratios if lo <= v < hi)
        bar = "#" * int(count / max_count * 40) if max_count else ""
        print(f"  {label:<10} {count:>6}  {bar}")

    # ── Per-candidate table (rejected only) ───────────────────────────────
    print(f"\n{'-'*70}")
    print("PER-CANDIDATE REJECTED TABLE")
    print(f"{'-'*70}")
    hdr = f"{'Timestamp':<28} {'Pair':<12} {'C3':>10} {'C1':>10} {'C2':>10} {'Avg':>10} {'Ratio':>8}  Reason"
    print(hdr)
    print("-" * len(hdr))
    for r in rejected:
        ratio_str = f"{r['ratio']:.6f}" if r["ratio"] is not None else "   N/A  "
        print(
            f"{r['timestamp']:<28} {r['pair']:<12} {r['c3_size']:>10.8f} "
            f"{r['c1_size']:>10.8f} {r['c2_size']:>10.8f} {r['avg_size']:>10.8f} "
            f"{ratio_str:>8}  {r['reason']}"
        )

    # ── Save full JSON ────────────────────────────────────────────────────
    out_path = ROOT / "reports" / "backtests" / "rejected_no_expansion_audit_bt_1bdecf6c1dce7b21a9109c79.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "run_id": "bt_1bdecf6c1dce7b21a9109c79",
        "symbol": SYMBOL,
        "tf_profile": TF_PROFILE_ID,
        "profile": PROFILE_F_VOLUME.profile_id,
        "engine_ratio_range": [ENGINE_MIN_RATIO, ENGINE_MAX_RATIO],
        "profile_ratio_range": [PROFILE_MIN_RATIO, PROFILE_MAX_RATIO],
        "effective_ratio_range": [EFFECTIVE_MIN, EFFECTIVE_MAX],
        "watched": len(watched),
        "rejected": len(rejected),
        "passed": len(passed),
        "reason_counts": reason_counts,
        "ratio_stats": {
            "min": min(rejected_ratios) if rejected_ratios else None,
            "max": max(rejected_ratios) if rejected_ratios else None,
            "mean": statistics.mean(rejected_ratios) if rejected_ratios else None,
            "median": statistics.median(rejected_ratios) if rejected_ratios else None,
        },
        "candidates": rows,
    }
    out_path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    print(f"\nFull JSON saved → {out_path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
