from __future__ import annotations

import csv
import html
import json
import statistics
import sys
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(ROOT / "scripts"))

import backtest_csv  # noqa: E402
from arjiobot.backtesting.historical_replay import load_ohlcv_csv  # noqa: E402
from arjiobot.backtesting.research_profiles import PROFILE_F_BALANCED, PROFILE_F_SELECTIVE, PROFILE_F_VOLUME  # noqa: E402


TP_MODELS = ("16M_FVG_BOUNDARY", "RR_1_0", "8M_PRE_RETRACE_EXTREME", "RR_1_5_CURRENT")
PROFILE_VARIANTS = (PROFILE_F_VOLUME, PROFILE_F_BALANCED, PROFILE_F_SELECTIVE)


@dataclass(frozen=True)
class EvaluatedTrade:
    record: dict[str, object]
    valid: bool
    invalid_reason: str | None = None


def optimize_tp_models(
    csv_path: Path,
    symbol: str,
    *,
    starting_balance: str,
    fixed_risk_amount: str,
    max_leverage: str,
    fees: str = "0",
    slippage: str = "0",
) -> dict[str, object]:
    candles = tuple(load_ohlcv_csv(csv_path, default_symbol=symbol))
    if len(candles) < 2:
        raise ValueError("TP optimization requires at least two candles")
    split_index = max(1, int(len(candles) * Decimal("0.70")))
    split_time = candles[split_index].timestamp
    rows: list[dict[str, object]] = []
    trade_lists: dict[str, list[dict[str, object]]] = {}
    rejections: list[dict[str, object]] = []

    for profile in PROFILE_VARIANTS:
        base = backtest_csv.run(
            csv_path,
            symbol,
            strategy_profile=profile.profile_id,
            starting_balance=starting_balance,
            fixed_risk_amount=fixed_risk_amount,
            max_leverage=max_leverage,
            fees=fees,
            slippage=slippage,
        )["summary"]
        base_trades = tuple(base["strategy_funnel"].get("trade_list", ()))
        for tp_model in TP_MODELS:
            evaluated = tuple(
                _evaluate_trade(
                    trade=trade,
                    candles=candles,
                    tp_model=tp_model,
                    fixed_risk_amount=Decimal(str(fixed_risk_amount)),
                    fees=Decimal(str(fees)),
                    slippage=Decimal(str(slippage)),
                )
                for trade in base_trades
                if isinstance(trade, dict)
            )
            valid_trades = [item.record for item in evaluated if item.valid]
            invalids = [item for item in evaluated if not item.valid]
            full = _metrics(valid_trades, Decimal(str(starting_balance)))
            training = _metrics([trade for trade in valid_trades if _parse_time(str(trade["entry_timestamp"])) < split_time], Decimal(str(starting_balance)))
            validation = _metrics([trade for trade in valid_trades if _parse_time(str(trade["entry_timestamp"])) >= split_time], Decimal(str(starting_balance)))
            row = {
                "profile": profile.profile_id,
                "timeframe_set": "16M/12M/8M/1M",
                "expansion_min": profile.expansion_ratio_min,
                "expansion_max": profile.expansion_ratio_max,
                "expansion": f"{profile.expansion_ratio_min:g}-{profile.expansion_ratio_max:g}",
                "retrace": "3x8M",
                "retracement_window": profile.retrace_window_8m_candles,
                "tp_model": tp_model,
                "entry_model": "Direct 12M retrace",
                "total_trades": len(evaluated),
                "valid_trades": len(valid_trades),
                "tp_invalid_count": len(invalids),
                **full,
                "training_trades": training["trades"],
                "training_win_rate": training["win_rate"],
                "training_net_pnl": training["net_pnl"],
                "training_profit_factor": training["profit_factor"],
                "training_max_drawdown": training["max_drawdown"],
                "validation_trades": validation["trades"],
                "validation_win_rate": validation["win_rate"],
                "validation_net_pnl": validation["net_pnl"],
                "validation_profit_factor": validation["profit_factor"],
                "validation_max_drawdown": validation["max_drawdown"],
            }
            rows.append(row)
            key = f"{profile.profile_id}__{tp_model}"
            trade_lists[key] = valid_trades
            for item in invalids:
                rejections.append(
                    {
                        "profile": profile.profile_id,
                        "tp_model": tp_model,
                        "trade_id": item.record.get("trade_id"),
                        "reason": item.invalid_reason,
                    }
                )

    ranked = sorted(rows, key=_rank_key, reverse=True)
    for index, row in enumerate(ranked, start=1):
        row["rank"] = index
    report = {
        "research_only": True,
        "production_settings_overwritten": False,
        "csv_path": str(csv_path),
        "symbol": symbol.upper(),
        "training_split": "first 70%",
        "validation_split": "last 30%",
        "rows": ranked,
        "trade_lists": trade_lists,
        "rejections": rejections,
        "summary": _summary(ranked),
    }
    _write_outputs(report)
    return report


