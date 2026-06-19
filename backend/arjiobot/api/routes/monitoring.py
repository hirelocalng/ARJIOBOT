"""Live monitoring session routes."""

from __future__ import annotations

import hashlib
from threading import Timer

from fastapi import APIRouter

from arjiobot.api.dependencies import get_state, now_iso
from arjiobot.api.errors import api_error
from arjiobot.api.schemas.common import ok
from arjiobot.exchange.account_vault import CredentialVaultError, decrypt_credentials
from arjiobot.live_automation import run_live_automation_once
from arjiobot.live_setup_detection import candles_from_bitget_rows, detect_live_setups_for_symbol
from arjiobot.market_data.candle_models import Candle

router = APIRouter(prefix="/api/monitoring", tags=["monitoring"])
MIN_POLL_INTERVAL_SECONDS = 5
LIVE_CANDLE_BUFFER_MAX_SIZE = 2000


@router.post("/start")
def start_monitoring(payload: dict[str, object] | None = None):
    payload = payload or {}
    state = get_state()
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
    return ok(
        {
            "monitoring_status": "ACTIVE",
            "message": "MONITORING STARTED - live market polling in progress",
            "session_id": session_id,
            "pairs": tuple(state.market_polls),
        }
    )


@router.post("/stop")
def stop_monitoring(payload: dict[str, object] | None = None):
    state = get_state()
    state.monitoring.update({"active": False, "stopped_at": now_iso(), "last_error": "None"})
    state.market_polls.clear()
    state.setups.clear()
    return ok({"monitoring_status": "NOT MONITORING", "message": "MONITORING STOPPED"})


@router.get("/status")
def monitoring_status():
    state = get_state()
    return ok({"monitoring": state.monitoring, "pairs": tuple(state.market_polls.values())})


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
    state = get_state()
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
            candles = state.bitget_environment.fetch_candles(symbol, "1m", 1000)
            rows = _normalize_candle_rows(candles.get("rows", ()))
            fresh_candles = candles_from_bitget_rows(symbol, rows)
            state.live_candles[symbol] = _merge_live_candles(state.live_candles.get(symbol, ()), fresh_candles)
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
                "last_error": "",
                "next_scheduled_refresh_time": completed,
            }
            detect_live_setups_for_symbol(state, symbol, source="MONITORING_POLL")
            successes += 1
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
    if successes:
        run_live_automation_once(state, source="MONITORING_POLL")
    _schedule_poll(session_id, delay=_poll_interval_seconds())


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
    existing: tuple[Candle, ...], fresh: tuple[Candle, ...], *, max_size: int = LIVE_CANDLE_BUFFER_MAX_SIZE
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
