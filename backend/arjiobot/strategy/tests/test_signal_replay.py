"""Replay tests for Strategy Engine."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from arjiobot.strategy.demo_strategy import make_entry_ready_setup
from arjiobot.strategy.signal_replay import replay_signals
from arjiobot.strategy.strategy_engine import benchmark_strategy_engine, StrategyEngine


def test_replay_consistency() -> None:
    setup = make_entry_ready_setup()

    first = replay_signals((setup,))[0]
    second = replay_signals((setup,))[0]

    assert first.signal_id == second.signal_id
    assert first.status == second.status


def test_benchmark_behavior() -> None:
    setups = [
        make_entry_ready_setup(
            symbol=f"BTC{index}USDT",
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(minutes=index),
            suffix=str(index),
        )
        for index in range(20)
    ]
    metrics = benchmark_strategy_engine(StrategyEngine(), setups)

    assert metrics["setups"] == 20.0
    assert metrics["signals"] == 20.0
    assert metrics["setups_per_second"] >= 0.0

