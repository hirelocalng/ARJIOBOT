"""Monitored pair routes."""

from __future__ import annotations

from fastapi import APIRouter

from arjiobot.api.dependencies import get_state, save_pairs
from arjiobot.api.schemas.common import ok

router = APIRouter(prefix="/api/pairs", tags=["pairs"])


@router.get("")
def list_pairs():
    return ok(tuple(get_state().monitored_pairs.values()))


@router.get("/status")
def pair_status():
    state = get_state()
    rows = []
    for pair in state.monitored_pairs.values():
        symbol = str(pair.get("symbol", "")).upper()
        poll = state.market_polls.get(symbol, {})
        rows.append(
            {
                "symbol": symbol,
                "enabled": bool(pair.get("enabled")),
                "monitoring_active": bool(state.monitoring.get("active")),
                "supported_by_bitget": "YES" if poll.get("contract_config_loaded") == "YES" else "NO",
                "contract_config_loaded": poll.get("contract_config_loaded", "NO"),
                "monitoring_status": _monitoring_status(state, poll),
                "last_price": poll.get("last_live_price", "N/A") if poll.get("poll_success") == "YES" else "N/A",
                "bid": poll.get("bid_price", "N/A"),
                "ask": poll.get("ask_price", "N/A"),
                "mark_price": poll.get("mark_price", "N/A"),
                "last_update": poll.get("last_poll_completed", "N/A"),
                "last_error": poll.get("last_error", "None"),
            }
    )
    return ok(tuple(rows))


def _monitoring_status(state, poll: dict[str, object]) -> str:
    if state.monitoring.get("active") and poll.get("poll_success") == "YES":
        return "ACTIVE"
    if state.monitoring.get("active") and poll.get("poll_status") == "POLLING":
        return "POLLING"
    if poll.get("last_error") and poll.get("poll_status") == "ERROR":
        return "ERROR"
    return "NOT MONITORING"


@router.post("")
def add_pair(payload: dict[str, object]):
    symbol = str(payload["symbol"]).upper()
    state = get_state()
    existing_leverage = (state.monitored_pairs.get(symbol) or {}).get("leverage")
    state.monitored_pairs[symbol] = {
        "symbol": symbol,
        "enabled": bool(payload.get("enabled", True)),
        "leverage": payload.get("leverage", existing_leverage),
    }
    save_pairs(state.monitored_pairs)
    return ok(state.monitored_pairs[symbol])


@router.delete("/{symbol}")
def remove_pair(symbol: str):
    state = get_state()
    state.monitored_pairs.pop(symbol.upper(), None)
    save_pairs(state.monitored_pairs)
    return ok({"deleted": True})


@router.patch("/{symbol}")
def update_pair(symbol: str, payload: dict[str, object]):
    state = get_state()
    pair = state.monitored_pairs.setdefault(symbol.upper(), {"symbol": symbol.upper(), "enabled": True, "leverage": None})
    pair["enabled"] = bool(payload.get("enabled", pair["enabled"]))
    if "leverage" in payload:
        pair["leverage"] = payload["leverage"]
    save_pairs(state.monitored_pairs)
    return ok(pair)


@router.post("/import")
def import_pairs(payload: dict[str, object]):
    imported = []
    for symbol in payload.get("symbols", []):
        normalized = str(symbol).upper()
        existing_leverage = (get_state().monitored_pairs.get(normalized) or {}).get("leverage")
        get_state().monitored_pairs[normalized] = {"symbol": normalized, "enabled": True, "leverage": existing_leverage}
        imported.append(normalized)
    save_pairs(get_state().monitored_pairs)
    return ok({"imported": imported})
