from __future__ import annotations

import csv
import html
import importlib.util
import json
import sys
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from arjiobot.backtesting.historical_replay import build_timeframe_profile, load_ohlcv_csv  # noqa: E402
from arjiobot.backtesting.research_profiles import PROFILE_F_BALANCED, PROFILE_F_SELECTIVE, PROFILE_F_VOLUME, STRICT_PROFILE, StrategyProfile  # noqa: E402
from arjiobot.backtesting.timeframe_profiles import DEFAULT_16_12_8, get_timeframe_profile  # noqa: E402
from arjiobot.expansion.expansion import ExpansionDetectionEngine  # noqa: E402
from arjiobot.fvg.fvg import FVGDetectionEngine  # noqa: E402
from arjiobot.risk.rr_profiles import PRODUCTION_RR_PROFILE, resolve_rr_value  # noqa: E402
from arjiobot.swings.swing_models import SwingType  # noqa: E402
from arjiobot.swings.swings import SwingDetectionEngine  # noqa: E402


MIN_TRADES = 25
MIN_WIN_RATE = 70.0
TARGET_PROFIT_FACTOR = Decimal("1.5")


def _load_csv_runner():
    script_path = ROOT / "scripts" / "backtest_csv.py"
    spec = importlib.util.spec_from_file_location("arjiobot_backtest_csv_runner_for_optimizer", script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load scripts/backtest_csv.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


RUNNER = _load_csv_runner()


def optimize(
    csv_path: Path,
    symbol: str,
    *,
    starting_balance: str,
    risk_amount_per_trade: str,
    max_leverage: str,
    timeframe_profile: str = "DEFAULT_16_12_8",
) -> dict[str, object]:
    candles = load_ohlcv_csv(csv_path, default_symbol=symbol)
    if len(candles) < 100:
        raise ValueError("optimization requires at least 100 1M candles")
    split_index = max(1, int(len(candles) * Decimal("0.70")))
    train_candles = candles[:split_index]
    validation_candles = candles[split_index:]
    tf_profile = get_timeframe_profile(timeframe_profile)
    train_context = _build_context(train_candles, tf_profile)
    validation_context = _build_context(validation_candles, tf_profile)
    variants = tuple(_build_variants())
    rows: list[dict[str, object]] = []
    for variant in variants:
        train = _evaluate_variant(
            variant=variant,
            context=train_context,
            symbol=symbol,
            tf_profile=tf_profile,
            starting_balance=starting_balance,
            risk_amount_per_trade=risk_amount_per_trade,
            max_leverage=max_leverage,
        )
        validation = _evaluate_variant(
            variant=variant,
            context=validation_context,
            symbol=symbol,
            tf_profile=tf_profile,
            starting_balance=starting_balance,
            risk_amount_per_trade=risk_amount_per_trade,
            max_leverage=max_leverage,
        )
        combined = _combine_metrics(train, validation)
        row = {
            "profile_name": variant.profile_id,
            "variant_name": _variant_name(variant),
            "variable_values_used": _variant_values(variant),
            "training": train,
            "validation": validation,
            **combined,
            "strong_on_training": _strong_train(train),
            "strong_on_validation": _strong_validation(validation),
            "overfitting_risk": _overfitting_risk(train, validation),
        }
        rows.append(row)
    ranked = sorted(rows, key=_rank_key, reverse=True)
    best_strict = next((row for row in ranked if row["profile_name"] == "STRICT_PROFILE"), None)
    best_profile_f = next((row for row in ranked if str(row["profile_name"]).startswith("PROFILE_F_")), None)
    best_overall = ranked[0] if ranked else None
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "symbol": symbol.upper(),
        "csv_path": str(csv_path),
        "candles_loaded": len(candles),
        "training_candles": len(train_candles),
        "validation_candles": len(validation_candles),
        "timeframe_profile": tf_profile.profile_id,
        "research_only": True,
        "production_settings_overwritten": False,
        "ranking_rules": (
            "minimum 25 trades",
            "win rate >= 70%",
            "profit factor",
            "net PnL",
            "lower drawdown",
        ),
        "rows": ranked,
        "best_strict_profile_variant": best_strict,
        "best_profile_f_variant": best_profile_f,
        "meets_25_trades_and_70_win_rate": "YES" if best_overall and best_overall["meets_25_trades_and_70_win_rate"] else "NO",
        "validation_still_profitable": "YES" if best_overall and best_overall["validation_still_profitable"] else "NO",
        "overfitting_risk": best_overall["overfitting_risk"] if best_overall else "HIGH",
    }
    _write_reports(report)
    return report


