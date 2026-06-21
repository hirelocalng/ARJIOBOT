"""Production strategy profile tests."""

import pytest

from arjiobot.backtesting.research_profiles import (
    DEFAULT_PROFILE_ID,
    PROFILE_F_BALANCED,
    PROFILE_F_SELECTIVE,
    PROFILE_F_VOLUME,
    PROFILE_G_CODEX_OPTIMIZED,
    PROFILE_2,
    PROFILE_RECOVERED_HIGH_WINRATE,
    STRICT_PROFILE,
    get_profile,
    get_strategy_profiles,
)


def test_production_profiles_are_exposed() -> None:
    profiles = get_strategy_profiles()
    profile_ids = {p.profile_id for p in profiles}

    assert profile_ids == {
        "STRICT_PROFILE",
        "PROFILE_F_VOLUME",
        "PROFILE_F_BALANCED",
        "PROFILE_F_SELECTIVE",
        "PROFILE_G_CODEX_OPTIMIZED",
        "PROFILE_RECOVERED_HIGH_WINRATE",
        "PROFILE_2",
    }


def test_profile_f_is_production_source_of_truth() -> None:
    profile = get_profile("PROFILE_F_VOLUME")

    assert profile is PROFILE_F_VOLUME
    assert profile.production_safe is True
    assert profile.inherited_base_profile == "STRICT_PROFILE"
    assert profile.expansion_ratio_min == 1.0
    assert profile.expansion_ratio_max == 4.0
    assert profile.retrace_window_8m_candles == 3
    assert profile.direct_12m_retrace_entry_enabled is True
    assert profile.require_1m_swing_confirmation is False


def test_strict_profile_is_production_source_of_truth() -> None:
    profile = get_profile("STRICT_PROFILE")

    assert profile is STRICT_PROFILE
    assert profile.production_safe is True
    assert profile.profile_id == "STRICT_PROFILE"
    assert profile.inherited_base_profile == "STRICT_PROFILE"
    assert profile.expansion_ratio_min == 2.0
    assert profile.expansion_ratio_max == 4.0
    assert profile.retrace_window_8m_candles == 3
    assert profile.direct_12m_retrace_entry_enabled is False
    assert profile.require_1m_swing_confirmation is True


def test_strict_and_profile_f_are_independent() -> None:
    strict = get_profile("STRICT_PROFILE")
    profile_f = get_profile("PROFILE_F_VOLUME")

    assert strict is not profile_f
    assert strict.profile_id != profile_f.profile_id
    assert strict.expansion_ratio_min != profile_f.expansion_ratio_min
    assert strict.direct_12m_retrace_entry_enabled != profile_f.direct_12m_retrace_entry_enabled
    assert strict.require_1m_swing_confirmation != profile_f.require_1m_swing_confirmation


def test_strict_profile_disables_direct_retrace_entry() -> None:
    strict = get_profile("STRICT_PROFILE")
    assert strict.direct_12m_retrace_entry_enabled is False


def test_profile_f_enables_direct_retrace_entry() -> None:
    profile_f = get_profile("PROFILE_F_VOLUME")
    assert profile_f.direct_12m_retrace_entry_enabled is True


def test_strict_profile_requires_1m_swing_confirmation() -> None:
    strict = get_profile("STRICT_PROFILE")
    assert strict.require_1m_swing_confirmation is True


def test_profile_f_does_not_require_1m_swing_confirmation() -> None:
    profile_f = get_profile("PROFILE_F_VOLUME")
    assert profile_f.require_1m_swing_confirmation is False


def test_production_profiles_are_safe_and_profile_g_is_research_only() -> None:
    for profile in get_strategy_profiles():
        if profile.profile_id in {"PROFILE_G_CODEX_OPTIMIZED", "PROFILE_RECOVERED_HIGH_WINRATE", "PROFILE_2"}:
            assert profile.production_safe is False
        else:
            assert profile.production_safe is True, f"{profile.profile_id} must be production_safe"


def test_all_profiles_base_on_strict_profile() -> None:
    for profile in get_strategy_profiles():
        assert profile.inherited_base_profile == "STRICT_PROFILE", (
            f"{profile.profile_id}.inherited_base_profile must be 'STRICT_PROFILE'"
        )


def test_strict_profile_expansion_ratio_range() -> None:
    strict = get_profile("STRICT_PROFILE")
    assert strict.expansion_ratio_min == 2.0
    assert strict.expansion_ratio_max == 4.0