def _evaluate_trade(*, trade: dict[str, object], candles, tp_model: str, fixed_risk_amount: Decimal, fees: Decimal, slippage: Decimal) -> EvaluatedTrade:
    direction = str(trade.get("direction", "")).upper()
    entry = Decimal(str(trade["entry_price"]))
    stop = Decimal(str(trade["stop_loss"]))
    risk_distance = abs(entry - stop)
    if risk_distance <= 0:
        return EvaluatedTrade({**trade, "tp_model": tp_model, "outcome": "TP_INVALID"}, False, "INVALID_RISK_DISTANCE")
    tp = _resolve_tp(trade, tp_model, direction, entry, stop)
    if tp is None:
        return EvaluatedTrade({**trade, "tp_model": tp_model, "outcome": "TP_INVALID"}, False, "TP_SOURCE_MISSING")
    if direction == "BEARISH" and tp >= entry:
        return EvaluatedTrade({**trade, "tp_model": tp_model, "take_profit": str(tp), "outcome": "TP_INVALID"}, False, "TP_NOT_BELOW_BEARISH_ENTRY")
    if direction == "BULLISH" and tp <= entry:
        return EvaluatedTrade({**trade, "tp_model": tp_model, "take_profit": str(tp), "outcome": "TP_INVALID"}, False, "TP_NOT_ABOVE_BULLISH_ENTRY")

    entry_time = _parse_time(str(trade["entry_timestamp"]))
    future = [candle for candle in candles if candle.timestamp > entry_time]
    position_size = fixed_risk_amount / risk_distance
    outcome = "OPEN_OR_UNRESOLVED"
    exit_price = Decimal(str(future[-1].close if future else entry))
    exit_timestamp = future[-1].end_timestamp if future else entry_time
    exit_reason = "DATA_ENDED_BEFORE_EXIT"
    for candle in future:
        if direction == "BEARISH":
            stop_hit = candle.high >= stop
            tp_hit = candle.low <= tp
        else:
            stop_hit = candle.low <= stop
            tp_hit = candle.high >= tp
        if stop_hit:
            outcome, exit_price, exit_timestamp, exit_reason = "LOSS", stop, candle.timestamp, "STOP_LOSS_HIT"
            break
        if tp_hit:
            outcome, exit_price, exit_timestamp, exit_reason = "WIN", tp, candle.timestamp, "TAKE_PROFIT_HIT"
            break

    gross = (entry - exit_price) * position_size if direction == "BEARISH" else (exit_price - entry) * position_size
    net = gross - fees - slippage
    effective_rr = abs(tp - entry) / risk_distance
    record = {
        **trade,
        "tp_model": tp_model,
        "take_profit": str(tp),
        "take_profit_price": str(tp),
        "effective_rr": str(effective_rr),
        "exit_timestamp": exit_timestamp.isoformat(),
        "exit_price": str(exit_price),
        "exit_reason": exit_reason,
        "outcome": outcome,
        "position_size": str(position_size),
        "gross_pnl": str(gross),
        "net_pnl": str(net),
        "rr_realized": str(net / fixed_risk_amount if fixed_risk_amount else Decimal("0")),
    }
    return EvaluatedTrade(record, True)


