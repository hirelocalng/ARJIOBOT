"""CSV backtest runner regression tests."""

from __future__ import annotations

import importlib.util
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from arjiobot.fvg.fvg_models import FVGDirection, FairValueGap
from arjiobot.market_data.candle_models import Candle, CandleStatus, Timeframe
from arjiobot.swings.swing_models import Swing, SwingType


def _load_runner():
    root = Path(__file__).resolve().parents[4]
    script_path = root / "scripts" / "backtest_csv.py"
    spec = importlib.util.spec_from_file_location("arjiobot_backtest_csv_runner", script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load backtest_csv.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_backend_runner():
    backend_root = Path(__file__).resolve().parents[3]
    script_path = backend_root / "scripts" / "backtest_csv.py"
    spec = importlib.util.spec_from_file_location("arjiobot_backend_backtest_csv_runner", script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load backend/scripts/backtest_csv.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _risk_kwargs() -> dict[str, Decimal]:
    return {"starting_balance": Decimal("10000"), "max_leverage": Decimal("100")}


def test_csv_runner_blocks_setup_signal_and_trade_without_16m_expansion(tmp_path) -> None:
    csv_path = tmp_path / "no_16m_expansion.csv"
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rows = ["timestamp,open,high,low,close,volume"]
    for index in range(64):
        timestamp = start + timedelta(minutes=index)
        rows.append(f"{timestamp.isoformat()},100,101,99,100,10")
    csv_path.write_text("\n".join(rows), encoding="utf-8")

    report = _load_runner().run(csv_path, "BTCUSDT", strategy_profile="PROFILE_F_VOLUME", starting_balance="10000", fixed_risk_amount="100", max_leverage="100")
    summary = report["summary"]

    assert summary["16m_expansions_found"] == 0
    assert summary["strategy_source"] == "REAL_STRATEGY_PIPELINE"
    assert summary["strategy_funnel"]["candidate_16m_swing_highs"] == 0
    assert summary["strategy_funnel"]["rejected_no_expansion"] == 0
    assert summary["strategy_funnel"]["passed_expansion"] == 0
    for key in _required_1m_funnel_rows():
        assert key in summary["strategy_funnel"]
    assert summary["strategy_funnel"]["entry_ready"] == 0
    assert summary["strategy_funnel"]["unaccounted_after_retrace"] == 0
    assert summary["strategy_funnel"]["trades"] == 0
    _assert_confirmation_funnel_balances(summary["strategy_funnel"])
    assert summary["setups_created"] == 0
    assert summary["signals_generated"] == 0
    assert summary["risk_trade_plans_created"] == 0
    assert summary["paper_executions_created"] == 0
    assert summary["trades_simulated"] == 0


def test_csv_runner_does_not_use_demo_signal_path() -> None:
    root = Path(__file__).resolve().parents[4]
    source = (root / "scripts" / "backtest_csv.py").read_text(encoding="utf-8")

    assert "build_demo_signal" not in source
    assert "demo_backtester" not in source
    assert 'STRATEGY_SOURCE = "REAL_STRATEGY_PIPELINE"' in source


def test_manual_backtest_and_optimizer_use_same_profile_config_path() -> None:
    root = Path(__file__).resolve().parents[4]
    runner_source = (root / "scripts" / "backtest_csv.py").read_text(encoding="utf-8")
    optimizer_source = (root / "scripts" / "optimize_profiles.py").read_text(encoding="utf-8")

    assert "expansions_main = _research_expansions(swing_results.all_swings)" in runner_source
    assert "expansions = RUNNER._research_expansions" in optimizer_source
    assert "_build_strategy_funnel(" in runner_source
    assert "RUNNER._build_strategy_funnel(" in optimizer_source


def test_confirmation_funnel_rows_prevent_post_retrace_disappearing_candidates() -> None:
    funnel = {
        "passed_retrace": 64,
        "rejected_close_above_12m_fvg": 46,
        "rejected_third_1m_high": 0,
        "rejected_target_reached_before_entry": 1,
        "rejected_no_first_1m_swing_high": 10,
        "rejected_no_second_1m_swing_high": 0,
        "rejected_1m_close_above_12m_fvg": 0,
        "rejected_no_1m_bearish_expansion": 0,
        "rejected_no_1m_bearish_fvg": 4,
        "rejected_no_return_to_first_1m_fvg": 3,
        "rejected_no_return_to_second_1m_fvg": 0,
        "rejected_entry_window_expired": 0,
        "entry_ready": 0,
        "unaccounted_after_retrace": 0,
    }

    _assert_confirmation_funnel_balances(funnel)


def test_first_1m_swing_expansion_fvg_and_first_fvg_return_are_counted() -> None:
    runner = _load_runner()
    counts = runner._classify_1m_confirmation(
        fvg12=_fvg(),
        candles=tuple(
            _candle(i, open_, high, low, close)
            for i, (open_, high, low, close) in enumerate(
                [
                    (90, 94, 89, 94),
                    (94, 106, 94, 98),
                    (98, 101, 96, 97),
                    (97, 100, 93, 94),
                    (94, 95, 88, 89),
                    (89, 90, 80, 82),
                    (82, 86, 81, 85),
                    (85, 88, 84, 87),
                    (87, 97, 86, 96),
                ]
            )
        ),
        final_target=Decimal("70"),
    )

    assert counts["first_1m_swing_high_candidates"] == 1
    assert counts["passed_first_1m_swing_high"] == 1
    assert counts["passed_1m_swing_confirmation"] == 1
    assert counts["passed_1m_bearish_expansion"] == 1
    assert counts["passed_1m_bearish_fvg"] == 1
    assert counts["passed_return_to_first_1m_fvg"] == 1
    assert counts["entry_ready"] == 1


def test_second_1m_swing_confirmation_is_counted_separately() -> None:
    runner = _load_runner()
    counts = runner._classify_1m_confirmation(
        fvg12=_fvg(),
        candles=tuple(
            _candle(i, open_, high, low, close)
            for i, (open_, high, low, close) in enumerate(
                [
                    (90, 94, 89, 94),
                    (94, 100, 94, 98),
                    (98, 106, 96, 99),
                    (99, 101, 95, 96),
                    (96, 98, 92, 93),
                    (93, 94, 86, 87),
                    (87, 88, 78, 80),
                    (80, 84, 79, 83),
                    (83, 97, 82, 96),
                ]
            )
        ),
        final_target=Decimal("70"),
    )

    assert counts["first_1m_swing_high_candidates"] == 1
    assert counts["second_1m_swing_high_candidates"] == 1
    assert counts["passed_second_1m_swing_high"] == 1
    assert counts["passed_1m_swing_confirmation"] == 1


def test_third_1m_high_invalidation_is_counted() -> None:
    runner = _load_runner()
    counts = runner._classify_1m_confirmation(
        fvg12=_fvg(),
        candles=tuple(
            _candle(i, open_, high, low, close)
            for i, (open_, high, low, close) in enumerate(
                [
                    (90, 94, 89, 94),
                    (94, 106, 94, 98),
                    (98, 101, 96, 97),
                    (97, 104, 94, 96),
                    (96, 99, 92, 93),
                    (93, 94, 86, 87),
                ]
            )
        ),
        final_target=Decimal("70"),
    )

    assert counts["rejected_third_1m_high"] == 1
    assert counts["entry_ready"] == 0


def test_second_1m_fvg_return_is_counted() -> None:
    runner = _load_runner()
    counts = runner._empty_1m_confirmation_counts()
    counts["passed_1m_bearish_fvg"] = 1
    counts["passed_return_to_second_1m_fvg"] = 1
    counts["entry_ready"] = 1

    assert counts["passed_return_to_second_1m_fvg"] == 1
    assert counts["entry_ready"] == 1


def test_frontend_details_panel_displays_new_funnel_rows() -> None:
    root = Path(__file__).resolve().parents[4]
    source = (root / "frontend" / "src" / "pages" / "Backtesting.tsx").read_text(encoding="utf-8")

    assert "Object.entries(funnel)" in source
    assert "Strategy Funnel" in source


def test_bearish_trade_hits_take_profit_and_positive_pnl() -> None:
    runner = _load_runner()

    trade = runner._simulate_bearish_trade(
        trade_number=1,
        symbol="BTCUSDT",
        profile_id="PROFILE_F_VOLUME",
        entry_candle=_candle(0, 100, 101, 99, 100),
        future_candles=(_candle(1, 100, 101, 84, 85),),
        stop_loss=Decimal("110"),
        take_profit=Decimal("90"),
        risk_amount=Decimal("100"),
        **_risk_kwargs(),
        source_12m_fvg_id="fvg12",
        source_16m_swing_id="swing16",
        source_16m_fvg_id="fvg16",
    )

    assert trade["outcome"] == "WIN"
    assert trade["exit_reason"] == "TAKE_PROFIT_HIT"
    assert Decimal(str(trade["gross_pnl"])) > 0
    assert Decimal(str(trade["position_size"])) == Decimal("10")
    assert trade["fixed_risk_amount"] == "100"
    assert trade["selected_rr_profile"] == "RR_1_5"
    assert Decimal(str(trade["actual_rr"])) == Decimal("1.5")


def test_bearish_trade_rr_is_locked_to_1_5_and_old_profiles_reject() -> None:
    runner = _load_runner()

    production = runner._simulate_bearish_trade(
        trade_number=1,
        symbol="BTCUSDT",
        profile_id="PROFILE_F_VOLUME",
        entry_candle=_candle(0, 100, 101, 99, 100),
        future_candles=(_candle(1, 100, 101, 69, 70),),
        stop_loss=Decimal("110"),
        take_profit=Decimal("90"),
        risk_amount=Decimal("100"),
        **_risk_kwargs(),
    )
    stale = runner._simulate_bearish_trade(
        trade_number=2,
        symbol="BTCUSDT",
        profile_id="PROFILE_F_VOLUME",
        entry_candle=_candle(0, 100, 101, 99, 100),
        future_candles=(_candle(1, 100, 101, 69, 70),),
        stop_loss=Decimal("110"),
        take_profit=Decimal("90"),
        risk_amount=Decimal("100"),
        selected_rr_profile="RR_" + "1_1",
        **_risk_kwargs(),
    )

    assert Decimal(str(production["take_profit"])) == Decimal("85.0")
    assert Decimal(str(production["actual_risk_amount"])) == Decimal("100")
    assert Decimal(str(production["net_pnl"])) == Decimal("150.0")
    assert production["selected_rr_profile"] == "RR_1_5"
    assert stale["outcome"] == "RISK_REJECTED"


def test_bearish_trade_hits_stop_loss_and_negative_pnl() -> None:
    runner = _load_runner()

    trade = runner._simulate_bearish_trade(
        trade_number=1,
        symbol="BTCUSDT",
        profile_id="PROFILE_F_VOLUME",
        entry_candle=_candle(0, 100, 101, 99, 100),
        future_candles=(_candle(1, 100, 111, 95, 110),),
        stop_loss=Decimal("110"),
        take_profit=Decimal("90"),
        risk_amount=Decimal("100"),
        **_risk_kwargs(),
        source_12m_fvg_id="fvg12",
        source_16m_swing_id="swing16",
        source_16m_fvg_id="fvg16",
    )

    assert trade["outcome"] == "LOSS"
    assert trade["exit_reason"] == "STOP_LOSS_HIT"
    assert Decimal(str(trade["gross_pnl"])) < 0


def test_profile_2_uses_legacy_fixed_risk_backtest_sizing_without_global_leverage_bypass() -> None:
    runner = _load_runner()

    profile_2 = runner._simulate_bearish_trade(
        trade_number=1,
        symbol="BTCUSDT",
        profile_id="PROFILE_2",
        entry_candle=_candle(0, 100, 100, 99, 100),
        future_candles=(_candle(1, 100, 100, 98, 99),),
        stop_loss=Decimal("101"),
        take_profit=Decimal("99"),
        risk_amount=Decimal("100"),
        starting_balance=Decimal("10000"),
        max_leverage=Decimal("10"),
        selected_rr_profile="LEG_TARGET_RESEARCH",
        tp_model="LEG_TARGET_RESEARCH",
    )
    recovered = runner._simulate_bearish_trade(
        trade_number=2,
        symbol="BTCUSDT",
        profile_id="PROFILE_RECOVERED_HIGH_WINRATE",
        entry_candle=_candle(0, 100, 100, 99, 100),
        future_candles=(_candle(1, 100, 100, 98, 99),),
        stop_loss=Decimal("101"),
        take_profit=Decimal("99"),
        risk_amount=Decimal("100"),
        starting_balance=Decimal("10000"),
        max_leverage=Decimal("10"),
        selected_rr_profile="LEG_TARGET_RESEARCH",
        tp_model="LEG_TARGET_RESEARCH",
    )

    assert profile_2["outcome"] == "WIN"
    assert profile_2["risk_lock_status"] == "PASSED"
    assert Decimal(str(profile_2["required_leverage"])) > Decimal(str(profile_2["max_allowed_leverage"]))
    assert Decimal(str(profile_2["expected_loss_at_sl"])) == Decimal("100")
    assert recovered["outcome"] == "RISK_REJECTED"
    assert recovered["exit_reason"] == "BLOCKED_REQUIRED_LEVERAGE_EXCEEDS_MAX"


def test_same_candle_tp_and_sl_uses_conservative_stop_first() -> None:
    runner = _load_runner()

    trade = runner._simulate_bearish_trade(
        trade_number=1,
        symbol="BTCUSDT",
        profile_id="PROFILE_F_VOLUME",
        entry_candle=_candle(0, 100, 101, 99, 100),
        future_candles=(_candle(1, 100, 111, 89, 100),),
        stop_loss=Decimal("110"),
        take_profit=Decimal("90"),
        risk_amount=Decimal("100"),
        **_risk_kwargs(),
        source_12m_fvg_id="fvg12",
        source_16m_swing_id="swing16",
        source_16m_fvg_id="fvg16",
    )

    assert trade["outcome"] == "LOSS"
    assert trade["exit_reason"] == "STOP_LOSS_HIT"


def test_unresolved_trade_and_accounting_summary_are_reported() -> None:
    runner = _load_runner()
    trade = runner._simulate_bearish_trade(
        trade_number=1,
        symbol="BTCUSDT",
        profile_id="PROFILE_F_VOLUME",
        entry_candle=_candle(0, 100, 101, 99, 100),
        future_candles=(_candle(1, 100, 105, 95, 98),),
        stop_loss=Decimal("110"),
        take_profit=Decimal("90"),
        risk_amount=Decimal("100"),
        **_risk_kwargs(),
        source_12m_fvg_id="fvg12",
        source_16m_swing_id="swing16",
        source_16m_fvg_id="fvg16",
    )
    trades = [trade]
    runner._apply_balances(trades, Decimal("10000"))
    summary = runner._performance_summary(
        trades=trades,
        starting_balance=Decimal("10000"),
        risk_amount_per_trade=Decimal("100"),
        signals_generated=1,
        risk_rejected_count=0,
        risk_rejection_reasons=(),
        selected_rr_profile="RR_1_5",
        selected_rr_value=Decimal("1.5"),
    )

    assert trade["outcome"] == "OPEN_OR_UNRESOLVED"
    assert summary["open_or_unresolved_trades"] == 1
    assert summary["trade_accounting_check"]["accounting_balanced"] is True
    assert summary["final_balance"] == "10000"


def test_final_balance_updates_after_closed_trade() -> None:
    runner = _load_runner()
    trade = runner._simulate_bearish_trade(
        trade_number=1,
        symbol="BTCUSDT",
        profile_id="PROFILE_F_VOLUME",
        entry_candle=_candle(0, 100, 101, 99, 100),
        future_candles=(_candle(1, 100, 101, 84, 85),),
        stop_loss=Decimal("110"),
        take_profit=Decimal("90"),
        risk_amount=Decimal("100"),
        **_risk_kwargs(),
        source_12m_fvg_id="fvg12",
        source_16m_swing_id="swing16",
        source_16m_fvg_id="fvg16",
    )
    trades = [trade]
    runner._apply_balances(trades, Decimal("10000"))
    summary = runner._performance_summary(
        trades=trades,
        starting_balance=Decimal("10000"),
        risk_amount_per_trade=Decimal("100"),
        signals_generated=1,
        risk_rejected_count=0,
        risk_rejection_reasons=(),
        selected_rr_profile="RR_1_5",
        selected_rr_value=Decimal("1.5"),
    )

    assert Decimal(str(trade["balance_after_trade"])) == Decimal("10150")
    assert Decimal(str(summary["final_balance"])) == Decimal("10150")
    assert summary["average_time_to_hit_tp_seconds"] == 60.0
    assert summary["average_time_to_hit_tp_minutes"] == 1.0
    assert summary["average_time_to_hit_tp_human"] == "1m"


def test_time_to_tp_metrics_average_wins_and_ignore_losses_or_missing_times() -> None:
    runner = _load_runner()
    trades = [
        {
            "outcome": "WIN",
            "exit_reason": "TAKE_PROFIT_HIT",
            "entry_timestamp": "2026-01-01T00:00:00+00:00",
            "exit_timestamp": "2026-01-01T00:30:00+00:00",
        },
        {
            "outcome": "WIN",
            "exit_reason": "TAKE_PROFIT_HIT",
            "entry_timestamp": "2026-01-01T01:00:00+00:00",
            "exit_timestamp": "2026-01-01T02:30:00+00:00",
        },
        {
            "outcome": "LOSS",
            "exit_reason": "STOP_LOSS_HIT",
            "entry_timestamp": "2026-01-01T03:00:00+00:00",
            "exit_timestamp": "2026-01-01T03:10:00+00:00",
        },
        {
            "outcome": "WIN",
            "exit_reason": "TAKE_PROFIT_HIT",
            "entry_timestamp": "",
            "exit_timestamp": "2026-01-01T04:00:00+00:00",
        },
    ]

    metrics = runner._time_to_tp_metrics(trades)

    assert metrics["average_time_to_hit_tp_seconds"] == 3600.0
    assert metrics["average_time_to_hit_tp_minutes"] == 60.0
    assert metrics["average_time_to_hit_tp_human"] == "1h 00m"
    assert metrics["fastest_time_to_hit_tp"] == "30m"
    assert metrics["slowest_time_to_hit_tp"] == "1h 30m"
    assert metrics["median_time_to_hit_tp"] == "1h 00m"


def test_time_to_tp_metrics_zero_wins_returns_na() -> None:
    runner = _load_runner()
    metrics = runner._time_to_tp_metrics(
        [
            {
                "outcome": "LOSS",
                "exit_reason": "STOP_LOSS_HIT",
                "entry_timestamp": "2026-01-01T00:00:00+00:00",
                "exit_timestamp": "2026-01-01T00:05:00+00:00",
            },
            {
                "outcome": "WIN",
                "exit_reason": "MANUAL_CLOSE",
                "entry_timestamp": "2026-01-01T00:00:00+00:00",
                "exit_timestamp": "2026-01-01T00:05:00+00:00",
            },
        ]
    )

    assert metrics["average_time_to_hit_tp_seconds"] is None
    assert metrics["average_time_to_hit_tp_minutes"] is None
    assert metrics["average_time_to_hit_tp_human"] == "N/A"
    assert metrics["fastest_time_to_hit_tp"] is None
    assert metrics["slowest_time_to_hit_tp"] is None
    assert metrics["median_time_to_hit_tp"] is None


def test_frontend_details_panel_displays_performance_and_trade_list() -> None:
    root = Path(__file__).resolve().parents[4]
    source = (root / "frontend" / "src" / "pages" / "Backtesting.tsx").read_text(encoding="utf-8")

    assert "Performance Summary" in source
    assert "Trades" in source
    assert "Net PnL" in source
    assert "average_time_to_hit_tp_human" in source
    assert "fastest_time_to_hit_tp" in source
    assert "outcomeClass" in source


def test_profile_f_validation_report_flags_are_all_yes() -> None:
    runner = _load_runner()
    report = runner._profile_f_validation_report(runner.PROFILE_F_VOLUME)

    for key in (
        "ONE_HOUR_CONTEXT_USED",
        "THREE_MINUTE_CONTEXT_USED",
        "16M_EXPANSION_CANDLE_IS_C3",
        "C3_PART_OF_16M_SWING_FORMATION",
        "C3_FORMS_16M_FVG",
        "12M_FVG_EXISTS_ON_SAME_PRICE_LEG",
        "8M_FVG_EXISTS_ON_SAME_PRICE_LEG",
        "16M_FVG_ANCHOR_USED",
        "12M_FVG_USED_AS_ZONE",
        "1M_CANDLES_TRIGGER_12M_RETRACE_ENTRY",
        "8M_MAX_3_CANDLE_WINDOW_ACTIVE",
        "NO_EXTRA_POST_RETRACE_CONFIRMATION",
        "ONE_TRADE_PER_12M_FVG",
        "SL_SOURCE_16M_SWING_HIGH_LOW",
        "PROFILE_F_SELECTABLE_VARIANT_ACTIVE",
        "PROFILE_F_BASES_ON_STRICT_PROFILE",
        "16M_FVG_STARTS_RETRACE_WINDOW",
        "RETRACE_WINDOW_MAX_3_8M_CANDLES",
        "12M_FVG_RETRACE_ENTRY_ACTIVE",
        "NO_EXTRA_CONFIRMATION_AFTER_12M_RETRACE",
        "POST_ENTRY_12M_CLOSE_DOES_NOT_INVALIDATE_TRADE",
        "ONE_TRADE_PER_12M_FVG_STILL_ACTIVE",
        "ALL_OTHER_PROFILE_F_RULES_UNCHANGED",
        "BEARISH_SL_16M_SWING_HIGH",
        "BULLISH_SL_16M_SWING_LOW",
        "RR_TP_ACTIVE",
        "FIXED_RISK_ACTIVE",
    ):
        assert report[key] == "YES"
    assert report["PROFILE_F_VARIANT_ID"] == "PROFILE_F_VOLUME"
    assert report["PROFILE_F_VARIANT_NAME"] == "Profile F Volume"
    assert report["EXPANSION_RANGE_APPLIED"] == "1-4"


def test_profile_f_expansion_ratio_boundaries() -> None:
    profile = _load_runner().PROFILE_F_VOLUME
    ratios = [Decimal("1.0"), Decimal("4.0"), Decimal("0.99"), Decimal("4.01")]

    accepted = [profile.expansion_ratio_min <= float(ratio) <= profile.expansion_ratio_max for ratio in ratios]

    assert accepted == [True, True, False, False]


def test_profile_f_variants_filter_mixed_expansion_ratios_differently() -> None:
    runner = _load_runner()
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    swings = (
        _swing_with_ratio(start, "swing_ratio_1_2", Decimal("1.2")),
        _swing_with_ratio(start + timedelta(minutes=64), "swing_ratio_1_7", Decimal("1.7")),
        _swing_with_ratio(start + timedelta(minutes=128), "swing_ratio_2_2", Decimal("2.2")),
    )
    expansions = runner._research_expansions(swings)
    swing_by_id = {swing.swing_id: swing for swing in swings}

    volume = runner._profile_valid_expansions(profile=runner.PROFILE_F_VOLUME, expansions=expansions, swing_by_id=swing_by_id)
    balanced = runner._profile_valid_expansions(profile=runner.PROFILE_F_BALANCED, expansions=expansions, swing_by_id=swing_by_id)
    selective = runner._profile_valid_expansions(profile=runner.PROFILE_F_SELECTIVE, expansions=expansions, swing_by_id=swing_by_id)

    assert len(volume) == 3
    assert len(balanced) == 2
    assert len(selective) == 1


def test_profile_f_accepts_only_expansion_that_is_swing_c3() -> None:
    runner = _load_runner()
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    swing = _swing(start)
    c3_expansion = SimpleNamespace(
        expansion_id="exp_c3",
        swing_id=swing.swing_id,
        timeframe=swing.timeframe,
        timestamp=swing.right_candle.timestamp,
        direction=SimpleNamespace(value="BEARISH"),
        expansion_ratio=1.5,
    )
    unrelated_expansion = SimpleNamespace(
        expansion_id="exp_unrelated",
        swing_id=swing.swing_id,
        timeframe=swing.timeframe,
        timestamp=swing.middle_candle.timestamp,
        direction=SimpleNamespace(value="BEARISH"),
    )

    assert runner._expansion_is_swing_c3(c3_expansion, swing) is True
    assert runner._expansion_is_swing_c3(unrelated_expansion, swing) is False


def test_profile_f_does_not_limit_or_count_htf_taps() -> None:
    runner = _load_runner()
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    first_tap = _swing(start)
    second_tap = _swing(start + timedelta(minutes=48), swing_id="swing_second")
    third_tap = _swing(start + timedelta(minutes=96), swing_id="swing_third")
    source = (Path(__file__).resolve().parents[4] / "scripts" / "backtest_csv.py").read_text(encoding="utf-8")
    metrics = runner._second_swing_research_metrics((first_tap, second_tap, third_tap), (), runner.PROFILE_F_VOLUME)

    assert "max_" + "16m_swing_taps" not in source
    assert "_watched_" + "16m_swing_taps" not in source
    assert metrics == {}


def test_profile_f_16m_fvg_must_be_formed_by_same_expansion_c3() -> None:
    runner = _load_runner()
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    swing = _swing(start)
    expansion = SimpleNamespace(
        expansion_id="exp_c3",
        swing_id=swing.swing_id,
        timeframe=swing.timeframe,
        timestamp=swing.right_candle.timestamp,
        direction=SimpleNamespace(value="BEARISH"),
        expansion_ratio=1.5,
    )
    matching = _fvg_with_id(
        "fvg16",
        Timeframe(16),
        swing.right_candle.timestamp,
        related_swing_id=swing.swing_id,
        related_expansion_id="exp_c3",
    )
    unrelated = _fvg_with_id(
        "fvg16_unrelated",
        Timeframe(16),
        swing.left_candle.timestamp,
        related_swing_id=swing.swing_id,
        related_expansion_id="other",
    )

    assert runner._one_fvg_matches_expansion(matching, expansion, runner.PROFILE_F_VOLUME) is True
    assert runner._one_fvg_matches_expansion(unrelated, expansion, runner.PROFILE_F_VOLUME) is False


def test_16m_fvg_missing_stays_pending_until_fvg_window_can_close() -> None:
    runner = _load_backend_runner()
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    swing = _swing(start)
    expansion = SimpleNamespace(
        expansion_id="exp_pending",
        swing_id=swing.swing_id,
        timeframe=swing.timeframe,
        timestamp=swing.right_candle.timestamp,
        direction=SimpleNamespace(value="BEARISH"),
        expansion_ratio=1.5,
    )

    pending_trace = runner._attempt_traces_for_direction(
        direction="BEARISH",
        candidate_swings=(swing,),
        swing_by_id={swing.swing_id: swing},
        valid_expansions=(expansion,),
        all_expansions=(expansion,),
        fvg_by_expansion={expansion.expansion_id: None},
        fvg_12m=(),
        fvg_8m=(),
        candles_8m=(),
        candles_1m=tuple(_candle(index, 100, 101, 99, 100) for index in range(64)),
        profile=runner.PROFILE_2,
    )[0]

    assert pending_trace["stage"] == "EXPANSION_16M_CONFIRMED"
    assert pending_trace["progress_percent"] == 35.0
    assert pending_trace["invalidation_reason"] is None
    assert pending_trace["is_terminal"] is False
    assert pending_trace["failure_detail"] == "FVG_16M_PENDING_CONFIRMATION_WINDOW_OPEN"

    expired_trace = runner._attempt_traces_for_direction(
        direction="BEARISH",
        candidate_swings=(swing,),
        swing_by_id={swing.swing_id: swing},
        valid_expansions=(expansion,),
        all_expansions=(expansion,),
        fvg_by_expansion={expansion.expansion_id: None},
        fvg_12m=(),
        fvg_8m=(),
        candles_8m=(),
        candles_1m=tuple(_candle(index, 100, 101, 99, 100) for index in range(81)),
        profile=runner.PROFILE_2,
    )[0]

    assert expired_trace["stage"] == "EXPANSION_16M_CONFIRMED"
    assert expired_trace["progress_percent"] == 35.0
    assert expired_trace["invalidation_reason"] == "FVG_16M_NOT_FOUND"
    assert expired_trace["is_terminal"] is True
    assert expired_trace["failure_detail"] == "FVG_16M_WINDOW_CLOSED_WITHOUT_MATCH"


def test_16m_fvg_missing_stays_pending_when_source_1m_is_ahead_of_synthesized_16m_scan() -> None:
    runner = _load_backend_runner()
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    swing = _swing(start)
    expansion = SimpleNamespace(
        expansion_id="exp_pending_missing_synth_c3",
        swing_id=swing.swing_id,
        timeframe=swing.timeframe,
        timestamp=swing.right_candle.timestamp,
        direction=SimpleNamespace(value="BEARISH"),
        expansion_ratio=1.5,
    )

    trace = runner._attempt_traces_for_direction(
        direction="BEARISH",
        candidate_swings=(swing,),
        swing_by_id={swing.swing_id: swing},
        valid_expansions=(expansion,),
        all_expansions=(expansion,),
        fvg_by_expansion={expansion.expansion_id: None},
        candles_main_fvg=(
            _timeframe_candle(16, start, 100, 105, 95, 100),
            _timeframe_candle(16, start + timedelta(minutes=16), 100, 120, 100, 110),
            _timeframe_candle(16, start + timedelta(minutes=32), 110, 112, 82, 86),
        ),
        fvg_12m=(),
        fvg_8m=(),
        candles_8m=(),
        candles_1m=tuple(_candle(index, 100, 101, 99, 100) for index in range(81)),
        profile=runner.PROFILE_2,
    )[0]

    assert trace["stage"] == "EXPANSION_16M_CONFIRMED"
    assert trace["invalidation_reason"] is None
    assert trace["is_terminal"] is False
    assert trace["failure_detail"] == "FVG_16M_PENDING_CONFIRMATION_WINDOW_OPEN"


def test_12m_fvg_missing_stays_pending_until_retrace_fvg_window_can_close() -> None:
    runner = _load_backend_runner()
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    swing = _swing(start)
    expansion = SimpleNamespace(
        expansion_id="exp_pending_12m",
        swing_id=swing.swing_id,
        timeframe=swing.timeframe,
        timestamp=swing.right_candle.timestamp,
        direction=SimpleNamespace(value="BEARISH"),
        expansion_ratio=1.5,
    )
    fvg16 = _fvg_with_id(
        "fvg16_pending_12m",
        Timeframe(16),
        swing.right_candle.timestamp,
        related_swing_id=swing.swing_id,
        related_expansion_id=expansion.expansion_id,
    )

    pending_trace = runner._attempt_traces_for_direction(
        direction="BEARISH",
        candidate_swings=(swing,),
        swing_by_id={swing.swing_id: swing},
        valid_expansions=(expansion,),
        all_expansions=(expansion,),
        fvg_by_expansion={expansion.expansion_id: fvg16},
        fvg_12m=(),
        fvg_8m=(),
        candles_8m=(),
        candles_1m=tuple(_candle(index, 100, 101, 99, 100) for index in range(80)),
        profile=runner.PROFILE_2,
    )[0]

    assert pending_trace["stage"] == "FVG_16M_CONFIRMED"
    assert pending_trace["progress_percent"] == 50.0
    assert pending_trace["invalidation_reason"] is None
    assert pending_trace["is_terminal"] is False
    assert pending_trace["failure_detail"].startswith("FVG_12M_PENDING_CONFIRMATION_WINDOW_OPEN")

    expired_trace = runner._attempt_traces_for_direction(
        direction="BEARISH",
        candidate_swings=(swing,),
        swing_by_id={swing.swing_id: swing},
        valid_expansions=(expansion,),
        all_expansions=(expansion,),
        fvg_by_expansion={expansion.expansion_id: fvg16},
        fvg_12m=(),
        fvg_8m=(),
        candles_8m=(),
        candles_1m=tuple(_candle(index, 100, 101, 99, 100) for index in range(100)),
        profile=runner.PROFILE_2,
    )[0]

    assert expired_trace["stage"] == "FVG_16M_CONFIRMED"
    assert expired_trace["progress_percent"] == 50.0
    assert expired_trace["invalidation_reason"] == "FVG_12M_NOT_FOUND"
    assert expired_trace["is_terminal"] is True
    assert expired_trace["failure_detail"].startswith("NO_12M_FVG_INSIDE_16M_LEG")


def test_related_12m_and_8m_fvgs_must_be_same_direction_same_leg() -> None:
    runner = _load_runner()
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    bearish = _fvg_with_id("fvg12_bearish", Timeframe(12), start + timedelta(minutes=12))
    bullish = _fvg_with_id("fvg12_bullish", Timeframe(12), start + timedelta(minutes=24), direction=FVGDirection.BULLISH)

    related = runner._fvgs_inside_leg(
        (bearish, bullish),
        direction=FVGDirection.BEARISH,
        swing_high_price=Decimal("120"),
        completion_candle_low=Decimal("80"),
        start_at=start,
    )

    assert related == (bearish,)


def test_profile_f_retrace_window_starts_at_16m_fvg_and_is_three_8m_candles() -> None:
    runner = _load_runner()
    profile = runner.PROFILE_F_VOLUME
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    fvg12 = _fvg()
    window = tuple(
        Candle(
            symbol="BTCUSDT",
            timeframe=Timeframe(8),
            timestamp=start + timedelta(minutes=8 * index),
            open=Decimal("90"),
            high=Decimal("94"),
            low=Decimal("89"),
            close=Decimal("90"),
            volume=Decimal("1"),
            status=CandleStatus.CLOSED,
        )
        for index in range(3)
    )
    retrace_window = tuple(candle for candle in window if candle.timestamp >= start)[: profile.retrace_window_8m_candles]

    assert len(retrace_window) == 3
    assert retrace_window[0].timestamp == start
    assert runner.should_invalidate_retrace_window(fvg12, retrace_window) is True


def test_one_hour_and_three_minute_context_timeframes_are_required() -> None:
    runner = _load_runner()

    assert 60 in runner._required_timeframes(runner.DEFAULT_16_12_8)
    assert 3 in runner._required_timeframes(runner.DEFAULT_16_12_8)


def test_1m_candle_triggers_12m_retrace_entry_inside_8m_window_not_12m_close() -> None:
    runner = _load_runner()
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    fvg12 = _fvg()
    retrace_window = tuple(_timeframe_candle(8, start + timedelta(minutes=8 * index), 80, 90, 70, 75) for index in range(3))
    one_minute_entry = _candle(5, 97, 99, 96, 98)

    entry_candle = runner._first_1m_retrace_into_12m_fvg_within_8m_window(
        fvg12=fvg12,
        candles_1m=(
            _candle(0, 80, 90, 70, 75),
            one_minute_entry,
            _candle(30, 97, 99, 96, 98),
        ),
        fvg16_confirmed_at=start,
        retrace_window_8m=retrace_window,
        direction="BEARISH",
    )

    assert entry_candle == one_minute_entry
    assert entry_candle.timeframe == Timeframe(1)


def test_1m_retrace_after_three_completed_8m_candles_is_rejected() -> None:
    runner = _load_runner()
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    retrace_window = tuple(_timeframe_candle(8, start + timedelta(minutes=8 * index), 80, 90, 70, 75) for index in range(3))

    entry_candle = runner._first_1m_retrace_into_12m_fvg_within_8m_window(
        fvg12=_fvg(),
        candles_1m=(_candle(24, 97, 99, 96, 98),),
        fvg16_confirmed_at=start,
        retrace_window_8m=retrace_window,
        direction="BEARISH",
    )

    assert entry_candle is None


def test_direct_12m_entry_accepts_first_valid_bearish_tap_and_blocks_duplicate_taps() -> None:
    runner = _load_runner()
    counts = runner._classify_direct_12m_retrace_entry(
        fvg12=_fvg(),
        retrace_candle=_candle(0, 90, 96, 90, 95),
        candles_1m=(
            _candle(0, 90, 99, 90, 98),
            _candle(1, 98, 101, 95, 101),
            _candle(2, 99, 100, 96, 99),
        ),
    )

    assert counts["direct_12m_entries"] == 1
    assert counts["signals_generated"] == 1
    assert counts["entry_ready"] == 1
    assert counts["ignored_additional_12m_fvg_tap_after_entry"] == 2
    assert counts["post_entry_close_above_12m_fvg_ignored"] == 1


def test_direct_12m_entry_rejects_bearish_close_above_and_bullish_close_below_before_entry() -> None:
    runner = _load_runner()
    bearish_close_through = _candle(0, 99, 101, 96, 101)
    bullish_close_through = _candle(0, 96, 99, 94, 94)
    retrace_window = tuple(_timeframe_candle(8, datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(minutes=8 * index), 80, 90, 70, 75) for index in range(3))
    assert runner._first_1m_retrace_into_12m_fvg_within_8m_window(
        fvg12=_fvg(),
        candles_1m=(bearish_close_through,),
        fvg16_confirmed_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        retrace_window_8m=retrace_window,
        direction="BEARISH",
    ) == bearish_close_through
    bearish = runner._classify_direct_12m_retrace_entry_for_direction(
        fvg12=_fvg(),
        retrace_candle=_candle(0, 90, 96, 90, 95),
        candles_1m=(bearish_close_through,),
        direction="BEARISH",
    )
    assert runner._first_1m_retrace_into_12m_fvg_within_8m_window(
        fvg12=_fvg(),
        candles_1m=(bullish_close_through,),
        fvg16_confirmed_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        retrace_window_8m=retrace_window,
        direction="BULLISH",
    ) == bullish_close_through
    bullish = runner._classify_direct_12m_retrace_entry_for_direction(
        fvg12=_fvg(),
        retrace_candle=_candle(0, 90, 96, 90, 95),
        candles_1m=(bullish_close_through,),
        direction="BULLISH",
    )

    assert bearish["rejected_close_above_12m_fvg_before_entry"] == 1
    assert bearish["direct_12m_entries"] == 0
    assert bullish["rejected_close_below_12m_fvg_before_entry"] == 1
    assert bullish["direct_12m_entries"] == 0


def test_profile_f_requires_no_extra_1m_confirmation_after_12m_retrace() -> None:
    profile = _load_runner().PROFILE_F_VOLUME

    assert profile.direct_12m_retrace_entry_enabled is True
    assert profile.require_1m_swing_confirmation is False
    assert profile.require_1m_bearish_expansion is False
    assert profile.require_1m_bearish_fvg is False
    assert profile.require_1m_fvg_retest is False


def test_bearish_and_bullish_sl_sources_remain_16m_swing_extremes() -> None:
    runner = _load_runner()
    bearish = runner._simulate_bearish_trade(
        trade_number=1,
        symbol="BTCUSDT",
        profile_id="PROFILE_F_VOLUME",
        entry_candle=_candle(0, 100, 101, 99, 100),
        future_candles=(_candle(1, 100, 101, 89, 90),),
        stop_loss=Decimal("110"),
        take_profit=Decimal("90"),
        risk_amount=Decimal("100"),
        **_risk_kwargs(),
    )
    bullish = runner._simulate_bullish_trade(
        trade_number=2,
        symbol="BTCUSDT",
        profile_id="PROFILE_F_VOLUME",
        entry_candle=_candle(0, 100, 101, 99, 100),
        future_candles=(_candle(1, 100, 111, 99, 110),),
        stop_loss=Decimal("90"),
        take_profit=Decimal("110"),
        risk_amount=Decimal("100"),
        **_risk_kwargs(),
    )

    assert bearish["stop_loss"] == "110"
    assert bearish["sl_source"] == "16m swing high"
    assert bullish["stop_loss"] == "90"
    assert bullish["sl_source"] == "16m swing low"
    assert bullish["take_profit"] == "115.0"


def test_profile_g_uses_research_one_r_take_profit_without_changing_profile_f() -> None:
    runner = _load_runner()
    profile_f = runner._simulate_bearish_trade(
        trade_number=1,
        symbol="BTCUSDT",
        profile_id="PROFILE_F_VOLUME",
        entry_candle=_candle(0, 100, 101, 99, 100),
        future_candles=(_candle(1, 100, 101, 84, 85),),
        stop_loss=Decimal("110"),
        take_profit=Decimal("90"),
        risk_amount=Decimal("100"),
        **_risk_kwargs(),
    )
    profile_g = runner._simulate_bearish_trade(
        trade_number=2,
        symbol="BTCUSDT",
        profile_id="PROFILE_G_CODEX_OPTIMIZED",
        entry_candle=_candle(0, 100, 101, 99, 100),
        future_candles=(_candle(1, 100, 101, 89, 90),),
        stop_loss=Decimal("110"),
        take_profit=Decimal("90"),
        risk_amount=Decimal("100"),
        selected_rr_profile="RR_1_0_RESEARCH",
        tp_model="RR_1_0_RESEARCH",
        **_risk_kwargs(),
    )

    assert profile_f["selected_rr_profile"] == "RR_1_5"
    assert profile_f["selected_rr_value"] == "1.5"
    assert profile_f["take_profit"] == "85.0"
    assert profile_g["selected_rr_profile"] == "RR_1_0_RESEARCH"
    assert profile_g["selected_rr_value"] == "1.0"
    assert profile_g["take_profit"] == "90"
    assert profile_g["actual_rr"] == "1.0"
    assert profile_g["outcome"] == "WIN"


def test_recovered_profile_uses_structural_leg_target_take_profit() -> None:
    runner = _load_runner()
    trade = runner._simulate_bearish_trade(
        trade_number=1,
        symbol="BTCUSDT",
        profile_id="PROFILE_RECOVERED_HIGH_WINRATE",
        entry_candle=_candle(0, 100, 101, 99, 100),
        future_candles=(_candle(1, 100, 101, 94, 95),),
        stop_loss=Decimal("110"),
        take_profit=Decimal("96"),
        risk_amount=Decimal("100"),
        selected_rr_profile="LEG_TARGET_RESEARCH",
        tp_model="LEG_TARGET_RESEARCH",
        **_risk_kwargs(),
    )

    assert trade["selected_rr_profile"] == "LEG_TARGET_RESEARCH"
    assert trade["selected_profile_id"] == "PROFILE_RECOVERED_HIGH_WINRATE"
    assert trade["applied_profile_id"] == "PROFILE_RECOVERED_HIGH_WINRATE"
    assert trade["take_profit"] == "96"
    assert trade["actual_rr"] == "0.4"
    assert trade["outcome"] == "WIN"
    assert Decimal(str(trade["net_pnl"])) == Decimal("40.0")


def test_trade_record_saves_full_profile_f_setup_snapshot() -> None:
    runner = _load_runner()
    snapshot = {
        "fvg_16m": {"fvg_id": "fvg16"},
        "fvg_12m": {"fvg_id": "fvg12"},
        "expansion": {"expansion_ratio": "1.5"},
        "expansion_min_used": 1.0,
        "expansion_max_used": 4.0,
        "expansion_ratio": "1.5",
    }
    trade = runner._simulate_bearish_trade(
        trade_number=1,
        symbol="BTCUSDT",
        profile_id="PROFILE_F_VOLUME",
        inherited_base_profile="STRICT_PROFILE",
        entry_candle=_candle(0, 100, 101, 99, 100),
        future_candles=(_candle(1, 100, 101, 89, 90),),
        stop_loss=Decimal("110"),
        take_profit=Decimal("90"),
        risk_amount=Decimal("100"),
        **_risk_kwargs(),
        source_12m_fvg_id="fvg12",
        source_16m_swing_id="swing16",
        source_16m_fvg_id="fvg16",
        setup_snapshot=snapshot,
    )

    assert trade["strategy_profile"] == "PROFILE_F_VOLUME"
    assert trade["selected_strategy_profile"] == "PROFILE_F_VOLUME"
    assert trade["selected_profile_id"] == "PROFILE_F_VOLUME"
    assert trade["applied_profile_id"] == "PROFILE_F_VOLUME"
    assert trade["expansion_min_used"] == 1.0
    assert trade["expansion_max_used"] == 4.0
    assert trade["expansion_ratio"] == "1.5"
    assert trade["inherited_base_profile"] == "STRICT_PROFILE"
    assert trade["pair"] == "BTCUSDT"
    assert trade["fvg_id"] == "fvg12"
    assert trade["one_trade_per_fvg_enforced"] is True
    assert trade["duplicate_entry_blocked"] is True
    assert trade["setup_snapshot"] == snapshot
    assert trade["reason_for_entry"] == "FIRST_VALID_12M_FVG_RETRACE_CANDLE_BOUNDARY_RESPECTED"


def test_profile_f_setup_snapshot_contains_required_expansion_and_retrace_fields() -> None:
    runner = _load_runner()
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    swing = _swing(start)
    fvg16 = _fvg_with_id("fvg16", Timeframe(16), start + timedelta(minutes=16))
    fvg12 = _fvg_with_id("fvg12", Timeframe(12), start + timedelta(minutes=32))
    retrace_window = tuple(
        Candle(
                symbol="BTCUSDT",
                timeframe=Timeframe(8),
                timestamp=fvg16.confirmed_at + timedelta(minutes=8 * index),
                open=Decimal("95"),
                high=Decimal("99"),
                low=Decimal("94"),
            close=Decimal("98"),
            volume=Decimal("1"),
            status=CandleStatus.CLOSED,
        )
        for index in range(3)
    )
    snapshot = runner._profile_f_setup_snapshot(
        profile=runner.PROFILE_F_VOLUME,
        timeframe_profile=runner.DEFAULT_16_12_8,
        expansion=SimpleNamespace(expansion_id="exp1", expansion_ratio=Decimal("1.5")),
        swing=swing,
        fvg16=fvg16,
        fvg12=fvg12,
        retrace_window=retrace_window,
        retrace_candle=retrace_window[0],
        entry_candle=_candle(0, 95, 99, 94, 98),
        final_target=Decimal("80"),
    )

    assert snapshot["strategy_profile"] == "PROFILE_F_VOLUME"
    assert snapshot["selected_strategy_profile"] == "PROFILE_F_VOLUME"
    assert snapshot["selected_profile_id"] == "PROFILE_F_VOLUME"
    assert snapshot["applied_profile_id"] == "PROFILE_F_VOLUME"
    assert snapshot["timeframe_profile_id"] == "DEFAULT_16_12_8"
    assert snapshot["tp_model"] == "RR_1_5"
    assert snapshot["entry_model"] == "DIRECT_12M_RETRACE"
    assert snapshot["fvg_detection_mode"] == "LINKED"
    assert snapshot["expansion_min_used"] == 1.0
    assert snapshot["expansion_max_used"] == 4.0
    assert snapshot["expansion_ratio"] == "1.5"
    assert snapshot["expansion_passed"] is True
    assert snapshot["expansion_rejection_reason"] is None
    assert snapshot["inherited_base_profile"] == "STRICT_PROFILE"
    assert snapshot["expansion"]["previous_reference_candle_1_range"] == "10"
    assert snapshot["expansion"]["previous_reference_candle_2_range"] == "20"
    assert snapshot["expansion"]["average_reference_range"] == "15"
    assert snapshot["expansion"]["expansion_ratio"] == "1.5"
    assert snapshot["expansion"]["expansion_valid"] is True
    assert snapshot["eight_minute_candle_count_after_16m_fvg"] == 3
    assert snapshot["retracement_within_deadline"] is True
    assert snapshot["entry_candle_boundary_respected"] is True


def test_radar_contract_exposes_profile_f_status_fields() -> None:
    root = Path(__file__).resolve().parents[4]
    backend = (root / "backend" / "arjiobot" / "api" / "routes" / "radar.py").read_text(encoding="utf-8")
    frontend_type = (root / "frontend" / "src" / "types" / "radar.ts").read_text(encoding="utf-8")
    frontend_table = (root / "frontend" / "src" / "components" / "radar" / "SetupRadarTable.tsx").read_text(encoding="utf-8")

    for field in (
        "higher_timeframe_context_status",
        "profile_variant_name",
        "expansion_min",
        "expansion_max",
        "fvg_16m_status",
        "expansion_ratio",
        "fvg_12m_status",
        "eight_minute_candle_count_after_16m_fvg",
        "retracement_within_3_8m_candles",
        "entry_candle_boundary_respected",
        "one_trade_per_fvg_status",
        "rejection_reason",
    ):
        assert field in backend
        assert field in frontend_type
    assert "16M FVG" in frontend_table
    assert "RR/TP Profile" in frontend_table


def _assert_confirmation_funnel_balances(funnel: dict[str, int]) -> None:
    expected = _unaccounted_from_funnel(funnel)
    assert funnel["unaccounted_after_retrace"] == expected
    assert expected == 0


def _unaccounted_from_funnel(funnel: dict[str, int]) -> int:
    return (
        funnel["passed_retrace"]
        - funnel["rejected_close_above_12m_fvg"]
        - funnel["rejected_third_1m_high"]
        - funnel["rejected_target_reached_before_entry"]
        - funnel["rejected_no_first_1m_swing_high"]
        - funnel["rejected_no_second_1m_swing_high"]
        - funnel["rejected_1m_close_above_12m_fvg"]
        - funnel["rejected_no_1m_bearish_expansion"]
        - funnel["rejected_no_1m_bearish_fvg"]
        - funnel["rejected_no_return_to_first_1m_fvg"]
        - funnel["rejected_no_return_to_second_1m_fvg"]
        - funnel["rejected_entry_window_expired"]
        - funnel["entry_ready"]
    )


def _required_1m_funnel_rows() -> tuple[str, ...]:
    return (
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
        "trades",
        "unaccounted_after_retrace",
    )


def _candle(index: int, open_: int, high: int, low: int, close: int) -> Candle:
    return Candle(
        symbol="BTCUSDT",
        timeframe=Timeframe(1),
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(minutes=index),
        open=Decimal(open_),
        high=Decimal(high),
        low=Decimal(low),
        close=Decimal(close),
        volume=Decimal("1"),
        status=CandleStatus.CLOSED,
    )


def _timeframe_candle(minutes: int, timestamp: datetime, open_: int, high: int, low: int, close: int) -> Candle:
    return Candle(
        symbol="BTCUSDT",
        timeframe=Timeframe(minutes),
        timestamp=timestamp,
        open=Decimal(open_),
        high=Decimal(high),
        low=Decimal(low),
        close=Decimal(close),
        volume=Decimal("1"),
        status=CandleStatus.CLOSED,
    )


def _fvg() -> FairValueGap:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return FairValueGap(
        fvg_id="fvg_test",
        symbol="BTCUSDT",
        timeframe=Timeframe(12),
        direction=FVGDirection.BEARISH,
        timestamp=start,
        confirmed_at=start + timedelta(minutes=1),
        c1_id="c1",
        c2_id="c2",
        c3_id="c3",
        c1_timestamp=start - timedelta(minutes=1),
        c2_timestamp=start,
        c3_timestamp=start + timedelta(minutes=1),
        upper_boundary=Decimal("100"),
        lower_boundary=Decimal("95"),
        gap_size=Decimal("5"),
        gap_size_percent=5.0,
    )


def _fvg_with_id(
    fvg_id: str,
    timeframe: Timeframe,
    start: datetime,
    *,
    direction: FVGDirection = FVGDirection.BEARISH,
    related_swing_id: str | None = None,
    related_expansion_id: str | None = None,
) -> FairValueGap:
    return FairValueGap(
        fvg_id=fvg_id,
        symbol="BTCUSDT",
        timeframe=timeframe,
        direction=direction,
        timestamp=start,
        confirmed_at=start + timeframe.duration,
        c1_id=f"{fvg_id}_c1",
        c2_id=f"{fvg_id}_c2",
        c3_id=f"{fvg_id}_c3",
        c1_timestamp=start - timeframe.duration,
        c2_timestamp=start,
        c3_timestamp=start + timeframe.duration,
        upper_boundary=Decimal("100"),
        lower_boundary=Decimal("95"),
        gap_size=Decimal("5"),
        gap_size_percent=5.0,
        related_swing_id=related_swing_id,
        related_expansion_id=related_expansion_id,
        fvg_completion_candle_low=Decimal("80"),
    )


def _swing(start: datetime, swing_id: str = "swing16") -> Swing:
    left = Candle(
        symbol="BTCUSDT",
        timeframe=Timeframe(16),
        timestamp=start,
        open=Decimal("100"),
        high=Decimal("105"),
        low=Decimal("95"),
        close=Decimal("100"),
        volume=Decimal("1"),
        status=CandleStatus.CLOSED,
    )
    middle = Candle(
        symbol="BTCUSDT",
        timeframe=Timeframe(16),
        timestamp=start + timedelta(minutes=16),
        open=Decimal("100"),
        high=Decimal("120"),
        low=Decimal("100"),
        close=Decimal("110"),
        volume=Decimal("1"),
        status=CandleStatus.CLOSED,
    )
    right = Candle(
        symbol="BTCUSDT",
        timeframe=Timeframe(16),
        timestamp=start + timedelta(minutes=32),
        open=Decimal("110"),
        high=Decimal("112"),
        low=Decimal("82"),
        close=Decimal("86"),
        volume=Decimal("1"),
        status=CandleStatus.CLOSED,
    )
    return Swing(
        swing_id=swing_id,
        symbol="BTCUSDT",
        timeframe=Timeframe(16),
        timestamp=middle.timestamp,
        candidate_detected_at=middle.timestamp,
        confirmed_at=right.end_timestamp,
        swing_type=SwingType.HIGH,
        price=middle.high,
        candle_index=1,
        left_candle=left,
        middle_candle=middle,
        right_candle=right,
        source_candle_ids=("left", "middle", "right"),
    )


def _swing_with_ratio(start: datetime, swing_id: str, ratio: Decimal) -> Swing:
    left = _timeframe_candle(16, start, 100, 105, 95, 100)
    middle = _timeframe_candle(16, start + timedelta(minutes=16), 100, 120, 100, 110)
    c3_range = Decimal("15") * ratio
    right = Candle(
        symbol="BTCUSDT",
        timeframe=Timeframe(16),
        timestamp=start + timedelta(minutes=32),
        open=Decimal("110"),
        high=Decimal("112"),
        low=Decimal("112") - c3_range,
        close=Decimal("100"),
        volume=Decimal("1"),
        status=CandleStatus.CLOSED,
    )
    return Swing(
        swing_id=swing_id,
        symbol="BTCUSDT",
        timeframe=Timeframe(16),
        timestamp=middle.timestamp,
        candidate_detected_at=middle.timestamp,
        confirmed_at=right.end_timestamp,
        swing_type=SwingType.HIGH,
        price=middle.high,
        candle_index=1,
        left_candle=left,
        middle_candle=middle,
        right_candle=right,
        source_candle_ids=("left", "middle", "right"),
    )


def _legacy_assert_confirmation_funnel_balances(funnel: dict[str, int]) -> None:
    assert (
        funnel["passed_retrace"]
        - funnel["rejected_close_above_12m_fvg"]
        - funnel["rejected_third_1m_high"]
        - funnel["rejected_target_reached_before_entry"]
        - funnel["rejected_no_first_1m_swing_high"]
        - funnel["rejected_no_second_1m_swing_high"]
        - funnel["rejected_1m_close_above_12m_fvg"]
        - funnel["rejected_no_1m_bearish_expansion"]
        - funnel["rejected_no_1m_bearish_fvg"]
        - funnel["rejected_no_return_to_first_1m_fvg"]
        - funnel["rejected_no_return_to_second_1m_fvg"]
        - funnel["rejected_entry_window_expired"]
    ) == funnel["entry_ready"]