def test_profile_f_expansion_ratio_range() -> None:
    assert PROFILE_F_VOLUME.expansion_ratio_min == 1.0
    assert PROFILE_F_VOLUME.expansion_ratio_max == 4.0
    assert PROFILE_F_BALANCED.expansion_ratio_min == 1.5
    assert PROFILE_F_BALANCED.expansion_ratio_max == 4.0
    assert PROFILE_F_SELECTIVE.expansion_ratio_min == 2.0
    assert PROFILE_F_SELECTIVE.expansion_ratio_max == 4.0


def test_all_profiles_use_3_candle_retrace_window() -> None:
    for profile in get_strategy_profiles():
        assert profile.retrace_window_8m_candles == 3, (
            f"{profile.profile_id}.retrace_window_8m_candles must be 3"
        )


def test_all_profiles_enforce_one_trade_per_12m_fvg() -> None:
    for profile in get_strategy_profiles():
        assert profile.one_trade_per_12m_fvg is True, (
            f"{profile.profile_id}.one_trade_per_12m_fvg must be True"
        )


def test_profile_g_is_real_research_profile() -> None:
    profile = get_profile("PROFILE_G_CODEX_OPTIMIZED")

    assert profile is PROFILE_G_CODEX_OPTIMIZED
    assert profile.production_safe is False
    assert profile.inherited_base_profile == "STRICT_PROFILE"
    assert profile.expansion_ratio_min == 1.0
    assert profile.expansion_ratio_max == 4.0
    assert profile.retrace_window_8m_candles == 3
    assert profile.direct_12m_retrace_entry_enabled is True
    assert profile.timeframe_profile_id == "DEFAULT_16_12_8"
    assert profile.tp_model == "RR_1_0_RESEARCH"
    assert "tp_model" in profile.tunable_parameters


def test_recovered_high_winrate_profile_matches_recovered_report_parameters() -> None:
    profile = get_profile("PROFILE_RECOVERED_HIGH_WINRATE")

    assert profile is PROFILE_RECOVERED_HIGH_WINRATE
    assert profile.production_safe is False
    assert profile.inherited_base_profile == "STRICT_PROFILE"
    assert profile.expansion_ratio_min == 1.0
    assert profile.expansion_ratio_max == 3.0
    assert profile.retrace_window_8m_candles == 3
    assert profile.direct_12m_retrace_entry_enabled is True
    assert profile.timeframe_profile_id == "PROFILE_15_10_5"
    assert profile.tp_model == "LEG_TARGET_RESEARCH"
    assert profile.require_expansion_c3 is False
    assert profile.use_linked_fvg_detection is False
    assert profile.main_fvg_match_mode == "LEGACY_EXPANSION_OR_NEXT_CANDLE"
    assert profile.main_fvg_match_window_candles == 1
    assert "tp_model" in profile.tunable_parameters
    assert "main_fvg_match_mode" in profile.tunable_parameters


def test_profile_2_matches_old_profile_f_recovered_parameters() -> None:
    profile = get_profile("PROFILE_2")

    assert profile is PROFILE_2
    assert profile.production_safe is False
    assert profile.inherited_base_profile == "STRICT_PROFILE"
    assert profile.expansion_ratio_min == 1.0
    assert profile.expansion_ratio_max == 3.0
    assert profile.retrace_window_8m_candles == 3
    assert profile.direct_12m_retrace_entry_enabled is True
    # PROFILE_2 always follows the 16M/12M/8M default timeframe stack (user instruction),
    # diverging here from the otherwise-identical PROFILE_RECOVERED_HIGH_WINRATE.
    assert profile.timeframe_profile_id == "DEFAULT_16_12_8"
    assert profile.tp_model == "LEG_TARGET_RESEARCH"
    assert profile.require_expansion_c3 is False
    assert profile.use_linked_fvg_detection is False
    assert profile.main_fvg_match_mode == "LEGACY_EXPANSION_OR_NEXT_CANDLE"
    assert profile.main_fvg_match_window_candles == 1
    assert "tp_model" in profile.tunable_parameters
    assert "main_fvg_match_mode" in profile.tunable_parameters


def test_unknown_profiles_are_rejected() -> None:
    removed_old_profile = "PROFILE_" + "F"
    for unknown in ("RESEARCH_PROFILE_A", removed_old_profile, "PROFILE_G"):
        with pytest.raises(ValueError):
            get_profile(unknown)


def test_profile_lookup_is_case_insensitive() -> None:
    assert get_profile("profile_f_volume") is PROFILE_F_VOLUME
    assert get_profile("strict_profile") is STRICT_PROFILE
    assert get_profile("Profile_F_Balanced") is PROFILE_F_BALANCED


def test_default_profile_is_profile_f_volume() -> None:
    assert DEFAULT_PROFILE_ID == "PROFILE_F_VOLUME"
    assert get_profile(None) is PROFILE_F_VOLUME

