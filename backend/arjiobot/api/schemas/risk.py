"""Risk API schemas."""

from __future__ import annotations

from pydantic import BaseModel


class TradePlanResponse(BaseModel):
    trade_plan_id: str
    signal_id: str
    symbol: str
    approval_status: str
