"""Account status route tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from arjiobot.api.dependencies import get_state
from arjiobot.api.tests.helpers import client
from arjiobot.api.routes import account_status
from arjiobot.exchange.bitget_environment import EnvironmentLockError


def test_account_status_no_account_blocks_live_execution() -> None:
    api = client()
    state = get_state()
    state.live_accounts.clear()
    state.encrypted_live_credentials.clear()
    state.active_live_account_id = None

    response = api.get("/api/account-status/summary")
    data = response.json()["data"]

    assert response.status_code == 200
    assert data["account_connection"]["connection_status"] == "NO ACTIVE ACCOUNT SELECTED"
    assert data["balance"]["available_balance"] == "N/A"
    assert data["open_positions"]["position_count"] == 0
    assert data["risk_status"]["live_execution_status"] == "BLOCKED"


def test_account_refresh_records_invalid_key_error(monkeypatch) -> None:
    api = client()
    state = get_state()
    state.active_live_account_id = "acct_1"
    state.live_accounts["acct_1"] = {
        "account_id": "acct_1",
        "account_name": "Primary",
        "exchange": "BITGET",
        "credential_type": "LIVE",
        "api_key": "abcd****wxyz",
        "is_active": True,
        "is_default": True,
        "connection_status": "CONNECTED",
        "verification_status": "VERIFIED",
        "last_successful_api_ping_time": "2026-06-15T00:00:00+00:00",
        "last_error": "None",
    }

    def fail_connection(symbol: str = "BTCUSDT"):
        raise EnvironmentLockError("invalid api key")

    monkeypatch.setattr(account_status, "_activate_selected_credentials", lambda: None)
    monkeypatch.setattr(state.bitget_environment, "test_connection", fail_connection)
    response = api.post("/api/account-status/refresh")
    summary = api.get("/api/account-status/summary").json()["data"]

    assert response.status_code == 400
    assert summary["account_connection"]["connection_status"] == "ERROR"
    assert summary["account_connection"]["last_error"] == "invalid api key"
    assert summary["balance"]["available_balance"] == "N/A"


def test_account_refresh_success_shows_signed_account_payload(monkeypatch) -> None:
    api = client()
    state = get_state()
    state.active_live_account_id = "acct_1"
    state.live_accounts["acct_1"] = {
        "account_id": "acct_1",
        "account_name": "Primary",
        "exchange": "BITGET",
        "credential_type": "LIVE",
        "api_key": "abcd****wxyz",
        "is_active": True,
        "is_default": True,
        "connection_status": "WAITING",
        "verification_status": "WAITING",
        "last_error": "None",
    }

    def fake_connection(symbol: str = "BTCUSDT"):
        payload = {
            "available_balance": "1000",
            "available_margin": "900",
            "total_equity": "1100",
            "frozen_margin": "25",
            "unrealized_pnl": "5",
            "margin_mode": "isolated",
            "position_mode": "one_way_mode",
            "fetched_at": "2026-06-15T00:00:00+00:00",
        }
        state.bitget_environment.last_account_payload = payload
        result = {
            "private_api_auth_status": "PASSED",
            "available_balance": "1000",
            "available_margin": "900",
            "account_payload": payload,
            "last_successful_verification_time": datetime.now(timezone.utc).isoformat(),
        }
        state.bitget_environment.last_connection_result = result
        return result

    monkeypatch.setattr(account_status, "_activate_selected_credentials", lambda: None)
    monkeypatch.setattr(state.bitget_environment, "test_connection", fake_connection)
    response = api.post("/api/account-status/refresh")
    data = response.json()["data"]

    assert response.status_code == 200
    assert data["account_connection"]["connection_status"] == "CONNECTED"
    assert data["account_connection"]["private_api_auth_status"] == "PASSED"
    assert data["balance"]["available_balance"] == "1000"
    assert data["margin_mode"]["margin_mode"] == "ISOLATED"


def test_positions_and_open_orders_use_real_empty_responses(monkeypatch) -> None:
    api = client()
    state = get_state()
    state.active_live_account_id = "acct_1"
    state.live_accounts["acct_1"] = {"account_id": "acct_1", "is_active": True, "is_default": True, "connection_status": "CONNECTED"}
    monkeypatch.setattr(account_status, "_activate_selected_credentials", lambda: None)

    monkeypatch.setattr(state.bitget_environment, "fetch_positions", lambda: {"positions": (), "position_count": 0, "fetched_at": "2026-06-15T00:00:00+00:00"})
    monkeypatch.setattr(state.bitget_environment, "fetch_open_orders", lambda: {"orders": (), "order_count": 0, "fetched_at": "2026-06-15T00:00:00+00:00"})

    positions = api.get("/api/account-status/positions").json()["data"]
    orders = api.get("/api/account-status/open-orders").json()["data"]

    assert positions["status"] == "NO OPEN POSITIONS"
    assert positions["positions"] == []
    assert orders["status"] == "NO OPEN ORDERS"
    assert orders["orders"] == []


def test_open_position_fields_are_returned(monkeypatch) -> None:
    api = client()
    state = get_state()
    state.active_live_account_id = "acct_1"
    state.live_accounts["acct_1"] = {"account_id": "acct_1", "is_active": True, "is_default": True, "connection_status": "CONNECTED"}
    monkeypatch.setattr(account_status, "_activate_selected_credentials", lambda: None)

    monkeypatch.setattr(
        state.bitget_environment,
        "fetch_positions",
        lambda: {"positions": ({"symbol": "BTCUSDT", "holdSide": "short", "total": "0.01", "unrealizedPL": "12"},), "fetched_at": "2026-06-15T00:00:00+00:00"},
    )
    data = api.get("/api/account-status/positions").json()["data"]

    assert data["status"] == "OPEN POSITIONS"
    assert data["position_count"] == 1
    assert data["positions"][0]["symbol"] == "BTCUSDT"
    assert data["positions"][0]["holdSide"] == "short"


def test_order_type_and_price_type_come_from_execution_settings() -> None:
    api = client()
    state = get_state()
    state.settings["order_type"] = "limit"
    state.settings["price_type"] = "post_only"

    data = api.get("/api/account-status/summary").json()["data"]

    assert data["order_type_price_type"]["order_type"] == "LIMIT"
    assert data["order_type_price_type"]["price_type"] == "POST_ONLY"


def test_stale_account_data_blocks_live_execution() -> None:
    api = client()
    state = get_state()
    stale_time = (datetime.now(timezone.utc) - timedelta(seconds=120)).isoformat()
    state.active_live_account_id = "acct_1"
    state.live_accounts["acct_1"] = {
        "account_id": "acct_1",
        "is_active": True,
        "is_default": True,
        "connection_status": "CONNECTED",
        "last_successful_api_ping_time": stale_time,
    }
    state.settings["risk_amount_per_trade"] = "100"

    data = api.get("/api/account-status/summary").json()["data"]

    assert data["data_freshness"]["account_data_status"] == "ACCOUNT DATA STALE"
    assert "ACCOUNT_DATA_STALE" in data["risk_status"]["blockers"]
    assert data["risk_status"]["live_execution_status"] == "BLOCKED"
