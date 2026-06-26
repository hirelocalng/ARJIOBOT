"""Disk-backed persistence for completed/invalidated Setup Radar history.

completed_setups and invalidated_setups are append-only, newest-first lists
(see live_setup_detection.py's _append_resolved_setup) - a setup is written
here exactly once, ever, and only ever removed by capping at
MAX_TRACKED_SETUP_ATTEMPTS (the oldest, at the end of the list). This module
mirrors that list, in that same order, to a JSON file under backend/data/, so
the lists are visible without needing to read process memory directly.

On every process boot load_setup_history_for_display (called from main.py)
reads whatever the previous session persisted here and populates
completed_setups / invalidated_setups in memory for immediate UI display -
without seeding the swing-level dedup cache (state.resolved_swing_keys),
and state.resolved_setup_ids), which start empty on every deploy. The pre-funnel staleness filter in
live_setup_detection.py (_filter_stale_swings) catches any historical swing
from the rolling candle buffer on the first poll and permanently dedupes it
there for the current process, so the cache stays small and fresh. IN PROGRESS (state.setups) is
never written here - it only reflects currently-active setups, by design.

wipe_setup_history is called only by the manual Clear History admin button
(POST /api/admin/clear-setup-history): it empties both in-memory lists, both
dedup caches, the JSON file, and records history_cleared_at so the bot
starts from a fully blank slate on the next poll.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from arjiobot.setup_tracker.setup_models import InvalidationReason, Setup, SetupDirection, SetupState, SetupStatus

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
STORE_PATH = DATA_DIR / "setup_history_store.json"


def _json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, (SetupDirection, SetupState, SetupStatus, InvalidationReason)):
        return value.value
    raise TypeError(f"object of type {type(value).__name__} is not JSON serializable")


def _setup_to_json(setup: Setup) -> dict[str, Any]:
    """Full serialization of a Setup, including state_history and metadata -
    setup_to_record() (setup_models.py) is a lighter, API-facing projection
    that drops fields (created_at, metadata, state_history) this audit trail
    keeps. Write-only - nothing reads this back into memory (see module
    docstring: every deploy starts with zero history)."""
    return json.loads(json.dumps(asdict(setup), default=_json_default))


def save_setup_history_store(state: Any) -> None:
    """Mirror completed_setups/invalidated_setups (and only the
    state.setup_history entries belonging to them) to disk, in their current
    in-memory order - call after every mutation to either list (i.e. only
    when a new entry was just appended - see _append_resolved_setup) so a
    restart can reload exactly what existed before it.

    No filtering, capping, or sorting happens here - the in-memory lists are
    already correct by construction (append-only, capped at insertion time),
    so this is pure, trustful persistence."""
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        payload = {
            "completed": [_setup_to_json(setup) for setup in state.completed_setups],
            "invalidated": [_setup_to_json(setup) for setup in state.invalidated_setups],
            "cleared_at": state.history_cleared_at.isoformat() if getattr(state, "history_cleared_at", None) else None,
            "setup_history": {
                setup.setup_id: state.setup_history.get(setup.setup_id, [])
                for setup in (*state.completed_setups, *state.invalidated_setups)
            },
        }
        STORE_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except Exception:
        # Persistence is a durability improvement, not a correctness
        # requirement for the current process - a write failure (e.g. a
        # read-only filesystem) must never break Setup Radar tracking itself.
        logger.exception("Failed to persist completed/invalidated setup history to %s", STORE_PATH)


def _json_to_setup(record: dict[str, Any]) -> Setup | None:
    """Reconstruct a Setup from a persisted JSON record for display.
    Returns None and logs a warning if any field is missing or unrecognisable.
    state_history is intentionally omitted (empty tuple) - it is not used by
    the radar display layer and avoids importing StateHistoryEntry subfields."""
    try:
        def _dt(s: Any) -> datetime | None:
            if not s:
                return None
            return datetime.fromisoformat(str(s).replace("Z", "+00:00"))

        def _dec(s: Any) -> Decimal | None:
            return Decimal(str(s)) if s is not None else None

        return Setup(
            setup_id=record["setup_id"],
            symbol=record["symbol"],
            direction=SetupDirection(record["direction"]),
            current_state=SetupState(record["current_state"]),
            progress_percent=float(record.get("progress_percent") or 0.0),
            status=SetupStatus(record["status"]),
            created_at=_dt(record.get("created_at")) or datetime.now(timezone.utc),
            updated_at=_dt(record.get("updated_at")) or datetime.now(timezone.utc),
            invalidated_at=_dt(record.get("invalidated_at")),
            invalidation_reason=InvalidationReason(record["invalidation_reason"]) if record.get("invalidation_reason") else None,
            last_valid_stage=record.get("last_valid_stage"),
            completed_at=_dt(record.get("completed_at")),
            htf_fvg_id=record.get("htf_fvg_id"),
            swing_16m_id=record.get("swing_16m_id"),
            expansion_16m_id=record.get("expansion_16m_id"),
            fvg_16m_id=record.get("fvg_16m_id"),
            fvg_12m_id=record.get("fvg_12m_id"),
            fvg_8m_id=record.get("fvg_8m_id"),
            retrace_tap_candle_id=record.get("retrace_tap_candle_id"),
            one_minute_swing_id=record.get("one_minute_swing_id"),
            one_minute_fvg_ids=tuple(record.get("one_minute_fvg_ids") or []),
            entry_fvg_id=record.get("entry_fvg_id"),
            stop_reference_price=_dec(record.get("stop_reference_price")),
            target_a_price=_dec(record.get("target_a_price")),
            target_b_price=_dec(record.get("target_b_price")),
            final_target_price=_dec(record.get("final_target_price")),
            time_remaining=record.get("time_remaining"),
            state_history=(),
            watched_timeframes=tuple(record.get("watched_timeframes") or ("30M", "1H", "16M", "12M", "8M", "1M")),
            execution_status=record.get("execution_status"),
            metadata=dict(record.get("metadata") or {}),
        )
    except Exception:
        logger.warning("Skipping unreadable setup record from disk (setup_id=%r)", record.get("setup_id"))
        return None


def load_setup_history_for_display(state: Any) -> tuple[int, int]:
    """On process startup: load whatever completed/invalidated history the
    previous session persisted to STORE_PATH into memory so the UI shows
    prior context immediately after a restart.

    Behaviour:
    - state.completed_setups and state.invalidated_setups are populated from
      the JSON in their persisted order (newest-first).
    - state.resolved_setup_ids and state.resolved_swing_keys are deliberately
      left EMPTY. The dedup caches are session-only; the pre-funnel staleness
      filter in live_setup_detection.py (_filter_stale_swings) classifies each
      swing independently on the first poll - fresh swings
      (<STALENESS_WINDOW_MINUTES) proceed through the funnel, stale ones are
      cached there without ever entering IN PROGRESS.
    - history_cleared_at is restored from the JSON if present.
    - If the file is absent, corrupt, or empty the function is a no-op and
      the bot starts with zero visible history (same as a fresh deploy).

    Returns (completed_count, invalidated_count) loaded."""
    try:
        previous = json.loads(STORE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.info("No prior setup history found at %s - starting with empty visible lists.", STORE_PATH)
        return 0, 0

    cleared_at_raw = previous.get("cleared_at")
    if cleared_at_raw:
        try:
            state.history_cleared_at = datetime.fromisoformat(str(cleared_at_raw).replace("Z", "+00:00"))
        except ValueError:
            pass

    completed_count = 0
    for record in previous.get("completed") or []:
        if not isinstance(record, dict):
            continue
        setup = _json_to_setup(record)
        if setup is None:
            continue
        state.completed_setups.append(setup)
        completed_count += 1

    invalidated_count = 0
    for record in previous.get("invalidated") or []:
        if not isinstance(record, dict):
            continue
        setup = _json_to_setup(record)
        if setup is None:
            continue
        state.invalidated_setups.append(setup)
        invalidated_count += 1

    logger.warning(
        "Setup Radar history loaded from disk: %d completed, %d invalidated - "
        "dedup caches start empty; pre-funnel staleness filter handles old swings on first poll.",
        completed_count,
        invalidated_count,
    )
    return completed_count, invalidated_count


def wipe_setup_history(state: Any) -> tuple[int, int]:
    """Fresh start: clear completed_setups/invalidated_setups in memory,
    clear both dedup caches (resolved_setup_ids and resolved_swing_keys),
    record history_cleared_at, and overwrite the persisted file with the
    empty shape - all in this one synchronous call, so no request in between
    can ever observe a partially-cleared state. Called by the manual Clear
    History endpoint; process boot loads JSON history for display only and
    also starts with empty dedup caches.

    resolved_swing_keys is cleared (not seeded from disk) because carrying
    over the previous session's dedup cache was silently blocking every swing
    that ever resolved in any prior session from re-entering the funnel on
    subsequent deploys - including genuinely fresh real-time swings whose
    conditions may have just re-aligned. A clean slate on each deploy lets the
    staleness gate (live_automation.py's _expire_if_stale, now gated on
    detected_at_wallclock rather than completed_at) handle age correctly
    instead of the funnel never seeing the swing at all.

    IN PROGRESS (state.setups) is never touched by this.

    Returns (completed_count, invalidated_count) cleared."""
    completed_count = len(state.completed_setups)
    invalidated_count = len(state.invalidated_setups)
    swing_keys_cleared = len(state.resolved_swing_keys)
    for setup in (*state.completed_setups, *state.invalidated_setups):
        state.setup_history.pop(setup.setup_id, None)
    state.completed_setups.clear()
    state.invalidated_setups.clear()
    state.resolved_setup_ids.clear()
    state.resolved_swing_keys.clear()
    getattr(state, "resolved_swing_key_timestamps", {}).clear()
    state.history_cleared_at = datetime.now(timezone.utc)
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        payload = {"completed": [], "invalidated": [], "cleared_at": state.history_cleared_at.isoformat(), "setup_history": {}}
        STORE_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except Exception:
        logger.exception("Failed to overwrite %s with the empty fresh-start state", STORE_PATH)
    logger.warning(
        "Setup history wiped: cleared %d completed setup(s), %d invalidated setup(s), and %d resolved swing key(s) - "
        "Setup Radar starts from zero visible history with a fresh funnel on the first poll after this deploy.",
        completed_count,
        invalidated_count,
        swing_keys_cleared,
    )
    return completed_count, invalidated_count
