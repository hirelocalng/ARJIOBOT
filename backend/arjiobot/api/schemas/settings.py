"""Settings API schemas."""

from __future__ import annotations

from pydantic import BaseModel


class SettingsUpdateRequest(BaseModel):
    default_timeframe_profile: str | None = None
    monitored_timeframes: list[str] | None = None
    max_open_trades: int | None = None
    max_daily_loss: str | None = None
    max_weekly_loss: str | None = None
    max_leverage: str | None = None
    risk_amount_per_trade: str | None = None
    adapter_mode: str | None = None
    live_trading_enabled: bool | None = None
