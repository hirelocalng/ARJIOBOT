"""Production strategy profile configuration."""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True, slots=True)
class StrategyProfile:
    profile_id: str
    label: str
    production_safe: bool
    inherited_base_profile: str
    expansion_ratio_min: float
    expansion_ratio_max: float
    retrace_window_8m_candles: int
    fvg_delay_16m_candles: int
    direct_12m_retrace_entry_enabled: bool = True
    one_trade_per_12m_fvg: bool = True
    require_1m_swing_confirmation: bool = False
    require_1m_bearish_expansion: bool = False
    require_1m_bearish_fvg: bool = False
    require_1m_fvg_retest: bool = False
    timeframe_profile_id: str = "DEFAULT_16_12_8"
    tp_model: str = "RR_1_5"
    require_expansion_c3: bool = True
    use_linked_fvg_detection: bool = True
    main_fvg_match_mode: str = "C2_IMMEDIATE"
    main_fvg_match_window_candles: int = 0
    tunable_parameters: tuple[str, ...] = ()
    note: str = ""

    def to_record(self) -> dict[str, object]:
        return asdict(self)


STRICT_BASE_PROFILE = "STRICT_PROFILE"
DEFAULT_PROFILE_ID = "PROFILE_F_VOLUME"
PROFILE_F_VARIANT_IDS = ("PROFILE_F_VOLUME", "PROFILE_F_BALANCED", "PROFILE_F_SELECTIVE")
PROFILE_G_ID = "PROFILE_G_CODEX_OPTIMIZED"
PROFILE_RECOVERED_ID = "PROFILE_RECOVERED_HIGH_WINRATE"
PROFILE_2_ID = "PROFILE_2"


STRICT_PROFILE = StrategyProfile(
    profile_id=STRICT_BASE_PROFILE,
    label="Strict Profile - original Arjio strategy",
    production_safe=True,
    inherited_base_profile=STRICT_BASE_PROFILE,
    expansion_ratio_min=2.0,
    expansion_ratio_max=4.0,
    retrace_window_8m_candles=3,
    fvg_delay_16m_candles=0,
    direct_12m_retrace_entry_enabled=False,
    one_trade_per_12m_fvg=True,
    require_1m_swing_confirmation=True,
    require_1m_bearish_expansion=False,
    require_1m_bearish_fvg=False,
    require_1m_fvg_retest=False,
    note=(
        "Original strict Arjio strategy. Full 1M confirmation chain: "
        "swing high -> expansion -> FVG -> retest. Expansion ratio 2.0-4.0. "
        "Three completed 8M candle retrace window."
    ),
)


def _profile_f_variant(
    *,
    profile_id: str,
    label: str,
    expansion_ratio_min: float,
    expansion_ratio_max: float,
    note: str,
) -> StrategyProfile:
    return StrategyProfile(
        profile_id=profile_id,
        label=label,
        production_safe=True,
        inherited_base_profile=STRICT_BASE_PROFILE,
        expansion_ratio_min=expansion_ratio_min,
        expansion_ratio_max=expansion_ratio_max,
        retrace_window_8m_candles=3,
        fvg_delay_16m_candles=0,
        direct_12m_retrace_entry_enabled=True,
        one_trade_per_12m_fvg=True,
        require_1m_swing_confirmation=False,
        require_1m_bearish_expansion=False,
        require_1m_bearish_fvg=False,
        require_1m_fvg_retest=False,
        note=note,
    )


PROFILE_F_VOLUME = _profile_f_variant(
    profile_id="PROFILE_F_VOLUME",
    label="Profile F Volume",
    expansion_ratio_min=1.0,
    expansion_ratio_max=4.0,
    note=(
        "Profile F Volume: highest-frequency production variant. "
        "Direct 12M FVG retrace entry, expansion ratio 1.0-4.0, "
        "three completed 8M candle retrace window, RR fixed at 1:1.5."
    ),
)

PROFILE_F_BALANCED = _profile_f_variant(
    profile_id="PROFILE_F_BALANCED",
    label="Profile F Balanced",
    expansion_ratio_min=1.5,
    expansion_ratio_max=4.0,
    note=(
        "Profile F Balanced: middle production variant. "
        "Direct 12M FVG retrace entry, expansion ratio 1.5-4.0, "
        "three completed 8M candle retrace window, RR fixed at 1:1.5."
    ),
)

PROFILE_F_SELECTIVE = _profile_f_variant(
    profile_id="PROFILE_F_SELECTIVE",
    label="Profile F Selective",
    expansion_ratio_min=2.0,
    expansion_ratio_max=4.0,
    note=(
        "Profile F Selective: most selective production variant. "
        "Direct 12M FVG retrace entry, expansion ratio 2.0-4.0, "
        "three completed 8M candle retrace window, RR fixed at 1:1.5."
    ),
)