def _resolve_tp(trade: dict[str, object], tp_model: str, direction: str, entry: Decimal, stop: Decimal) -> Decimal | None:
    snapshot = trade.get("setup_snapshot", {})
    if not isinstance(snapshot, dict):
        snapshot = {}
    if tp_model == "RR_1_0":
        risk = abs(entry - stop)
        return entry - risk if direction == "BEARISH" else entry + risk
    if tp_model == "RR_1_5_CURRENT":
        risk = abs(entry - stop)
        return entry - risk * Decimal("1.5") if direction == "BEARISH" else entry + risk * Decimal("1.5")
    if tp_model == "16M_FVG_BOUNDARY":
        fvg16 = snapshot.get("fvg_16m", {})
        if not isinstance(fvg16, dict):
            return None
        key = "lower_boundary" if direction == "BEARISH" else "upper_boundary"
        return Decimal(str(fvg16[key])) if key in fvg16 else None
    if tp_model == "8M_PRE_RETRACE_EXTREME":
        candles = snapshot.get("eight_minute_candles_after_16m_fvg", ())
        entry_time = _parse_time(str(trade["entry_timestamp"]))
        eligible = [c for c in candles if isinstance(c, dict) and _parse_time(str(c["timestamp"])) < entry_time]
        if not eligible:
            return None
        values = [Decimal(str(c["low" if direction == "BEARISH" else "high"])) for c in eligible]
        return min(values) if direction == "BEARISH" else max(values)
    raise ValueError(f"unknown TP model: {tp_model}")


def _metrics(trades: list[dict[str, object]], starting_balance: Decimal) -> dict[str, object]:
    closed = [t for t in trades if t.get("outcome") in {"WIN", "LOSS"}]
    wins = [t for t in closed if t.get("outcome") == "WIN"]
    losses = [t for t in closed if t.get("outcome") == "LOSS"]
    pnls = [Decimal(str(t.get("net_pnl", "0"))) for t in closed]
    gross_profit = sum((p for p in pnls if p > 0), Decimal("0"))
    gross_loss = sum((p for p in pnls if p < 0), Decimal("0"))
    net_pnl = sum(pnls, Decimal("0"))
    effective_rrs = [Decimal(str(t.get("effective_rr", "0"))) for t in trades]
    return {
        "trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": (len(wins) / len(closed) * 100.0) if closed else 0.0,
        "net_pnl": str(net_pnl),
        "gross_profit": str(gross_profit),
        "gross_loss": str(gross_loss),
        "profit_factor": str(gross_profit / abs(gross_loss)) if gross_loss else ("INF" if gross_profit else "0"),
        "max_drawdown": str(_max_drawdown(pnls, starting_balance)),
        "expectancy": str(net_pnl / len(closed)) if closed else "0",
        "average_win": str(gross_profit / len(wins)) if wins else "0",
        "average_loss": str(gross_loss / len(losses)) if losses else "0",
        "average_effective_rr": str(sum(effective_rrs, Decimal("0")) / len(effective_rrs)) if effective_rrs else "0",
        "median_effective_rr": str(statistics.median(effective_rrs)) if effective_rrs else "0",
        "min_effective_rr": str(min(effective_rrs)) if effective_rrs else "0",
        "max_effective_rr": str(max(effective_rrs)) if effective_rrs else "0",
        **_time_to_tp_metrics(trades),
        "longest_losing_streak": _longest_losing_streak(closed),
    }


def _time_to_tp_metrics(trades: list[dict[str, object]]) -> dict[str, object]:
    durations: list[float] = []
    for trade in trades:
        if str(trade.get("outcome", "")).upper() != "WIN":
            continue
        exit_reason = str(trade.get("exit_reason", "")).upper()
        if exit_reason and exit_reason not in {"TAKE_PROFIT_HIT", "TP_HIT", "TAKE_PROFIT"}:
            continue
        entry_time = trade.get("entry_timestamp") or trade.get("entry_time")
        exit_time = trade.get("exit_timestamp") or trade.get("exit_time")
        if not entry_time or not exit_time:
            continue
        try:
            entry_dt = datetime.fromisoformat(str(entry_time).replace("Z", "+00:00"))
            exit_dt = datetime.fromisoformat(str(exit_time).replace("Z", "+00:00"))
        except ValueError:
            continue
        seconds = (exit_dt - entry_dt).total_seconds()
        if seconds >= 0:
            durations.append(seconds)
    if not durations:
        return {
            "average_time_to_hit_tp_seconds": None,
            "average_time_to_hit_tp_minutes": None,
            "average_time_to_hit_tp_human": "N/A",
            "fastest_time_to_hit_tp": None,
            "slowest_time_to_hit_tp": None,
            "median_time_to_hit_tp": None,
        }
    average_seconds = sum(durations) / len(durations)
    return {
        "average_time_to_hit_tp_seconds": average_seconds,
        "average_time_to_hit_tp_minutes": average_seconds / 60,
        "average_time_to_hit_tp_human": _format_duration_human(average_seconds),
        "fastest_time_to_hit_tp": _format_duration_human(min(durations)),
        "slowest_time_to_hit_tp": _format_duration_human(max(durations)),
        "median_time_to_hit_tp": _format_duration_human(float(statistics.median(durations))),
    }


