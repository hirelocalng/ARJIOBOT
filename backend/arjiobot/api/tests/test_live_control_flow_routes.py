"""Live control-flow route tests."""

from datetime import datetime, timezone

from arjiobot.api.dependencies import get_state
from arjiobot.api.routes import monitoring
from arjiobot.api.tests.helpers import client


def test_monitoring_start_blocks_without_pairs() -> None:
    api = client()
    get_state().monitored_pairs.clear()

    response = api.post("/api/monitoring/start", json={})

    assert response.status_code == 400
    assert "no pairs selected" in _error(response)


def test_monitoring_start_blocks_mock_adapter() -> None:
    api = client()
    api.patch("/api/settings", json={"adapter_mode": "MOCK", "trading_mode": "OFF"})

    response = api.post("/api/monitoring/start", json={})

    assert response.status_code == 400
    assert "exchange adapter is MOCK" in _error(response)


def test_monitoring_start_returns_before_live_market_poll(monkeypatch) -> None:
    api = client()
    state = get_state()
    state.settings["adapter_mode"] = "BITGET_LIVE"

    def blocked_if_called_synchronously(symbol: str, product_type: str = "USDT-FUTURES"):
        raise RuntimeError("simulated slow Bitget route")

    monkeypatch.setattr(state.bitget_environment, "fetch_contract_config", blocked_if_called_synchronously)

    response = api.post("/api/monitoring/start", json={})

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["monitoring_status"] == "ACTIVE"
    assert state.monitoring["active"] is True
    assert state.market_polls["BTCUSDT"]["poll_status"] in {"POLLING", "ERROR"}


def test_stop_monitoring_clears_live_state() -> None:
    api = client()
    state = get_state()
    state.monitoring["active"] = True
    state.market_polls["BTCUSDT"] = {"poll_success": "YES"}

    response = api.post("/api/monitoring/stop").json()["data"]

    assert response["monitoring_status"] == "NOT MONITORING"
    assert state.monitoring["active"] is False
    assert state.market_polls == {}


def test_monitoring_poll_feeds_live_candle_rows_into_strategy_state(monkeypatch) -> None:
    api = client()
    state = get_state()
    state.settings["adapter_mode"] = "BITGET_LIVE"
    state.monitoring.update({"active": True, "session_id": "test_session"})
    state.market_polls["BTCUSDT"] = {"symbol": "BTCUSDT", "poll_success": "NO"}

    monkeypatch.setattr(monitoring, "_schedule_poll", lambda session_id, *, delay: None)
    monkeypatch.setattr(state.bitget_environment, "fetch_contract_config", lambda symbol, product_type="USDT-FUTURES": _contract(symbol))
    monkeypatch.setattr(state.bitget_environment, "fetch_ticker", lambda symbol, product_type="USDT-FUTURES": _ticker(symbol))
    monkeypatch.setattr(state.bitget_environment, "fetch_candles", lambda symbol, granularity="1m", limit=1000, product_type="USDT-FUTURES": _bitget_list_rows(symbol))

    monitoring._poll_enabled_pairs("test_session")

    assert state.market_polls["BTCUSDT"]["poll_success"] == "YES"
    assert state.market_polls["BTCUSDT"]["live_candle_count"] == 3
    assert len(state.live_candles["BTCUSDT"]) == 3
    assert state.live_setup_detection["last_status"] == "WAITING"
    assert "not enough live candles" in state.live_setup_detection["last_blocked_reason"]


def test_live_trading_on_blocks_without_connected_account() -> None:
    api = client()
    state = get_state()
    state.live_accounts.clear()
    state.encrypted_live_credentials.clear()
    state.active_live_account_id = None

    response = api.post("/api/live-trading/toggle", json={"enabled": True, "understand_real_funds": True, "confirmation_text": "ENABLE LIVE"})

    assert response.status_code == 400
    assert "no connected active Bitget account selected" in _error(response)


def test_live_trading_off_always_disables() -> None:
    api = client()
    get_state().settings["live_trading_enabled"] = True

    response = api.post("/api/live-trading/toggle", json={"enabled": False}).json()["data"]

    assert response["live_trading_enabled"] is False
    assert response["message"] == "LIVE TRADING OFF"


def _error(response) -> str:
    payload = response.json()
    detail = payload.get("detail", payload)
    if isinstance(detail, dict):
        return str(detail.get("error", {}).get("message") or detail)
    return str(detail)


def _contract(symbol: str) -> dict[str, object]:
    return {
        "symbol": symbol,
        "product_type": "USDT-FUTURES",
        "margin_coin": "USDT",
        "contract_config_loaded": "YES",
        "supported": "YES",
        "symbol_status": "normal",
        "minTradeNum": "0.001",
        "minTradeUSDT": "1",
        "maxLever": "125",
    }


def _ticker(symbol: str) -> dict[str, object]:
    return {
        "symbol": symbol,
        "product_type": "USDT-FUTURES",
        "last_price": "100",
        "bid_price": "99.9",
        "ask_price": "100.1",
        "mark_price": "100",
        "index_price": "100",
    }


def _bitget_list_rows(symbol: str) -> dict[str, object]:
    base = int(datetime(2024, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
    rows = [
        [str(base), "100", "101", "99", "100.5", "10"],
        [str(base + 60_000), "100.5", "102", "100", "101", "12"],
        [str(base + 120_000), "101", "103", "100.5", "102", "11"],
    ]
    return {
        "symbol": symbol,
        "product_type": "USDT-FUTURES",
        "granularity": "1m",
        "candle_count": len(rows),
        "candles_loaded": "YES",
        "last_candle_timestamp": rows[-1][0],
        "rows": rows,
    }
