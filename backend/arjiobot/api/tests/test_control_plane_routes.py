"""Control-plane route tests."""

from __future__ import annotations

from arjiobot.api.tests.helpers import client


def test_control_plane_exposes_unified_state() -> None:
    api = client()
    from arjiobot.api.dependencies import get_state
    get_state().live_accounts.clear()
    get_state().encrypted_live_credentials.clear()
    get_state().active_live_account_id = None
    api.patch(
        "/api/settings",
        json={
            "active_strategy_profile": "PROFILE_RECOVERED_HIGH_WINRATE",
            "default_backtesting_profile": "PROFILE_RECOVERED_HIGH_WINRATE",
            "risk_amount_per_trade": "100",
            "max_leverage": "10",
            "trading_mode": "OFF",
        },
    )
    api.post("/api/pairs", json={"symbol": "ETHUSDT", "enabled": True})

    snapshot = api.get("/api/control-plane").json()["data"]

    assert snapshot["source_of_truth"] == "BACKEND_CONTROL_PLANE"
    assert snapshot["active_strategy"]["selected_profile"] == "PROFILE_RECOVERED_HIGH_WINRATE"
    assert snapshot["active_exchange_mode"]["selected_trade_mode"] == "OFF"
    assert snapshot["active_risk_settings"]["fixed_risk_amount"] == "100"
    eth = next(pair for pair in snapshot["active_pairs"] if pair["symbol"] == "ETHUSDT")
    assert eth["monitoring_status"] == "NOT MONITORING"
    assert eth["market_data_stream_active"] == "NO"
    assert eth["last_price"] == "N/A"
    assert eth["last_price_update_time"] == "N/A"
    assert snapshot["active_account"]["connection_status"] == "NOT CONNECTED"
    assert "connection_status" in snapshot["active_account"]
    assert "api_credentials_present" in snapshot["connection_diagnostics"]
    assert "execution_ready" in snapshot["execution_readiness"]
    assert snapshot["live_execution_readiness_checklist"]["title"] == "LIVE EXECUTION READINESS CHECKLIST"
    assert snapshot["live_execution_readiness_checklist"]["overall_status"] == "BLOCKED"
    assert snapshot["live_execution_readiness_checklist"]["checks"]["Account Ready"]["ready"] == "NO"


def test_settings_profile_save_updates_control_plane_active_profile() -> None:
    api = client()
    response = api.patch(
        "/api/settings",
        json={
            "active_strategy_profile": "PROFILE_2",
            "default_backtesting_profile": "PROFILE_2",
            "trading_mode": "OFF",
        },
    )
    assert response.status_code == 200

    snapshot = api.get("/api/control-plane").json()["data"]

    assert snapshot["active_strategy"]["selected_profile"] == "PROFILE_2"
    assert snapshot["settings"]["active_strategy_profile"] == "PROFILE_2"
