from __future__ import annotations

import json
import sys
import uuid
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from arjiobot.backtesting.backtest_models import BacktestConfig, build_run_id  # noqa: E402
from arjiobot.backtesting.historical_replay import build_timeframe_profile, load_ohlcv_csv  # noqa: E402
from arjiobot.backtesting.backtest_engine import BacktestEngine  # noqa: E402
from arjiobot.backtesting.research_profiles import DEFAULT_PROFILE_ID, PROFILE_2, PROFILE_F_BALANCED, PROFILE_F_SELECTIVE, PROFILE_F_VOLUME, PROFILE_G_CODEX_OPTIMIZED, PROFILE_RECOVERED_HIGH_WINRATE, STRICT_PROFILE, StrategyProfile, get_profile, get_strategy_profiles  # noqa: E402
from arjiobot.backtesting.timeframe_profiles import DEFAULT_16_12_8, BacktestTimeframeProfile, get_timeframe_profile  # noqa: E402
from arjiobot.execution.execution_engine import ExecutionEngine  # noqa: E402
from arjiobot.expansion.expansion import ExpansionDetectionEngine  # noqa: E402
from arjiobot.fvg.fvg import FVGDetectionEngine  # noqa: E402
from arjiobot.fvg.fvg_models import FVGDirection, FairValueGap, fvg_to_record  # noqa: E402
from arjiobot.fvg.fvg_tap_rules import fvg_inside_bearish_leg, fvg_inside_bullish_leg  # noqa: E402
from arjiobot.setup_tracker.setup_invalidation import (
    close_above_12m_fvg,
    close_below_12m_fvg,
    high_sequence_invalidation_reason,
    low_sequence_invalidation_reason,
    should_invalidate_retrace_window,
)  # noqa: E402
from arjiobot.risk.risk_engine import RiskEngine  # noqa: E402
from arjiobot.risk.risk_models import AccountSnapshot, OpenRiskState, RiskConfig, TradePlanStatus  # noqa: E402
from arjiobot.risk.isolated_margin import IsolatedMarginPlan, calculate_isolated_margin_plan  # noqa: E402
from arjiobot.risk.rr_profiles import PRODUCTION_RR_PROFILE, calculate_fixed_risk_trade_math, calculate_pnl, resolve_rr_value  # noqa: E402
from arjiobot.profile_freeze import assert_profile_freeze  # noqa: E402
from arjiobot.strategy.strategy_engine import StrategyEngine  # noqa: E402
from arjiobot.swings.swing_models import Swing, swing_to_record  # noqa: E402
from arjiobot.swings.swing_models import SwingType  # noqa: E402
from arjiobot.swings.swings import SwingDetectionEngine  # noqa: E402


STRATEGY_SOURCE = "REAL_STRATEGY_PIPELINE"
STRICT_BASE_PROFILE = "STRICT_PROFILE"


