"""Live monitoring session routes."""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from threading import Timer

from fastapi import APIRouter

from arjiobot.api.dependencies import ApiState, get_state, now_iso, save_settings
from arjiobot.api.errors import api_error
from arjiobot.api.schemas.common import ok
from arjiobot.backtesting.historical_replay import build_timeframe_profile
from arjiobot.exchange.account_vault import CredentialVaultError, decrypt_credentials
from arjiobot.exchange.bitget_environment import BITGET_CANDLE_REQUEST_LIMIT
from arjiobot.live_automation import run_live_automation_once
from arjiobot.live_setup_detection import candles_from_bitget_rows, detect_live_setups_for_symbol
from arjiobot.market_data.candle_models import Candle

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/monitoring", tags=["monitoring"])
MIN_POLL_INTERVAL_SECONDS = 5
LIVE_CANDLE_HISTORY_LIMIT = 2_000
LIVE_CANDLE_FETCH_LIMIT = BITGET_CANDLE_REQUEST_LIMIT
DERIVED_CHART_TIMEFRAMES_MINUTES: tuple[int, ...] = (60, 30, 16, 12, 8)


@router.post("/start")
def start_monitoring(payload: dict[str, object] | None = None):
    payload = payload or {}
    state = get_state()
    result = _activate_monitoring_session(state)
    state.settings["monitoring_enabled"] = True
    save_settings(state.settings)
    return ok(result)


@router.post("/stop")
def stop_monitoring(payload: dict[str, object] | None = None):
    state = get_state()
    state.monitoring.update({"active": False, "stopped_at": now_iso(), "last_error": "None"})
    state.market_polls.clear()
    state.setups.clear()
    state.settings["monitoring_enabled"] = False
    save_settings(state.settings)
    return ok({"monitoring_status": "NOT MONITORING", "message": "MONITORING STOPPED"})


def _activate_monitoring_session(state: ApiState) -> dict[str, object]:
    enabled_pairs = [pair for pair in state.monitored_pairs.values() if pair.get("enabled")]
    if not enabled_pairs:
        raise api_error(400, "MONITORING_NO_PAIRS", "MONITORING FAILED: no pairs selected")
    if str(state.settings.get("adapter_mode", "MOCK")).upper() == "MOCK":
        raise api_error(400, "MONITORING_MOCK_ADAPTER", "MONITORING FAILED: exchange adapter is MOCK")
    session_id = _session_id()
    state.monitoring.update(
        {
            "active": True,
            "session_id": session_id,
            "started_at": now_iso(),
            "stopped_at": "None",
            "last_error": "None",
            "source": "LIVE_MARKET_DATA",
            "polling_status": "STARTING",
            "poll_interval_seconds": _poll_interval_seconds(),
            "poll_cycle_count": 0,
        }
    )
    state.market_polls.clear()
    for pair in enabled_pairs:
        symbol = str(pair.get("symbol", "")).upper()
        state.market_polls[symbol] = _pending_poll(symbol)
    _schedule_poll(session_id, delay=0.5)
    return {
        "monitoring_status": "ACTIVE",
        "message": "MONITORING STARTED - live market polling in progress",
        "session_id": session_id,
        "pairs": tuple(state.market_polls),
    }


def resume_monitoring_if_enabled(state: ApiState) -> None:
    """Re-arm the polling loop on process startup if monitoring was active
    before the last restart/redeploy.

    `state.monitoring` is in-memory only and resets to inactive on every
    boot, but `settings.monitoring_enabled` is persisted (database or JSON
    fallback - see save_settings). Without this, every redeploy silently
    turns live monitoring off until a human notices and clicks Start again.
    Never raises - a startup convenience, not a requirement for the app to
    come up.
    """
    if not state.settings.get("monitoring_enabled"):
        return
    try:
        result = _activate_monitoring_session(state)
        logger.info("Resumed live monitoring on startup: session=%s pairs=%s", result["session_id"], result["pairs"])
    except Exception as exc:
        logger.warning("monitoring_enabled=True but auto-resume on startup failed: %s", exc)


@router.get("/status")
def monitoring_status():
    state = get_state()
    return ok({"monitoring": {**state.monitoring, "watchdog": _watchdog_status(state.monitoring)}, "pairs": tuple(state.market_polls.values())})