def _build_variants() -> Iterable[StrategyProfile]:
    profile_ranges = {
        "STRICT_PROFILE": STRICT_PROFILE,
        "PROFILE_F_VOLUME": PROFILE_F_VOLUME,
        "PROFILE_F_BALANCED": PROFILE_F_BALANCED,
        "PROFILE_F_SELECTIVE": PROFILE_F_SELECTIVE,
    }
    for base in profile_ranges.values():
        for expansion_min in (1.0, 1.5, 2.0):
            for expansion_max in (3.0, 3.5, 4.0):
                if expansion_min >= expansion_max:
                    continue
                yield replace(
                    base,
                    expansion_ratio_min=expansion_min,
                    expansion_ratio_max=expansion_max,
                    retrace_window_8m_candles=3,
                    fvg_delay_16m_candles=0,
                )


def _build_context(candles, tf_profile) -> dict[str, object]:
    if not candles:
        return {"candles": (), "profiles": {}, "bearish_swing_highs": (), "expansions": (), "fvg_results": {}}
    required_minutes = RUNNER._required_timeframes(tf_profile)
    profiles = {minutes: build_timeframe_profile(candles, minutes) for minutes in required_minutes}
    swing_results = SwingDetectionEngine().detect_all_swings(profiles[tf_profile.swing_timeframe])
    bearish_swing_highs = tuple(swing for swing in swing_results.swing_highs if swing.swing_type is SwingType.HIGH)
    expansions = RUNNER._research_expansions(swing_results.all_swings)
    fvg_results = {
        minutes: FVGDetectionEngine().detect_fvgs(profiles[minutes])
        for minutes in required_minutes
        if minutes != 1
    }
    return {
        "candles": tuple(candles),
        "profiles": profiles,
        "bearish_swing_highs": bearish_swing_highs,
        "expansions": expansions,
        "fvg_results": fvg_results,
    }


def _evaluate_variant(
    *,
    variant: StrategyProfile,
    context: dict[str, object],
    symbol: str,
    tf_profile,
    starting_balance: str,
    risk_amount_per_trade: str,
    max_leverage: str,
) -> dict[str, object]:
    candles = context["candles"]
    if not candles:
        return _empty_metrics()
    profiles = context["profiles"]
    fvg_results = context["fvg_results"]
    funnel = RUNNER._build_strategy_funnel(
        profile=variant,
        timeframe_profile=tf_profile,
        candidate_16m_swing_highs=context["bearish_swing_highs"],
        expansions_16m=context["expansions"],
        fvg_16m=fvg_results[tf_profile.main_fvg_timeframe].fvgs,
        fvg_12m=fvg_results[tf_profile.retrace_fvg_timeframe].fvgs,
        fvg_8m=fvg_results[tf_profile.internal_fvg_timeframe].fvgs,
        candles_8m=profiles[tf_profile.retrace_window_timeframe],
        candles_1m=profiles[1],
        starting_balance=starting_balance,
        risk_amount_per_trade=risk_amount_per_trade,
        max_leverage=max_leverage,
        selected_rr_profile=PRODUCTION_RR_PROFILE,
    )
    performance = funnel["performance_summary"]
    return {
        "candles": len(candles),
        "total_trades": int(performance["total_trades"]),
        "wins": int(performance["wins"]),
        "losses": int(performance["losses"]),
        "win_rate": float(performance["win_rate"]),
        "net_pnl": str(performance["net_profit"]),
        "profit_factor": str(performance["profit_factor"]),
        "max_drawdown": str(performance["max_drawdown"]),
        "average_win": str(performance["average_win"]),
        "average_loss": str(performance["average_loss"]),
        "expectancy": str(performance["expectancy_per_trade"]),
        "rejected_setup_counts": _rejected_counts(funnel),
        "trade_list": tuple(funnel["trade_list"]),
    }


