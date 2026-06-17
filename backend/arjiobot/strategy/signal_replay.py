"""Replay helpers for Strategy Engine."""

from __future__ import annotations

from typing import Iterable

from arjiobot.setup_tracker.setup_models import Setup
from arjiobot.strategy.strategy_engine import StrategyEngine
from arjiobot.strategy.strategy_models import TradeSignal


def replay_signals(setups: Iterable[Setup]) -> tuple[TradeSignal, ...]:
    """Replay setups through a fresh engine."""
    return StrategyEngine().replay_setups(setups)