def _watchdog_status(monitoring: dict[str, object]) -> dict[str, object]:
    """Surface whether the poll cycle has gone silent for longer than expected.

    The poll chain already self-heals from exceptions and re-arms on process
    boot (see _poll_enabled_pairs / resume_monitoring_if_enabled); the one
    failure mode neither covers is a *hung* (not crashed) cycle, which would
    otherwise look identical to "no issue" from the outside. This makes that
    gap visible without adding a redundant supervisory thread.
    """
    if not monitoring.get("active"):
        return {"is_stale": False, "reason": "monitoring is not active"}
    reference = monitoring.get("last_poll_cycle_completed") or monitoring.get("started_at")
    if not reference or reference == "None":
        return {"is_stale": False, "reason": "no poll cycle has completed yet"}
    try:
        parsed = datetime.fromisoformat(str(reference).replace("Z", "+00:00"))
    except ValueError:
        return {"is_stale": True, "reason": f"unparseable timestamp: {reference}"}
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    interval = int(monitoring.get("poll_interval_seconds") or MIN_POLL_INTERVAL_SECONDS)
    threshold_seconds = max(interval * 3, MIN_POLL_INTERVAL_SECONDS * 3)
    elapsed_seconds = (datetime.now(timezone.utc) - parsed).total_seconds()
    is_stale = elapsed_seconds > threshold_seconds
    if is_stale:
        logger.warning(
            "Live monitoring poll cycle has gone silent for %.0fs (threshold %ss) - last completed at %s. "
            "The poll chain may be hung on a blocking call.",
            elapsed_seconds,
            threshold_seconds,
            reference,
        )
    return {
        "is_stale": is_stale,
        "seconds_since_last_completed_cycle": round(elapsed_seconds, 1),
        "threshold_seconds": threshold_seconds,
        "reason": "poll cycle is current" if not is_stale else "no completed poll cycle within 3x the configured interval",
    }


@router.get("/candles/{symbol}")
def live_timeframe_candles(symbol: str):
    """Read-only view of the live 1H/30M/16M/12M/8M chart series kept for ``symbol``."""
    state = get_state()
    symbol = symbol.upper()
    by_timeframe = state.live_timeframe_candles.get(symbol, {})
    return ok(
        {
            "symbol": symbol,
            "one_minute_candle_count": len(state.live_candles.get(symbol, ())),
            "timeframes": {
                f"{minutes}M": {
                    "candle_count": len(candles),
                    "latest": _candle_summary(candles[-1]) if candles else None,
                }
                for minutes, candles in sorted(by_timeframe.items())
            },
        }
    )


def _candle_summary(candle: Candle) -> dict[str, str]:
    return {
        "timestamp": candle.timestamp.isoformat(),
        "open": str(candle.open),
        "high": str(candle.high),
        "low": str(candle.low),
        "close": str(candle.close),
    }


def _pending_poll(symbol: str) -> dict[str, object]:
    started = now_iso()
    return {
        "symbol": symbol,
        "poll_success": "NO",
        "poll_status": "POLLING",
        "last_poll_started": started,
        "last_poll_completed": "N/A",
        "last_live_price": "N/A",
        "bid_price": "N/A",
        "ask_price": "N/A",
        "mark_price": "N/A",
        "contract_config_loaded": "NO",
        "last_error": "Live market poll in progress.",
    }


def _poll_enabled_pairs(session_id: str) -> None:
    """Timer callback for one polling cycle. Always reschedules the next
    cycle in `finally`, even if this cycle raised - a single bad cycle
    (e.g. an unexpected credential-decrypt error) must not permanently and
    silently end the polling chain while `monitoring.active` stays True."""
    state = get_state()
    _watchdog_status(state.monitoring)  # logs a warning on its own if the previous cycle went silent
    try:
        _run_poll_cycle(state, session_id)
    except Exception as exc:
        logger.exception("Live monitoring poll cycle for session %s crashed; rescheduling next poll", session_id)
        state.monitoring["last_error"] = f"poll cycle crashed: {exc}"
        state.monitoring["polling_status"] = "ERROR"
    finally:
        _schedule_poll(session_id, delay=_poll_interval_seconds())