def _empty_metrics() -> dict[str, object]:
    return {
        "candles": 0,
        "total_trades": 0,
        "wins": 0,
        "losses": 0,
        "win_rate": 0.0,
        "net_pnl": "0",
        "profit_factor": "0",
        "max_drawdown": "0",
        "average_win": "0",
        "average_loss": "0",
        "expectancy": "0",
        "rejected_setup_counts": {},
        "trade_list": (),
    }


def _combine_metrics(train: dict[str, object], validation: dict[str, object]) -> dict[str, object]:
    total_trades = int(train["total_trades"]) + int(validation["total_trades"])
    wins = int(train["wins"]) + int(validation["wins"])
    losses = int(train["losses"]) + int(validation["losses"])
    net_pnl = Decimal(str(train["net_pnl"])) + Decimal(str(validation["net_pnl"]))
    win_rate = (wins / (wins + losses) * 100.0) if wins + losses else 0.0
    max_drawdown = max(Decimal(str(train["max_drawdown"])), Decimal(str(validation["max_drawdown"])))
    profit_factor = _combined_profit_factor(train, validation)
    return {
        "total_trades": total_trades,
        "wins": wins,
        "losses": losses,
        "win_rate": win_rate,
        "net_pnl": str(net_pnl),
        "profit_factor": str(profit_factor),
        "max_drawdown": str(max_drawdown),
        "average_win": _weighted_average(train, validation, "average_win", "wins"),
        "average_loss": _weighted_average(train, validation, "average_loss", "losses"),
        "expectancy": str(net_pnl / total_trades) if total_trades else "0",
        "meets_25_trades_and_70_win_rate": total_trades >= MIN_TRADES and win_rate >= MIN_WIN_RATE,
        "validation_still_profitable": Decimal(str(validation["net_pnl"])) > 0,
    }


def _combined_profit_factor(train: dict[str, object], validation: dict[str, object]) -> Decimal | str:
    gross_profit = _gross_profit(train) + _gross_profit(validation)
    gross_loss = abs(_gross_loss(train) + _gross_loss(validation))
    if gross_loss == 0:
        return "INF" if gross_profit > 0 else Decimal("0")
    return gross_profit / gross_loss


def _gross_profit(metrics: dict[str, object]) -> Decimal:
    return Decimal(str(metrics["average_win"])) * Decimal(str(metrics["wins"]))


def _gross_loss(metrics: dict[str, object]) -> Decimal:
    return Decimal(str(metrics["average_loss"])) * Decimal(str(metrics["losses"]))


def _weighted_average(left: dict[str, object], right: dict[str, object], value_key: str, weight_key: str) -> str:
    weight = Decimal(str(left[weight_key])) + Decimal(str(right[weight_key]))
    if weight == 0:
        return "0"
    value = Decimal(str(left[value_key])) * Decimal(str(left[weight_key])) + Decimal(str(right[value_key])) * Decimal(str(right[weight_key]))
    return str(value / weight)


def _rejected_counts(funnel: dict[str, object]) -> dict[str, int]:
    return {
        key: int(value)
        for key, value in funnel.items()
        if key.startswith("rejected_") and isinstance(value, int)
    }


def _strong_train(metrics: dict[str, object]) -> bool:
    return (
        int(metrics["total_trades"]) >= MIN_TRADES
        and float(metrics["win_rate"]) >= MIN_WIN_RATE
        and Decimal(str(metrics["net_pnl"])) > 0
    )


def _strong_validation(metrics: dict[str, object]) -> bool:
    validation_min_trades = max(1, int(MIN_TRADES * 0.30))
    return (
        int(metrics["total_trades"]) >= validation_min_trades
        and float(metrics["win_rate"]) >= MIN_WIN_RATE
        and Decimal(str(metrics["net_pnl"])) > 0
    )


def _overfitting_risk(train: dict[str, object], validation: dict[str, object]) -> str:
    if not _strong_train(train):
        return "MEDIUM"
    if not _strong_validation(validation):
        return "HIGH"
    train_win = max(float(train["win_rate"]), 1.0)
    validation_win = float(validation["win_rate"])
    if validation_win < train_win * 0.80:
        return "MEDIUM"
    return "LOW"