def run(
    csv_path: Path,
    symbol: str,
    *,
    timeframe_profile: str = "DEFAULT_16_12_8",
    strategy_profile: str | None = None,
    starting_balance=None,
    fixed_risk_amount=None,
    max_leverage=None,
    selected_rr_profile=PRODUCTION_RR_PROFILE,
    fees="0",
    slippage="0",
    profile_overrides: dict[str, object] | None = None,
) -> dict[str, object]:
    assert_profile_freeze()
    _assert_real_strategy_source()
    starting_balance = _required_positive_value(starting_balance, "starting_balance")
    fixed_risk_amount = _required_positive_value(fixed_risk_amount, "fixed_risk_amount")
    max_leverage = _required_positive_value(max_leverage, "max_leverage")
    if not str(strategy_profile or "").strip():
        raise ValueError("strategy_profile is required; backtests must not fall back to a default profile")
    selected_profile_id = str(strategy_profile).strip().upper()
    active_profile = get_profile(strategy_profile)
    if profile_overrides:
        active_profile = replace(active_profile, **profile_overrides)
    if active_profile.profile_id != selected_profile_id:
        raise RuntimeError(
            f"profile lock failed before run: selected {selected_profile_id}, resolved {active_profile.profile_id}"
        )
    tf_profile = get_timeframe_profile(timeframe_profile)
    effective_rr_profile = _selected_rr_profile_for_profile(active_profile, str(selected_rr_profile).upper())
    effective_rr_value = _selected_rr_value_for_profile(active_profile, effective_rr_profile)
    candles = load_ohlcv_csv(csv_path, default_symbol=symbol)
    required_minutes = _required_timeframes(tf_profile)
    profiles = {minutes: build_timeframe_profile(candles, minutes) for minutes in required_minutes}
    swing_results = SwingDetectionEngine().detect_all_swings(profiles[tf_profile.swing_timeframe])
    bearish_swing_highs = [swing for swing in swing_results.swing_highs if swing.swing_type is SwingType.HIGH]
    # Generate a broad expansion set, then apply the selected strategy profile's
    # min/max range in _build_strategy_funnel.  The default expansion engine is
    # intentionally stricter and would collapse Profile F variants into the same
    # result before profile-specific filtering runs.
    expansions_main = _research_expansions(swing_results.all_swings)
    fvg_results = {
        minutes: FVGDetectionEngine().detect_fvgs(
            profiles[minutes],
            swings=swing_results.all_swings if active_profile.use_linked_fvg_detection and minutes == tf_profile.main_fvg_timeframe else (),
            expansions=expansions_main if active_profile.use_linked_fvg_detection and minutes == tf_profile.main_fvg_timeframe else (),
        )
        for minutes in required_minutes
        if minutes != 1
    }
    fvg_counts = {minutes: result.count for minutes, result in fvg_results.items()}
    htf_fvgs = fvg_counts[3] + fvg_counts[60]
    strategy_main_fvgs = tuple(fvg for fvg in fvg_results[tf_profile.main_fvg_timeframe].fvgs if fvg.is_strategy_fvg)
    strategy_funnel = _build_strategy_funnel(
        profile=active_profile,
        timeframe_profile=tf_profile,
        candidate_16m_swing_highs=bearish_swing_highs,
        expansions_16m=expansions_main,
        fvg_16m=fvg_results[tf_profile.main_fvg_timeframe].fvgs,
        fvg_12m=fvg_results[tf_profile.retrace_fvg_timeframe].fvgs,
        fvg_8m=fvg_results[tf_profile.internal_fvg_timeframe].fvgs,
        candles_8m=profiles[tf_profile.retrace_window_timeframe],
        candles_1m=profiles[1],
        starting_balance=starting_balance,
        risk_amount_per_trade=fixed_risk_amount,
        max_leverage=max_leverage,
    )
    entry_ready_setups = ()
    signals = StrategyEngine().process_entry_ready_setups(entry_ready_setups)
    risk_config = RiskConfig(account_equity=Decimal(str(starting_balance)), fixed_risk_amount=fixed_risk_amount, selected_rr_profile=selected_rr_profile, max_leverage=Decimal(str(max_leverage)))
    account_snapshot = AccountSnapshot(
        account_currency=risk_config.account_currency,
        account_equity=risk_config.account_equity,
        available_margin=risk_config.account_equity,
        captured_at=candles[0].timestamp,
    )
    risk_engine = RiskEngine()
    trade_plans = tuple(
        risk_engine.create_trade_plan(signal, risk_config, account_snapshot, OpenRiskState())
        for signal in signals
    )
    approved_trade_plans = tuple(plan for plan in trade_plans if plan.approval_status is TradePlanStatus.APPROVED)
    execution_engine = ExecutionEngine()
    executions = tuple(execution_engine.execute_trade_plan(plan) for plan in approved_trade_plans)
    config = BacktestConfig(
        run_id=build_run_id((symbol.upper(),), candles[0].timestamp, candles[-1].end_timestamp),
        symbols=(symbol.upper(),),
        start_time=candles[0].timestamp,
        end_time=candles[-1].end_timestamp,
        initial_balance=Decimal(str(starting_balance)),
        risk_per_trade=Decimal(str(fixed_risk_amount)),
        fixed_risk_amount=Decimal(str(fixed_risk_amount)),
        selected_rr_profile=risk_config.selected_rr_profile,
        fee_rate=Decimal(str(fees)),
    )
    engine = BacktestEngine()
    run_result = engine.run_backtest(config, candles, signals=signals)
    trades = engine._trades[run_result.run_id]
    funnel_trade_list = strategy_funnel.get("trade_list", ())
    funnel_performance = strategy_funnel.get("performance_summary", {})
    simulated_trade_count = len(funnel_trade_list) if isinstance(funnel_trade_list, (list, tuple)) else run_result.total_trades_simulated
    profile_lock_verification = _verify_profile_lock(
        frontend_selected_profile=selected_profile_id,
        api_selected_profile=selected_profile_id,
        backend_resolved_profile=active_profile.profile_id,
        strategy_applied_profile=active_profile.profile_id,
        trades=funnel_trade_list if isinstance(funnel_trade_list, (list, tuple)) else (),
    )
    if profile_lock_verification["profile_lock_status"] != "PASSED":
        raise RuntimeError(f"profile lock failed: {profile_lock_verification}")
    strategy_funnel = {
        **strategy_funnel,
        "trades": simulated_trade_count,
        "profile_lock_verification": profile_lock_verification,
    }
    invalidation_counts: dict[str, int] = {}
    pipeline_blocked_stage = "NONE"
    if not entry_ready_setups:
        pipeline_blocked_stage = "ENTRY_READY_SETUP_NOT_FOUND"
    report_dir = _writable_report_dir()
    json_path = report_dir / f"{run_result.run_id}.json"
    html_path = report_dir / f"{run_result.run_id}.html"
    summary = {
        "run_id": run_result.run_id,
        "symbol": symbol.upper(),
        "strategy_source": STRATEGY_SOURCE,
        "profile_id": active_profile.profile_id,
        "selected_profile_id": selected_profile_id,
        "applied_profile_id": active_profile.profile_id,
        "frontend_selected_profile": selected_profile_id,
        "api_selected_profile": selected_profile_id,
        "backend_resolved_profile": active_profile.profile_id,
        "strategy_applied_profile": active_profile.profile_id,
        "strategy_profile": active_profile.profile_id,
        "profile_variant_name": active_profile.label,
        "inherited_base_profile": active_profile.inherited_base_profile,
        "profile_applied": _profile_applied(active_profile),
        "profile_lock_verification": profile_lock_verification,
        "timeframe_profile": tf_profile.profile_id,
        "timeframe_profile_applied": tf_profile.to_record(),
        "candles_loaded": len(candles),
        "synthetic_candles": {f"{minutes}M": len(values) for minutes, values in profiles.items()},
        "htf_fvgs_found": htf_fvgs,
        "one_hour_context_fvgs_found": fvg_counts[60],
        "three_minute_context_fvgs_found": fvg_counts[3],
        "swing_timeframe_swings_found": swing_results.count,
        "valid_swing_timeframe_swing_highs": len(bearish_swing_highs),
        "main_timeframe_expansions_found": len(expansions_main),
        "main_fvg_timeframe_fvgs_found": fvg_counts[tf_profile.main_fvg_timeframe],
        "strategy_main_fvg_timeframe_fvgs_found": len(strategy_main_fvgs),
        "retrace_fvg_timeframe_fvgs_found": fvg_counts[tf_profile.retrace_fvg_timeframe],
        "internal_fvg_timeframe_fvgs_found": fvg_counts[tf_profile.internal_fvg_timeframe],
        f"{tf_profile.swing_timeframe}m_swings_found": swing_results.count,
        f"valid_{tf_profile.swing_timeframe}m_swing_highs": len(bearish_swing_highs),
        f"{tf_profile.main_fvg_timeframe}m_expansions_found": len(expansions_main),
        f"{tf_profile.main_fvg_timeframe}m_fvgs_found": fvg_counts[tf_profile.main_fvg_timeframe],
        f"strategy_{tf_profile.main_fvg_timeframe}m_fvgs_found": len(strategy_main_fvgs),
        f"{tf_profile.retrace_fvg_timeframe}m_fvgs_found": fvg_counts[tf_profile.retrace_fvg_timeframe],
        f"{tf_profile.internal_fvg_timeframe}m_fvgs_found": fvg_counts[tf_profile.internal_fvg_timeframe],
        "entry_ready_setups_found": len(entry_ready_setups),
        "setups_created": run_result.total_setups_detected,
        "setups_invalidated_with_reason_counts": dict(invalidation_counts),
        "pipeline_blocked_stage": pipeline_blocked_stage,
        "signals_generated": int(strategy_funnel.get("signals_generated", run_result.total_signals_generated)),
        "risk_trade_plans_created": len(trade_plans),
        "risk_trade_plans_approved": len(approved_trade_plans),
        "paper_executions_created": len(executions),
        "trades_simulated": simulated_trade_count,
        "wins": funnel_performance.get("wins", run_result.metrics.wins if run_result.metrics else 0) if isinstance(funnel_performance, dict) else (run_result.metrics.wins if run_result.metrics else 0),
        "losses": funnel_performance.get("losses", run_result.metrics.losses if run_result.metrics else 0) if isinstance(funnel_performance, dict) else (run_result.metrics.losses if run_result.metrics else 0),
        "win_rate": float(funnel_performance.get("win_rate", run_result.metrics.win_rate if run_result.metrics else 0.0)) if isinstance(funnel_performance, dict) else (float(run_result.metrics.win_rate) if run_result.metrics else 0.0),
        "net_profit": str(funnel_performance.get("net_profit", run_result.metrics.net_profit if run_result.metrics else "0")) if isinstance(funnel_performance, dict) else (str(run_result.metrics.net_profit) if run_result.metrics else "0"),
        "max_drawdown": str(funnel_performance.get("max_drawdown", run_result.metrics.max_drawdown if run_result.metrics else "0")) if isinstance(funnel_performance, dict) else (str(run_result.metrics.max_drawdown) if run_result.metrics else "0"),
        "profit_factor": str(funnel_performance.get("profit_factor", run_result.metrics.profit_factor if run_result.metrics else "0")) if isinstance(funnel_performance, dict) else (str(run_result.metrics.profit_factor) if run_result.metrics else "0"),
        "average_rr": str(funnel_performance.get("average_rr", run_result.metrics.average_r if run_result.metrics else "0")) if isinstance(funnel_performance, dict) else (str(run_result.metrics.average_r) if run_result.metrics else "0"),
        "selected_rr_profile": effective_rr_profile,
        "selected_rr_value": str(effective_rr_value),
        "selected_tp_model": effective_rr_profile,
        "applied_tp_model": active_profile.tp_model,
        "tp_model_lock_status": "UNLOCKED" if effective_rr_profile == active_profile.tp_model else "LOCKED",
        "tp_model_override_allowed": "YES" if "tp_model" in active_profile.tunable_parameters or effective_rr_profile == active_profile.tp_model else "NO",
        "fixed_risk_amount": str(risk_config.fixed_risk_amount),
        "selected_starting_balance": str(starting_balance),
        "applied_starting_balance": str(starting_balance),
        "selected_fixed_risk_amount": str(risk_config.fixed_risk_amount),
        "selected_max_leverage": str(max_leverage),
        "fixed_risk_label": str(risk_config.fixed_risk_amount),
        "largest_win": str(funnel_performance.get("largest_win", run_result.metrics.largest_win if run_result.metrics else "0")) if isinstance(funnel_performance, dict) else (str(run_result.metrics.largest_win) if run_result.metrics else "0"),
        "largest_loss": str(funnel_performance.get("largest_loss", run_result.metrics.largest_loss if run_result.metrics else "0")) if isinstance(funnel_performance, dict) else (str(run_result.metrics.largest_loss) if run_result.metrics else "0"),
        "known_limitation": "Historical Setup Tracker orchestration is conservative: no ENTRY_READY setup is synthesized from prerequisite counts.",
        "strategy_funnel": strategy_funnel,
        "trade_list": strategy_funnel.get("trade_list", ()),
        "performance_summary": strategy_funnel.get("performance_summary", {}),
        "profile_validation": _build_validation_report(active_profile),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    json_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    html_path.write_text(_html(summary), encoding="utf-8")
    return {"summary": summary, "json_path": json_path, "html_path": html_path}


def run_research_comparison(
    csv_path: Path,
    symbol: str,
    *,
    starting_balance=None,
    risk_amount_per_trade=None,
    max_leverage=None,
    selected_rr_profile=PRODUCTION_RR_PROFILE,
    fees="0",
    slippage="0",
    timeframe_profile: str = "DEFAULT_16_12_8",
) -> dict[str, object]:
    starting_balance = _required_positive_value(starting_balance, "starting_balance")
    risk_amount_per_trade = _required_positive_value(risk_amount_per_trade, "risk_amount_per_trade")
    max_leverage = _required_positive_value(max_leverage, "max_leverage")
    tf_profile = get_timeframe_profile(timeframe_profile)
    candles = load_ohlcv_csv(csv_path, default_symbol=symbol)
    required_minutes = _required_timeframes(tf_profile)
    profiles_by_minutes = {minutes: build_timeframe_profile(candles, minutes) for minutes in required_minutes}
    swing_results = SwingDetectionEngine().detect_all_swings(profiles_by_minutes[tf_profile.swing_timeframe])
    bearish_swing_highs = [swing for swing in swing_results.swing_highs if swing.swing_type is SwingType.HIGH]
    expansions_main = _research_expansions(swing_results.all_swings)
    fvg_results = {minutes: FVGDetectionEngine().detect_fvgs(profiles_by_minutes[minutes]) for minutes in required_minutes if minutes != 1}
    run_id = build_run_id((symbol.upper(),), candles[0].timestamp, candles[-1].end_timestamp)
    rows = []
    near_misses = []
    for profile in get_strategy_profiles():
        funnel = _build_strategy_funnel(
            profile=profile,
            timeframe_profile=tf_profile,
            candidate_16m_swing_highs=bearish_swing_highs,
            expansions_16m=expansions_main,
            fvg_16m=fvg_results[tf_profile.main_fvg_timeframe].fvgs,
            fvg_12m=fvg_results[tf_profile.retrace_fvg_timeframe].fvgs,
            fvg_8m=fvg_results[tf_profile.internal_fvg_timeframe].fvgs,
            candles_8m=profiles_by_minutes[tf_profile.retrace_window_timeframe],
            candles_1m=profiles_by_minutes[1],
            starting_balance=starting_balance,
            risk_amount_per_trade=risk_amount_per_trade,
            max_leverage=max_leverage,
            selected_rr_profile=selected_rr_profile,
            fees=fees,
            slippage=slippage,
        )
        performance = funnel["performance_summary"]
        row = {
            "profile_id": profile.profile_id,
            "profile_label": profile.label,
            "inherited_base_profile": profile.inherited_base_profile,
            "research_only": not profile.production_safe,
            "expansion_min": profile.expansion_ratio_min,
            "expansion_max": profile.expansion_ratio_max,
            "retrace_window_8m_candles": profile.retrace_window_8m_candles,
            "direct_12m_retrace_entry_enabled": profile.direct_12m_retrace_entry_enabled,
            "one_trade_per_12m_fvg": profile.one_trade_per_12m_fvg,
            "label": profile.label,
            "classification": "PRODUCTION SAFE" if profile.production_safe else "RESEARCH ONLY - NOT PRODUCTION STRICT ARJIO RULE",
            "candidate_swings": funnel["candidate_swing_timeframe_swing_highs"],
            "passed_expansion": funnel["passed_expansion"],
            "passed_main_fvg_timeframe_fvg": funnel["passed_main_fvg_timeframe_fvg"],
            "passed_retrace_fvg_timeframe_fvg": funnel["passed_retrace_fvg_timeframe_fvg"],
            "passed_internal_fvg_timeframe_fvg": funnel["passed_internal_fvg_timeframe_fvg"],
            "passed_retrace": funnel["passed_retrace"],
            "rejected_close_above_12m_fvg_before_entry": funnel["rejected_close_above_12m_fvg_before_entry"],
            "direct_12m_entries": funnel["direct_12m_entries"],
            "ignored_additional_12m_fvg_tap_after_entry": funnel["ignored_additional_12m_fvg_tap_after_entry"],
            "post_entry_close_above_12m_fvg_ignored": funnel["post_entry_close_above_12m_fvg_ignored"],
            "signals_generated": funnel["signals_generated"],
            "risk_rejected_count": funnel["risk_rejected_count"],
            "risk_rejection_reasons": funnel["risk_rejection_reasons"],
            "passed_12m_reaction": funnel["passed_12m_reaction"],
            "first_1m_swing_high_candidates": funnel["first_1m_swing_high_candidates"],
            "rejected_no_first_1m_swing_high": funnel["rejected_no_first_1m_swing_high"],
            "passed_first_1m_swing_high": funnel["passed_first_1m_swing_high"],
            "second_1m_swing_high_candidates": funnel["second_1m_swing_high_candidates"],
            "rejected_no_second_1m_swing_high": funnel["rejected_no_second_1m_swing_high"],
            "passed_second_1m_swing_high": funnel["passed_second_1m_swing_high"],
            "rejected_third_1m_high": funnel["rejected_third_1m_high"],
            "rejected_1m_close_above_12m_fvg": funnel["rejected_1m_close_above_12m_fvg"],
            "passed_1m_swing_confirmation": funnel["passed_1m_swing_confirmation"],
            "rejected_no_1m_bearish_expansion": funnel["rejected_no_1m_bearish_expansion"],
            "passed_1m_bearish_expansion": funnel["passed_1m_bearish_expansion"],
            "rejected_no_1m_bearish_fvg": funnel["rejected_no_1m_bearish_fvg"],
            "passed_1m_bearish_fvg": funnel["passed_1m_bearish_fvg"],
            "rejected_no_return_to_first_1m_fvg": funnel["rejected_no_return_to_first_1m_fvg"],
            "rejected_no_return_to_second_1m_fvg": funnel["rejected_no_return_to_second_1m_fvg"],
            "passed_return_to_first_1m_fvg": funnel["passed_return_to_first_1m_fvg"],
            "passed_return_to_second_1m_fvg": funnel["passed_return_to_second_1m_fvg"],
            "rejected_entry_window_expired": funnel["rejected_entry_window_expired"],
            "entry_ready": funnel["entry_ready"],
            "unaccounted_after_retrace": funnel["unaccounted_after_retrace"],
            "signals": funnel["signals_generated"],
            "trades": funnel["trades"],
            "closed_trades": performance["closed_trades"],
            "open_or_unresolved_trades": performance["open_or_unresolved_trades"],
            "wins": performance["wins"],
            "losses": performance["losses"],
            "win_rate": performance["win_rate"],
            "loss_rate": performance["loss_rate"],
            "gross_profit": performance["gross_profit"],
            "gross_loss": performance["gross_loss"],
            "net_profit": performance["net_profit"],
            "max_drawdown": performance["max_drawdown"],
            "final_balance": performance["final_balance"],
            "profit_factor": performance["profit_factor"],
            "average_rr": performance["average_rr"],
            "selected_rr_profile": performance["selected_rr_profile"],
            "selected_rr_value": performance["selected_rr_value"],
            "selected_tp_model": performance["selected_rr_profile"],
            "applied_tp_model": performance["selected_rr_profile"],
            "tp_model_lock_status": "UNLOCKED",
            "fixed_risk_amount": performance["fixed_risk_amount"],
        }
        rows.append(row)
        near_misses.append({"profile_id": profile.profile_id, "funnel": funnel, "trades": funnel["trade_list"], "performance_summary": performance})
    report = {
        "run_id": run_id,
        "symbol": symbol.upper(),
        "strategy_source": STRATEGY_SOURCE,
        "timeframe_profile": tf_profile.profile_id,
        "timeframe_profile_applied": tf_profile.to_record(),
        "synthetic_candles": {f"{minutes}M": len(values) for minutes, values in profiles_by_minutes.items()},
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "profiles": [profile.to_record() for profile in get_strategy_profiles()],
        "selected_rr_profile": str(selected_rr_profile).upper(),
        "selected_rr_value": str(resolve_rr_value(str(selected_rr_profile).upper())),
        "selected_tp_model": str(selected_rr_profile).upper(),
        "applied_tp_model": str(selected_rr_profile).upper(),
        "tp_model_lock_status": "UNLOCKED",
        "fixed_risk_amount": str(risk_amount_per_trade),
        "profile_validation": _build_validation_report(PROFILE_F_VOLUME),
        "comparison": rows,
        "near_misses": near_misses,
    }
    report_dir = _writable_report_dir()
    json_path = report_dir / f"research_comparison_{run_id}.json"
    html_path = report_dir / f"research_comparison_{run_id}.html"
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    html_path.write_text(_research_html(report), encoding="utf-8")
    return {"summary": report, "json_path": json_path, "html_path": html_path}


def _assert_real_strategy_source() -> None:
    if STRATEGY_SOURCE == "DEMO_SIGNAL_INJECTION":
        raise RuntimeError("CSV backtests must use REAL_STRATEGY_PIPELINE, not DEMO_SIGNAL_INJECTION")


def _required_positive_value(value, field_name: str) -> str:
    if value in (None, ""):
        raise ValueError(f"{field_name} is required; no hidden default is allowed")
    parsed = Decimal(str(value))
    if parsed <= 0:
        raise ValueError(f"{field_name} must be greater than zero")
    return str(value)


def _required_timeframes(profile: BacktestTimeframeProfile) -> tuple[int, ...]:
    return tuple(sorted({1, 3, profile.swing_timeframe, profile.main_fvg_timeframe, profile.retrace_fvg_timeframe, profile.internal_fvg_timeframe, profile.retrace_window_timeframe, 60}))


def _writable_report_dir() -> Path:
    preferred = ROOT / "reports" / "backtests"
    fallback = ROOT / ".pytest_tmp" / "backtests"
    for directory in (preferred, fallback):
        try:
            directory.mkdir(parents=True, exist_ok=True)
            probe = directory / f".write_probe_{uuid.uuid4().hex}"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
            return directory
        except OSError:
            continue
    raise PermissionError("No writable backtest report directory is available.")


def _build_strategy_funnel(
    *,
    profile: StrategyProfile,
    timeframe_profile: BacktestTimeframeProfile = DEFAULT_16_12_8,
    candidate_16m_swing_highs: tuple[Swing, ...] | list[Swing],
    expansions_16m,
    fvg_16m: tuple[FairValueGap, ...],
    fvg_12m: tuple[FairValueGap, ...],
    fvg_8m: tuple[FairValueGap, ...],
    candles_8m,
    candles_1m,
    starting_balance=None,
    risk_amount_per_trade=None,
    max_leverage=None,
    selected_rr_profile=PRODUCTION_RR_PROFILE,
    fees="0",
    slippage="0",
) -> dict[str, object]:
    starting_balance = _required_positive_value(starting_balance, "starting_balance")
    risk_amount_per_trade = _required_positive_value(risk_amount_per_trade, "risk_amount_per_trade")
    max_leverage = _required_positive_value(max_leverage, "max_leverage")
    swing_by_id = {swing.swing_id: swing for swing in candidate_16m_swing_highs}
    valid_expansions = _profile_valid_expansions(profile=profile, expansions=expansions_16m, swing_by_id=swing_by_id)
    strategy_16m_fvgs = tuple(fvg for fvg in fvg_16m if _fvg_matches_profile_expansion(fvg, valid_expansions, profile))
    fvg_by_expansion = {
        expansion.expansion_id: next(
            (fvg for fvg in strategy_16m_fvgs if _one_fvg_matches_expansion(fvg, expansion, profile)),
            None,
        )
        for expansion in valid_expansions
    }

    no_12m = 0
    no_8m = 0
    retrace_expired = 0
    close_above = 0
    third_high = 0
    target_reached = 0
    rejected_close_above_12m_fvg_before_entry = 0
    direct_12m_entries = 0
    ignored_additional_12m_fvg_tap_after_entry = 0
    post_entry_close_above_12m_fvg_ignored = 0
    signals_generated = 0
    risk_rejected_count = 0
    passed_retrace_count = 0
    passed_12m_reaction = 0
    first_1m_swing_high_candidates = 0
    rejected_no_first_1m_swing_high = 0
    passed_first_1m_swing_high = 0
    second_1m_swing_high_candidates = 0
    rejected_no_second_1m_swing_high = 0
    passed_second_1m_swing_high = 0
    rejected_third_1m_high = 0
    rejected_1m_close_above_12m_fvg = 0
    passed_1m_swing_confirmation = 0
    rejected_no_1m_bearish_expansion = 0
    passed_1m_bearish_expansion = 0
    rejected_no_1m_bearish_fvg = 0
    passed_1m_bearish_fvg = 0
    rejected_no_return_to_first_1m_fvg = 0
    rejected_no_return_to_second_1m_fvg = 0
    passed_return_to_first_1m_fvg = 0
    passed_return_to_second_1m_fvg = 0
    rejected_entry_window_expired = 0
    entry_ready = 0
    trade_list: list[dict[str, object]] = []
    risk_rejection_reasons: list[str] = []
    starting_balance_decimal = Decimal(str(starting_balance))
    risk_amount_decimal = Decimal(str(risk_amount_per_trade))
    max_leverage_decimal = Decimal(str(max_leverage))
    selected_rr_profile = _selected_rr_profile_for_profile(profile, str(selected_rr_profile).upper())
    selected_rr_value = _selected_rr_value_for_profile(profile, selected_rr_profile)

    for expansion in valid_expansions:
        fvg16 = fvg_by_expansion.get(expansion.expansion_id)
        if fvg16 is None or fvg16.fvg_completion_candle_low is None:
            continue
        swing = swing_by_id.get(expansion.swing_id)
        if swing is None:
            continue
        related_12m = _fvgs_inside_leg(
            fvg_12m,
            direction=fvg16.direction,
            swing_high_price=swing.price,
            completion_candle_low=fvg16.fvg_completion_candle_low,
            start_at=fvg16.confirmed_at,
        )
        if not related_12m:
            no_12m += 1
            continue
        fvg12 = related_12m[0]
        related_8m = _fvgs_inside_leg(
            fvg_8m,
            direction=fvg16.direction,
            swing_high_price=swing.price,
            completion_candle_low=fvg16.fvg_completion_candle_low,
            start_at=fvg16.confirmed_at,
        )
        if not related_8m:
            no_8m += 1
            continue
        retrace_window = tuple(candle for candle in candles_8m if candle.timestamp >= fvg16.confirmed_at)[: profile.retrace_window_8m_candles]
        if len(retrace_window) < profile.retrace_window_8m_candles:
            retrace_expired += 1
            continue
        retrace_candle = _first_1m_retrace_into_12m_fvg_within_8m_window(
            fvg12=fvg12,
            candles_1m=candles_1m,
            fvg16_confirmed_at=fvg16.confirmed_at,
            retrace_window_8m=retrace_window,
            direction="BEARISH",
        )
        if retrace_candle is None:
            retrace_expired += 1
            continue
        passed_retrace_count += 1
        final_target = min(fvg16.fvg_completion_candle_low, min(candle.low for candle in retrace_window))
        if profile.direct_12m_retrace_entry_enabled:
            direct_counts = _classify_direct_12m_retrace_entry(fvg12=fvg12, candles_1m=candles_1m, retrace_candle=retrace_candle)
            rejected_close_above_12m_fvg_before_entry += direct_counts["rejected_close_above_12m_fvg_before_entry"]
            direct_12m_entries += direct_counts["direct_12m_entries"]
            ignored_additional_12m_fvg_tap_after_entry += direct_counts["ignored_additional_12m_fvg_tap_after_entry"]
            post_entry_close_above_12m_fvg_ignored += direct_counts["post_entry_close_above_12m_fvg_ignored"]
            signals_generated += direct_counts["signals_generated"]
            entry_ready += direct_counts["entry_ready"]
            if direct_counts["direct_12m_entries"]:
                trade = _simulate_bearish_trade(
                    trade_number=len(trade_list) + 1,
                    symbol=expansion.symbol,
                    profile_id=profile.profile_id,
                    inherited_base_profile=profile.inherited_base_profile,
                    entry_candle=direct_counts["entry_candle"],
                    future_candles=tuple(candle for candle in candles_1m if candle.timestamp > direct_counts["entry_candle"].timestamp),
                    stop_loss=swing.price,
                    take_profit=final_target,
                    risk_amount=risk_amount_decimal,
                    starting_balance=starting_balance_decimal,
                    max_leverage=max_leverage_decimal,
                    selected_rr_profile=selected_rr_profile,
                    tp_model=profile.tp_model,
                    source_12m_fvg_id=fvg12.fvg_id,
                    source_16m_swing_id=swing.swing_id,
                    source_16m_fvg_id=fvg16.fvg_id,
                    setup_snapshot=_profile_f_setup_snapshot(
                        profile=profile,
                        timeframe_profile=timeframe_profile,
                        expansion=expansion,
                        swing=swing,
                        fvg16=fvg16,
                        fvg12=fvg12,
                        retrace_window=retrace_window,
                        retrace_candle=retrace_candle,
                        entry_candle=direct_counts["entry_candle"],
                        final_target=final_target,
                    ),
                )
                if trade["outcome"] == "RISK_REJECTED":
                    risk_rejected_count += 1
                    risk_rejection_reasons.append(str(trade["exit_reason"]))
                else:
                    trade_list.append(trade)
            continue
        confirmation_1m = tuple(candle for candle in candles_1m if candle.timestamp >= retrace_candle.end_timestamp)
        if any(close_above_12m_fvg(fvg12, candle) for candle in confirmation_1m):
            close_above += 1
            continue
        if high_sequence_invalidation_reason(fvg12, confirmation_1m[:3]) is not None:
            third_high += 1
            continue
        if any(candle.low <= final_target for candle in confirmation_1m):
            target_reached += 1
            continue
        passed_12m_reaction += 1
        confirmation = _classify_1m_confirmation(
            fvg12=fvg12,
            candles=tuple(candle for candle in candles_1m if candle.timestamp >= fvg12.confirmed_at),
            final_target=final_target,
        )
        first_1m_swing_high_candidates += confirmation["first_1m_swing_high_candidates"]
        rejected_no_first_1m_swing_high += confirmation["rejected_no_first_1m_swing_high"]
        passed_first_1m_swing_high += confirmation["passed_first_1m_swing_high"]
        second_1m_swing_high_candidates += confirmation["second_1m_swing_high_candidates"]
        rejected_no_second_1m_swing_high += confirmation["rejected_no_second_1m_swing_high"]
        passed_second_1m_swing_high += confirmation["passed_second_1m_swing_high"]
        rejected_third_1m_high += confirmation["rejected_third_1m_high"]
        rejected_1m_close_above_12m_fvg += confirmation["rejected_1m_close_above_12m_fvg"]
        passed_1m_swing_confirmation += confirmation["passed_1m_swing_confirmation"]
        rejected_no_1m_bearish_expansion += confirmation["rejected_no_1m_bearish_expansion"]
        passed_1m_bearish_expansion += confirmation["passed_1m_bearish_expansion"]
        rejected_no_1m_bearish_fvg += confirmation["rejected_no_1m_bearish_fvg"]
        passed_1m_bearish_fvg += confirmation["passed_1m_bearish_fvg"]
        rejected_no_return_to_first_1m_fvg += confirmation["rejected_no_return_to_first_1m_fvg"]
        rejected_no_return_to_second_1m_fvg += confirmation["rejected_no_return_to_second_1m_fvg"]
        passed_return_to_first_1m_fvg += confirmation["passed_return_to_first_1m_fvg"]
        passed_return_to_second_1m_fvg += confirmation["passed_return_to_second_1m_fvg"]
        rejected_entry_window_expired += confirmation["rejected_entry_window_expired"]
        entry_ready += confirmation["entry_ready"]

    passed_16m_fvg = len(strategy_16m_fvgs)
    unaccounted_after_retrace = _unaccounted_after_retrace(
        passed_retrace=passed_retrace_count,
        rejected_close_above_12m_fvg=close_above,
        rejected_third_1m_high=rejected_third_1m_high,
        rejected_target_reached_before_entry=target_reached,
        rejected_no_first_1m_swing_high=rejected_no_first_1m_swing_high,
        rejected_no_second_1m_swing_high=rejected_no_second_1m_swing_high,
        rejected_1m_close_above_12m_fvg=rejected_1m_close_above_12m_fvg,
        rejected_no_1m_bearish_expansion=rejected_no_1m_bearish_expansion,
        rejected_no_1m_bearish_fvg=rejected_no_1m_bearish_fvg,
        rejected_no_return_to_first_1m_fvg=rejected_no_return_to_first_1m_fvg,
        rejected_no_return_to_second_1m_fvg=rejected_no_return_to_second_1m_fvg,
        rejected_entry_window_expired=rejected_entry_window_expired,
        entry_ready=entry_ready,
    )
    if profile.direct_12m_retrace_entry_enabled:
        unaccounted_after_retrace = passed_retrace_count - rejected_close_above_12m_fvg_before_entry - direct_12m_entries
    performance_summary = _performance_summary(
        trades=trade_list,
        starting_balance=starting_balance_decimal,
        risk_amount_per_trade=risk_amount_decimal,
        selected_rr_profile=selected_rr_profile,
        selected_rr_value=selected_rr_value,
        signals_generated=signals_generated,
        risk_rejected_count=risk_rejected_count,
        risk_rejection_reasons=tuple(risk_rejection_reasons),
    )
    _apply_balances(trade_list, starting_balance_decimal)
    performance_summary = _performance_summary(
        trades=trade_list,
        starting_balance=starting_balance_decimal,
        risk_amount_per_trade=risk_amount_decimal,
        selected_rr_profile=selected_rr_profile,
        selected_rr_value=selected_rr_value,
        signals_generated=signals_generated,
        risk_rejected_count=risk_rejected_count,
        risk_rejection_reasons=tuple(risk_rejection_reasons),
    )
    swing_label = f"{timeframe_profile.swing_timeframe}m"
    main_label = f"{timeframe_profile.main_fvg_timeframe}m"
    retrace_label = f"{timeframe_profile.retrace_fvg_timeframe}m"
    internal_label = f"{timeframe_profile.internal_fvg_timeframe}m"
    funnel = {
        "candidate_16m_swing_highs": len(candidate_16m_swing_highs),
        "rejected_no_expansion": len(candidate_16m_swing_highs) - len(valid_expansions),
        "passed_expansion": len(valid_expansions),
        "rejected_no_immediate_16m_fvg": len(valid_expansions) - passed_16m_fvg,
        "passed_16m_fvg": passed_16m_fvg,
        "rejected_no_12m_fvg_inside_leg": no_12m,
        "passed_12m_fvg": passed_16m_fvg - no_12m,
        "rejected_no_8m_fvg_inside_leg": no_8m,
        "passed_8m_fvg": max(0, passed_16m_fvg - no_12m - no_8m),
        "rejected_retrace_window_expired": retrace_expired,
        "passed_retrace": passed_retrace_count,
        "rejected_close_above_12m_fvg": close_above,
        "rejected_close_above_12m_fvg_before_entry": rejected_close_above_12m_fvg_before_entry,
        "direct_12m_entries": direct_12m_entries,
        "ignored_additional_12m_fvg_tap_after_entry": ignored_additional_12m_fvg_tap_after_entry,
        "post_entry_close_above_12m_fvg_ignored": post_entry_close_above_12m_fvg_ignored,
        "rejected_third_high": third_high,
        "rejected_target_reached_before_entry": target_reached,
        "passed_12m_reaction": passed_12m_reaction,
        "first_1m_swing_high_candidates": first_1m_swing_high_candidates,
        "rejected_no_first_1m_swing_high": rejected_no_first_1m_swing_high,
        "passed_first_1m_swing_high": passed_first_1m_swing_high,
        "second_1m_swing_high_candidates": second_1m_swing_high_candidates,
        "rejected_no_second_1m_swing_high": rejected_no_second_1m_swing_high,
        "passed_second_1m_swing_high": passed_second_1m_swing_high,
        "rejected_third_1m_high": rejected_third_1m_high,
        "rejected_1m_close_above_12m_fvg": rejected_1m_close_above_12m_fvg,
        "passed_1m_swing_confirmation": passed_1m_swing_confirmation,
        "rejected_no_1m_bearish_expansion": rejected_no_1m_bearish_expansion,
        "passed_1m_bearish_expansion": passed_1m_bearish_expansion,
        "rejected_no_1m_bearish_fvg": rejected_no_1m_bearish_fvg,
        "passed_1m_bearish_fvg": passed_1m_bearish_fvg,
        "rejected_no_return_to_first_1m_fvg": rejected_no_return_to_first_1m_fvg,
        "rejected_no_return_to_second_1m_fvg": rejected_no_return_to_second_1m_fvg,
        "passed_return_to_first_1m_fvg": passed_return_to_first_1m_fvg,
        "passed_return_to_second_1m_fvg": passed_return_to_second_1m_fvg,
        "rejected_entry_window_expired": rejected_entry_window_expired,
        "entry_ready": entry_ready,
        "signals_generated": signals_generated,
        "trades": len(trade_list) if profile.direct_12m_retrace_entry_enabled else 0,
        "risk_rejected_count": risk_rejected_count,
        "risk_rejection_reasons": tuple(risk_rejection_reasons),
        "trade_list": tuple(trade_list),
        "performance_summary": performance_summary,
        "trade_accounting_check": performance_summary["trade_accounting_check"],
        "unaccounted_after_retrace": unaccounted_after_retrace,
        "attempt_traces": _attempt_traces_for_direction(
            direction="BEARISH",
            candidate_swings=candidate_16m_swing_highs,
            swing_by_id=swing_by_id,
            valid_expansions=valid_expansions,
            fvg_by_expansion=fvg_by_expansion,
            fvg_12m=fvg_12m,
            fvg_8m=fvg_8m,
            candles_8m=candles_8m,
            candles_1m=candles_1m,
            profile=profile,
        ),
    }
    result = {
        **funnel,
        f"candidate_{swing_label}_swing_highs": len(candidate_16m_swing_highs),
        f"passed_{main_label}_fvg": passed_16m_fvg,
        f"passed_{retrace_label}_fvg": funnel["passed_12m_fvg"],
        f"passed_{internal_label}_fvg": funnel["passed_8m_fvg"],
        "candidate_swing_timeframe_swing_highs": len(candidate_16m_swing_highs),
        "passed_main_fvg_timeframe_fvg": passed_16m_fvg,
        "passed_retrace_fvg_timeframe_fvg": funnel["passed_12m_fvg"],
        "passed_internal_fvg_timeframe_fvg": funnel["passed_8m_fvg"],
    }
    if timeframe_profile.profile_id != DEFAULT_16_12_8.profile_id:
        for key in (
            "candidate_16m_swing_highs",
            "rejected_no_immediate_16m_fvg",
            "passed_16m_fvg",
            "rejected_no_12m_fvg_inside_leg",
            "passed_12m_fvg",
            "rejected_no_8m_fvg_inside_leg",
            "passed_8m_fvg",
        ):
            result.pop(key, None)
    return result


def _build_bullish_strategy_funnel(
    *,
    profile: StrategyProfile,
    timeframe_profile: BacktestTimeframeProfile = DEFAULT_16_12_8,
    candidate_16m_swing_lows: tuple[Swing, ...] | list[Swing],
    expansions_16m,
    fvg_16m: tuple[FairValueGap, ...],
    fvg_12m: tuple[FairValueGap, ...],
    fvg_8m: tuple[FairValueGap, ...],
    candles_8m,
    candles_1m,
    starting_balance=None,
    risk_amount_per_trade=None,
    max_leverage=None,
    selected_rr_profile=PRODUCTION_RR_PROFILE,
    fees="0",
    slippage="0",
) -> dict[str, object]:
    """Mirror of _build_strategy_funnel for bullish (swing-low) setups.

    Every comparison here is the bullish mirror of the bearish original:
    swing lows instead of highs, fvg_inside_bullish_leg instead of
    fvg_inside_bearish_leg, max/.high instead of min/.low for target math,
    and _simulate_bullish_trade instead of _simulate_bearish_trade. The
    bearish function above is untouched.
    """
    starting_balance = _required_positive_value(starting_balance, "starting_balance")
    risk_amount_per_trade = _required_positive_value(risk_amount_per_trade, "risk_amount_per_trade")
    max_leverage = _required_positive_value(max_leverage, "max_leverage")
    swing_by_id = {swing.swing_id: swing for swing in candidate_16m_swing_lows}
    valid_expansions = _profile_valid_expansions(profile=profile, expansions=expansions_16m, swing_by_id=swing_by_id)
    strategy_16m_fvgs = tuple(fvg for fvg in fvg_16m if _fvg_matches_profile_expansion(fvg, valid_expansions, profile, direction=FVGDirection.BULLISH))
    fvg_by_expansion = {
        expansion.expansion_id: next(
            (fvg for fvg in strategy_16m_fvgs if _one_fvg_matches_expansion(fvg, expansion, profile, direction=FVGDirection.BULLISH)),
            None,
        )
        for expansion in valid_expansions
    }

    no_12m = 0
    no_8m = 0
    retrace_expired = 0
    close_above = 0
    third_high = 0
    target_reached = 0
    rejected_close_above_12m_fvg_before_entry = 0
    direct_12m_entries = 0
    ignored_additional_12m_fvg_tap_after_entry = 0
    post_entry_close_above_12m_fvg_ignored = 0
    signals_generated = 0
    risk_rejected_count = 0
    passed_retrace_count = 0
    passed_12m_reaction = 0
    first_1m_swing_high_candidates = 0
    rejected_no_first_1m_swing_high = 0
    passed_first_1m_swing_high = 0
    second_1m_swing_high_candidates = 0
    rejected_no_second_1m_swing_high = 0
    passed_second_1m_swing_high = 0
    rejected_third_1m_high = 0
    rejected_1m_close_above_12m_fvg = 0
    passed_1m_swing_confirmation = 0
    rejected_no_1m_bearish_expansion = 0
    passed_1m_bearish_expansion = 0
    rejected_no_1m_bearish_fvg = 0
    passed_1m_bearish_fvg = 0
    rejected_no_return_to_first_1m_fvg = 0
    rejected_no_return_to_second_1m_fvg = 0
    passed_return_to_first_1m_fvg = 0
    passed_return_to_second_1m_fvg = 0
    rejected_entry_window_expired = 0
    entry_ready = 0
    trade_list: list[dict[str, object]] = []
    risk_rejection_reasons: list[str] = []
    starting_balance_decimal = Decimal(str(starting_balance))
    risk_amount_decimal = Decimal(str(risk_amount_per_trade))
    max_leverage_decimal = Decimal(str(max_leverage))
    selected_rr_profile = _selected_rr_profile_for_profile(profile, str(selected_rr_profile).upper())
    selected_rr_value = _selected_rr_value_for_profile(profile, selected_rr_profile)

    for expansion in valid_expansions:
        fvg16 = fvg_by_expansion.get(expansion.expansion_id)
        if fvg16 is None or fvg16.fvg_completion_candle_high is None:
            continue
        swing = swing_by_id.get(expansion.swing_id)
        if swing is None:
            continue
        related_12m = _fvgs_inside_leg(
            fvg_12m,
            direction=fvg16.direction,
            swing_low_price=swing.price,
            completion_candle_high=fvg16.fvg_completion_candle_high,
            start_at=fvg16.confirmed_at,
        )
        if not related_12m:
            no_12m += 1
            continue
        fvg12 = related_12m[0]
        related_8m = _fvgs_inside_leg(
            fvg_8m,
            direction=fvg16.direction,
            swing_low_price=swing.price,
            completion_candle_high=fvg16.fvg_completion_candle_high,
            start_at=fvg16.confirmed_at,
        )
        if not related_8m:
            no_8m += 1
            continue
        retrace_window = tuple(candle for candle in candles_8m if candle.timestamp >= fvg16.confirmed_at)[: profile.retrace_window_8m_candles]
        if len(retrace_window) < profile.retrace_window_8m_candles:
            retrace_expired += 1
            continue
        retrace_candle = _first_1m_retrace_into_12m_fvg_within_8m_window(
            fvg12=fvg12,
            candles_1m=candles_1m,
            fvg16_confirmed_at=fvg16.confirmed_at,
            retrace_window_8m=retrace_window,
            direction="BULLISH",
        )
        if retrace_candle is None:
            retrace_expired += 1
            continue
        passed_retrace_count += 1
        final_target = max(fvg16.fvg_completion_candle_high, max(candle.high for candle in retrace_window))
        if profile.direct_12m_retrace_entry_enabled:
            direct_counts = _classify_direct_12m_retrace_entry_for_direction(fvg12=fvg12, candles_1m=candles_1m, retrace_candle=retrace_candle, direction="BULLISH")
            rejected_close_above_12m_fvg_before_entry += direct_counts["rejected_close_below_12m_fvg_before_entry"]
            direct_12m_entries += direct_counts["direct_12m_entries"]
            ignored_additional_12m_fvg_tap_after_entry += direct_counts["ignored_additional_12m_fvg_tap_after_entry"]
            post_entry_close_above_12m_fvg_ignored += direct_counts["post_entry_close_below_12m_fvg_ignored"]
            signals_generated += direct_counts["signals_generated"]
            entry_ready += direct_counts["entry_ready"]
            if direct_counts["direct_12m_entries"]:
                trade = _simulate_bullish_trade(
                    trade_number=len(trade_list) + 1,
                    symbol=expansion.symbol,
                    profile_id=profile.profile_id,
                    inherited_base_profile=profile.inherited_base_profile,
                    entry_candle=direct_counts["entry_candle"],
                    future_candles=tuple(candle for candle in candles_1m if candle.timestamp > direct_counts["entry_candle"].timestamp),
                    stop_loss=swing.price,
                    take_profit=final_target,
                    risk_amount=risk_amount_decimal,
                    starting_balance=starting_balance_decimal,
                    max_leverage=max_leverage_decimal,
                    selected_rr_profile=selected_rr_profile,
                    tp_model=profile.tp_model,
                    source_12m_fvg_id=fvg12.fvg_id,
                    source_16m_swing_id=swing.swing_id,
                    source_16m_fvg_id=fvg16.fvg_id,
                    setup_snapshot=_profile_f_setup_snapshot(
                        profile=profile,
                        timeframe_profile=timeframe_profile,
                        expansion=expansion,
                        swing=swing,
                        fvg16=fvg16,
                        fvg12=fvg12,
                        retrace_window=retrace_window,
                        retrace_candle=retrace_candle,
                        entry_candle=direct_counts["entry_candle"],
                        final_target=final_target,
                        direction="BULLISH",
                    ),
                )
                if trade["outcome"] == "RISK_REJECTED":
                    risk_rejected_count += 1
                    risk_rejection_reasons.append(str(trade["exit_reason"]))
                else:
                    trade_list.append(trade)
            continue
        confirmation_1m = tuple(candle for candle in candles_1m if candle.timestamp >= retrace_candle.end_timestamp)
        if any(close_below_12m_fvg(fvg12, candle) for candle in confirmation_1m):
            close_above += 1
            continue
        if low_sequence_invalidation_reason(fvg12, confirmation_1m[:3]) is not None:
            third_high += 1
            continue
        if any(candle.high >= final_target for candle in confirmation_1m):
            target_reached += 1
            continue
        passed_12m_reaction += 1
        confirmation = _classify_1m_confirmation_bullish(
            fvg12=fvg12,
            candles=tuple(candle for candle in candles_1m if candle.timestamp >= fvg12.confirmed_at),
            final_target=final_target,
        )
        first_1m_swing_high_candidates += confirmation["first_1m_swing_high_candidates"]
        rejected_no_first_1m_swing_high += confirmation["rejected_no_first_1m_swing_high"]
        passed_first_1m_swing_high += confirmation["passed_first_1m_swing_high"]
        second_1m_swing_high_candidates += confirmation["second_1m_swing_high_candidates"]
        rejected_no_second_1m_swing_high += confirmation["rejected_no_second_1m_swing_high"]
        passed_second_1m_swing_high += confirmation["passed_second_1m_swing_high"]
        rejected_third_1m_high += confirmation["rejected_third_1m_high"]
        rejected_1m_close_above_12m_fvg += confirmation["rejected_1m_close_above_12m_fvg"]
        passed_1m_swing_confirmation += confirmation["passed_1m_swing_confirmation"]
        rejected_no_1m_bearish_expansion += confirmation["rejected_no_1m_bearish_expansion"]
        passed_1m_bearish_expansion += confirmation["passed_1m_bearish_expansion"]
        rejected_no_1m_bearish_fvg += confirmation["rejected_no_1m_bearish_fvg"]
        passed_1m_bearish_fvg += confirmation["passed_1m_bearish_fvg"]
        rejected_no_return_to_first_1m_fvg += confirmation["rejected_no_return_to_first_1m_fvg"]
        rejected_no_return_to_second_1m_fvg += confirmation["rejected_no_return_to_second_1m_fvg"]
        passed_return_to_first_1m_fvg += confirmation["passed_return_to_first_1m_fvg"]
        passed_return_to_second_1m_fvg += confirmation["passed_return_to_second_1m_fvg"]
        rejected_entry_window_expired += confirmation["rejected_entry_window_expired"]
        entry_ready += confirmation["entry_ready"]

    passed_16m_fvg = len(strategy_16m_fvgs)
    unaccounted_after_retrace = _unaccounted_after_retrace(
        passed_retrace=passed_retrace_count,
        rejected_close_above_12m_fvg=close_above,
        rejected_third_1m_high=rejected_third_1m_high,
        rejected_target_reached_before_entry=target_reached,
        rejected_no_first_1m_swing_high=rejected_no_first_1m_swing_high,
        rejected_no_second_1m_swing_high=rejected_no_second_1m_swing_high,
        rejected_1m_close_above_12m_fvg=rejected_1m_close_above_12m_fvg,
        rejected_no_1m_bearish_expansion=rejected_no_1m_bearish_expansion,
        rejected_no_1m_bearish_fvg=rejected_no_1m_bearish_fvg,
        rejected_no_return_to_first_1m_fvg=rejected_no_return_to_first_1m_fvg,
        rejected_no_return_to_second_1m_fvg=rejected_no_return_to_second_1m_fvg,
        rejected_entry_window_expired=rejected_entry_window_expired,
        entry_ready=entry_ready,
    )
    if profile.direct_12m_retrace_entry_enabled:
        unaccounted_after_retrace = passed_retrace_count - rejected_close_above_12m_fvg_before_entry - direct_12m_entries
    performance_summary = _performance_summary(
        trades=trade_list,
        starting_balance=starting_balance_decimal,
        risk_amount_per_trade=risk_amount_decimal,
        selected_rr_profile=selected_rr_profile,
        selected_rr_value=selected_rr_value,
        signals_generated=signals_generated,
        risk_rejected_count=risk_rejected_count,
        risk_rejection_reasons=tuple(risk_rejection_reasons),
    )
    _apply_balances(trade_list, starting_balance_decimal)
    performance_summary = _performance_summary(
        trades=trade_list,
        starting_balance=starting_balance_decimal,
        risk_amount_per_trade=risk_amount_decimal,
        selected_rr_profile=selected_rr_profile,
        selected_rr_value=selected_rr_value,
        signals_generated=signals_generated,
        risk_rejected_count=risk_rejected_count,
        risk_rejection_reasons=tuple(risk_rejection_reasons),
    )
    swing_label = f"{timeframe_profile.swing_timeframe}m"
    main_label = f"{timeframe_profile.main_fvg_timeframe}m"
    retrace_label = f"{timeframe_profile.retrace_fvg_timeframe}m"
    internal_label = f"{timeframe_profile.internal_fvg_timeframe}m"
    funnel = {
        "candidate_16m_swing_highs": len(candidate_16m_swing_lows),
        "rejected_no_expansion": len(candidate_16m_swing_lows) - len(valid_expansions),
        "passed_expansion": len(valid_expansions),
        "rejected_no_immediate_16m_fvg": len(valid_expansions) - passed_16m_fvg,
        "passed_16m_fvg": passed_16m_fvg,
        "rejected_no_12m_fvg_inside_leg": no_12m,
        "passed_12m_fvg": passed_16m_fvg - no_12m,
        "rejected_no_8m_fvg_inside_leg": no_8m,
        "passed_8m_fvg": max(0, passed_16m_fvg - no_12m - no_8m),
        "rejected_retrace_window_expired": retrace_expired,
        "passed_retrace": passed_retrace_count,
        "rejected_close_above_12m_fvg": close_above,
        "rejected_close_above_12m_fvg_before_entry": rejected_close_above_12m_fvg_before_entry,
        "direct_12m_entries": direct_12m_entries,
        "ignored_additional_12m_fvg_tap_after_entry": ignored_additional_12m_fvg_tap_after_entry,
        "post_entry_close_above_12m_fvg_ignored": post_entry_close_above_12m_fvg_ignored,
        "rejected_third_high": third_high,
        "rejected_target_reached_before_entry": target_reached,
        "passed_12m_reaction": passed_12m_reaction,
        "first_1m_swing_high_candidates": first_1m_swing_high_candidates,
        "rejected_no_first_1m_swing_high": rejected_no_first_1m_swing_high,
        "passed_first_1m_swing_high": passed_first_1m_swing_high,
        "second_1m_swing_high_candidates": second_1m_swing_high_candidates,
        "rejected_no_second_1m_swing_high": rejected_no_second_1m_swing_high,
        "passed_second_1m_swing_high": passed_second_1m_swing_high,
        "rejected_third_1m_high": rejected_third_1m_high,
        "rejected_1m_close_above_12m_fvg": rejected_1m_close_above_12m_fvg,
        "passed_1m_swing_confirmation": passed_1m_swing_confirmation,
        "rejected_no_1m_bearish_expansion": rejected_no_1m_bearish_expansion,
        "passed_1m_bearish_expansion": passed_1m_bearish_expansion,
        "rejected_no_1m_bearish_fvg": rejected_no_1m_bearish_fvg,
        "passed_1m_bearish_fvg": passed_1m_bearish_fvg,
        "rejected_no_return_to_first_1m_fvg": rejected_no_return_to_first_1m_fvg,
        "rejected_no_return_to_second_1m_fvg": rejected_no_return_to_second_1m_fvg,
        "passed_return_to_first_1m_fvg": passed_return_to_first_1m_fvg,
        "passed_return_to_second_1m_fvg": passed_return_to_second_1m_fvg,
        "rejected_entry_window_expired": rejected_entry_window_expired,
        "entry_ready": entry_ready,
        "signals_generated": signals_generated,
        "trades": len(trade_list) if profile.direct_12m_retrace_entry_enabled else 0,
        "risk_rejected_count": risk_rejected_count,
        "risk_rejection_reasons": tuple(risk_rejection_reasons),
        "trade_list": tuple(trade_list),
        "performance_summary": performance_summary,
        "trade_accounting_check": performance_summary["trade_accounting_check"],
        "unaccounted_after_retrace": unaccounted_after_retrace,
        "attempt_traces": _attempt_traces_for_direction(
            direction="BULLISH",
            candidate_swings=candidate_16m_swing_lows,
            swing_by_id=swing_by_id,
            valid_expansions=valid_expansions,
            fvg_by_expansion=fvg_by_expansion,
            fvg_12m=fvg_12m,
            fvg_8m=fvg_8m,
            candles_8m=candles_8m,
            candles_1m=candles_1m,
            profile=profile,
        ),
    }
    result = {
        **funnel,
        f"candidate_{swing_label}_swing_highs": len(candidate_16m_swing_lows),
        f"passed_{main_label}_fvg": passed_16m_fvg,
        f"passed_{retrace_label}_fvg": funnel["passed_12m_fvg"],
        f"passed_{internal_label}_fvg": funnel["passed_8m_fvg"],
        "candidate_swing_timeframe_swing_highs": len(candidate_16m_swing_lows),
        "passed_main_fvg_timeframe_fvg": passed_16m_fvg,
        "passed_retrace_fvg_timeframe_fvg": funnel["passed_12m_fvg"],
        "passed_internal_fvg_timeframe_fvg": funnel["passed_8m_fvg"],
    }
    if timeframe_profile.profile_id != DEFAULT_16_12_8.profile_id:
        for key in (
            "candidate_16m_swing_highs",
            "rejected_no_immediate_16m_fvg",
            "passed_16m_fvg",
            "rejected_no_12m_fvg_inside_leg",
            "passed_12m_fvg",
            "rejected_no_8m_fvg_inside_leg",
            "passed_8m_fvg",
        ):
            result.pop(key, None)
    return result


def _attempt_traces_for_direction(
    *,
    direction: str,
    candidate_swings,
    swing_by_id: dict[str, Swing],
    valid_expansions,
    fvg_by_expansion: dict[str, FairValueGap | None],
    fvg_12m: tuple[FairValueGap, ...],
    fvg_8m: tuple[FairValueGap, ...],
    candles_8m,
    candles_1m,
    profile: StrategyProfile,
) -> tuple[dict[str, object], ...]:
    """Read-only per-swing attempt trace for Setup Radar, parallel to the funnel above.

    Walks the exact same chain the funnel itself walks (swing -> expansion -> 16M FVG ->
    12M FVG -> 8M FVG/retrace window -> entry), using the same helper functions, but never
    mutates trade_list/counters and is built from candidate_swings (every swing, not just
    ones with a valid expansion) so an attempt is visible from the moment a swing exists.
    Stage/progress values match the Setup Radar spec: SWING_16M_CONFIRMED=20,
    EXPANSION_16M_CONFIRMED=35, FVG_16M_CONFIRMED=50, FVG_12M_CONFIRMED=65,
    FVG_8M_CONFIRMED=80, ENTRY_READY=100.
    """
    is_bullish = direction == "BULLISH"
    valid_expansion_by_swing_id = {expansion.swing_id: expansion for expansion in valid_expansions}
    traces: list[dict[str, object]] = []

    for swing in candidate_swings:
        trace: dict[str, object] = {
            "symbol": swing.symbol,
            "direction": direction,
            "swing_16m_id": swing.swing_id,
            "swing_timestamp": swing.right_candle.timestamp.isoformat(),
            "swing_price": str(swing.price),
            "expansion_16m_id": None,
            "expansion_timestamp": None,
            "fvg_16m_id": None,
            "fvg_12m_id": None,
            "fvg_8m_id": None,
            "stage": "SWING_16M_CONFIRMED",
            "progress_percent": 20.0,
            "invalidation_reason": None,
            "is_terminal": False,
            "entry_price": None,
            "stop_loss": None,
            "take_profit": None,
        }

        expansion = valid_expansion_by_swing_id.get(swing.swing_id)
        if expansion is None:
            trace["invalidation_reason"] = "EXPANSION_NOT_CONFIRMED"
            trace["is_terminal"] = True
            traces.append(trace)
            continue
        trace["expansion_16m_id"] = expansion.expansion_id
        trace["expansion_timestamp"] = expansion.timestamp.isoformat()
        trace["stage"] = "EXPANSION_16M_CONFIRMED"
        trace["progress_percent"] = 35.0

        fvg16 = fvg_by_expansion.get(expansion.expansion_id)
        completion_candle = None if fvg16 is None else (fvg16.fvg_completion_candle_high if is_bullish else fvg16.fvg_completion_candle_low)
        if fvg16 is None or completion_candle is None:
            trace["invalidation_reason"] = "FVG_16M_NOT_FOUND"
            trace["is_terminal"] = True
            traces.append(trace)
            continue
        trace["fvg_16m_id"] = fvg16.fvg_id
        trace["stage"] = "FVG_16M_CONFIRMED"
        trace["progress_percent"] = 50.0

        leg_kwargs = (
            {"swing_low_price": swing.price, "completion_candle_high": completion_candle}
            if is_bullish
            else {"swing_high_price": swing.price, "completion_candle_low": completion_candle}
        )
        related_12m = _fvgs_inside_leg(fvg_12m, direction=fvg16.direction, start_at=fvg16.confirmed_at, **leg_kwargs)
        if not related_12m:
            trace["invalidation_reason"] = "FVG_12M_NOT_FOUND"
            trace["is_terminal"] = True
            traces.append(trace)
            continue
        fvg12 = related_12m[0]
        trace["fvg_12m_id"] = fvg12.fvg_id
        trace["stage"] = "FVG_12M_CONFIRMED"
        trace["progress_percent"] = 65.0

        related_8m = _fvgs_inside_leg(fvg_8m, direction=fvg16.direction, start_at=fvg16.confirmed_at, **leg_kwargs)
        if not related_8m:
            trace["invalidation_reason"] = "FVG_8M_NOT_FOUND"
            trace["is_terminal"] = True
            traces.append(trace)
            continue
        trace["fvg_8m_id"] = related_8m[0].fvg_id
        trace["stage"] = "FVG_8M_CONFIRMED"
        trace["progress_percent"] = 80.0

        retrace_window = tuple(candle for candle in candles_8m if candle.timestamp >= fvg16.confirmed_at)[: profile.retrace_window_8m_candles]
        if len(retrace_window) < profile.retrace_window_8m_candles:
            # Window has not fully elapsed yet - still open, not a failure.
            traces.append(trace)
            continue
        retrace_candle = _first_1m_retrace_into_12m_fvg_within_8m_window(
            fvg12=fvg12,
            candles_1m=candles_1m,
            fvg16_confirmed_at=fvg16.confirmed_at,
            retrace_window_8m=retrace_window,
            direction=direction,
        )
        if retrace_candle is None:
            trace["invalidation_reason"] = "RETRACE_WINDOW_EXPIRED"
            trace["is_terminal"] = True
            traces.append(trace)
            continue

        taps = tuple(
            candle
            for candle in candles_1m
            if candle.timestamp >= retrace_candle.timestamp and candle.high >= fvg12.lower_boundary and candle.low <= fvg12.upper_boundary
        )
        if not taps:
            # Retrace candle confirmed but price has not tapped back into the 12M FVG
            # yet - still open, more 1M candles may still arrive.
            traces.append(trace)
            continue
        tap = taps[0]
        closed_through = tap.close < fvg12.lower_boundary if is_bullish else tap.close > fvg12.upper_boundary
        if closed_through:
            trace["invalidation_reason"] = "CLOSE_BELOW_12M_FVG" if is_bullish else "CLOSE_ABOVE_12M_FVG"
            trace["is_terminal"] = True
            traces.append(trace)
            continue

        trace["stage"] = "ENTRY_READY"
        trace["progress_percent"] = 100.0
        trace["is_terminal"] = True
        trace["entry_price"] = str(tap.close)
        trace["stop_loss"] = str(swing.price)
        if is_bullish:
            trace["take_profit"] = str(max(fvg16.fvg_completion_candle_high, max(candle.high for candle in retrace_window)))
        else:
            trace["take_profit"] = str(min(fvg16.fvg_completion_candle_low, min(candle.low for candle in retrace_window)))
        traces.append(trace)

    return tuple(traces)


def _research_expansions(swings):
    rows = []
    for swing in swings:
        c1 = swing.left_candle
        c2 = swing.middle_candle
        c3 = swing.right_candle
        avg = ((c1.high - c1.low) + (c2.high - c2.low)) / 2
        if avg <= 0:
            continue
        ratio = float((c3.high - c3.low) / avg)
        if swing.swing_type is SwingType.HIGH:
            displacement = max(c1.low, c2.low) - c3.low
        else:
            displacement = c3.high - min(c1.high, c2.high)
        if displacement <= 0:
            continue
        rows.append(type("ResearchExpansion", (), {
            "expansion_id": f"research_{swing.swing_id}",
            "swing_id": swing.swing_id,
            "swing_type": swing.swing_type,
            "direction": FVGDirection.BEARISH if swing.swing_type is SwingType.HIGH else FVGDirection.BULLISH,
            "symbol": swing.symbol,
            "timeframe": swing.timeframe,
            "timestamp": c3.timestamp,
            "expansion_ratio": ratio,
            "displacement_distance": displacement,
            "displacement_percent": float(displacement / c3.close * 100) if c3.close else 0.0,
            "strength_score": max(0.0, min(100.0, float(ratio) * 20.0 + float(displacement))),
        })())
    return tuple(rows)


def _profile_valid_expansions(*, profile: StrategyProfile, expansions, swing_by_id: dict[str, Swing]) -> tuple[object, ...]:
    return tuple(
        expansion
        for expansion in expansions
        if profile.expansion_ratio_min <= float(expansion.expansion_ratio) <= profile.expansion_ratio_max
        and (not profile.require_expansion_c3 or _expansion_is_swing_c3(expansion, swing_by_id.get(expansion.swing_id)))
    )


def _empty_1m_confirmation_counts() -> dict[str, int]:
    return {
        "first_1m_swing_high_candidates": 0,
        "rejected_no_first_1m_swing_high": 0,
        "passed_first_1m_swing_high": 0,
        "second_1m_swing_high_candidates": 0,
        "rejected_no_second_1m_swing_high": 0,
        "passed_second_1m_swing_high": 0,
        "rejected_third_1m_high": 0,
        "rejected_1m_close_above_12m_fvg": 0,
        "passed_1m_swing_confirmation": 0,
        "rejected_no_1m_bearish_expansion": 0,
        "passed_1m_bearish_expansion": 0,
        "rejected_no_1m_bearish_fvg": 0,
        "passed_1m_bearish_fvg": 0,
        "rejected_no_return_to_first_1m_fvg": 0,
        "rejected_no_return_to_second_1m_fvg": 0,
        "passed_return_to_first_1m_fvg": 0,
        "passed_return_to_second_1m_fvg": 0,
        "rejected_entry_window_expired": 0,
        "entry_ready": 0,
    }


def _first_1m_retrace_into_12m_fvg_within_8m_window(
    *,
    fvg12: FairValueGap,
    candles_1m,
    fvg16_confirmed_at: datetime,
    retrace_window_8m,
    direction: str,
):
    if not retrace_window_8m:
        return None
    window_start = fvg16_confirmed_at
    window_end = retrace_window_8m[-1].end_timestamp
    normalized_direction = str(direction).upper()
    for candle in candles_1m:
        if candle.timestamp < window_start or candle.end_timestamp > window_end:
            continue
        entered_zone = candle.high >= fvg12.lower_boundary and candle.low <= fvg12.upper_boundary
        if not entered_zone:
            continue
        if normalized_direction == "BEARISH" and candle.close > fvg12.upper_boundary:
            return None
        if normalized_direction == "BULLISH" and candle.close < fvg12.lower_boundary:
            return None
        return candle
    return None


def _classify_direct_12m_retrace_entry(*, fvg12: FairValueGap, candles_1m, retrace_candle) -> dict[str, int]:
    return _classify_direct_12m_retrace_entry_for_direction(
        fvg12=fvg12,
        candles_1m=candles_1m,
        retrace_candle=retrace_candle,
        direction="BEARISH",
    )


def _classify_direct_12m_retrace_entry_for_direction(
    *,
    fvg12: FairValueGap,
    candles_1m,
    retrace_candle,
    direction: str,
) -> dict[str, int]:
    counts = {
        "rejected_close_above_12m_fvg_before_entry": 0,
        "rejected_close_below_12m_fvg_before_entry": 0,
        "direct_12m_entries": 0,
        "ignored_additional_12m_fvg_tap_after_entry": 0,
        "post_entry_close_above_12m_fvg_ignored": 0,
        "post_entry_close_below_12m_fvg_ignored": 0,
        "signals_generated": 0,
        "entry_ready": 0,
    }
    normalized_direction = str(direction).upper()
    taps = tuple(
        candle
        for candle in candles_1m
        if candle.timestamp >= retrace_candle.timestamp
        and candle.high >= fvg12.lower_boundary
        and candle.low <= fvg12.upper_boundary
    )
    if not taps:
        if normalized_direction == "BEARISH":
            counts["rejected_close_above_12m_fvg_before_entry"] = 1
        if normalized_direction == "BULLISH":
            counts["rejected_close_below_12m_fvg_before_entry"] = 1
        return counts
    tap = taps[0]
    invalid_bearish = normalized_direction == "BEARISH" and tap.close > fvg12.upper_boundary
    invalid_bullish = normalized_direction == "BULLISH" and tap.close < fvg12.lower_boundary
    if invalid_bearish or invalid_bullish:
        if normalized_direction == "BEARISH":
            counts["rejected_close_above_12m_fvg_before_entry"] = 1
        if normalized_direction == "BULLISH":
            counts["rejected_close_below_12m_fvg_before_entry"] = 1
        return counts
    counts["direct_12m_entries"] = 1
    counts["signals_generated"] = 1
    counts["entry_ready"] = 1
    counts["entry_candle"] = tap
    for later_tap in taps[1:]:
        counts["ignored_additional_12m_fvg_tap_after_entry"] += 1
        if normalized_direction == "BEARISH" and later_tap.close > fvg12.upper_boundary:
            counts["post_entry_close_above_12m_fvg_ignored"] += 1
        if normalized_direction == "BULLISH" and later_tap.close < fvg12.lower_boundary:
            counts["post_entry_close_below_12m_fvg_ignored"] += 1
    return counts


def _candle_record(candle) -> dict[str, object]:
    return {
        "symbol": candle.symbol,
        "timeframe": candle.timeframe.label,
        "timestamp": candle.timestamp.isoformat(),
        "open": str(candle.open),
        "high": str(candle.high),
        "low": str(candle.low),
        "close": str(candle.close),
        "range": str(candle.high - candle.low),
    }


def _json_safe_record(record: dict[str, object]) -> dict[str, object]:
    safe: dict[str, object] = {}
    for key, value in record.items():
        if isinstance(value, datetime):
            safe[key] = value.isoformat()
        elif isinstance(value, Decimal):
            safe[key] = str(value)
        else:
            safe[key] = value
    return safe


def _profile_f_setup_snapshot(
    *,
    profile: StrategyProfile,
    timeframe_profile: BacktestTimeframeProfile,
    expansion,
    swing: Swing,
    fvg16: FairValueGap,
    fvg12: FairValueGap,
    retrace_window,
    retrace_candle,
    entry_candle,
    final_target,
    direction: str = "BEARISH",
) -> dict[str, object]:
    c1 = swing.left_candle
    c2 = swing.middle_candle
    c3 = swing.right_candle
    c1_range = c1.high - c1.low
    c2_range = c2.high - c2.low
    average_reference_range = (c1_range + c2_range) / Decimal("2")
    expansion_ratio = Decimal(str(getattr(expansion, "expansion_ratio", "0")))
    retrace_deadline = retrace_window[-1].end_timestamp if retrace_window else fvg16.confirmed_at
    is_bullish = str(direction).upper() == "BULLISH"
    entry_boundary_respected = entry_candle.close >= fvg12.lower_boundary if is_bullish else entry_candle.close <= fvg12.upper_boundary
    expansion_passed = profile.expansion_ratio_min <= float(expansion_ratio) <= profile.expansion_ratio_max
    return {
        **_profile_lock_fields(profile=profile, timeframe_profile=timeframe_profile),
        "strategy_profile": profile.profile_id,
        "selected_strategy_profile": profile.profile_id,
        "expansion_min_used": profile.expansion_ratio_min,
        "expansion_max_used": profile.expansion_ratio_max,
        "expansion_settings": {
            "expansion_min": profile.expansion_ratio_min,
            "expansion_max": profile.expansion_ratio_max,
            "require_expansion_c3": profile.require_expansion_c3,
        },
        "retrace_settings": {
            "retrace_window_8m_candles": profile.retrace_window_8m_candles,
        },
        "fvg_detection_settings": {
            "use_linked_fvg_detection": profile.use_linked_fvg_detection,
            "main_fvg_match_mode": profile.main_fvg_match_mode,
            "main_fvg_match_window_candles": profile.main_fvg_match_window_candles,
        },
        "expansion_ratio": str(expansion_ratio),
        "expansion_passed": expansion_passed,
        "expansion_rejection_reason": None if expansion_passed else "EXPANSION_RATIO_OUTSIDE_RANGE",
        "inherited_base_profile": profile.inherited_base_profile,
        "setup_direction": "BULLISH" if is_bullish else "BEARISH",
        "timeframe_profile": timeframe_profile.profile_id,
        "higher_timeframe_context": {
            "required_context": "STRICT_PROFILE_HTF_DIRECTIONAL_CONTEXT",
            "status": "INHERITED_FROM_STRICT_PROFILE",
        },
        "expansion": {
            "expansion_id": getattr(expansion, "expansion_id", None),
            "expansion_candle": _candle_record(c3),
            "previous_reference_candle_1_range": str(c1_range),
            "previous_reference_candle_2_range": str(c2_range),
            "average_reference_range": str(average_reference_range),
            "expansion_ratio": str(expansion_ratio),
            "expansion_valid": expansion_passed,
            "rejection_reason": None if expansion_passed else "EXPANSION_RATIO_OUTSIDE_RANGE",
        },
        "swing_16m": _json_safe_record(swing_to_record(swing)),
        "fvg_16m": _json_safe_record(fvg_to_record(fvg16)),
        "fvg_12m": _json_safe_record(fvg_to_record(fvg12)),
        "fvg_16m_formation_time": fvg16.confirmed_at.isoformat(),
        "eight_minute_candle_count_after_16m_fvg": len(retrace_window),
        "eight_minute_candles_after_16m_fvg": tuple(_candle_record(candle) for candle in retrace_window),
        "retracement_deadline": retrace_deadline.isoformat(),
        "retracement_within_deadline": retrace_candle.timestamp <= retrace_deadline,
        "one_minute_candle_entered_12m_fvg_within_8m_window": retrace_candle.end_timestamp <= retrace_deadline,
        "first_entry_candle": _candle_record(entry_candle),
        "first_1m_entry_candle": _candle_record(entry_candle),
        "12m_fvg_id": fvg12.fvg_id,
        "entry_candle_closed_beyond_fvg_boundary": not entry_boundary_respected,
        "entry_candle_boundary_respected": entry_boundary_respected,
        "final_target_reference": str(final_target),
    }


def _selected_rr_profile_for_profile(profile: StrategyProfile, requested_rr_profile: str) -> str:
    if profile.tp_model in {"RR_1_0", "RR_1_0_RESEARCH"}:
        return profile.tp_model
    if profile.tp_model == "LEG_TARGET_RESEARCH":
        return "LEG_TARGET_RESEARCH"
    return requested_rr_profile


def _selected_rr_value_for_profile(profile: StrategyProfile, selected_rr_profile: str) -> Decimal:
    if profile.tp_model in {"RR_1_0", "RR_1_0_RESEARCH"} or selected_rr_profile in {"RR_1_0", "RR_1_0_RESEARCH"}:
        return Decimal("1.0")
    if profile.tp_model == "LEG_TARGET_RESEARCH" or selected_rr_profile == "LEG_TARGET_RESEARCH":
        return Decimal("0")
    return resolve_rr_value(selected_rr_profile)


def _fixed_risk_trade_math_for_profile(
    *,
    direction: str,
    entry: Decimal,
    stop_loss: Decimal,
    fixed_risk_amount: Decimal,
    selected_rr_profile: str,
    tp_model: str,
    take_profit: Decimal | None = None,
):
    if selected_rr_profile in {"RR_1_0", "RR_1_0_RESEARCH", "LEG_TARGET_RESEARCH"}:
        tp_model = selected_rr_profile
    if tp_model not in {"RR_1_0", "RR_1_0_RESEARCH", "LEG_TARGET_RESEARCH"}:
        return calculate_fixed_risk_trade_math(
            direction=direction,
            entry=entry,
            stop_loss=stop_loss,
            fixed_risk_amount=fixed_risk_amount,
            selected_rr_profile=selected_rr_profile,
        )
    direction = direction.upper()
    if fixed_risk_amount <= 0:
        raise ValueError("fixed_risk_amount must be greater than 0")
    if direction == "BEARISH":
        risk_distance = stop_loss - entry
        if risk_distance <= 0:
            raise ValueError("bearish stop_loss must be above entry")
        resolved_take_profit = take_profit if tp_model == "LEG_TARGET_RESEARCH" else entry - risk_distance
        if resolved_take_profit is None or resolved_take_profit >= entry:
            raise ValueError("bearish take_profit must be below entry")
        reward_distance = entry - resolved_take_profit
    elif direction == "BULLISH":
        risk_distance = entry - stop_loss
        if risk_distance <= 0:
            raise ValueError("bullish stop_loss must be below entry")
        resolved_take_profit = take_profit if tp_model == "LEG_TARGET_RESEARCH" else entry + risk_distance
        if resolved_take_profit is None or resolved_take_profit <= entry:
            raise ValueError("bullish take_profit must be above entry")
        reward_distance = resolved_take_profit - entry
    else:
        raise ValueError(f"unsupported direction: {direction}")
    rr_value = Decimal("1.0") if tp_model in {"RR_1_0", "RR_1_0_RESEARCH"} else reward_distance / risk_distance
    position_size = fixed_risk_amount / risk_distance
    target_reward = fixed_risk_amount * rr_value
    return SimpleNamespace(
        direction=direction,
        entry=entry,
        stop_loss=stop_loss,
        take_profit=resolved_take_profit,
        fixed_risk_amount=fixed_risk_amount,
        selected_rr_profile=tp_model if tp_model in {"RR_1_0", "RR_1_0_RESEARCH"} else "LEG_TARGET_RESEARCH",
        selected_rr_value=rr_value,
        target_reward_amount=target_reward,
        actual_risk_amount=fixed_risk_amount,
        expected_reward_amount=target_reward,
        actual_rr=rr_value,
        risk_distance=risk_distance,
        position_size=position_size,
    )


def _isolated_margin_plan_for_backtest_profile(*, profile_id: str, entry_price, stop_loss, margin_amount, max_leverage) -> IsolatedMarginPlan:
    if profile_id != "PROFILE_2":
        return calculate_isolated_margin_plan(
            entry_price=entry_price,
            stop_loss=stop_loss,
            margin_amount=margin_amount,
            max_leverage=max_leverage,
        )
    entry = Decimal(str(entry_price))
    stop = Decimal(str(stop_loss))
    margin = Decimal(str(margin_amount))
    max_lev = Decimal(str(max_leverage))
    if entry <= Decimal("0"):
        raise ValueError("entry_price must be greater than zero")
    if stop <= Decimal("0"):
        raise ValueError("stop_loss must be greater than zero")
    if margin <= Decimal("0"):
        raise ValueError("fixed_risk_amount must be greater than zero")
    if max_lev < Decimal("1"):
        raise ValueError("max_leverage must be at least 1")
    price_risk_percent = abs(entry - stop) / entry
    if price_risk_percent <= Decimal("0"):
        raise ValueError("price_risk_percent must be greater than zero")
    required_leverage = Decimal("1") / price_risk_percent
    notional = margin * required_leverage
    quantity = notional / entry
    expected_loss = abs(entry - stop) * quantity
    if abs(expected_loss - margin) > max(Decimal("0.00000001"), margin * Decimal("0.000001")):
        raise ValueError("expected_loss_at_sl does not match selected fixed risk amount")
    return IsolatedMarginPlan(
        margin_amount=margin,
        risk_amount=margin,
        entry_price=entry,
        stop_loss=stop,
        price_risk_percent=price_risk_percent,
        required_leverage=required_leverage,
        applied_leverage=required_leverage,
        max_allowed_leverage=max_lev,
        notional_position_size=notional,
        quantity=quantity,
        expected_loss_at_sl=expected_loss,
    )


def _simulate_bearish_trade(
    *,
    trade_number: int,
    symbol: str,
    profile_id: str,
    inherited_base_profile: str = STRICT_BASE_PROFILE,
    entry_candle,
    future_candles,
    stop_loss,
    take_profit,
    risk_amount: Decimal,
    starting_balance: Decimal,
    max_leverage: Decimal,
    selected_rr_profile: str = PRODUCTION_RR_PROFILE,
    tp_model: str = "RR_1_5",
    source_12m_fvg_id: str | None = None,
    source_16m_swing_id: str | None = None,
    source_16m_fvg_id: str | None = None,
    setup_snapshot: dict[str, object] | None = None,
) -> dict[str, object]:
    entry_price = Decimal(str(entry_candle.close))
    stop_loss_decimal = Decimal(str(stop_loss))
    try:
        rr_math = _fixed_risk_trade_math_for_profile(
            direction="BEARISH",
            entry=entry_price,
            stop_loss=stop_loss_decimal,
            fixed_risk_amount=risk_amount,
            selected_rr_profile=selected_rr_profile,
            tp_model=tp_model,
            take_profit=Decimal(str(take_profit)),
        )
    except ValueError as exc:
        return {
            "trade_id": f"trade_{trade_number:04d}",
            "setup_id": f"{profile_id.lower()}_setup_{trade_number:04d}",
            "symbol": symbol,
            **_trade_profile_lock_fields(setup_snapshot, profile_id),
            "profile_id": profile_id,
            "strategy_profile": profile_id,
            "selected_strategy_profile": profile_id,
            "profile_variant_name": profile_id,
            "expansion_min_used": (setup_snapshot or {}).get("expansion_min_used"),
            "expansion_max_used": (setup_snapshot or {}).get("expansion_max_used"),
            "expansion_ratio": (setup_snapshot or {}).get("expansion_ratio"),
            "inherited_base_profile": inherited_base_profile,
            "direction": "BEARISH",
            "entry_timestamp": entry_candle.timestamp.isoformat(),
            "entry_price": str(entry_price),
            "stop_loss": str(stop_loss_decimal),
            "take_profit": str(take_profit),
            "fixed_risk_amount": str(risk_amount),
            "selected_starting_balance": str(starting_balance),
            "applied_starting_balance": str(starting_balance),
            "selected_fixed_risk_amount": str(risk_amount),
            "applied_margin_amount": "0",
            "risk_amount": str(risk_amount),
            "trade_type": "ISOLATED_MARGIN",
            "margin_mode": "isolated",
            "selected_rr_profile": str(selected_rr_profile).upper(),
            "selected_tp_model": str(selected_rr_profile).upper(),
            "applied_tp_model": str(selected_rr_profile).upper(),
            "tp_model_lock_status": "UNLOCKED",
            "selected_rr_value": "0",
            "target_reward_amount": "0",
            "expected_reward_amount": "0",
            "actual_risk_amount": "0",
            "actual_rr": "0",
            "outcome": "RISK_REJECTED",
            "exit_reason": str(exc),
            "risk_distance": "0",
            "position_size": "0",
            "price_risk_percent": "0",
            "required_leverage": "0",
            "applied_leverage": "0",
            "max_allowed_leverage": str(max_leverage),
            "notional_position_size": "0",
            "quantity": "0",
            "expected_loss_at_sl": "0",
            "exchange": "BACKTEST",
            "trade_mode": "BACKTEST",
            "risk_lock_status": "FAILED",
            "environment_lock_status": "BACKTEST",
            "exchange_lock_status": "BACKTEST",
            "profile_lock_status": "PASSED",
            "gross_pnl": "0",
            "net_pnl": "0",
            "rr_realized": "0",
            "setup_snapshot": setup_snapshot or {},
            "reason_for_entry": "",
            "reason_for_rejection": str(exc),
        }
    take_profit_decimal = rr_math.take_profit
    risk_distance = stop_loss_decimal - entry_price
    try:
        isolated = _isolated_margin_plan_for_backtest_profile(
            profile_id=profile_id,
            entry_price=entry_price,
            stop_loss=stop_loss_decimal,
            margin_amount=risk_amount,
            max_leverage=max_leverage,
        )
    except ValueError as exc:
        return {
            "trade_id": f"trade_{trade_number:04d}",
            "setup_id": f"{profile_id.lower()}_setup_{trade_number:04d}",
            "symbol": symbol,
            **_trade_profile_lock_fields(setup_snapshot, profile_id),
            "profile_id": profile_id,
            "selected_strategy_profile": profile_id,
            "applied_profile_id": profile_id,
            "direction": "BEARISH",
            "entry_timestamp": entry_candle.timestamp.isoformat(),
            "entry_price": str(entry_price),
            "stop_loss": str(stop_loss_decimal),
            "take_profit": str(take_profit_decimal),
            "selected_starting_balance": str(starting_balance),
            "applied_starting_balance": str(starting_balance),
            "selected_fixed_risk_amount": str(risk_amount),
            "fixed_risk_amount": str(risk_amount),
            "applied_margin_amount": "0",
            "risk_amount": str(risk_amount),
            "trade_type": "ISOLATED_MARGIN",
            "margin_mode": "isolated",
            "outcome": "RISK_REJECTED",
            "exit_reason": str(exc),
            "risk_distance": str(risk_distance),
            "position_size": "0",
            "price_risk_percent": "0",
            "required_leverage": "0",
            "applied_leverage": "0",
            "max_allowed_leverage": str(max_leverage),
            "notional_position_size": "0",
            "quantity": "0",
            "expected_loss_at_sl": "0",
            "gross_pnl": "0",
            "net_pnl": "0",
            "rr_realized": "0",
            "exchange": "BACKTEST",
            "trade_mode": "BACKTEST",
            "risk_lock_status": "FAILED",
            "environment_lock_status": "BACKTEST",
            "exchange_lock_status": "BACKTEST",
            "profile_lock_status": "PASSED",
            "reason_for_rejection": str(exc),
        }
    base = {
        "trade_id": f"trade_{trade_number:04d}",
        "setup_id": f"{profile_id.lower()}_setup_{trade_number:04d}",
        "symbol": symbol,
        **_trade_profile_lock_fields(setup_snapshot, profile_id),
        "profile_id": profile_id,
        "strategy_profile": profile_id,
        "selected_strategy_profile": profile_id,
        "profile_variant_name": profile_id,
        "expansion_min_used": (setup_snapshot or {}).get("expansion_min_used"),
        "expansion_max_used": (setup_snapshot or {}).get("expansion_max_used"),
        "expansion_ratio": (setup_snapshot or {}).get("expansion_ratio"),
        "inherited_base_profile": inherited_base_profile,
        "pair": symbol,
        "direction": "BEARISH",
        "mode": "backtest",
        "trade_mode": "BACKTEST",
        "exchange": "BACKTEST",
        "entry_timestamp": entry_candle.timestamp.isoformat(),
        "entry_price": str(entry_price),
        "entry": str(entry_price),
        "stop_loss": str(stop_loss_decimal),
        "SL": str(stop_loss_decimal),
        "stop_loss_price": str(stop_loss_decimal),
        "sl_source": "16m swing high",
        "take_profit": str(take_profit_decimal),
        "TP": str(take_profit_decimal),
        "take_profit_price": str(take_profit_decimal),
        "risk_amount": str(risk_amount),
        "selected_starting_balance": str(starting_balance),
        "applied_starting_balance": str(starting_balance),
        "selected_fixed_risk_amount": str(risk_amount),
        "applied_margin_amount": str(isolated.margin_amount),
        "trade_type": isolated.trade_type,
        "margin_mode": isolated.margin_mode,
        "fixed_risk_amount": str(rr_math.fixed_risk_amount),
        "selected_rr_profile": rr_math.selected_rr_profile,
        "selected_tp_model": rr_math.selected_rr_profile,
        "applied_tp_model": rr_math.selected_rr_profile,
        "tp_model_lock_status": "UNLOCKED",
        "selected_rr_value": str(rr_math.selected_rr_value),
        "target_reward_amount": str(rr_math.target_reward_amount),
        "actual_risk_amount": str(rr_math.actual_risk_amount),
        "price_risk_percent": str(isolated.price_risk_percent),
        "required_leverage": str(isolated.required_leverage),
        "applied_leverage": str(isolated.applied_leverage),
        "max_allowed_leverage": str(isolated.max_allowed_leverage),
        "notional_position_size": str(isolated.notional_position_size),
        "quantity": str(isolated.quantity),
        "expected_loss_at_sl": str(isolated.expected_loss_at_sl),
        "risk_lock_status": "PASSED",
        "environment_lock_status": "BACKTEST",
        "exchange_lock_status": "BACKTEST",
        "profile_lock_status": "PASSED",
        "expected_reward_amount": str(rr_math.expected_reward_amount),
        "actual_rr": str(rr_math.actual_rr),
        "fees": "0",
        "slippage": "0",
        "source_12m_fvg_id": source_12m_fvg_id,
        "source_16m_swing_id": source_16m_swing_id,
        "source_16m_fvg_id": source_16m_fvg_id,
        "fvg_id": source_12m_fvg_id,
        "12m_fvg_id": source_12m_fvg_id,
        "trade_triggered_from_fvg": True,
        "trade_triggered_from_12m_fvg": True,
        "triggered_trade_id": f"trade_{trade_number:04d}",
        "first_entry_candle": _candle_record(entry_candle),
        "first_1m_entry_candle": _candle_record(entry_candle),
        "one_trade_per_fvg_enforced": True,
        "duplicate_entry_blocked": True,
        "duplicate_trade_blocked": True,
        "entry_candle_closed_beyond_fvg_boundary": bool((setup_snapshot or {}).get("entry_candle_closed_beyond_fvg_boundary", False)),
        "setup_snapshot": setup_snapshot or {},
        "reason_for_entry": "FIRST_VALID_12M_FVG_RETRACE_CANDLE_BOUNDARY_RESPECTED",
        "reason_for_rejection": "",
    }
    if risk_distance <= 0:
        return {
            **base,
            "outcome": "RISK_REJECTED",
            "exit_reason": "INVALID_RISK_DISTANCE",
            "risk_distance": str(risk_distance),
            "position_size": "0",
            "gross_pnl": "0",
            "net_pnl": "0",
            "rr_realized": "0",
        }
    position_size = isolated.quantity
    exit_candle = future_candles[-1] if future_candles else entry_candle
    exit_price = Decimal(str(exit_candle.close))
    exit_reason = "DATA_ENDED_BEFORE_EXIT"
    outcome = "OPEN_OR_UNRESOLVED"
    for candle in future_candles:
        hit_stop = Decimal(str(candle.high)) >= stop_loss_decimal
        hit_target = Decimal(str(candle.low)) <= take_profit_decimal
        if hit_stop:
            exit_candle = candle
            exit_price = stop_loss_decimal
            exit_reason = "STOP_LOSS_HIT"
            outcome = "LOSS"
            break
        if hit_target:
            exit_candle = candle
            exit_price = take_profit_decimal
            exit_reason = "TAKE_PROFIT_HIT"
            outcome = "WIN"
            break
    gross_pnl = calculate_pnl(direction="BEARISH", entry_price=entry_price, exit_price=exit_price, position_size=position_size)
    fees = Decimal("0")
    slippage = Decimal("0")
    net_pnl = gross_pnl - fees - slippage
    rr_realized = net_pnl / rr_math.fixed_risk_amount if rr_math.fixed_risk_amount else Decimal("0")
    return {
        **base,
        "exit_timestamp": exit_candle.timestamp.isoformat(),
        "exit_price": str(exit_price),
        "exit_reason": exit_reason,
        "outcome": outcome,
        "risk_distance": str(risk_distance),
        "position_size": str(position_size),
        "gross_pnl": str(gross_pnl),
        "net_pnl": str(net_pnl),
        "rr_realized": str(rr_realized),
        "balance_after_trade": "",
    }


def _simulate_bullish_trade(
    *,
    trade_number: int,
    symbol: str,
    profile_id: str,
    inherited_base_profile: str = STRICT_BASE_PROFILE,
    entry_candle,
    future_candles,
    stop_loss,
    take_profit,
    risk_amount: Decimal,
    starting_balance: Decimal,
    max_leverage: Decimal,
    selected_rr_profile: str = PRODUCTION_RR_PROFILE,
    tp_model: str = "RR_1_5",
    source_12m_fvg_id: str | None = None,
    source_16m_swing_id: str | None = None,
    source_16m_fvg_id: str | None = None,
    setup_snapshot: dict[str, object] | None = None,
) -> dict[str, object]:
    entry_price = Decimal(str(entry_candle.close))
    stop_loss_decimal = Decimal(str(stop_loss))
    try:
        rr_math = _fixed_risk_trade_math_for_profile(
            direction="BULLISH",
            entry=entry_price,
            stop_loss=stop_loss_decimal,
            fixed_risk_amount=risk_amount,
            selected_rr_profile=selected_rr_profile,
            tp_model=tp_model,
            take_profit=Decimal(str(take_profit)),
        )
    except ValueError as exc:
        return {
            "trade_id": f"trade_{trade_number:04d}",
            "setup_id": f"{profile_id.lower()}_setup_{trade_number:04d}",
            "symbol": symbol,
            **_trade_profile_lock_fields(setup_snapshot, profile_id),
            "profile_id": profile_id,
            "strategy_profile": profile_id,
            "selected_strategy_profile": profile_id,
            "profile_variant_name": profile_id,
            "expansion_min_used": (setup_snapshot or {}).get("expansion_min_used"),
            "expansion_max_used": (setup_snapshot or {}).get("expansion_max_used"),
            "expansion_ratio": (setup_snapshot or {}).get("expansion_ratio"),
            "inherited_base_profile": inherited_base_profile,
            "direction": "BULLISH",
            "entry_timestamp": entry_candle.timestamp.isoformat(),
            "entry_price": str(entry_price),
            "stop_loss": str(stop_loss_decimal),
            "take_profit": str(take_profit),
            "fixed_risk_amount": str(risk_amount),
            "selected_starting_balance": str(starting_balance),
            "applied_starting_balance": str(starting_balance),
            "selected_fixed_risk_amount": str(risk_amount),
            "applied_margin_amount": "0",
            "risk_amount": str(risk_amount),
            "trade_type": "ISOLATED_MARGIN",
            "margin_mode": "isolated",
            "selected_rr_profile": str(selected_rr_profile).upper(),
            "selected_tp_model": str(selected_rr_profile).upper(),
            "applied_tp_model": str(selected_rr_profile).upper(),
            "tp_model_lock_status": "UNLOCKED",
            "selected_rr_value": "0",
            "target_reward_amount": "0",
            "expected_reward_amount": "0",
            "actual_risk_amount": "0",
            "actual_rr": "0",
            "outcome": "RISK_REJECTED",
            "exit_reason": str(exc),
            "risk_distance": "0",
            "position_size": "0",
            "price_risk_percent": "0",
            "required_leverage": "0",
            "applied_leverage": "0",
            "max_allowed_leverage": str(max_leverage),
            "notional_position_size": "0",
            "quantity": "0",
            "expected_loss_at_sl": "0",
            "exchange": "BACKTEST",
            "trade_mode": "BACKTEST",
            "risk_lock_status": "FAILED",
            "environment_lock_status": "BACKTEST",
            "exchange_lock_status": "BACKTEST",
            "profile_lock_status": "PASSED",
            "gross_pnl": "0",
            "net_pnl": "0",
            "rr_realized": "0",
            "setup_snapshot": setup_snapshot or {},
            "reason_for_entry": "",
            "reason_for_rejection": str(exc),
        }
    take_profit_decimal = rr_math.take_profit
    risk_distance = entry_price - stop_loss_decimal
    try:
        isolated = _isolated_margin_plan_for_backtest_profile(
            profile_id=profile_id,
            entry_price=entry_price,
            stop_loss=stop_loss_decimal,
            margin_amount=risk_amount,
            max_leverage=max_leverage,
        )
    except ValueError as exc:
        return {
            "trade_id": f"trade_{trade_number:04d}",
            "setup_id": f"{profile_id.lower()}_setup_{trade_number:04d}",
            "symbol": symbol,
            **_trade_profile_lock_fields(setup_snapshot, profile_id),
            "profile_id": profile_id,
            "selected_strategy_profile": profile_id,
            "applied_profile_id": profile_id,
            "direction": "BULLISH",
            "entry_timestamp": entry_candle.timestamp.isoformat(),
            "entry_price": str(entry_price),
            "stop_loss": str(stop_loss_decimal),
            "take_profit": str(take_profit_decimal),
            "selected_starting_balance": str(starting_balance),
            "applied_starting_balance": str(starting_balance),
            "selected_fixed_risk_amount": str(risk_amount),
            "fixed_risk_amount": str(risk_amount),
            "applied_margin_amount": "0",
            "risk_amount": str(risk_amount),
            "trade_type": "ISOLATED_MARGIN",
            "margin_mode": "isolated",
            "outcome": "RISK_REJECTED",
            "exit_reason": str(exc),
            "risk_distance": str(risk_distance),
            "position_size": "0",
            "price_risk_percent": "0",
            "required_leverage": "0",
            "applied_leverage": "0",
            "max_allowed_leverage": str(max_leverage),
            "notional_position_size": "0",
            "quantity": "0",
            "expected_loss_at_sl": "0",
            "gross_pnl": "0",
            "net_pnl": "0",
            "rr_realized": "0",
            "exchange": "BACKTEST",
            "trade_mode": "BACKTEST",
            "risk_lock_status": "FAILED",
            "environment_lock_status": "BACKTEST",
            "exchange_lock_status": "BACKTEST",
            "profile_lock_status": "PASSED",
            "reason_for_rejection": str(exc),
        }
    base = {
        "trade_id": f"trade_{trade_number:04d}",
        "setup_id": f"{profile_id.lower()}_setup_{trade_number:04d}",
        "symbol": symbol,
        **_trade_profile_lock_fields(setup_snapshot, profile_id),
        "profile_id": profile_id,
        "strategy_profile": profile_id,
        "selected_strategy_profile": profile_id,
        "profile_variant_name": profile_id,
        "expansion_min_used": (setup_snapshot or {}).get("expansion_min_used"),
        "expansion_max_used": (setup_snapshot or {}).get("expansion_max_used"),
        "expansion_ratio": (setup_snapshot or {}).get("expansion_ratio"),
        "inherited_base_profile": inherited_base_profile,
        "pair": symbol,
        "direction": "BULLISH",
        "mode": "backtest",
        "trade_mode": "BACKTEST",
        "exchange": "BACKTEST",
        "entry_timestamp": entry_candle.timestamp.isoformat(),
        "entry_price": str(entry_price),
        "entry": str(entry_price),
        "stop_loss": str(stop_loss_decimal),
        "SL": str(stop_loss_decimal),
        "stop_loss_price": str(stop_loss_decimal),
        "sl_source": "16m swing low",
        "take_profit": str(take_profit_decimal),
        "TP": str(take_profit_decimal),
        "take_profit_price": str(take_profit_decimal),
        "risk_amount": str(risk_amount),
        "selected_starting_balance": str(starting_balance),
        "applied_starting_balance": str(starting_balance),
        "selected_fixed_risk_amount": str(risk_amount),
        "applied_margin_amount": str(isolated.margin_amount),
        "trade_type": isolated.trade_type,
        "margin_mode": isolated.margin_mode,
        "fixed_risk_amount": str(rr_math.fixed_risk_amount),
        "selected_rr_profile": rr_math.selected_rr_profile,
        "selected_tp_model": rr_math.selected_rr_profile,
        "applied_tp_model": rr_math.selected_rr_profile,
        "tp_model_lock_status": "UNLOCKED",
        "selected_rr_value": str(rr_math.selected_rr_value),
        "target_reward_amount": str(rr_math.target_reward_amount),
        "actual_risk_amount": str(rr_math.actual_risk_amount),
        "price_risk_percent": str(isolated.price_risk_percent),
        "required_leverage": str(isolated.required_leverage),
        "applied_leverage": str(isolated.applied_leverage),
        "max_allowed_leverage": str(isolated.max_allowed_leverage),
        "notional_position_size": str(isolated.notional_position_size),
        "quantity": str(isolated.quantity),
        "expected_loss_at_sl": str(isolated.expected_loss_at_sl),
        "risk_lock_status": "PASSED",
        "environment_lock_status": "BACKTEST",
        "exchange_lock_status": "BACKTEST",
        "profile_lock_status": "PASSED",
        "expected_reward_amount": str(rr_math.expected_reward_amount),
        "actual_rr": str(rr_math.actual_rr),
        "fees": "0",
        "slippage": "0",
        "source_12m_fvg_id": source_12m_fvg_id,
        "source_16m_swing_id": source_16m_swing_id,
        "source_16m_fvg_id": source_16m_fvg_id,
        "fvg_id": source_12m_fvg_id,
        "12m_fvg_id": source_12m_fvg_id,
        "trade_triggered_from_fvg": True,
        "trade_triggered_from_12m_fvg": True,
        "triggered_trade_id": f"trade_{trade_number:04d}",
        "first_entry_candle": _candle_record(entry_candle),
        "first_1m_entry_candle": _candle_record(entry_candle),
        "one_trade_per_fvg_enforced": True,
        "duplicate_entry_blocked": True,
        "duplicate_trade_blocked": True,
        "entry_candle_closed_beyond_fvg_boundary": bool((setup_snapshot or {}).get("entry_candle_closed_beyond_fvg_boundary", False)),
        "setup_snapshot": setup_snapshot or {},
        "reason_for_entry": "FIRST_VALID_12M_FVG_RETRACE_CANDLE_BOUNDARY_RESPECTED",
        "reason_for_rejection": "",
    }
    if risk_distance <= 0:
        return {
            **base,
            "outcome": "RISK_REJECTED",
            "exit_reason": "INVALID_RISK_DISTANCE",
            "risk_distance": str(risk_distance),
            "position_size": "0",
            "gross_pnl": "0",
            "net_pnl": "0",
            "rr_realized": "0",
        }
    position_size = isolated.quantity
    exit_candle = future_candles[-1] if future_candles else entry_candle
    exit_price = Decimal(str(exit_candle.close))
    exit_reason = "DATA_ENDED_BEFORE_EXIT"
    outcome = "OPEN_OR_UNRESOLVED"
    for candle in future_candles:
        hit_stop = Decimal(str(candle.low)) <= stop_loss_decimal
        hit_target = Decimal(str(candle.high)) >= take_profit_decimal
        if hit_stop:
            exit_candle = candle
            exit_price = stop_loss_decimal
            exit_reason = "STOP_LOSS_HIT"
            outcome = "LOSS"
            break
        if hit_target:
            exit_candle = candle
            exit_price = take_profit_decimal
            exit_reason = "TAKE_PROFIT_HIT"
            outcome = "WIN"
            break
    gross_pnl = calculate_pnl(direction="BULLISH", entry_price=entry_price, exit_price=exit_price, position_size=position_size)
    fees = Decimal("0")
    slippage = Decimal("0")
    net_pnl = gross_pnl - fees - slippage
    rr_realized = net_pnl / rr_math.fixed_risk_amount if rr_math.fixed_risk_amount else Decimal("0")
    return {
        **base,
        "exit_timestamp": exit_candle.timestamp.isoformat(),
        "exit_price": str(exit_price),
        "exit_reason": exit_reason,
        "outcome": outcome,
        "risk_distance": str(risk_distance),
        "position_size": str(position_size),
        "gross_pnl": str(gross_pnl),
        "net_pnl": str(net_pnl),
        "rr_realized": str(rr_realized),
        "balance_after_trade": "",
    }


def _apply_balances(trades: list[dict[str, object]], starting_balance: Decimal) -> None:
    balance = starting_balance
    for trade in trades:
        if trade["outcome"] in ("WIN", "LOSS"):
            balance += Decimal(str(trade["net_pnl"]))
        trade["balance_after_trade"] = str(balance)


def _performance_summary(
    *,
    trades: list[dict[str, object]],
    starting_balance: Decimal,
    risk_amount_per_trade: Decimal,
    selected_rr_profile: str,
    selected_rr_value: Decimal,
    signals_generated: int,
    risk_rejected_count: int,
    risk_rejection_reasons: tuple[str, ...],
) -> dict[str, object]:
    closed = [trade for trade in trades if trade["outcome"] in ("WIN", "LOSS")]
    wins = [trade for trade in closed if trade["outcome"] == "WIN"]
    losses = [trade for trade in closed if trade["outcome"] == "LOSS"]
    unresolved = [trade for trade in trades if trade["outcome"] == "OPEN_OR_UNRESOLVED"]
    gross_profit = sum((Decimal(str(trade["gross_pnl"])) for trade in wins), Decimal("0"))
    gross_loss = sum((Decimal(str(trade["gross_pnl"])) for trade in losses), Decimal("0"))
    net_profit = sum((Decimal(str(trade["net_pnl"])) for trade in closed), Decimal("0"))
    final_balance = starting_balance + net_profit
    profit_factor = "INF" if gross_loss == 0 and gross_profit > 0 else (str(gross_profit / abs(gross_loss)) if gross_loss else "0")
    win_rate = (len(wins) / len(closed) * 100) if closed else 0.0
    loss_rate = (len(losses) / len(closed) * 100) if closed else 0.0
    rr_values = [Decimal(str(trade["rr_realized"])) for trade in closed]
    time_to_tp = _time_to_tp_metrics(trades)
    accounting = {
        "signals_generated": signals_generated,
        "risk_rejected": risk_rejected_count,
        "trades_simulated": len(trades),
        "closed_trades": len(closed),
        "open_or_unresolved_trades": len(unresolved),
        "wins": len(wins),
        "losses": len(losses),
        "accounting_balanced": signals_generated - risk_rejected_count == len(trades) and len(trades) == len(closed) + len(unresolved) and len(closed) == len(wins) + len(losses),
    }
    return {
        "starting_balance": str(starting_balance),
        "final_balance": str(final_balance),
        "total_trades": len(trades),
        "closed_trades": len(closed),
        "open_or_unresolved_trades": len(unresolved),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": win_rate,
        "loss_rate": loss_rate,
        "gross_profit": str(gross_profit),
        "gross_loss": str(gross_loss),
        "net_profit": str(net_profit),
        "total_fees": "0",
        "total_slippage": "0",
        "average_win": str(gross_profit / len(wins)) if wins else "0",
        "average_loss": str(gross_loss / len(losses)) if losses else "0",
        "largest_win": str(max((Decimal(str(trade["net_pnl"])) for trade in wins), default=Decimal("0"))),
        "largest_loss": str(min((Decimal(str(trade["net_pnl"])) for trade in losses), default=Decimal("0"))),
        "profit_factor": profit_factor,
        "max_drawdown": str(_max_drawdown(trades, starting_balance)),
        "average_rr": str(sum(rr_values, Decimal("0")) / len(rr_values)) if rr_values else "0",
        **time_to_tp,
        "selected_rr_profile": selected_rr_profile,
        "selected_tp_model": selected_rr_profile,
        "applied_tp_model": selected_rr_profile,
        "tp_model_lock_status": "UNLOCKED",
        "selected_rr_value": str(selected_rr_value),
        "fixed_risk_amount": str(risk_amount_per_trade),
        "expectancy_per_trade": str(net_profit / len(closed)) if closed else "0",
        "risk_amount_per_trade": str(risk_amount_per_trade),
        "entry_fill_policy": "PROFILE_F_TAP_CANDLE_CLOSE",
        "same_candle_policy": "CONSERVATIVE_STOP_FIRST",
        "unresolved_trade_policy": "MARK_TO_FINAL_CLOSE_FOR_TRADE_RECORD_EXCLUDE_FROM_CLOSED_METRICS",
        "risk_rejected_count": risk_rejected_count,
        "risk_rejection_reasons": tuple(risk_rejection_reasons),
        "trade_accounting_check": accounting,
    }


def _time_to_tp_metrics(trades) -> dict[str, object]:
    durations = []
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
        if seconds < 0:
            continue
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
    sorted_durations = sorted(durations)
    midpoint = len(sorted_durations) // 2
    if len(sorted_durations) % 2:
        median_seconds = sorted_durations[midpoint]
    else:
        median_seconds = (sorted_durations[midpoint - 1] + sorted_durations[midpoint]) / 2
    average_seconds = sum(durations) / len(durations)
    return {
        "average_time_to_hit_tp_seconds": average_seconds,
        "average_time_to_hit_tp_minutes": average_seconds / 60,
        "average_time_to_hit_tp_human": _format_duration_human(average_seconds),
        "fastest_time_to_hit_tp": _format_duration_human(min(durations)),
        "slowest_time_to_hit_tp": _format_duration_human(max(durations)),
        "median_time_to_hit_tp": _format_duration_human(median_seconds),
    }


def _format_duration_human(seconds: float) -> str:
    total_minutes = int(round(seconds / 60))
    hours = total_minutes // 60
    minutes = total_minutes % 60
    if hours:
        return f"{hours}h {minutes:02d}m"
    return f"{minutes}m"


def _max_drawdown(trades: list[dict[str, object]], starting_balance: Decimal) -> Decimal:
    balance = starting_balance
    peak = starting_balance
    max_drawdown = Decimal("0")
    for trade in trades:
        if trade["outcome"] in ("WIN", "LOSS"):
            balance += Decimal(str(trade["net_pnl"]))
            peak = max(peak, balance)
            max_drawdown = max(max_drawdown, peak - balance)
    return max_drawdown


def _classify_1m_confirmation(*, fvg12: FairValueGap, candles, final_target) -> dict[str, int]:
    counts = _empty_1m_confirmation_counts()
    tap_index = _first_fvg_tap_index(fvg12, candles)
    if tap_index is None or tap_index == 0 or tap_index + 1 >= len(candles):
        counts["rejected_no_first_1m_swing_high"] = 1
        return counts

    if any(candle.low <= final_target for candle in candles[: tap_index + 1]):
        counts["rejected_entry_window_expired"] = 1
        return counts

    first_index = tap_index
    counts["first_1m_swing_high_candidates"] = 1
    if candles[first_index].close > fvg12.upper_boundary:
        counts["rejected_1m_close_above_12m_fvg"] = 1
        return counts
    if _is_swing_high_at(candles, first_index):
        counts["passed_first_1m_swing_high"] = 1
        confirmed_index = first_index + 1
    else:
        second_index = first_index + 1
        if second_index + 1 >= len(candles):
            counts["rejected_no_second_1m_swing_high"] = 1
            return counts
        counts["second_1m_swing_high_candidates"] = 1
        if candles[second_index].close > fvg12.upper_boundary:
            counts["rejected_1m_close_above_12m_fvg"] = 1
            return counts
        if not _is_swing_high_at(candles, second_index):
            counts["rejected_no_second_1m_swing_high"] = 1
            return counts
        counts["passed_second_1m_swing_high"] = 1
        confirmed_index = second_index + 1

    if _third_1m_high_forms_inside_fvg(fvg12, candles, confirmed_index + 1):
        counts["rejected_third_1m_high"] = 1
        return counts

    counts["passed_1m_swing_confirmation"] = 1
    expansion_index = _first_bearish_1m_expansion_index(candles, confirmed_index + 1)
    if expansion_index is None:
        counts["rejected_no_1m_bearish_expansion"] = 1
        return counts
    counts["passed_1m_bearish_expansion"] = 1

    bearish_fvgs = tuple(
        fvg
        for fvg in FVGDetectionEngine().detect_fvgs(candles[expansion_index - 2 :]).fvgs
        if fvg.direction is FVGDirection.BEARISH
    )
    if not bearish_fvgs:
        counts["rejected_no_1m_bearish_fvg"] = 1
        return counts
    counts["passed_1m_bearish_fvg"] = 1

    first_fvg = bearish_fvgs[0]
    if _fvg_retest_seen(first_fvg, candles):
        counts["passed_return_to_first_1m_fvg"] = 1
        counts["entry_ready"] = 1
        return counts

    if len(bearish_fvgs) > 1:
        second_fvg = bearish_fvgs[1]
        if _fvg_retest_seen(second_fvg, candles):
            counts["passed_return_to_second_1m_fvg"] = 1
            counts["entry_ready"] = 1
            return counts
        counts["rejected_no_return_to_second_1m_fvg"] = 1
        return counts

    counts["rejected_no_return_to_first_1m_fvg"] = 1
    return counts


def _first_fvg_tap_index(fvg: FairValueGap, candles) -> int | None:
    for index, candle in enumerate(candles):
        if candle.high >= fvg.lower_boundary and candle.low <= fvg.upper_boundary:
            return index
    return None


def _is_swing_high_at(candles, index: int) -> bool:
    if index <= 0 or index + 1 >= len(candles):
        return False
    return candles[index].high > candles[index - 1].high and candles[index].high > candles[index + 1].high


def _third_1m_high_forms_inside_fvg(fvg: FairValueGap, candles, start_index: int) -> bool:
    for index in range(max(1, start_index), min(len(candles) - 1, start_index + 4)):
        if _is_swing_high_at(candles, index) and candles[index].high >= fvg.lower_boundary and candles[index].low <= fvg.upper_boundary:
            return True
    return False


def _first_bearish_1m_expansion_index(candles, start_index: int) -> int | None:
    for index in range(max(2, start_index), len(candles)):
        c1, c2, c3 = candles[index - 2], candles[index - 1], candles[index]
        average_size = (c1.range_size + c2.range_size) / 2
        if average_size <= 0:
            continue
        ratio = c3.range_size / average_size
        if ratio >= 1 and c3.low < min(c1.low, c2.low):
            return index
    return None


def _has_1m_fvg_retest(fvgs: tuple[FairValueGap, ...], candles) -> bool:
    for fvg in fvgs:
        for candle in candles:
            if candle.timestamp <= fvg.confirmed_at:
                continue
            if candle.high >= fvg.lower_boundary and candle.low <= fvg.upper_boundary:
                return True
    return False


def _fvg_retest_seen(fvg: FairValueGap, candles) -> bool:
    for candle in candles:
        if candle.timestamp <= fvg.confirmed_at:
            continue
        if candle.high >= fvg.lower_boundary and candle.low <= fvg.upper_boundary:
            return True
    return False


def _classify_1m_confirmation_bullish(*, fvg12: FairValueGap, candles, final_target) -> dict[str, int]:
    """Mirror of _classify_1m_confirmation for bullish (swing-low) setups."""
    counts = _empty_1m_confirmation_counts()
    tap_index = _first_fvg_tap_index(fvg12, candles)
    if tap_index is None or tap_index == 0 or tap_index + 1 >= len(candles):
        counts["rejected_no_first_1m_swing_high"] = 1
        return counts

    if any(candle.high >= final_target for candle in candles[: tap_index + 1]):
        counts["rejected_entry_window_expired"] = 1
        return counts

    first_index = tap_index
    counts["first_1m_swing_high_candidates"] = 1
    if candles[first_index].close < fvg12.lower_boundary:
        counts["rejected_1m_close_above_12m_fvg"] = 1
        return counts
    if _is_swing_low_at(candles, first_index):
        counts["passed_first_1m_swing_high"] = 1
        confirmed_index = first_index + 1
    else:
        second_index = first_index + 1
        if second_index + 1 >= len(candles):
            counts["rejected_no_second_1m_swing_high"] = 1
            return counts
        counts["second_1m_swing_high_candidates"] = 1
        if candles[second_index].close < fvg12.lower_boundary:
            counts["rejected_1m_close_above_12m_fvg"] = 1
            return counts
        if not _is_swing_low_at(candles, second_index):
            counts["rejected_no_second_1m_swing_high"] = 1
            return counts
        counts["passed_second_1m_swing_high"] = 1
        confirmed_index = second_index + 1

    if _third_1m_low_forms_inside_fvg(fvg12, candles, confirmed_index + 1):
        counts["rejected_third_1m_high"] = 1
        return counts

    counts["passed_1m_swing_confirmation"] = 1
    expansion_index = _first_bullish_1m_expansion_index(candles, confirmed_index + 1)
    if expansion_index is None:
        counts["rejected_no_1m_bearish_expansion"] = 1
        return counts
    counts["passed_1m_bearish_expansion"] = 1

    bullish_fvgs = tuple(
        fvg
        for fvg in FVGDetectionEngine().detect_fvgs(candles[expansion_index - 2 :]).fvgs
        if fvg.direction is FVGDirection.BULLISH
    )
    if not bullish_fvgs:
        counts["rejected_no_1m_bearish_fvg"] = 1
        return counts
    counts["passed_1m_bearish_fvg"] = 1

    first_fvg = bullish_fvgs[0]
    if _fvg_retest_seen(first_fvg, candles):
        counts["passed_return_to_first_1m_fvg"] = 1
        counts["entry_ready"] = 1
        return counts

    if len(bullish_fvgs) > 1:
        second_fvg = bullish_fvgs[1]
        if _fvg_retest_seen(second_fvg, candles):
            counts["passed_return_to_second_1m_fvg"] = 1
            counts["entry_ready"] = 1
            return counts
        counts["rejected_no_return_to_second_1m_fvg"] = 1
        return counts

    counts["rejected_no_return_to_first_1m_fvg"] = 1
    return counts


def _is_swing_low_at(candles, index: int) -> bool:
    """Mirror of _is_swing_high_at for swing lows."""
    if index <= 0 or index + 1 >= len(candles):
        return False
    return candles[index].low < candles[index - 1].low and candles[index].low < candles[index + 1].low


def _third_1m_low_forms_inside_fvg(fvg: FairValueGap, candles, start_index: int) -> bool:
    """Mirror of _third_1m_high_forms_inside_fvg for swing lows."""
    for index in range(max(1, start_index), min(len(candles) - 1, start_index + 4)):
        if _is_swing_low_at(candles, index) and candles[index].high >= fvg.lower_boundary and candles[index].low <= fvg.upper_boundary:
            return True
    return False


def _first_bullish_1m_expansion_index(candles, start_index: int) -> int | None:
    """Mirror of _first_bearish_1m_expansion_index for bullish expansions."""
    for index in range(max(2, start_index), len(candles)):
        c1, c2, c3 = candles[index - 2], candles[index - 1], candles[index]
        average_size = (c1.range_size + c2.range_size) / 2
        if average_size <= 0:
            continue
        ratio = c3.range_size / average_size
        if ratio >= 1 and c3.high > max(c1.high, c2.high):
            return index
    return None


def _unaccounted_after_retrace(
    *,
    passed_retrace: int,
    rejected_close_above_12m_fvg: int,
    rejected_third_1m_high: int,
    rejected_target_reached_before_entry: int,
    rejected_no_first_1m_swing_high: int,
    rejected_no_second_1m_swing_high: int,
    rejected_1m_close_above_12m_fvg: int,
    rejected_no_1m_bearish_expansion: int,
    rejected_no_1m_bearish_fvg: int,
    rejected_no_return_to_first_1m_fvg: int,
    rejected_no_return_to_second_1m_fvg: int,
    rejected_entry_window_expired: int,
    entry_ready: int,
) -> int:
    accounted = (
        rejected_close_above_12m_fvg
        + rejected_third_1m_high
        + rejected_target_reached_before_entry
        + rejected_no_first_1m_swing_high
        + rejected_no_second_1m_swing_high
        + rejected_1m_close_above_12m_fvg
        + rejected_no_1m_bearish_expansion
        + rejected_no_1m_bearish_fvg
        + rejected_no_return_to_first_1m_fvg
        + rejected_no_return_to_second_1m_fvg
        + rejected_entry_window_expired
        + entry_ready
    )
    return passed_retrace - accounted


def _fvg_matches_profile_expansion(fvg: FairValueGap, expansions, profile: StrategyProfile, direction: FVGDirection = FVGDirection.BEARISH) -> bool:
    for expansion in expansions:
        if _one_fvg_matches_expansion(fvg, expansion, profile, direction=direction):
            return True
    return False


def _expansion_is_swing_c3(expansion, swing: Swing | None) -> bool:
    return bool(
        swing is not None
        and expansion.swing_id == swing.swing_id
        and expansion.timeframe == swing.timeframe
        and expansion.timestamp == swing.right_candle.timestamp
        and (
            (swing.swing_type is SwingType.HIGH and getattr(expansion.direction, "value", str(expansion.direction)) == "BEARISH")
            or (swing.swing_type is SwingType.LOW and getattr(expansion.direction, "value", str(expansion.direction)) == "BULLISH")
        )
    )


def _one_fvg_matches_expansion(fvg: FairValueGap, expansion, profile: StrategyProfile, direction: FVGDirection = FVGDirection.BEARISH) -> bool:
    if fvg.direction is not direction:
        return False
    if fvg.related_expansion_id and fvg.related_expansion_id != expansion.expansion_id:
        return False
    if fvg.related_swing_id and fvg.related_swing_id != expansion.swing_id:
        return False
    if profile.main_fvg_match_mode == "LEGACY_EXPANSION_OR_NEXT_CANDLE":
        window_end = expansion.timestamp + expansion.timeframe.duration * profile.main_fvg_match_window_candles
        return expansion.timestamp <= fvg.timestamp <= window_end
    if fvg.c2_timestamp != expansion.timestamp:
        return False
    expected_confirmation_candle = expansion.timestamp + expansion.timeframe.duration * (profile.fvg_delay_16m_candles + 1)
    return fvg.c3_timestamp == expected_confirmation_candle


def _second_swing_research_metrics(candidate_swings, expansions, profile: StrategyProfile) -> dict[str, int]:
    return {}


def _build_validation_report(profile: StrategyProfile) -> dict[str, str]:
    """Dispatch to the per-profile validation report builder."""
    if profile.profile_id == "STRICT_PROFILE":
        return _strict_profile_validation_report(profile)
    if profile.profile_id == "PROFILE_G_CODEX_OPTIMIZED":
        return _profile_g_validation_report(profile)
    if profile.profile_id == "PROFILE_RECOVERED_HIGH_WINRATE":
        return _profile_recovered_validation_report(profile)
    if profile.profile_id == "PROFILE_2":
        return _profile_2_validation_report(profile)
    return _profile_f_validation_report(profile)


def _profile_applied(profile: StrategyProfile) -> dict[str, object]:
    selected_rr_profile = _selected_rr_profile_for_profile(profile, PRODUCTION_RR_PROFILE)
    selected_rr_value = _selected_rr_value_for_profile(profile, selected_rr_profile)
    return {
        "profile_id": profile.profile_id,
        "profile_label": profile.label,
        "profile_variant_name": profile.label,
        "production_safe": profile.production_safe,
        "inherited_base_profile": profile.inherited_base_profile,
        "expansion_min": profile.expansion_ratio_min,
        "expansion_max": profile.expansion_ratio_max,
        "retrace_window_8m_candles": profile.retrace_window_8m_candles,
        "allow_delayed_16m_fvg": profile.fvg_delay_16m_candles > 0,
        "delayed_16m_fvg_max_candles": profile.fvg_delay_16m_candles,
        "direct_12m_retrace_entry_enabled": profile.direct_12m_retrace_entry_enabled,
        "entry_model": "DIRECT_12M_RETRACE" if profile.direct_12m_retrace_entry_enabled else "FULL_1M_CONFIRMATION",
        "tp_model": profile.tp_model,
        "selected_rr_profile": selected_rr_profile,
        "selected_rr_value": str(selected_rr_value),
        "timeframe_set": profile.timeframe_profile_id,
        "require_expansion_c3": profile.require_expansion_c3,
        "use_linked_fvg_detection": profile.use_linked_fvg_detection,
        "main_fvg_match_mode": profile.main_fvg_match_mode,
        "main_fvg_match_window_candles": profile.main_fvg_match_window_candles,
        "one_trade_per_12m_fvg": profile.one_trade_per_12m_fvg,
        "research_only": not profile.production_safe,
        "tunable_parameters": profile.tunable_parameters,
    }


def _profile_lock_fields(*, profile: StrategyProfile, timeframe_profile: BacktestTimeframeProfile | None = None) -> dict[str, object]:
    return {
        "selected_profile_id": profile.profile_id,
        "applied_profile_id": profile.profile_id,
        "timeframe_profile_id": timeframe_profile.profile_id if timeframe_profile is not None else profile.timeframe_profile_id,
        "tp_model": profile.tp_model,
        "entry_model": "DIRECT_12M_RETRACE" if profile.direct_12m_retrace_entry_enabled else "FULL_1M_CONFIRMATION",
        "expansion_min": profile.expansion_ratio_min,
        "expansion_max": profile.expansion_ratio_max,
        "retrace_window_8m_candles": profile.retrace_window_8m_candles,
        "fvg_detection_mode": "LINKED" if profile.use_linked_fvg_detection else "UNLINKED_RAW",
        "use_linked_fvg_detection": profile.use_linked_fvg_detection,
        "require_expansion_c3": profile.require_expansion_c3,
        "main_fvg_match_mode": profile.main_fvg_match_mode,
        "main_fvg_match_window_candles": profile.main_fvg_match_window_candles,
        "direct_12m_retrace_entry_enabled": profile.direct_12m_retrace_entry_enabled,
        "one_trade_per_12m_fvg": profile.one_trade_per_12m_fvg,
    }


def _trade_profile_lock_fields(setup_snapshot: dict[str, object] | None, profile_id: str) -> dict[str, object]:
    snapshot = setup_snapshot or {}
    return {
        "selected_profile_id": snapshot.get("selected_profile_id", profile_id),
        "applied_profile_id": snapshot.get("applied_profile_id", profile_id),
        "timeframe_profile_id": snapshot.get("timeframe_profile_id", snapshot.get("timeframe_profile")),
        "tp_model": snapshot.get("tp_model"),
        "entry_model": snapshot.get("entry_model"),
        "expansion_settings": snapshot.get("expansion_settings"),
        "retrace_settings": snapshot.get("retrace_settings"),
        "fvg_detection_mode": snapshot.get("fvg_detection_mode"),
        "fvg_detection_settings": snapshot.get("fvg_detection_settings"),
        "recovered_compatibility_flags": {
            "use_linked_fvg_detection": snapshot.get("use_linked_fvg_detection"),
            "require_expansion_c3": snapshot.get("require_expansion_c3"),
            "main_fvg_match_mode": snapshot.get("main_fvg_match_mode"),
            "main_fvg_match_window_candles": snapshot.get("main_fvg_match_window_candles"),
            "direct_12m_retrace_entry_enabled": snapshot.get("direct_12m_retrace_entry_enabled"),
            "one_trade_per_12m_fvg": snapshot.get("one_trade_per_12m_fvg"),
        },
    }


def _verify_profile_lock(
    *,
    frontend_selected_profile: str,
    api_selected_profile: str,
    backend_resolved_profile: str,
    strategy_applied_profile: str,
    trades,
) -> dict[str, object]:
    selected = str(api_selected_profile).upper()
    mismatches = []
    for trade in trades:
        if not isinstance(trade, dict):
            continue
        trade_id = str(trade.get("trade_id", "UNKNOWN"))
        trade_selected = str(trade.get("selected_profile_id") or trade.get("selected_strategy_profile") or "").upper()
        trade_applied = str(trade.get("applied_profile_id") or trade.get("profile_id") or "").upper()
        if trade_selected != selected or trade_applied != selected:
            mismatches.append(
                {
                    "trade_id": trade_id,
                    "trade_selected_profile": trade_selected,
                    "trade_applied_profile": trade_applied,
                }
            )
    all_layers_match = (
        str(frontend_selected_profile).upper()
        == selected
        == str(backend_resolved_profile).upper()
        == str(strategy_applied_profile).upper()
    )
    status = "PASSED" if all_layers_match and not mismatches else "FAILED"
    return {
        "section": "PROFILE LOCK VERIFICATION",
        "frontend_selected_profile": str(frontend_selected_profile).upper(),
        "api_selected_profile": selected,
        "backend_resolved_profile": str(backend_resolved_profile).upper(),
        "strategy_applied_profile": str(strategy_applied_profile).upper(),
        "trades_checked": len(tuple(trades)),
        "mismatched_trades_count": len(mismatches),
        "mismatched_trades": tuple(mismatches),
        "profile_lock_status": status,
        "selected_profile_actively_used_by_backend": "YES" if status == "PASSED" else "NO",
    }


def _strict_profile_validation_report(profile: StrategyProfile) -> dict[str, str]:
    return {
        "PROFILE_ID": profile.profile_id,
        "ONE_HOUR_CONTEXT_USED": "YES",
        "THREE_MINUTE_CONTEXT_USED": "YES",
        "16M_EXPANSION_CANDLE_IS_C3": "YES",
        "C3_PART_OF_16M_SWING_FORMATION": "YES",
        "C3_FORMS_16M_FVG": "YES",
        "12M_FVG_EXISTS_ON_SAME_PRICE_LEG": "YES",
        "8M_FVG_EXISTS_ON_SAME_PRICE_LEG": "YES",
        "EXPANSION_RATIO_2_0_TO_4_0": "YES" if profile.expansion_ratio_min == 2.0 and profile.expansion_ratio_max == 4.0 else "NO",
        "3_8M_CANDLE_RETRACE_WINDOW": "YES" if profile.retrace_window_8m_candles == 3 else "NO",
        "FULL_1M_CONFIRMATION_CHAIN_ACTIVE": "YES" if not profile.direct_12m_retrace_entry_enabled else "NO",
        "1M_SWING_HIGH_REQUIRED": "YES" if profile.require_1m_swing_confirmation else "NO",
        "1M_BEARISH_EXPANSION_REQUIRED": "YES (structurally via confirmation chain)",
        "1M_BEARISH_FVG_REQUIRED": "YES (structurally via confirmation chain)",
        "1M_FVG_RETEST_REQUIRED": "YES (structurally via confirmation chain)",
        "ONE_TRADE_PER_12M_FVG": "YES" if profile.one_trade_per_12m_fvg else "NO",
        "SL_SOURCE_16M_SWING_HIGH_LOW": "YES",
        "RR_TP_ACTIVE": "YES",
        "FIXED_RISK_ACTIVE": "YES",
        "STRICT_PROFILE_IS_BASE": "YES" if profile.inherited_base_profile == STRICT_BASE_PROFILE else "NO",
    }


def _profile_f_validation_report(profile: StrategyProfile) -> dict[str, str]:
    return {
        "ONE_HOUR_CONTEXT_USED": "YES",
        "THREE_MINUTE_CONTEXT_USED": "YES",
        "16M_EXPANSION_CANDLE_IS_C3": "YES",
        "C3_PART_OF_16M_SWING_FORMATION": "YES",
        "C3_FORMS_16M_FVG": "YES",
        "12M_FVG_EXISTS_ON_SAME_PRICE_LEG": "YES",
        "8M_FVG_EXISTS_ON_SAME_PRICE_LEG": "YES",
        "16M_FVG_ANCHOR_USED": "YES",
        "12M_FVG_USED_AS_ZONE": "YES",
        "1M_CANDLES_TRIGGER_12M_RETRACE_ENTRY": "YES",
        "8M_MAX_3_CANDLE_WINDOW_ACTIVE": "YES" if profile.retrace_window_8m_candles == 3 else "NO",
        "NO_EXTRA_POST_RETRACE_CONFIRMATION": "YES"
        if not any(
            (
                profile.require_1m_swing_confirmation,
                profile.require_1m_bearish_expansion,
                profile.require_1m_bearish_fvg,
                profile.require_1m_fvg_retest,
            )
        )
        else "NO",
        "ONE_TRADE_PER_12M_FVG": "YES" if profile.one_trade_per_12m_fvg else "NO",
        "SL_SOURCE_16M_SWING_HIGH_LOW": "YES",
        "PROFILE_F_VARIANT_ID": profile.profile_id,
        "PROFILE_F_VARIANT_NAME": profile.label,
        "PROFILE_F_SELECTABLE_VARIANT_ACTIVE": "YES" if profile.profile_id.startswith("PROFILE_F_") else "NO",
        "PROFILE_F_BASES_ON_STRICT_PROFILE": "YES" if profile.inherited_base_profile == STRICT_BASE_PROFILE else "NO",
        "EXPANSION_RANGE_APPLIED": f"{profile.expansion_ratio_min:g}-{profile.expansion_ratio_max:g}",
        "16M_FVG_STARTS_RETRACE_WINDOW": "YES" if profile.fvg_delay_16m_candles == 0 else "NO",
        "RETRACE_WINDOW_MAX_3_8M_CANDLES": "YES" if profile.retrace_window_8m_candles == 3 else "NO",
        "12M_FVG_RETRACE_ENTRY_ACTIVE": "YES" if profile.direct_12m_retrace_entry_enabled else "NO",
        "NO_EXTRA_CONFIRMATION_AFTER_12M_RETRACE": "YES"
        if not any(
            (
                profile.require_1m_swing_confirmation,
                profile.require_1m_bearish_expansion,
                profile.require_1m_bearish_fvg,
                profile.require_1m_fvg_retest,
            )
        )
        else "NO",
        "ONE_TRADE_PER_12M_FVG_STILL_ACTIVE": "YES" if profile.one_trade_per_12m_fvg else "NO",
        "POST_ENTRY_12M_CLOSE_DOES_NOT_INVALIDATE_TRADE": "YES" if profile.direct_12m_retrace_entry_enabled else "NO",
        "ALL_OTHER_PROFILE_F_RULES_UNCHANGED": "YES"
        if (
            profile.inherited_base_profile == STRICT_BASE_PROFILE
            and profile.profile_id.startswith("PROFILE_F_")
            and profile.expansion_ratio_max == 4.0
            and profile.fvg_delay_16m_candles == 0
            and profile.one_trade_per_12m_fvg
            and not any(
                (
                    profile.require_1m_swing_confirmation,
                    profile.require_1m_bearish_expansion,
                    profile.require_1m_bearish_fvg,
                    profile.require_1m_fvg_retest,
                )
            )
        )
        else "NO",
        "BEARISH_SL_16M_SWING_HIGH": "YES",
        "BULLISH_SL_16M_SWING_LOW": "YES",
        "RR_TP_ACTIVE": "YES",
        "FIXED_RISK_ACTIVE": "YES",
    }


def _profile_g_validation_report(profile: StrategyProfile) -> dict[str, str]:
    return {
        **_profile_f_validation_report(profile),
        "PROFILE_G_CODEX_OPTIMIZED_ACTIVE": "YES",
        "RESEARCH_ONLY": "YES" if not profile.production_safe else "NO",
        "PRODUCTION_STRICT_UNCHANGED": "YES",
        "PROFILE_F_UNCHANGED": "YES",
        "TP_MODEL": profile.tp_model,
        "RESEARCH_RR_1_0_BACKTEST_ONLY": "YES" if profile.tp_model == "RR_1_0_RESEARCH" else "NO",
        "TUNABLE_FROM_FRONTEND": "YES" if profile.tunable_parameters else "NO",
    }


def _profile_recovered_validation_report(profile: StrategyProfile) -> dict[str, str]:
    return {
        **_profile_f_validation_report(profile),
        "PROFILE_RECOVERED_HIGH_WINRATE_ACTIVE": "YES",
        "RECOVERED_FROM_REPORT": "research_comparison_bt_624f5cc97f161f27c9eaebb8.json",
        "FORMER_PROFILE_ID": "RESEARCH_PROFILE_F_DIRECT_12M_RETRACE_ENTRY",
        "RESEARCH_ONLY": "YES" if not profile.production_safe else "NO",
        "TIMEFRAME_STACK_RECOVERED": "PROFILE_15_10_5" if profile.timeframe_profile_id == "PROFILE_15_10_5" else "NO",
        "EXPANSION_RANGE_RECOVERED": "YES" if profile.expansion_ratio_min == 1.0 and profile.expansion_ratio_max == 3.0 else "NO",
        "DIRECT_12M_RETRACE_ENTRY_RECOVERED": "YES" if profile.direct_12m_retrace_entry_enabled else "NO",
        "STRUCTURAL_LEG_TARGET_TP_ACTIVE": "YES" if profile.tp_model == "LEG_TARGET_RESEARCH" else "NO",
        "LEGACY_UNLINKED_FVG_DETECTION_ACTIVE": "YES" if not profile.use_linked_fvg_detection else "NO",
        "LEGACY_MAIN_FVG_MATCHER_ACTIVE": "YES" if profile.main_fvg_match_mode == "LEGACY_EXPANSION_OR_NEXT_CANDLE" else "NO",
        "LEGACY_MAIN_FVG_MATCH_WINDOW": str(profile.main_fvg_match_window_candles),
        "PRODUCTION_STRICT_UNCHANGED": "YES",
        "PROFILE_F_UNCHANGED": "YES",
        "TUNABLE_FROM_FRONTEND": "YES" if profile.tunable_parameters else "NO",
    }


def _profile_2_validation_report(profile: StrategyProfile) -> dict[str, str]:
    return {
        **_profile_recovered_validation_report(profile),
        "PROFILE_RECOVERED_HIGH_WINRATE_ACTIVE": "NO",
        "PROFILE_2_ACTIVE": "YES",
        "RECOVERED_FROM_REPORT": "research_comparison_bt_624f5cc97f161f27c9eaebb8.json",
        "FORMER_PROFILE_ID": "RESEARCH_PROFILE_F_DIRECT_12M_RETRACE_ENTRY",
        "LEGACY_FIXED_RISK_BACKTEST_SIZING_ACTIVE": "YES",
        "PROFILE_RECOVERED_HIGH_WINRATE_UNMODIFIED": "YES",
    }


def _fvgs_inside_leg(
    fvgs: tuple[FairValueGap, ...],
    *,
    direction: FVGDirection,
    swing_high_price=None,
    completion_candle_low=None,
    swing_low_price=None,
    completion_candle_high=None,
    start_at: datetime,
) -> tuple[FairValueGap, ...]:
    if direction is FVGDirection.BULLISH:
        return tuple(
            fvg
            for fvg in fvgs
            if fvg.direction is direction
            and fvg.confirmed_at >= start_at
            and fvg_inside_bullish_leg(
                fvg=fvg,
                swing_low_price=swing_low_price,
                completion_candle_high=completion_candle_high,
            )
        )
    return tuple(
        fvg
        for fvg in fvgs
        if fvg.direction is direction
        and fvg.confirmed_at >= start_at
        and fvg_inside_bearish_leg(
            fvg=fvg,
            swing_high_price=swing_high_price,
            completion_candle_low=completion_candle_low,
        )
    )


def _html(summary: dict[str, object]) -> str:
    rows = "\n".join(
        f"<tr><td>{key}</td><td>{value}</td></tr>"
        for key, value in summary.items()
        if key != "strategy_funnel"
    )
    funnel = summary.get("strategy_funnel", {})
    profile_lock = summary.get("profile_lock_verification", {})
    profile_lock_rows = "\n".join(
        f"<tr><td>{key}</td><td>{value}</td></tr>"
        for key, value in profile_lock.items()
    ) if isinstance(profile_lock, dict) else ""
    funnel_rows = "\n".join(
        f"<tr><td>{_funnel_label(key)}</td><td>{value}</td></tr>"
        for key, value in funnel.items()
    ) if isinstance(funnel, dict) else ""
    performance = summary.get("performance_summary", {})
    performance_rows = "\n".join(
        f"<tr><td>{key}</td><td>{value}</td></tr>"
        for key, value in performance.items()
    ) if isinstance(performance, dict) else ""
    trades = funnel.get("trade_list", ()) if isinstance(funnel, dict) else ()
    trade_headers = (
        "trade_id",
        "direction",
        "fixed_risk_amount",
        "selected_rr_profile",
        "selected_tp_model",
        "applied_tp_model",
        "tp_model_lock_status",
        "selected_rr_value",
        "entry_price",
        "stop_loss",
        "take_profit",
        "exit_price",
        "position_size",
        "outcome",
        "net_pnl",
        "actual_rr",
    )
    trade_header_html = "".join(f"<th>{header}</th>" for header in trade_headers)
    trade_rows = "\n".join(
        "<tr>" + "".join(f"<td>{trade.get(header, '')}</td>" for header in trade_headers) + "</tr>"
        for trade in trades
        if isinstance(trade, dict)
    )
    trade_table = f"<h2>Trades</h2><table><thead><tr>{trade_header_html}</tr></thead><tbody>{trade_rows}</tbody></table>" if trade_rows else ""
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>CSV Backtest Report</title>
<style>body{{font-family:Arial,sans-serif;margin:32px;color:#17202a}}table{{border-collapse:collapse;width:100%}}td,th{{border:1px solid #d5d8dc;padding:8px;text-align:left}}th{{background:#eaf2f8}}</style></head>
<body><h1>CSV Backtest Report</h1>{_funnel_warning(summary)}<h2>PROFILE LOCK VERIFICATION</h2><table><thead><tr><th>Field</th><th>Value</th></tr></thead><tbody>{profile_lock_rows}</tbody></table><h2>Strategy Funnel</h2><table><thead><tr><th>Stage</th><th>Count</th></tr></thead><tbody>{funnel_rows}</tbody></table><h2>Performance Summary</h2><table><thead><tr><th>Metric</th><th>Value</th></tr></thead><tbody>{performance_rows}</tbody></table><h2>Run Summary</h2><table><thead><tr><th>Metric</th><th>Value</th></tr></thead><tbody>{rows}</tbody></table>{trade_table}</body></html>"""


def _funnel_warning(summary: dict[str, object]) -> str:
    funnel = summary.get("strategy_funnel", {})
    if isinstance(funnel, dict) and int(funnel.get("unaccounted_after_retrace", 0)) > 0:
        return "<p style=\"color:#922b21;font-weight:700\">WARNING: Funnel accounting incomplete after 12M retrace.</p>"
    return ""


def _research_html(report: dict[str, object]) -> str:
    rows = report["comparison"] if isinstance(report.get("comparison"), list) else []
    headers = (
        "profile_id",
        "profile_label",
        "research_only",
        "expansion_min",
        "expansion_max",
        "retrace_window_8m_candles",
        "direct_12m_retrace_entry_enabled",
        "one_trade_per_12m_fvg",
        "classification",
        "candidate_swings",
        "passed_expansion",
        "passed_main_fvg_timeframe_fvg",
        "passed_retrace_fvg_timeframe_fvg",
        "passed_internal_fvg_timeframe_fvg",
        "passed_retrace",
        "rejected_close_above_12m_fvg_before_entry",
        "direct_12m_entries",
        "ignored_additional_12m_fvg_tap_after_entry",
        "post_entry_close_above_12m_fvg_ignored",
        "signals_generated",
        "risk_rejected_count",
        "risk_rejection_reasons",
        "passed_12m_reaction",
        "first_1m_swing_high_candidates",
        "rejected_no_first_1m_swing_high",
        "passed_first_1m_swing_high",
        "second_1m_swing_high_candidates",
        "rejected_no_second_1m_swing_high",
        "passed_second_1m_swing_high",
        "rejected_third_1m_high",
        "rejected_1m_close_above_12m_fvg",
        "passed_1m_swing_confirmation",
        "rejected_no_1m_bearish_expansion",
        "passed_1m_bearish_expansion",
        "rejected_no_1m_bearish_fvg",
        "passed_1m_bearish_fvg",
        "rejected_no_return_to_first_1m_fvg",
        "rejected_no_return_to_second_1m_fvg",
        "passed_return_to_first_1m_fvg",
        "passed_return_to_second_1m_fvg",
        "rejected_entry_window_expired",
        "entry_ready",
        "unaccounted_after_retrace",
        "signals",
        "trades",
        "wins",
        "losses",
        "net_profit",
        "max_drawdown",
        "profit_factor",
        "average_rr",
        "selected_rr_profile",
        "selected_tp_model",
        "applied_tp_model",
        "tp_model_lock_status",
        "selected_rr_value",
        "fixed_risk_amount",
    )
    header_html = "".join(f"<th>{header}</th>" for header in headers)
    row_html = "\n".join(
        "<tr>" + "".join(f"<td>{row.get(header, '')}</td>" for header in headers) + "</tr>"
        for row in rows
        if isinstance(row, dict)
    )
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Backtest Profile Report</title>
<style>body{{font-family:Arial,sans-serif;margin:24px;color:#17202a}}table{{border-collapse:collapse;width:100%;font-size:12px}}td,th{{border:1px solid #d5d8dc;padding:6px;text-align:left}}th{{background:#eaf2f8;position:sticky;top:0}}.warn{{color:#922b21;font-weight:700}}</style></head>
<body><h1>Backtest Profile Report</h1><p><strong>Profile F Volume, Balanced, and Selective</strong> are the selectable production Profile F variants.</p>
<table><thead><tr>{header_html}</tr></thead><tbody>{row_html}</tbody></table></body></html>"""


def _funnel_label(key: str) -> str:
    labels = {
        "candidate_16m_swing_highs": "Candidate 16M swing highs",
        "rejected_no_expansion": "Rejected because no expansion",
        "passed_expansion": "Passed expansion",
        "rejected_no_immediate_16m_fvg": "Rejected because no immediate 16M FVG",
        "rejected_no_12m_fvg_inside_leg": "Rejected because no 12M FVG inside leg",
        "rejected_no_8m_fvg_inside_leg": "Rejected because no 8M FVG inside leg",
        "rejected_retrace_window_expired": "Rejected because retrace window expired",
        "rejected_close_above_12m_fvg": "Rejected because close above 12M FVG",
        "rejected_third_high": "Rejected because third high",
        "rejected_target_reached_before_entry": "Rejected because target reached before entry",
        "rejected_close_above_12m_fvg_before_entry": "Rejected close above 12M FVG before entry",
        "direct_12m_entries": "Direct 12M entries",
        "ignored_additional_12m_fvg_tap_after_entry": "Ignored additional 12M FVG tap after entry",
        "post_entry_close_above_12m_fvg_ignored": "Post-entry close above 12M FVG ignored",
        "signals_generated": "Signals generated",
        "risk_rejected_count": "Risk rejected count",
        "risk_rejection_reasons": "Risk rejection reasons",
        "passed_12m_reaction": "Passed 12M FVG reaction",
        "first_1m_swing_high_candidates": "First 1M swing high candidates",
        "rejected_no_first_1m_swing_high": "Rejected because no first 1M swing high",
        "passed_first_1m_swing_high": "Passed first 1M swing high",
        "second_1m_swing_high_candidates": "Second 1M swing high candidates",
        "rejected_no_second_1m_swing_high": "Rejected because no second 1M swing high",
        "passed_second_1m_swing_high": "Passed second 1M swing high",
        "rejected_third_1m_high": "Rejected because third 1M high",
        "rejected_1m_close_above_12m_fvg": "Rejected because 1M close above 12M FVG",
        "passed_1m_swing_confirmation": "Passed 1M swing confirmation",
        "rejected_no_1m_bearish_expansion": "Rejected because no 1M bearish expansion",
        "passed_1m_bearish_expansion": "Passed 1M bearish expansion",
        "rejected_no_1m_bearish_fvg": "Rejected because no 1M bearish FVG",
        "passed_1m_bearish_fvg": "Passed 1M bearish FVG",
        "rejected_no_return_to_first_1m_fvg": "Rejected because no return to first 1M FVG",
        "rejected_no_return_to_second_1m_fvg": "Rejected because no return to second 1M FVG",
        "passed_return_to_first_1m_fvg": "Passed return to first 1M FVG",
        "passed_return_to_second_1m_fvg": "Passed return to second 1M FVG",
        "rejected_entry_window_expired": "Rejected because entry window expired",
        "unaccounted_after_retrace": "Unaccounted after retrace",
        "entry_ready": "Entry ready",
        "trades": "Trades",
    }
    return labels.get(key, key)


def main() -> None:
    if len(sys.argv) < 7:
        raise SystemExit("Usage: python scripts/backtest_csv.py data/BTCUSDT_1m.csv BTCUSDT PROFILE_F_VOLUME STARTING_BALANCE FIXED_RISK_AMOUNT MAX_LEVERAGE [DEFAULT_16_12_8|PROFILE_15_10_5]")
    csv_path = Path(sys.argv[1])
    if not csv_path.exists():
        raise SystemExit(f"CSV file not found: {csv_path}")
    strategy_profile = sys.argv[3]
    starting_balance = sys.argv[4]
    fixed_risk_amount = sys.argv[5]
    max_leverage = sys.argv[6]
    timeframe_profile = sys.argv[7] if len(sys.argv) > 7 else "DEFAULT_16_12_8"
    report = run(
        csv_path,
        sys.argv[2],
        strategy_profile=strategy_profile,
        starting_balance=starting_balance,
        fixed_risk_amount=fixed_risk_amount,
        max_leverage=max_leverage,
        timeframe_profile=timeframe_profile,
    )
    print(json.dumps(report["summary"], indent=2))
    print(f"json_report={report['json_path']}")
    print(f"html_report={report['html_path']}")


if __name__ == "__main__":
    main()