def _run_poll_cycle(state, session_id: str) -> None:
    _activate_selected_account_credentials()
    successes = 0
    failures: list[str] = []
    for pair in list(state.monitored_pairs.values()):
        if not state.monitoring.get("active") or state.monitoring.get("session_id") != session_id:
            return
        if not pair.get("enabled"):
            continue
        symbol = str(pair.get("symbol", "")).upper()
        started = now_iso()
        existing = state.market_polls.get(symbol, _pending_poll(symbol))
        state.market_polls[symbol] = {**existing, "poll_status": "POLLING", "last_poll_started": started, "last_error": "Live market poll in progress."}
        try:
            contract = state.bitget_environment.fetch_contract_config(symbol)
            ticker = state.bitget_environment.fetch_ticker(symbol)
            existing_candle_count = len(state.live_candles.get(symbol, ()))
            if existing_candle_count < LIVE_CANDLE_HISTORY_LIMIT:
                # Cold start for this symbol: page backward to bootstrap the
                # 2,000-candle rolling lookback. This is enough to synthesize
                # 30+ closed 16M/12M/8M candles while avoiding the old 31-day
                # backlog and its polling cost.
                candles = state.bitget_environment.backfill_candles(symbol, "1m", total=LIVE_CANDLE_HISTORY_LIMIT)
            else:
                candles = state.bitget_environment.fetch_candles(symbol, "1m", LIVE_CANDLE_FETCH_LIMIT)
            rows = _normalize_candle_rows(candles.get("rows", ()))
            fresh_candles = candles_from_bitget_rows(symbol, rows)
            state.live_candles[symbol] = _merge_live_candles(state.live_candles.get(symbol, ()), fresh_candles)
            state.live_timeframe_candles[symbol] = _derived_timeframe_candles(state.live_candles[symbol])
            completed = now_iso()
            state.market_polls[symbol] = {
                "symbol": symbol,
                "last_poll_started": started,
                "last_poll_completed": completed,
                "poll_success": "YES",
                "poll_status": "READY",
                "product_type": contract.get("product_type", "USDT-FUTURES"),
                "contract_config_loaded": contract.get("contract_config_loaded", "YES"),
                "symbol_status": contract.get("symbol_status", "UNKNOWN"),
                "minTradeNum": contract.get("minTradeNum", "N/A"),
                "minTradeUSDT": contract.get("minTradeUSDT", "N/A"),
                "maxLever": contract.get("maxLever", "N/A"),
                "last_live_price": ticker.get("last_price", "N/A"),
                "bid_price": ticker.get("bid_price", "N/A"),
                "ask_price": ticker.get("ask_price", "N/A"),
                "mark_price": ticker.get("mark_price", "N/A"),
                "index_price": ticker.get("index_price", "N/A"),
                "last_candle_timeframe_update": completed,
                "live_candle_count": len(state.live_candles.get(symbol, ())),
                "live_candle_history_limit": LIVE_CANDLE_HISTORY_LIMIT,
                "last_error": "",
                "next_scheduled_refresh_time": completed,
            }
            detect_live_setups_for_symbol(state, symbol, source="MONITORING_POLL")
            successes += 1
            # Attempt execution immediately for whatever is ENTRY_READY right
            # now - including the setup this pair's own detection may have
            # just created - instead of waiting for every other monitored
            # pair to also be polled first. run_live_automation_once is
            # idempotent (processed_setup_ids/executed_trade_plan_ids) and
            # has its own internal exception guard, so calling it once per
            # pair instead of once per cycle is safe and cheap when there is
            # nothing new to act on.
            run_live_automation_once(state, source="MONITORING_POLL")
        except Exception as exc:
            completed = now_iso()
            message = str(exc)
            failures.append(f"{symbol}: {message}")
            state.market_polls[symbol] = {
                "symbol": symbol,
                "poll_success": "NO",
                "poll_status": "ERROR",
                "last_live_price": "N/A",
                "bid_price": "N/A",
                "ask_price": "N/A",
                "mark_price": "N/A",
                "contract_config_loaded": "NO",
                "last_error": message,
                "last_poll_started": started,
                "last_poll_completed": completed,
            }
    if not state.monitoring.get("active") or state.monitoring.get("session_id") != session_id:
        return
    state.monitoring["polling_status"] = "READY" if successes else "ERROR"
    state.monitoring["last_error"] = "None" if successes else "; ".join(failures) if failures else "No enabled pairs polled."
    state.monitoring["last_poll_cycle_completed"] = now_iso()
    state.monitoring["poll_cycle_count"] = int(state.monitoring.get("poll_cycle_count") or 0) + 1