def _rank_key(row: dict[str, object]) -> tuple:
    pf = _pf_value(row["profit_factor"])
    return (
        bool(row["meets_25_trades_and_70_win_rate"]),
        bool(row["validation_still_profitable"]),
        pf,
        Decimal(str(row["net_pnl"])),
        -Decimal(str(row["max_drawdown"])),
    )


def _pf_value(value) -> Decimal:
    if str(value).upper() == "INF":
        return Decimal("999999")
    return Decimal(str(value))


def _variant_name(profile: StrategyProfile) -> str:
    return (
        f"{profile.profile_id}_exp_{profile.expansion_ratio_min:g}_{profile.expansion_ratio_max:g}"
        f"_retrace_{profile.retrace_window_8m_candles}"
    )


def _variant_values(profile: StrategyProfile) -> dict[str, object]:
    return {
        "expansion_ratio_min": profile.expansion_ratio_min,
        "expansion_ratio_max": profile.expansion_ratio_max,
        "retrace_window_8m_candles": profile.retrace_window_8m_candles,
        "fvg_delay_16m_candles": profile.fvg_delay_16m_candles,
        "direct_12m_retrace_entry_enabled": profile.direct_12m_retrace_entry_enabled,
        "one_trade_per_12m_fvg": profile.one_trade_per_12m_fvg,
        "selected_rr_profile": PRODUCTION_RR_PROFILE,
        "selected_rr_value": str(resolve_rr_value(PRODUCTION_RR_PROFILE)),
    }


def _write_reports(report: dict[str, object]) -> None:
    reports_dir = ROOT / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    csv_path = reports_dir / "optimization_results.csv"
    html_path = reports_dir / "optimization_summary.html"
    fields = (
        "rank",
        "profile_name",
        "variant_name",
        "variable_values_used",
        "total_trades",
        "win_rate",
        "net_pnl",
        "profit_factor",
        "max_drawdown",
        "average_win",
        "average_loss",
        "expectancy",
        "training_total_trades",
        "training_win_rate",
        "training_net_pnl",
        "validation_total_trades",
        "validation_win_rate",
        "validation_net_pnl",
        "validation_profit_factor",
        "rejected_setup_counts",
        "trade_list",
        "overfitting_risk",
    )
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for index, row in enumerate(report["rows"], start=1):
            writer.writerow(_csv_row(index, row))
    html_path.write_text(_html(report), encoding="utf-8")
    report["csv_path"] = str(csv_path)
    report["html_path"] = str(html_path)


def _csv_row(rank: int, row: dict[str, object]) -> dict[str, object]:
    training = row["training"]
    validation = row["validation"]
    return {
        "rank": rank,
        "profile_name": row["profile_name"],
        "variant_name": row["variant_name"],
        "variable_values_used": json.dumps(row["variable_values_used"], sort_keys=True),
        "total_trades": row["total_trades"],
        "win_rate": row["win_rate"],
        "net_pnl": row["net_pnl"],
        "profit_factor": row["profit_factor"],
        "max_drawdown": row["max_drawdown"],
        "average_win": row["average_win"],
        "average_loss": row["average_loss"],
        "expectancy": row["expectancy"],
        "training_total_trades": training["total_trades"],
        "training_win_rate": training["win_rate"],
        "training_net_pnl": training["net_pnl"],
        "validation_total_trades": validation["total_trades"],
        "validation_win_rate": validation["win_rate"],
        "validation_net_pnl": validation["net_pnl"],
        "validation_profit_factor": validation["profit_factor"],
        "rejected_setup_counts": json.dumps(training["rejected_setup_counts"], sort_keys=True),
        "trade_list": json.dumps(row["training"]["trade_list"] + row["validation"]["trade_list"], default=str),
        "overfitting_risk": row["overfitting_risk"],
    }


