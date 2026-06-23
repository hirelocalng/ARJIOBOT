"""Admin route tests."""

from __future__ import annotations

from arjiobot.api.dependencies import get_state
from arjiobot.api.tests.helpers import client
from arjiobot.live_setup_detection import _setup_from_trade


def test_clear_setup_history_endpoint_clears_completed_and_invalidated() -> None:
    """POST /api/admin/clear-setup-history must clear completed_setups/
    invalidated_setups in memory and report how many were cleared. The
    global conftest.py autouse fixture already redirects the persisted file
    to a tmp_path for this test, so it never touches the real
    backend/data/ files."""
    api = client()
    state = get_state()
    trade = _setup_from_trade(
        {
            "trade_id": "trade_admin_clear_1",
            "symbol": "ADAUSDT",
            "direction": "BEARISH",
            "entry_timestamp": "2026-06-24T01:30:00+00:00",
            "entry_price": "100",
            "stop_loss": "120",
            "take_profit": "80",
            "source_12m_fvg_id": "fvg12_admin_clear",
            "source_16m_swing_id": "swing_admin_clear",
            "source_16m_fvg_id": "fvg16_admin_clear",
        },
        state=state,
        profile_id="PROFILE_2",
        timeframe_profile_id="DEFAULT_16_12_8",
    )
    state.completed_setups[trade.setup_id] = trade
    state.setup_history[trade.setup_id] = [{"from_state": None, "to_state": "ENTRY_READY"}]

    result = api.post("/api/admin/clear-setup-history").json()["data"]

    assert result["cleared_completed_count"] == 1
    assert state.completed_setups == {}
    assert trade.setup_id not in state.setup_history
