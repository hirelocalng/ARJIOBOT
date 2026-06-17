"""Signal API schemas."""

from __future__ import annotations

from pydantic import BaseModel


class SignalResponse(BaseModel):
    signal_id: str
    setup_id: str
    symbol: str
    status: str
    action: str
