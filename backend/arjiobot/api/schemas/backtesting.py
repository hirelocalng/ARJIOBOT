"""Backtesting API schemas."""

from __future__ import annotations

from pydantic import BaseModel


class BacktestRunRequest(BaseModel):
    symbol: str
    timeframe: str = "1M"