def _format_duration_human(seconds: float) -> str:
    total_minutes = int(round(seconds / 60))
    hours = total_minutes // 60
    minutes = total_minutes % 60
    if hours:
        return f"{hours}h {minutes:02d}m"
    return f"{minutes}m"


def _max_drawdown(pnls: list[Decimal], starting_balance: Decimal) -> Decimal:
    balance = starting_balance
    peak = starting_balance
    max_dd = Decimal("0")
    for pnl in pnls:
        balance += pnl
        peak = max(peak, balance)
        max_dd = max(max_dd, peak - balance)
    return max_dd


def _longest_losing_streak(trades: list[dict[str, object]]) -> int:
    longest = current = 0
    for trade in trades:
        if trade.get("outcome") == "LOSS":
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest


def _rank_key(row: dict[str, object]) -> tuple:
    return (
        int(row["valid_trades"]) >= 25,
        Decimal(str(row["validation_net_pnl"])) > 0,
        float(row["validation_win_rate"]),
        _pf(row["validation_profit_factor"]),
        float(row["win_rate"]),
        _pf(row["profit_factor"]),
        Decimal(str(row["net_pnl"])),
        -Decimal(str(row["max_drawdown"])),
        Decimal(str(row["expectancy"])),
        -int(row["longest_losing_streak"]),
    )


def _pf(value: object) -> Decimal:
    return Decimal("999999") if str(value).upper() == "INF" else Decimal(str(value))


def _summary(rows: list[dict[str, object]]) -> dict[str, object]:
    best = rows[0] if rows else {}
    return {
        "BEST_TP_MODEL_OVERALL": best.get("tp_model", "NONE"),
        "BEST_TP_MODEL_FOR_PROFILE_F_VOLUME": _best_for(rows, "PROFILE_F_VOLUME"),
        "BEST_TP_MODEL_FOR_PROFILE_F_BALANCED": _best_for(rows, "PROFILE_F_BALANCED"),
        "BEST_TP_MODEL_FOR_PROFILE_F_SELECTIVE": _best_for(rows, "PROFILE_F_SELECTIVE"),
        "ANY_25_PLUS_TRADES": "YES" if any(int(r["valid_trades"]) >= 25 for r in rows) else "NO",
        "ANY_70_PLUS_WIN_RATE": "YES" if any(float(r["win_rate"]) >= 70 for r in rows) else "NO",
        "ANY_PROFITABLE_VALIDATION": "YES" if any(Decimal(str(r["validation_net_pnl"])) > 0 for r in rows) else "NO",
        "HIGHEST_WIN_RATE_MODEL": max(rows, key=lambda r: float(r["win_rate"]))["tp_model"] if rows else "NONE",
        "BEST_PROFIT_FACTOR_MODEL": max(rows, key=lambda r: _pf(r["profit_factor"]))["tp_model"] if rows else "NONE",
        "BEST_NET_PNL_MODEL": max(rows, key=lambda r: Decimal(str(r["net_pnl"])))["tp_model"] if rows else "NONE",
        "LOWEST_DRAWDOWN_MODEL": min(rows, key=lambda r: Decimal(str(r["max_drawdown"])))["tp_model"] if rows else "NONE",
        "MOST_STABLE_VALIDATION_MODEL": best.get("tp_model", "NONE"),
    }


def _best_for(rows: list[dict[str, object]], profile: str) -> str:
    matches = [row for row in rows if row["profile"] == profile]
    return matches[0]["tp_model"] if matches else "NONE"


