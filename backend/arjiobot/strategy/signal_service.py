"""Service facade for the Strategy Engine."""

from __future__ import annotations

from arjiobot.strategy.strategy_engine import StrategyEngine


class SignalService(StrategyEngine):
    """Authoritative trade signal service."""