def _schedule_poll(session_id: str, *, delay: float) -> None:
    state = get_state()
    if not state.monitoring.get("active") or state.monitoring.get("session_id") != session_id:
        return
    worker = Timer(delay, _poll_enabled_pairs, args=(session_id,))
    worker.daemon = True
    worker.start()


def _activate_selected_account_credentials() -> None:
    state = get_state()
    account_id = state.active_live_account_id or str(state.settings.get("active_account_id") or "")
    encrypted = state.encrypted_live_credentials.get(account_id)
    if not encrypted:
        return
    try:
        state.bitget_environment.runtime_credentials = decrypt_credentials(encrypted)
    except CredentialVaultError as exc:
        account = state.live_accounts.get(account_id)
        if account is not None:
            account["connection_status"] = "NEEDS_RECONNECT"
            account["verification_status"] = "NEEDS_RECONNECT"
            account["last_error"] = str(exc)


def _merge_live_candles(
    existing: tuple[Candle, ...], fresh: tuple[Candle, ...], *, max_size: int = LIVE_CANDLE_HISTORY_LIMIT
) -> tuple[Candle, ...]:
    """Merge freshly polled candles into the rolling live buffer.

    Candles are keyed by (symbol, timeframe, timestamp); when the same key
    appears in both ``existing`` and ``fresh``, the freshly fetched candle wins
    since it reflects the latest Bitget poll. The result is sorted chronologically
    and trimmed to the most recent ``max_size`` candles.
    """
    merged: dict[tuple[str, object, object], Candle] = {}
    for candle in (*existing, *fresh):
        merged[(candle.symbol, candle.timeframe, candle.timestamp)] = candle
    ordered = tuple(sorted(merged.values(), key=lambda candle: (candle.timestamp, candle.symbol, candle.timeframe.minutes)))
    return ordered[-max_size:]


def _derived_timeframe_candles(candles_1m: tuple[Candle, ...]) -> dict[int, tuple[Candle, ...]]:
    """Build the 1H/30M/16M/12M/8M chart series kept live from the 1-minute buffer.

    Informational/diagnostic only - the strategy funnel keeps sourcing exactly the
    timeframes its active timeframe_profile_id specifies (see live_setup_detection.py);
    this does not change strategy behavior.
    """
    profiles = {minutes: build_timeframe_profile(candles_1m, minutes) for minutes in DERIVED_CHART_TIMEFRAMES_MINUTES}
    if candles_1m:
        logger.info(
            "[HTF_SYNTHESIS] source_1m=%d latest_1m=%s 16M=%d 12M=%d 8M=%d min30_16M=%s min30_12M=%s min30_8M=%s",
            len(candles_1m),
            candles_1m[-1].timestamp.isoformat(),
            len(profiles.get(16, ())),
            len(profiles.get(12, ())),
            len(profiles.get(8, ())),
            len(profiles.get(16, ())) >= 30,
            len(profiles.get(12, ())) >= 30,
            len(profiles.get(8, ())) >= 30,
        )
    return profiles


def _normalize_candle_rows(rows: object) -> tuple[tuple[str, ...], ...]:
    if not isinstance(rows, (tuple, list)):
        return ()
    normalized: list[tuple[str, ...]] = []
    for row in rows:
        if isinstance(row, (tuple, list)):
            normalized.append(tuple(str(cell) for cell in row))
    return tuple(normalized)


def _poll_interval_seconds() -> int:
    try:
        value = int(str(get_state().settings.get("refresh_interval_seconds") or "15"))
    except ValueError:
        value = 15
    return max(MIN_POLL_INTERVAL_SECONDS, value)


def _session_id() -> str:
    return "mon_" + hashlib.sha256(now_iso().encode("utf-8")).hexdigest()[:16]