PROFILE_G_CODEX_OPTIMIZED = StrategyProfile(
    profile_id=PROFILE_G_ID,
    label="Profile G Codex Optimized",
    production_safe=False,
    inherited_base_profile=STRICT_BASE_PROFILE,
    expansion_ratio_min=1.0,
    expansion_ratio_max=4.0,
    retrace_window_8m_candles=3,
    fvg_delay_16m_candles=0,
    direct_12m_retrace_entry_enabled=True,
    one_trade_per_12m_fvg=True,
    require_1m_swing_confirmation=False,
    require_1m_bearish_expansion=False,
    require_1m_bearish_fvg=False,
    require_1m_fvg_retest=False,
    timeframe_profile_id="DEFAULT_16_12_8",
    tp_model="RR_1_0_RESEARCH",
    tunable_parameters=(
        "timeframe_profile_id",
        "expansion_ratio_min",
        "expansion_ratio_max",
        "retrace_window_8m_candles",
        "tp_model",
        "direct_12m_retrace_entry_enabled",
    ),
    note=(
        "Research-only optimized profile selected from SOLUSDT April 2026 diagnostics. "
        "It keeps the Profile F direct 12M retrace entry model and broad 1.0-4.0 "
        "C3 expansion range, but uses a research-only 1R take-profit model because "
        "that variant produced the strongest trade count plus validation stability. "
        "Not approved for production, demo trading, or live trading."
    ),
)

PROFILE_RECOVERED_HIGH_WINRATE = StrategyProfile(
    profile_id=PROFILE_RECOVERED_ID,
    label="Profile Recovered High Winrate",
    production_safe=False,
    inherited_base_profile=STRICT_BASE_PROFILE,
    expansion_ratio_min=1.0,
    expansion_ratio_max=3.0,
    retrace_window_8m_candles=3,
    fvg_delay_16m_candles=0,
    direct_12m_retrace_entry_enabled=True,
    one_trade_per_12m_fvg=True,
    require_1m_swing_confirmation=False,
    require_1m_bearish_expansion=False,
    require_1m_bearish_fvg=False,
    require_1m_fvg_retest=False,
    timeframe_profile_id="PROFILE_15_10_5",
    tp_model="LEG_TARGET_RESEARCH",
    require_expansion_c3=False,
    use_linked_fvg_detection=False,
    main_fvg_match_mode="LEGACY_EXPANSION_OR_NEXT_CANDLE",
    main_fvg_match_window_candles=1,
    tunable_parameters=(
        "timeframe_profile_id",
        "expansion_ratio_min",
        "expansion_ratio_max",
        "retrace_window_8m_candles",
        "tp_model",
        "require_expansion_c3",
        "use_linked_fvg_detection",
        "main_fvg_match_mode",
        "main_fvg_match_window_candles",
        "direct_12m_retrace_entry_enabled",
    ),
    note=(
        "Recovered research-only profile from "
        "reports/backtests/research_comparison_bt_624f5cc97f161f27c9eaebb8.json. "
        "Formerly RESEARCH_PROFILE_F_DIRECT_12M_RETRACE_ENTRY. Uses the 15M/10M/5M "
        "timeframe stack, 1.0-3.0 C3 expansion range, direct 12M retrace entry, "
        "one trade per FVG, and variable structural leg target TP."
    ),
)

PROFILE_2 = StrategyProfile(
    profile_id=PROFILE_2_ID,
    label="Profile 2",
    production_safe=False,
    inherited_base_profile=STRICT_BASE_PROFILE,
    expansion_ratio_min=1.0,
    expansion_ratio_max=3.0,
    retrace_window_8m_candles=3,
    fvg_delay_16m_candles=0,
    direct_12m_retrace_entry_enabled=True,
    one_trade_per_12m_fvg=True,
    require_1m_swing_confirmation=False,
    require_1m_bearish_expansion=False,
    require_1m_bearish_fvg=False,
    require_1m_fvg_retest=False,
    timeframe_profile_id="DEFAULT_16_12_8",
    tp_model="LEG_TARGET_RESEARCH",
    require_expansion_c3=False,
    use_linked_fvg_detection=False,
    main_fvg_match_mode="LEGACY_EXPANSION_OR_NEXT_CANDLE",
    main_fvg_match_window_candles=1,
    tunable_parameters=(
        "timeframe_profile_id",
        "expansion_ratio_min",
        "expansion_ratio_max",
        "retrace_window_8m_candles",
        "tp_model",
        "require_expansion_c3",
        "use_linked_fvg_detection",
        "main_fvg_match_mode",
        "main_fvg_match_window_candles",
        "direct_12m_retrace_entry_enabled",
    ),
    note=(
        "Profile 2: recovered old Profile F from "
        "reports/backtests/research_comparison_bt_624f5cc97f161f27c9eaebb8.json. "
        "Formerly RESEARCH_PROFILE_F_DIRECT_12M_RETRACE_ENTRY. Always uses the 16M/12M/8M "
        "default timeframe stack, 1.0-3.0 expansion range, direct 12M retrace entry, "
        "unlinked legacy FVG matching, one trade per FVG, and structural leg target TP. "
        "Backtest reconstruction uses legacy fixed-risk sizing for this profile only."
    ),
)

PRODUCTION_PROFILES: tuple[StrategyProfile, ...] = (
    STRICT_PROFILE,
    PROFILE_F_VOLUME,
    PROFILE_F_BALANCED,
    PROFILE_F_SELECTIVE,
    PROFILE_G_CODEX_OPTIMIZED,
    PROFILE_RECOVERED_HIGH_WINRATE,
    PROFILE_2,
)

_PROFILE_MAP: dict[str, StrategyProfile] = {profile.profile_id: profile for profile in PRODUCTION_PROFILES}


def get_strategy_profiles() -> tuple[StrategyProfile, ...]:
    return PRODUCTION_PROFILES


def get_profile(profile_id: str | None) -> StrategyProfile:
    normalized = str(profile_id or DEFAULT_PROFILE_ID).strip().upper()
    profile = _PROFILE_MAP.get(normalized)
    if profile is not None:
        return profile
    raise ValueError(f"unknown strategy profile: {profile_id!r}")
