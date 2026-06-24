"""Disk-backed persistence for completed/invalidated Setup Radar history.

completed_setups and invalidated_setups are append-only, newest-first lists
(see live_setup_detection.py's _append_resolved_setup) - a setup is written
here exactly once, ever, and only ever removed by capping at
MAX_TRACKED_SETUP_ATTEMPTS (the oldest, at the end of the list). This module
mirrors that list, in that same order, to a JSON file under backend/data/, so
the lists are visible without needing to read process memory directly.

Every deploy starts with zero *visible* history (see wipe_setup_history,
called once at process boot from main.py): the completed/invalidated lists
the UI reads are always wiped empty. The swing-level dedup cache
(state.resolved_swing_keys) is the one exception - it is seeded from this
same file's previous content before the wipe overwrites it (Fix 3), so a
swing already resolved in an earlier deployment session stays permanently
blocked from re-entering the live detection funnel even though the visible
lists start empty. IN PROGRESS (state.setups) is never written here either
way - it always reflects only currently-active setups, with nothing that
needs to survive a restart, by design.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from arjiobot.setup_tracker.setup_models import InvalidationReason, Setup, SetupDirection, SetupState, SetupStatus, build_swing_dedup_key

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


def _seed_swing_cache_from_disk(state: Any) -> int:
    """Fix 3 (Setup Radar swing-level dedup): read whatever the *previous*
    deployment session actually persisted to STORE_PATH - before
    wipe_setup_history below overwrites it with the empty fresh-start shape
    - and seed state.resolved_swing_keys from every completed/invalidated
    entry in it. A swing the previous session already resolved must stay
    permanently blocked from re-entering the live detection funnel, even
    though the visible completed/invalidated lists the UI reads start empty
    on every deploy.

    Order matters here: this must run before the file is overwritten, never
    after - see wipe_setup_history's call site.

    Returns the number of swing keys seeded (0 for a brand new deploy with
    no existing file, or one with no readable content yet)."""
    try:
        previous = json.loads(STORE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0
    seeded = 0
    for record in (*(previous.get("completed") or ()), *(previous.get("invalidated") or ())):
        symbol = record.get("symbol")
        direction = record.get("direction")
        swing_timestamp = record.get("created_at")
        if not symbol or not direction or not swing_timestamp:
            continue
        state.resolved_swing_keys.add(build_swing_dedup_key(symbol=symbol, direction=direction, swing_timestamp=swing_timestamp))
        seeded += 1
    return seeded


def wipe_setup_history(state: Any) -> tuple[int, int]:
    """Fresh start: clear completed_setups/invalidated_setups in memory,
    clear the seen-setups dedup cache (resolved_setup_ids), record
    history_cleared_at, and overwrite the persisted file with the empty
    shape - all in this one synchronous call, so no request in between can
    ever observe a partially-cleared state. Called unconditionally on every
    process boot (see main.py's create_app) - every deploy starts with zero
    *visible* history - and on demand for a manual operator clear (see
    api/routes/admin.py's POST /api/admin/clear-setup-history).

    Fix 3 (Setup Radar swing-level dedup): before any of that happens, the
    permanent swing dedup cache is seeded from the file's previous content
    (_seed_swing_cache_from_disk) - so a swing already resolved in an
    earlier deployment session (or earlier in this same session, for a
    manual clear) stays permanently blocked from re-entering the live
    detection funnel even though the visible lists this call empties out
    start fresh. Unlike resolved_setup_ids, resolved_swing_keys is never
    cleared here (or anywhere) - it is permanent for the life of the
    process, by design.

    IN PROGRESS (state.setups) is never touched by this.

    Returns (completed_count, invalidated_count) cleared."""
    completed_count = len(state.completed_setups)
    invalidated_count = len(state.invalidated_setups)
    seeded_swing_keys = _seed_swing_cache_from_disk(state)
    for setup in (*state.completed_setups, *state.invalidated_setups):
        state.setup_history.pop(setup.setup_id, None)
    state.completed_setups.clear()
    state.invalidated_setups.clear()
    state.resolved_setup_ids.clear()
    state.history_cleared_at = datetime.now(timezone.utc)
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        payload = {"completed": [], "invalidated": [], "cleared_at": state.history_cleared_at.isoformat(), "setup_history": {}}
        STORE_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except Exception:
        logger.exception("Failed to overwrite %s with the empty fresh-start state", STORE_PATH)
    logger.warning(
        "Setup history wiped: cleared %d completed setup(s) and %d invalidated setup(s) (seeded %d swing key(s) into "
        "the permanent dedup cache from the previous session's history first), cleared the seen-setups dedup cache, "
        "and recorded history_cleared_at=%s - %s starts with zero visible history.",
        completed_count,
        invalidated_count,
        seeded_swing_keys,
        state.history_cleared_at.isoformat(),
        STORE_PATH,
    )
    return completed_count, invalidated_count
