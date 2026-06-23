"""Disk-backed persistence for completed/invalidated Setup Radar history.

completed_setups and invalidated_setups previously lived purely in memory,
so every process restart (a deploy, a crash, a redeploy) silently reset
both Setup Radar tabs to empty. This module persists both stores (and the
state.setup_history entries that belong to them) to a JSON file under
backend/data/, the same pattern already used for runtime_settings.json and
the encrypted accounts vault, so completed/invalidated setups now survive a
restart the same way everything else this app already persists does.

IN PROGRESS (state.setups) is deliberately never persisted here - it always
reflects only currently-active setups, with nothing historical that needs
to survive a restart.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from arjiobot.setup_tracker.setup_models import (
    InvalidationReason,
    Setup,
    SetupDirection,
    SetupState,
    SetupStatus,
    StateHistoryEntry,
)

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
STORE_PATH = DATA_DIR / "setup_history_store.json"
# Tracks whether the one-time history-clear migration has already run - a
# marker file, not a repeated-on-every-startup wipe, so genuine history
# accumulated after the migration survives every later restart instead of
# being wiped again each time.
HISTORY_CLEARED_MARKER_PATH = DATA_DIR / ".history_cleared"

_DATETIME_FIELDS = ("created_at", "updated_at", "invalidated_at", "completed_at")


def _json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, (SetupDirection, SetupState, SetupStatus, InvalidationReason)):
        return value.value
    raise TypeError(f"object of type {type(value).__name__} is not JSON serializable")


def _setup_to_json(setup: Setup) -> dict[str, Any]:
    """Full round-trip serialization of a Setup, including state_history and
    metadata - setup_to_record() (setup_models.py) is a lighter, API-facing
    projection that drops fields (created_at, metadata, state_history) this
    persistence layer needs for a faithful reload after a restart."""
    return json.loads(json.dumps(asdict(setup), default=_json_default))


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value)


def _setup_from_json(data: dict[str, Any]) -> Setup:
    payload = dict(data)
    payload["direction"] = SetupDirection(payload["direction"])
    payload["current_state"] = SetupState(payload["current_state"])
    payload["status"] = SetupStatus(payload["status"])
    payload["invalidation_reason"] = InvalidationReason(payload["invalidation_reason"]) if payload.get("invalidation_reason") else None
    for field_name in _DATETIME_FIELDS:
        payload[field_name] = _parse_datetime(payload.get(field_name))
    payload["state_history"] = tuple(
        StateHistoryEntry(
            from_state=SetupState(entry["from_state"]) if entry.get("from_state") else None,
            to_state=SetupState(entry["to_state"]),
            changed_at=_parse_datetime(entry["changed_at"]),
            reason=entry.get("reason"),
            triggering_object_type=entry.get("triggering_object_type"),
            triggering_object_id=entry.get("triggering_object_id"),
        )
        for entry in payload.get("state_history") or ()
    )
    payload["one_minute_fvg_ids"] = tuple(payload.get("one_minute_fvg_ids") or ())
    payload["watched_timeframes"] = tuple(payload.get("watched_timeframes") or ("30M", "1H", "16M", "12M", "8M", "1M"))
    return Setup(**payload)


def save_setup_history_store(state: Any) -> None:
    """Persist completed_setups/invalidated_setups (and only the
    state.setup_history entries belonging to them) to disk - call after
    every mutation to either store so a restart can reload exactly what
    existed before it."""
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        payload = {
            "completed_setups": {setup_id: _setup_to_json(setup) for setup_id, setup in state.completed_setups.items()},
            "invalidated_setups": {setup_id: _setup_to_json(setup) for setup_id, setup in state.invalidated_setups.items()},
            "setup_history": {
                setup_id: state.setup_history.get(setup_id, [])
                for setup_id in (*state.completed_setups, *state.invalidated_setups)
            },
        }
        STORE_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except Exception:
        # Persistence is a durability improvement, not a correctness
        # requirement for the current process - a write failure (e.g. a
        # read-only filesystem) must never break Setup Radar tracking itself.
        logger.exception("Failed to persist completed/invalidated setup history to %s", STORE_PATH)


def load_setup_history_store(state: Any) -> tuple[int, int]:
    """Load completed_setups/invalidated_setups (and their setup_history
    entries) from disk at startup, so they survive this restart instead of
    starting empty every time. Returns (completed_count, invalidated_count)
    loaded, for logging."""
    if not STORE_PATH.exists():
        return 0, 0
    try:
        payload = json.loads(STORE_PATH.read_text(encoding="utf-8"))
    except Exception:
        logger.exception("Failed to read %s - starting with empty completed/invalidated setup history", STORE_PATH)
        return 0, 0
    completed_count = 0
    invalidated_count = 0
    for setup_id, data in (payload.get("completed_setups") or {}).items():
        try:
            state.completed_setups[setup_id] = _setup_from_json(data)
            completed_count += 1
        except Exception:
            logger.exception("Failed to load persisted completed setup %s - skipping it", setup_id)
    for setup_id, data in (payload.get("invalidated_setups") or {}).items():
        try:
            state.invalidated_setups[setup_id] = _setup_from_json(data)
            invalidated_count += 1
        except Exception:
            logger.exception("Failed to load persisted invalidated setup %s - skipping it", setup_id)
    for setup_id, history in (payload.get("setup_history") or {}).items():
        if setup_id in state.completed_setups or setup_id in state.invalidated_setups:
            state.setup_history[setup_id] = history
    return completed_count, invalidated_count


def clear_setup_history(state: Any) -> tuple[int, int]:
    """Clear completed_setups/invalidated_setups in memory, reset both of
    those in-memory dicts to empty, AND delete the persisted file from disk -
    all three in this one synchronous call, so no request in between can ever
    observe a partially-cleared state. The on-demand equivalent of the
    one-time startup migration below, for an operator to trigger manually
    (see api/routes/admin.py's POST /api/admin/clear-setup-history) without
    waiting for a restart. IN PROGRESS (state.setups) is never touched.
    Returns (completed_count, invalidated_count) cleared."""
    completed_count = len(state.completed_setups)
    invalidated_count = len(state.invalidated_setups)
    for setup_id in (*state.completed_setups, *state.invalidated_setups):
        state.setup_history.pop(setup_id, None)
    state.completed_setups.clear()
    state.invalidated_setups.clear()
    STORE_PATH.unlink(missing_ok=True)
    logger.warning(
        "Manual clear: cleared %d completed setup(s) and %d invalidated setup(s) and deleted %s.",
        completed_count,
        invalidated_count,
        STORE_PATH,
    )
    return completed_count, invalidated_count


def run_one_time_history_clear_migration(state: Any) -> bool:
    """Exactly once - tracked by HISTORY_CLEARED_MARKER_PATH, never by a
    repeated startup wipe - clear completed_setups/invalidated_setups in
    memory and save that now-empty state to disk, OVERWRITING whatever was
    already in setup_history_store.json (including a file that predates
    this migration entirely, e.g. one left over from before the marker
    existed). This is what guarantees the wipe happens on the next deploy
    regardless of what is already on disk - then it never runs again, so
    genuine history recorded after this point survives every later restart.

    Returns whether the wipe actually ran (False on every call after the
    first, once the marker file exists).
    """
    if HISTORY_CLEARED_MARKER_PATH.exists():
        return False
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    completed_count = len(state.completed_setups)
    invalidated_count = len(state.invalidated_setups)
    for setup_id in list(state.completed_setups):
        state.completed_setups.pop(setup_id, None)
        state.setup_history.pop(setup_id, None)
    for setup_id in list(state.invalidated_setups):
        state.invalidated_setups.pop(setup_id, None)
        state.setup_history.pop(setup_id, None)
    # Overwrites any pre-existing setup_history_store.json with the now-empty
    # state, rather than relying on the file not existing - this is what
    # makes the migration correct even when an old file with stale entries
    # is already sitting on disk before this code ever runs.
    save_setup_history_store(state)
    HISTORY_CLEARED_MARKER_PATH.write_text(datetime.now(timezone.utc).isoformat(), encoding="utf-8")
    logger.warning(
        "One-time migration: cleared %d completed setup(s) and %d invalidated setup(s) and saved the empty state "
        "to %s - COMPLETED/INVALIDATED tabs start at 0 from this deploy forward; this migration will not run again.",
        completed_count,
        invalidated_count,
        STORE_PATH,
    )
    return True