def _write_outputs(report: dict[str, object]) -> None:
    reports = ROOT / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    rows = report["rows"]
    csv_path = reports / "tp_optimization_results.csv"
    fields = tuple(rows[0].keys()) if rows else ("rank",)
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    (reports / "tp_optimization_trade_lists.json").write_text(json.dumps(report["trade_lists"], indent=2, default=str), encoding="utf-8")
    _write_rejections(reports / "tp_optimization_rejection_summary.csv", report["rejections"])
    (reports / "tp_optimization_top_12.md").write_text(_markdown(report), encoding="utf-8")
    (reports / "tp_optimization_summary.html").write_text(_html(report), encoding="utf-8")
    report["csv_path"] = str(csv_path)


def _write_rejections(path: Path, rows: list[dict[str, object]]) -> None:
    fields = ("profile", "tp_model", "trade_id", "reason")
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _markdown(report: dict[str, object]) -> str:
    rows = report["rows"]
    lines = [
        "# TP Optimization Top 12",
        "",
        "Research only. Production RR_1_5 and live/demo settings were not changed.",
        "",
        "| Rank | Profile | Timeframe set | Expansion | Retrace | TP model | Entry model | Trades | Win rate | Net PnL | PF | Max DD | Expectancy | Avg effective RR | Validation |",
        "|---:|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in rows[:12]:
        validation = f"{row['validation_trades']} trades, {float(row['validation_win_rate']):.2f}%, PnL {row['validation_net_pnl']}, PF {row['validation_profit_factor']}"
        lines.append(
            f"| {row['rank']} | {row['profile']} | {row['timeframe_set']} | {row['expansion']} | {row['retrace']} | {row['tp_model']} | {row['entry_model']} | {row['valid_trades']} | {float(row['win_rate']):.2f}% | {row['net_pnl']} | {row['profit_factor']} | {row['max_drawdown']} | {row['expectancy']} | {row['average_effective_rr']} | {validation} |"
        )
    lines.extend(["", "## Final Summary", ""])
    lines.extend(f"- {key}: {value}" for key, value in report["summary"].items())
    return "\n".join(lines) + "\n"


def _html(report: dict[str, object]) -> str:
    md_rows = "\n".join(
        "<tr>"
        f"<td>{row['rank']}</td><td>{html.escape(str(row['profile']))}</td><td>{html.escape(str(row['tp_model']))}</td>"
        f"<td>{row['valid_trades']}</td><td>{float(row['win_rate']):.2f}%</td><td>{row['net_pnl']}</td>"
        f"<td>{row['profit_factor']}</td><td>{row['max_drawdown']}</td><td>{row['validation_net_pnl']}</td>"
        "</tr>"
        for row in report["rows"]
    )
    summary = "".join(f"<li>{html.escape(str(k))}: {html.escape(str(v))}</li>" for k, v in report["summary"].items())
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>TP Optimization Summary</title>
<style>body{{font-family:Arial,sans-serif;margin:24px}}table{{border-collapse:collapse;width:100%}}td,th{{border:1px solid #ccc;padding:6px}}</style></head>
<body><h1>TP Optimization Summary</h1><p><strong>Research only.</strong> Production settings were not changed.</p>
<ul>{summary}</ul><table><thead><tr><th>Rank</th><th>Profile</th><th>TP Model</th><th>Trades</th><th>Win Rate</th><th>Net PnL</th><th>PF</th><th>Max DD</th><th>Validation PnL</th></tr></thead><tbody>{md_rows}</tbody></table></body></html>"""


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def main() -> None:
    if len(sys.argv) < 6:
        raise SystemExit("Usage: python scripts/optimize_tp_models.py data/SOLUSDT-1m-2026-04.csv SOLUSDT STARTING_BALANCE FIXED_RISK_AMOUNT MAX_LEVERAGE")
    report = optimize_tp_models(Path(sys.argv[1]), sys.argv[2], starting_balance=sys.argv[3], fixed_risk_amount=sys.argv[4], max_leverage=sys.argv[5])
    for key, value in report["summary"].items():
        print(f"{key}: {value}")
    print("csv_report=reports/tp_optimization_results.csv")
    print("html_report=reports/tp_optimization_summary.html")


if __name__ == "__main__":
    main()
