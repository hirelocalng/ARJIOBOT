from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

from arjiobot.api.routes.backtesting import _apply_time_based_exit
from arjiobot.live_automation import _order_payload_from_plan
from arjiobot.strategy.strategy_models import SignalAction


def test_time_based_exit_minutes_change_exit_price_and_timestamp() -> None:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    candles = tuple(
        SimpleNamespace(timestamp=start + timedelta(minutes=index), high=Decimal("110"), low=Decimal("80"), close=Decimal(str(100 - index)))
        for index in range(40)
    )
    summary = _summary_with_trade(start)

    five = _apply_time_based_exit(summary, candles=candles, time_exit_minutes=5, selected_tp_model="TIME_BASED_EXIT")
    thirty = _apply_time_based_exit(summary, candles=candles, time_exit_minutes=30, selected_tp_model="TIME_BASED_EXIT")
    five_trade = five["trade_list"][0]
    thirty_trade = thirty["trade_list"][0]

    assert five_trade["applied_tp_model"] == "TIME_BASED_EXIT"
    assert five_trade["time_exit_minutes"] == 5
    assert five_trade["exit_reason"] == "TIME_BASED_EXIT"
    assert five_trade["actual_exit_timestamp"] != thirty_trade["actual_exit_timestamp"]
    assert five_trade["exit_price"] != thirty_trade["exit_price"]


def test_time_based_exit_reports_data_unavailable_when_csv_ends_first() -> None:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    candles = tuple(
        SimpleNamespace(timestamp=start + timedelta(minutes=index), high=Decimal("99"), low=Decimal("80"), close=Decimal("95"))
        for index in range(10)
    )

    result = _apply_time_based_exit(_summary_with_trade(start), candles=candles, time_exit_minutes=120, selected_tp_model="TIME_BASED_EXIT")
    trade = result["trade_list"][0]

    assert trade["exit_reason"] == "DATA_UNAVAILABLE"
    assert trade["result"] == "DATA_UNAVAILABLE"
    assert result["strategy_funnel"]["time_based_exit_entry_parity"]["status"] == "PASSED"


def test_live_time_based_exit_payload_omits_normal_take_profit() -> None:
    plan = SimpleNamespace(
        selected_rr_profile="TIME_BASED_EXIT",
        metadata={"time_exit_enabled": "YES", "time_exit_minutes": "5", "planned_time_exit_at": "2026-01-01T00:05:00+00:00"},
        action=SignalAction.MARKET_SELL_READY,
        symbol="BTCUSDT",
        entry_reference_price=Decimal("100"),
        stop_loss_price=Decimal("110"),
        take_profit_price=None,
        risk_amount=Decimal("100"),
        max_allowed_leverage=Decimal("10"),
        trade_plan_id="tpl_time_exit",
        signal_id="sig_time_exit",
        setup_id="setup_time_exit",
    )
    state = SimpleNamespace(settings={"active_strategy_profile": "PROFILE_2", "time_exit_minutes": "5", "max_daily_loss": "500", "max_open_trades": 1})

    payload = _order_payload_from_plan(state, plan)

    assert payload["selected_tp_model"] == "TIME_BASED_EXIT"
    assert payload["time_exit_enabled"] is True
    assert payload["time_exit_minutes"] == "5"
    assert "take_profit" not in payload


def _summary_with_trade(entry_time: datetime) -> dict[str, object]:
    trade = {
        "trade_id": "trade_0001",
        "symbol": "BTCUSDT",
        "direction": "BEARISH",
        "entry_timestamp": entry_time.isoformat(),
        "entry_price": "100",
        "stop_loss": "120",
        "take_profit": "70",
        "position_size": "1",
        "fixed_risk_amount": "100",
        "outcome": "WIN",
        "net_pnl": "30",
        "gross_pnl": "30",
    }
    return {
        "selected_starting_balance": "10000",
        "trade_list": (trade,),
        "strategy_funnel": {"trade_list": (trade,), "performance_summary": {}},
    }
