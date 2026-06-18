"""PROTECTED_PROFILE_LOGIC profile freeze verification.

This module must not change profile behavior. It only snapshots and verifies
that locked strategy profiles and protected strategy source files still match
profiles.lock.json.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from arjiobot.backtesting.research_profiles import get_strategy_profiles
from arjiobot.backtesting.timeframe_profiles import get_timeframe_profile

PROFILE_FREEZE_RUNTIME_WARNING = "Profile freeze active: strategy logic locked."
ALLOW_PROFILE_MUTATION_ENV = "ALLOW_PROFILE_MUTATION"
LOCK_FILE_NAME = "profiles.lock.json"
LOCK_SCHEMA_VERSION = 1

ROOT = Path(__file__).resolve().parents[2]
LOCK_PATH = ROOT / LOCK_FILE_NAME

PROTECTED_PROFILE_LOGIC_PATHS: tuple[str, ...] = (
    "arjiobot/backtesting/research_profiles.py",
    "arjiobot/backtesting/timeframe_profiles.py",
    "arjiobot/swings/swings.py",
    "arjiobot/fvg/fvg.py",
    "arjiobot/fvg/fvg_tap_rules.py",
    "arjiobot/setup_tracker/setup_invalidation.py",
    "arjiobot/strategy/strategy_engine.py",
    "arjiobot/risk/rr_profiles.py",
    "scripts/backtest_csv.py",
)


class ProfileFreezeError(RuntimeError):
    """Raised when locked profile logic differs from profiles.lock.json."""


def profile_mutation_allowed() -> bool:
    return os.getenv(ALLOW_PROFILE_MUTATION_ENV, "").strip().lower() == "true"


def _canonical_json(data: Any) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _profile_snapshot(profile) -> dict[str, Any]:
    record = profile.to_record()
    timeframe_stack = get_timeframe_profile(str(record["timeframe_profile_id"])).to_record()
    locked_record = {
        "profile_id": record["profile_id"],
        "full_parameters": record,
        "timeframe_stack": timeframe_stack,
        "tp_model": record["tp_model"],
        "entry_model": "DIRECT_12M_RETRACE"
        if record["direct_12m_retrace_entry_enabled"]
        else "STRICT_1M_CONFIRMATION",
        "fvg_mode": {
            "use_linked_fvg_detection": record["use_linked_fvg_detection"],
            "main_fvg_match_mode": record["main_fvg_match_mode"],
            "main_fvg_match_window_candles": record["main_fvg_match_window_candles"],
        },
        "expansion_rules": {
            "expansion_ratio_min": record["expansion_ratio_min"],
            "expansion_ratio_max": record["expansion_ratio_max"],
            "require_expansion_c3": record["require_expansion_c3"],
        },
        "retrace_rules": {
            "retrace_window_8m_candles": record["retrace_window_8m_candles"],
            "fvg_delay_16m_candles": record["fvg_delay_16m_candles"],
            "direct_12m_retrace_entry_enabled": record["direct_12m_retrace_entry_enabled"],
            "one_trade_per_12m_fvg": record["one_trade_per_12m_fvg"],
        },
        "compatibility_flags": {
            "require_1m_swing_confirmation": record["require_1m_swing_confirmation"],
            "require_1m_bearish_expansion": record["require_1m_bearish_expansion"],
            "require_1m_bearish_fvg": record["require_1m_bearish_fvg"],
            "require_1m_fvg_retest": record["require_1m_fvg_retest"],
            "tunable_parameters": list(record["tunable_parameters"]),
        },
    }
    locked_record["profile_hash"] = _sha256_text(_canonical_json(locked_record))
    return locked_record


def build_profile_freeze_snapshot() -> dict[str, Any]:
    profiles = [_profile_snapshot(profile) for profile in get_strategy_profiles()]
    source_hashes = {
        relative_path: _sha256_file(ROOT / relative_path)
        for relative_path in PROTECTED_PROFILE_LOGIC_PATHS
    }
    return {
        "schema_version": LOCK_SCHEMA_VERSION,
        "protected_area": "PROTECTED_PROFILE_LOGIC",
        "runtime_warning": PROFILE_FREEZE_RUNTIME_WARNING,
        "allow_mutation_env": ALLOW_PROFILE_MUTATION_ENV,
        "locked_profile_ids": [profile["profile_id"] for profile in profiles],
        "profiles": profiles,
        "protected_source_hashes": source_hashes,
    }


def load_profile_lock() -> dict[str, Any]:
    if not LOCK_PATH.exists():
        raise ProfileFreezeError(f"profile freeze lock file missing: {LOCK_PATH}")
    return json.loads(LOCK_PATH.read_text(encoding="utf-8"))


def profile_freeze_differences() -> list[str]:
    expected = load_profile_lock()
    actual = build_profile_freeze_snapshot()
    differences: list[str] = []
    if expected.get("schema_version") != actual.get("schema_version"):
        differences.append("schema_version changed")
    if expected.get("locked_profile_ids") != actual.get("locked_profile_ids"):
        differences.append(
            f"locked profile registry changed: expected {expected.get('locked_profile_ids')}, "
            f"actual {actual.get('locked_profile_ids')}"
        )
    expected_profiles = {profile["profile_id"]: profile for profile in expected.get("profiles", [])}
    actual_profiles = {profile["profile_id"]: profile for profile in actual.get("profiles", [])}
    for profile_id in expected_profiles:
        if profile_id not in actual_profiles:
            differences.append(f"profile deleted or renamed: {profile_id}")
            continue
        if expected_profiles[profile_id].get("profile_hash") != actual_profiles[profile_id].get("profile_hash"):
            differences.append(f"profile changed: {profile_id}")
    for profile_id in actual_profiles:
        if profile_id not in expected_profiles:
            differences.append(f"profile added or renamed: {profile_id}")
    expected_sources = expected.get("protected_source_hashes", {})
    actual_sources = actual.get("protected_source_hashes", {})
    for relative_path, expected_hash in expected_sources.items():
        actual_hash = actual_sources.get(relative_path)
        if actual_hash is None:
            differences.append(f"protected source missing: {relative_path}")
        elif expected_hash != actual_hash:
            differences.append(f"protected source changed: {relative_path}")
    for relative_path in actual_sources:
        if relative_path not in expected_sources:
            differences.append(f"protected source added to guard: {relative_path}")
    return differences


def assert_profile_freeze() -> None:
    if profile_mutation_allowed():
        return
    differences = profile_freeze_differences()
    if differences:
        details = "; ".join(differences)
        raise ProfileFreezeError(
            f"{PROFILE_FREEZE_RUNTIME_WARNING} Locked profile verification failed: {details}. "
            f"Set {ALLOW_PROFILE_MUTATION_ENV}=true only for an intentional profile migration."
        )