def _html(report: dict[str, object]) -> str:
    rows = []
    for index, row in enumerate(report["rows"], start=1):
        rows.append(
            "<tr>"
            f"<td>{index}</td>"
            f"<td>{html.escape(str(row['profile_name']))}</td>"
            f"<td>{html.escape(str(row['variant_name']))}</td>"
            f"<td>{row['total_trades']}</td>"
            f"<td>{float(row['win_rate']):.2f}%</td>"
            f"<td>{html.escape(str(row['net_pnl']))}</td>"
            f"<td>{html.escape(str(row['profit_factor']))}</td>"
            f"<td>{html.escape(str(row['max_drawdown']))}</td>"
            f"<td>{html.escape(str(row['overfitting_risk']))}</td>"
            "</tr>"
        )
    best_strict = report["best_strict_profile_variant"]
    best_f = report["best_profile_f_variant"]
    return f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>ArjioBot Optimization Summary</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 24px; color: #111827; }}
    table {{ border-collapse: collapse; width: 100%; font-size: 13px; }}
    th, td {{ border: 1px solid #d1d5db; padding: 6px 8px; text-align: left; }}
    th {{ background: #f3f4f6; }}
    .warn {{ padding: 10px; background: #fff7ed; border: 1px solid #fed7aa; margin: 12px 0; }}
  </style>
</head>
<body>
  <h1>Parameter Optimization Summary</h1>
  <p><strong>Research only.</strong> Production settings were not overwritten.</p>
  <p>Training candles: {report['training_candles']} | Validation candles: {report['validation_candles']}</p>
  <div class="warn">Overfitting warning: {html.escape(str(report['overfitting_risk']))}. Results must be forward-tested before production use.</div>
  <h2>Final Output</h2>
  <ul>
    <li>BEST_STRICT_PROFILE_VARIANT: {html.escape(str(best_strict['variant_name'] if best_strict else 'NONE'))}</li>
    <li>BEST_PROFILE_F_VARIANT: {html.escape(str(best_f['variant_name'] if best_f else 'NONE'))}</li>
    <li>MEETS_25_TRADES_AND_70_WIN_RATE: {report['meets_25_trades_and_70_win_rate']}</li>
    <li>VALIDATION_STILL_PROFITABLE: {report['validation_still_profitable']}</li>
    <li>OVERFITTING_RISK: {html.escape(str(report['overfitting_risk']))}</li>
  </ul>
  <h2>Ranked Candidates</h2>
  <table>
    <thead><tr><th>Rank</th><th>Profile</th><th>Variant</th><th>Trades</th><th>Win Rate</th><th>Net PnL</th><th>PF</th><th>Max DD</th><th>Overfit Risk</th></tr></thead>
    <tbody>{''.join(rows)}</tbody>
  </table>
</body>
</html>
"""


def main() -> None:
    if len(sys.argv) < 6:
        raise SystemExit("Usage: python scripts/optimize_profiles.py data/BTCUSDT-1m.csv BTCUSDT STARTING_BALANCE FIXED_RISK_AMOUNT MAX_LEVERAGE [DEFAULT_16_12_8]")
    csv_path = Path(sys.argv[1])
    if not csv_path.exists():
        raise SystemExit(f"CSV file not found: {csv_path}")
    timeframe_profile = sys.argv[6] if len(sys.argv) > 6 else "DEFAULT_16_12_8"
    report = optimize(csv_path, sys.argv[2], starting_balance=sys.argv[3], risk_amount_per_trade=sys.argv[4], max_leverage=sys.argv[5], timeframe_profile=timeframe_profile)
    best_strict = report["best_strict_profile_variant"]
    best_f = report["best_profile_f_variant"]
    print(f"BEST_STRICT_PROFILE_VARIANT: {best_strict['variant_name'] if best_strict else 'NONE'}")
    print(f"BEST_PROFILE_F_VARIANT: {best_f['variant_name'] if best_f else 'NONE'}")
    print(f"MEETS_25_TRADES_AND_70_WIN_RATE: {report['meets_25_trades_and_70_win_rate']}")
    print(f"VALIDATION_STILL_PROFITABLE: {report['validation_still_profitable']}")
    print(f"OVERFITTING_RISK: {report['overfitting_risk']}")
    print(f"csv_report={report['csv_path']}")
    print(f"html_report={report['html_path']}")


if __name__ == "__main__":
    main()
