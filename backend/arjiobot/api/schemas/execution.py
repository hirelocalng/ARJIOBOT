"""Execution API schemas."""

from __future__ import annotations

from pydantic import BaseModel


class ExecutionResponse(BaseModel):
    execution_id: str
    trade_plan_id: str
    symbol: str
    status: str
