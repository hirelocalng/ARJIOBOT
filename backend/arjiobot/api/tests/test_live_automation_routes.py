"""Live automation route tests."""

from __future__ import annotations

from arjiobot.api.dependencies import get_state
from arjiobot.api.tests.helpers import client
from arjiobot.exchange.bitget_environment import BitgetCredentialConfig, TradeMode
from arjiobot.strategy.demo_strategy import make_entry_ready_setup


def test_live_automation_processes_entry_ready_setup_to_bitget_order(monkeypatch) -> None:
    api = client()
    state = get_state()
    service = state.bitget_environment
    service.runtime_credentials = BitgetCredentialConfig(api_key="key", api_secret="secret", passphrase="pass")
    service.mode = TradeMode.LIVE
    service.live_armed = True
    service.last_connection_result = {
        "connection_status": "PASSED",
        "available_balance": "1000",
        "available_margin": "1000",
        "last_successful_verification_time": "2026-06-16T00:00:00+00:00",
    }
    service.last_account_payload = {
        "total_equity": "1000",
        "available_margin": "1000",
        "margin_mode": "isolated",
    }
    state.settings.update(
        {
            "adapter_mode": "BITGET_LIVE",
            "live_trading_enabled": True,
            "trading_mode": "LIVE",
            "active_strategy_profile": "PROFILE_2",
            "selected_rr_profile": "LEG_TARGET_RESEARCH",
            "risk_amount_per_trade": "10",
            "max_leverage": "100",
            "max_daily_loss": "500",
            "max_open_trades": 5,
        }
    )
    state.monitoring.update({"active": True, "session_id": "test", "source": "LIVE_MARKET_DATA"})
    state.market_polls["BTCUSDT"] = {
        "symbol": "BTCUSDT",
        "poll_success": "YES",
        "poll_status": "READY",
        "last_live_price": "90",
    }
    setup = make_entry_ready_setup(latest_price="90")
    state.setups[setup.setup_id] = setup

    monkeypatch.setattr(service, "fetch_contract_config", lambda symbol, product_type="USDT-FUTURES": _contract(symbol))
    monkeypatch.setattr(service, "fetch_ticker", lambda symbol, product_type="USDT-FUTURES": _ticker(symbol))
    monkeypatch.setattr(service, "fetch_candles", lambda symbol, granularity="1m", limit=100, product_type="USDT-FUTURES": _candles(symbol))
    monkeypatch.setattr(service, "_private_request", lambda method, path, **kwargs: {"code": "00000", "msg": "success", "data": {"orderId": "ord_live_1"}})

    result = api.post("/api/live-automation/run-once").json()["data"]
    status = api.get("/api/live-automation/status").json()["data"]

    assert result["status"] == "SUBMITTED"
    assert len(state.signals) == 1
    assert len(state.trade_plans) == 1
    assert len(service.orders) == 1
    assert service.orders[0]["bitget_order_id"] == "ord_live_1"
    assert status["executed_trade_plan_count"] == 1
    assert status["latest_attempt"]["stage"] == "BITGET_LIVE_ORDER"


def test_live_automation_blocks_without_entry_ready_setup() -> None:
    api = client()
    state = get_state()
    service = state.bitget_environment
    service.runtime_credentials = BitgetCredentialConfig(api_key="key", api_secret="secret", passphrase="pass")
    service.mode = TradeMode.LIVE
    service.live_armed = True
    state.settings.update(
        {
            "adapter_mode": "BITGET_LIVE",
            "live_trading_enabled": True,
            "trading_mode": "LIVE",
            "risk_amount_per_trade": "10",
            "max_leverage": "100",
        }
    )
    state.monitoring["active"] = True
    state.market_polls["BTCUSDT"] = {"symbol": "BTCUSDT", "poll_success": "YES", "poll_status": "READY"}

    result = api.post("/api/live-automation/run-once").json()["data"]

    assert result["status"] == "WAITING"
    assert result["stage"] == "SETUP_RADAR"
    assert state.bitget_environment.orders == []


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
        "pricePlace": "2",
        "volumePlace": "3",
        "sizeMultiplier": "0.001",
        "minLever": "1",
        "maxLever": "125",
        "maxMarketOrderQty": "1000",
        "maxOrderQty": "1000",
    }


def _ticker(symbol: str) -> dict[str, object]:
    return {
        "symbol": symbol,
        "product_type": "USDT-FUTURES",
        "last_price": "90",
        "bid_price": "89.9",
        "ask_price": "90.1",
        "mark_price": "90",
        "index_price": "90",
        "timestamp": "1",
    }


def _candles(symbol: str) -> dict[str, object]:
    return {
        "symbol": symbol,
        "product_type": "USDT-FUTURES",
        "granularity": "1m",
        "candle_count": 100,
        "candles_loaded": "YES",
        "last_candle_timestamp": "1",
    }
