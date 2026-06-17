"""Backtesting timeframe profile configuration."""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True, slots=True)
class BacktestTimeframeProfile:
    profile_id: str
    label: str
    swing_timeframe: int
    main_fvg_timeframe: int
    retrace_fvg_timeframe: int
    internal_fvg_timeframe: int
    retrace_window_timeframe: int

    def to_record(self) -> dict[str, object]:
        return {
            **asdict(self),
            "swing_timeframe_label": f"{self.swing_timeframe}M",
            "main_fvg_timeframe_label": f"{self.main_fvg_timeframe}M",
            "retrace_fvg_timeframe_label": f"{self.retrace_fvg_timeframe}M",
            "internal_fvg_timeframe_label": f"{self.internal_fvg_timeframe}M",
            "retrace_window_timeframe_label": f"{self.retrace_window_timeframe}M",
        }


DEFAULT_16_12_8 = BacktestTimeframeProfile("DEFAULT_16_12_8", "16M / 12M / 8M / 1M", 16, 16, 12, 8, 8)
PROFILE_15_10_5 = BacktestTimeframeProfile("PROFILE_15_10_5", "15M / 10M / 5M / 1M", 15, 15, 10, 5, 5)
PROFILE_30_16_8 = BacktestTimeframeProfile("PROFILE_30_16_8", "30M / 16M / 8M / 1M", 30, 16, 8, 8, 8)
PROFILE_12_8_4 = BacktestTimeframeProfile("PROFILE_12_8_4", "12M / 8M / 4M / 1M", 12, 12, 8, 4, 4)
PROFILE_8_4_2 = BacktestTimeframeProfile("PROFILE_8_4_2", "8M / 4M / 2M / 1M", 8, 8, 4, 2, 2)
TIMEFRAME_PROFILES: tuple[BacktestTimeframeProfile, ...] = (
    DEFAULT_16_12_8,
    PROFILE_15_10_5,
    PROFILE_30_16_8,
    PROFILE_12_8_4,
    PROFILE_8_4_2,
)

ALIASES = {
    "ARJIO_V1": "DEFAULT_16_12_8",
    "16M / 12M / 8M": "DEFAULT_16_12_8",
    "16M / 12M / 8M / 1M": "DEFAULT_16_12_8",
    "15M / 10M / 5M": "PROFILE_15_10_5",
    "15M / 10M / 5M / 1M": "PROFILE_15_10_5",
    "30M / 16M / 8M": "PROFILE_30_16_8",
    "30M / 16M / 8M / 1M": "PROFILE_30_16_8",
    "12M / 8M / 4M": "PROFILE_12_8_4",
    "12M / 8M / 4M / 1M": "PROFILE_12_8_4",
    "8M / 4M / 2M": "PROFILE_8_4_2",
    "8M / 4M / 2M / 1M": "PROFILE_8_4_2",
}


def get_timeframe_profile(profile_id: str | None) -> BacktestTimeframeProfile:
    normalized = str(profile_id or "DEFAULT_16_12_8").strip().upper()
    normalized = ALIASES.get(normalized, normalized)
    for profile in TIMEFRAME_PROFILES:
        if profile.profile_id == normalized:
            return profile
    raise ValueError(f"unknown timeframe profile: {profile_id}")


def get_timeframe_profiles() -> tuple[BacktestTimeframeProfile, ...]:
    return TIMEFRAME_PROFILES
