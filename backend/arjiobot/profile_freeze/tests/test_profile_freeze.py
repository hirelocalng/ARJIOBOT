"""Regression tests for PROTECTED_PROFILE_LOGIC."""

from __future__ import annotations

import os

from arjiobot.profile_freeze.profile_freeze import (
    ALLOW_PROFILE_MUTATION_ENV,
    ProfileFreezeError,
    assert_profile_freeze,
    profile_freeze_differences,
)


def test_profiles_are_frozen() -> None:
    if os.getenv(ALLOW_PROFILE_MUTATION_ENV, "").strip().lower() == "true":
        return

    differences = profile_freeze_differences()
    assert differences == []


def test_profile_freeze_assertion_blocks_mutation() -> None:
    if os.getenv(ALLOW_PROFILE_MUTATION_ENV, "").strip().lower() == "true":
        assert_profile_freeze()
        return

    try:
        assert_profile_freeze()
    except ProfileFreezeError as exc:
        raise AssertionError(str(exc)) from exc
