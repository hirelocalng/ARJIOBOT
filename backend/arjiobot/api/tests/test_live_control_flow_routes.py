"""Live control-flow route tests."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from arjiobot.api.dependencies import get_state
from arjiobot.api.routes import monitoring
from arjiobot.api.tests.helpers import client
from arjiobot.market_data.candle_models import Candle, Timeframe


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


def test_live_candle_history_limit_matches_confirmed_backtest_depth() -> None:
    """2,000 1M candles keep live polling fast while still yielding 30+ 16M,
    12M, and 8M synthetic candles for Setup Radar/FVG scanning."""
    assert monitoring.LIVE_CANDLE_HISTORY_LIMIT == 2_000


def test_two_thousand_candles_produce_minimum_htf_scan_depth() -> None:
    candles = tuple(_candle(index) for index in range(monitoring.LIVE_CANDLE_HISTORY_LIMIT))

    profiles = monitoring._derived_timeframe_candles(candles)

    assert len(profiles[16]) >= 30
    assert len(profiles[12]) >= 30
    assert len(profiles[8]) >= 30


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
    assert state.market_polls["BTCUSDT"]["live_candle_history_limit"] == 2_000
    assert len(state.live_candles["BTCUSDT"]) == 3
    assert state.live_setup_detection["last_status"] == "WAITING"
    assert "not enough live candles" in state.live_setup_detection["last_blocked_reason"]


def test_merge_live_candles_appends_new_candles_to_existing() -> None:
    existing = (_candle(0), _candle(1))
    fresh = (_candle(2), _candle(3))

    merged = monitoring._merge_live_candles(existing, fresh)

    assert [candle.timestamp for candle in merged] == [candle.timestamp for candle in (*existing, *fresh)]


def test_merge_live_candles_replaces_duplicate_timestamp_with_fresh_candle() -> None:
    existing = (_candle(0, close="100"), _candle(1, close="100"))
    fresh = (_candle(0, close="999"),)

    merged = monitoring._merge_live_candles(existing, fresh)

    assert len(merged) == 2
    assert merged[0].close == Decimal("999")


def test_merge_live_candles_sorts_chronologically() -> None:
    existing = (_candle(2),)
    fresh = (_candle(0), _candle(1))

    merged = monitoring._merge_live_candles(existing, fresh)

    assert [candle.timestamp for candle in merged] == sorted(candle.timestamp for candle in merged)


def test_merge_live_candles_trims_to_configured_max_size() -> None:
    existing = tuple(_candle(i) for i in range(5))
    fresh = (_candle(5),)

    merged = monitoring._merge_live_candles(existing, fresh, max_size=3)

    assert len(merged) == 3
    assert [candle.timestamp.minute for candle in merged] == [3, 4, 5]


def test_monitoring_poll_merges_fresh_candles_into_existing_live_buffer(monkeypatch) -> None:
    api = client()
    state = get_state()
    state.settings["adapter_mode"] = "BITGET_LIVE"
    state.monitoring.update({"active": True, "session_id": "test_session"})
    state.market_polls["BTCUSDT"] = {"symbol": "BTCUSDT", "poll_success": "NO"}
    pre_existing = _candle(-10)
    state.live_candles["BTCUSDT"] = (pre_existing,)

    monkeypatch.setattr(monitoring, "_schedule_poll", lambda session_id, *, delay: None)
    monkeypatch.setattr(state.bitget_environment, "fetch_contract_config", lambda symbol, product_type="USDT-FUTURES": _contract(symbol))
    monkeypatch.setattr(state.bitget_environment, "fetch_ticker", lambda symbol, product_type="USDT-FUTURES": _ticker(symbol))
    monkeypatch.setattr(state.bitget_environment, "fetch_candles", lambda symbol, granularity="1m", limit=1000, product_type="USDT-FUTURES": _bitget_list_rows(symbol))

    monitoring._poll_enabled_pairs("test_session")

    candles = state.live_candles["BTCUSDT"]
    assert pre_existing.timestamp in {candle.timestamp for candle in candles}
    assert len(candles) == 4
    assert [candle.timestamp for candle in candles] == sorted(candle.timestamp for candle in candles)


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


def _candle(minute_offset: int, *, close: str = "100", symbol: str = "BTCUSDT") -> Candle:
    timestamp = datetime(2024, 1, 1, tzinfo=timezone.utc) + timedelta(minutes=minute_offset)
    return Candle(
        symbol=symbol,
        timeframe=Timeframe(1),
        timestamp=timestamp,
        open=close,
        high=close,
        low=close,
        close=close,
        volume="1",
    )


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
