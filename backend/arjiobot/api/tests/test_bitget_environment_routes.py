"""Live-only Bitget Futures environment route tests."""

from __future__ import annotations

import re

from arjiobot.api.dependencies import get_state
from arjiobot.api.tests.helpers import client
from arjiobot.exchange.bitget_environment import BitgetCredentialConfig, BitgetEnvironmentService, TradeMode


def _credentials() -> dict[str, str]:
    return {
        "mode": "LIVE",
        "api_key": "live_key_123456",
        "api_secret": "live_secret",
        "passphrase": "live_pass",
        "environment": "LIVE",
    }


def _order(profile: str = "PROFILE_RECOVERED_HIGH_WINRATE") -> dict[str, object]:
    return {
        "selected_profile_id": profile,
        "applied_profile_id": profile,
        "profile_lock_status": "PASSED",
        "risk_lock_status": "PASSED",
        "environment_lock_status": "PASSED",
        "exchange_lock_status": "PASSED",
        "symbol": "BTCUSDT",
        "side": "SELL",
        "trade_type": "ISOLATED_MARGIN",
        "margin_mode": "isolated",
        "selected_fixed_risk_amount": "100",
        "risk_amount": "100",
        "entry_price": "100",
        "stop_loss": "101",
        "take_profit": "98.5",
        "max_allowed_leverage": "100",
        "selected_max_leverage": "100",
        "max_risk_per_trade": "100",
        "max_daily_loss": "500",
        "max_trades_per_day": 5,
        "max_open_positions": 2,
        "entry_model": "DIRECT_12M_RETRACE",
    }


def _order_with(*, risk: str = "100", side: str = "SELL", entry: str = "100", stop: str = "101", target: str = "98.5", max_leverage: str = "100") -> dict[str, object]:
    payload = _order()
    payload.update(
        {
            "selected_fixed_risk_amount": risk,
            "risk_amount": risk,
            "max_risk_per_trade": risk,
            "side": side,
            "entry_price": entry,
            "stop_loss": stop,
            "take_profit": target,
            "max_allowed_leverage": max_leverage,
            "selected_max_leverage": max_leverage,
        }
    )
    return payload


def test_signature_with_query_and_post_body_are_bitget_compatible() -> None:
    service = BitgetEnvironmentService()
    credentials = BitgetCredentialConfig(api_key="key", api_secret="secret", passphrase="pass")

    signed_get = service.build_signed_request(
        "GET",
        "/api/v2/mix/account/account",
        query={"symbol": "BTCUSDT", "productType": "USDT-FUTURES", "marginCoin": "USDT"},
        credentials=credentials,
    )
    signed_post = service.build_signed_request(
        "POST",
        "/api/v2/mix/order/place-order",
        body={"symbol": "BTCUSDT", "productType": "USDT-FUTURES", "size": "1"},
        credentials=credentials,
    )

    assert re.fullmatch(r"\d{13}", signed_get.timestamp)
    assert "GET/api/v2/mix/account/account?symbol=BTCUSDT&productType=USDT-FUTURES&marginCoin=USDT" in signed_get.prehash
    assert signed_get.headers["ACCESS-PASSPHRASE"] == "pass"
    assert signed_get.headers["ACCESS-SIGN"]
    assert "POST/api/v2/mix/order/place-order" in signed_post.prehash
    assert '"symbol":"BTCUSDT"' in signed_post.prehash
    assert "paptrading" not in signed_get.headers
    assert "paptrading" not in signed_post.headers


def test_default_mode_is_off_and_demo_routes_are_removed() -> None:
    api = client()

    mode = api.get("/api/bitget/mode").json()["data"]
    demo_connection = api.post("/api/bitget/connection/demo")
    demo_order = api.post("/api/bitget/orders/test-demo", json=_order())

    assert mode["trading_mode"] == "OFF"
    assert mode["live_armed"] == "NO"
    assert mode["environment_lock_verified"] == "NO"
    assert demo_connection.status_code == 404
    assert demo_order.status_code == 404


def test_live_credentials_are_saved_without_secret_exposure() -> None:
    api = client()

    saved = api.post("/api/bitget/credentials", json=_credentials()).json()["data"]
    status = api.get("/api/bitget/credentials/status").json()["data"]

    assert "api_secret" not in saved
    assert "passphrase" not in saved
    assert saved["credential_type"] == "LIVE"
    assert saved["account_type"] == "REAL"
    assert saved["rest_base_url"] == "https://api.bitget.com"
    assert status["live"]["configured"] is True


def test_dry_run_mode_can_start_without_credentials_but_live_credentials_lock_when_present(monkeypatch) -> None:
    monkeypatch.delenv("BITGET_API_KEY", raising=False)
    monkeypatch.delenv("BITGET_API_SECRET", raising=False)
    monkeypatch.delenv("BITGET_API_PASSPHRASE", raising=False)
    api = client()
    state = get_state()
    state.live_accounts.clear()
    state.encrypted_live_credentials.clear()
    state.active_live_account_id = None
    state.settings["active_account_id"] = ""

    public_only = api.post("/api/bitget/mode", json={"mode": "DRY_RUN_PREVIEW"}).json()["data"]
    api.post("/api/bitget/credentials", json=_credentials())
    switched = api.post("/api/bitget/mode", json={"mode": "DRY_RUN_PREVIEW"}).json()["data"]

    assert public_only["trading_mode"] == "DRY_RUN_PREVIEW"
    assert public_only["live_armed"] == "NO"
    assert public_only["environment_lock_verified"] == "NO"
    assert switched["trading_mode"] == "DRY_RUN_PREVIEW"
    assert switched["live_armed"] == "NO"
    assert switched["environment_lock_verified"] == "YES"


def test_live_mode_requires_enable_live_confirmation() -> None:
    api = client()
    api.post("/api/bitget/credentials", json=_credentials())

    blocked = api.post("/api/bitget/mode", json={"mode": "LIVE"})

    assert blocked.status_code == 400
    assert "ENABLE LIVE" in _error(blocked)


def test_dry_run_preview_builds_payload_without_submission(monkeypatch) -> None:
    api = client()
    api.post("/api/bitget/credentials", json=_credentials())
    api.post("/api/bitget/mode", json={"mode": "DRY_RUN_PREVIEW"})
    service = _service()

    monkeypatch.setattr(service, "fetch_contract_config", lambda symbol, product_type="USDT-FUTURES": _contract(symbol))
    monkeypatch.setattr(service, "fetch_ticker", lambda symbol, product_type="USDT-FUTURES": _ticker(symbol))
    monkeypatch.setattr(service, "fetch_candles", lambda symbol, granularity="1m", limit=100, product_type="USDT-FUTURES": _candles(symbol))

    preview = api.post("/api/bitget/orders/dry-run-preview", json=_order()).json()["data"]

    assert preview["would_place_order"] == "YES"
    assert preview["network_submitted"] is False
    assert preview["endpoint"] == "/api/v2/mix/order/place-order"
    assert preview["sanitized_payload"]["productType"] == "USDT-FUTURES"
    assert preview["sanitized_payload"]["marginMode"] == "isolated"
    assert preview["sanitized_payload"]["marginCoin"] == "USDT"
    assert preview["sanitized_payload"]["side"] == "sell"
    assert preview["selected_fixed_risk_amount"] == "100"
    assert preview["applied_fixed_risk_amount"] == "100"
    assert preview["applied_margin_amount"] == "100"
    assert preview["expected_loss_at_sl_excluding_fees"] == "100.000"
    assert preview["risk_within_limit"] == "YES"


def test_selected_fixed_risk_amounts_drive_sizing_without_old_defaults(monkeypatch) -> None:
    api = client()
    api.post("/api/bitget/credentials", json=_credentials())
    api.post("/api/bitget/mode", json={"mode": "DRY_RUN_PREVIEW"})
    service = _service()
    monkeypatch.setattr(service, "fetch_contract_config", lambda symbol, product_type="USDT-FUTURES": _contract(symbol))
    monkeypatch.setattr(service, "fetch_ticker", lambda symbol, product_type="USDT-FUTURES": _ticker(symbol))
    monkeypatch.setattr(service, "fetch_candles", lambda symbol, granularity="1m", limit=100, product_type="USDT-FUTURES": _candles(symbol))

    previews = [api.post("/api/bitget/orders/dry-run-preview", json=_order_with(risk=risk)).json()["data"] for risk in ("10", "25", "100")]

    assert [item["selected_fixed_risk_amount"] for item in previews] == ["10", "25", "100"]
    assert [item["applied_fixed_risk_amount"] for item in previews] == ["10", "25", "100"]
    assert [item["applied_margin_amount"] for item in previews] == ["10", "25", "100"]
    assert [item["expected_loss_at_sl_excluding_fees"] for item in previews] == ["10.000", "25.000", "100.000"]
    assert [item["size"] for item in previews] == ["10.000", "25.000", "100.000"]
    assert all(item["required_leverage"] == "1E+2" for item in previews)


def test_buy_and_sell_dry_run_payloads_map_to_bitget_sides(monkeypatch) -> None:
    api = client()
    api.post("/api/bitget/credentials", json=_credentials())
    api.post("/api/bitget/mode", json={"mode": "DRY_RUN_PREVIEW"})
    service = _service()
    monkeypatch.setattr(service, "fetch_contract_config", lambda symbol, product_type="USDT-FUTURES": _contract(symbol))
    monkeypatch.setattr(service, "fetch_ticker", lambda symbol, product_type="USDT-FUTURES": _ticker(symbol))
    monkeypatch.setattr(service, "fetch_candles", lambda symbol, granularity="1m", limit=100, product_type="USDT-FUTURES": _candles(symbol))

    buy = api.post("/api/bitget/orders/dry-run-preview", json=_order_with(side="BUY", entry="100", stop="99", target="101.5")).json()["data"]
    sell = api.post("/api/bitget/orders/dry-run-preview", json=_order_with(side="SELL", entry="100", stop="101", target="98.5")).json()["data"]

    assert buy["side"] == "BUY"
    assert buy["sanitized_payload"]["side"] == "buy"
    assert sell["side"] == "SELL"
    assert sell["sanitized_payload"]["side"] == "sell"


def test_required_leverage_uses_exchange_cap_not_user_selected_cap(monkeypatch) -> None:
    api = client()
    api.post("/api/bitget/credentials", json=_credentials())
    api.post("/api/bitget/mode", json={"mode": "DRY_RUN_PREVIEW"})
    service = _service()

    def lower_exchange_contract(symbol: str, product_type="USDT-FUTURES"):
        contract = _contract(symbol)
        contract["maxLever"] = "50"
        return contract

    monkeypatch.setattr(service, "fetch_contract_config", lower_exchange_contract)
    monkeypatch.setattr(service, "fetch_ticker", lambda symbol, product_type="USDT-FUTURES": _ticker(symbol))
    monkeypatch.setattr(service, "fetch_candles", lambda symbol, granularity="1m", limit=100, product_type="USDT-FUTURES": _candles(symbol))

    allowed = api.post("/api/bitget/orders/dry-run-preview", json=_order_with(entry="100", stop="102", max_leverage="100")).json()["data"]
    blocked = api.post("/api/bitget/orders/dry-run-preview", json=_order_with(entry="100", stop="101", max_leverage="100")).json()["data"]

    assert allowed["would_place_order"] == "YES"
    assert allowed["exchange_max_leverage"] == "50"
    assert allowed["effective_max_leverage"] == "50"
    assert blocked["would_place_order"] == "NO"
    assert blocked["blocked_reason"] == "BLOCKED_REQUIRED_LEVERAGE_EXCEEDS_MAX"


def test_fee_slippage_buffer_can_block_preview(monkeypatch) -> None:
    api = client()
    api.post("/api/bitget/credentials", json=_credentials())
    api.post("/api/bitget/mode", json={"mode": "DRY_RUN_PREVIEW"})
    service = _service()
    monkeypatch.setattr(service, "fetch_contract_config", lambda symbol, product_type="USDT-FUTURES": _contract(symbol))
    monkeypatch.setattr(service, "fetch_ticker", lambda symbol, product_type="USDT-FUTURES": _ticker(symbol))
    monkeypatch.setattr(service, "fetch_candles", lambda symbol, granularity="1m", limit=100, product_type="USDT-FUTURES": _candles(symbol))

    blocked = api.post("/api/bitget/orders/dry-run-preview", json={**_order_with(risk="10"), "fee_rate": "0.02", "slippage_rate": "0.02"}).json()["data"]

    assert blocked["would_place_order"] == "NO"
    assert blocked["blocked_reason"] == "ESTIMATED_TOTAL_RISK_EXCEEDS_ALLOWED_TOLERANCE"


def test_live_order_blocked_without_recent_dry_run_and_confirmation() -> None:
    api = client()
    api.post("/api/bitget/credentials", json=_credentials())

    no_confirmation = api.post("/api/bitget/orders/live", json=_order())

    assert no_confirmation.status_code == 400
    assert "ENABLE LIVE" in _error(no_confirmation)


def test_live_order_builds_backend_preview_without_manual_preview(monkeypatch) -> None:
    service = BitgetEnvironmentService()
    service.runtime_credentials = BitgetCredentialConfig(api_key="key", api_secret="secret", passphrase="pass")
    service.mode = TradeMode.LIVE
    service.live_armed = True
    monkeypatch.setattr(service, "fetch_contract_config", lambda symbol, product_type="USDT-FUTURES": _contract(symbol))
    monkeypatch.setattr(service, "fetch_ticker", lambda symbol, product_type="USDT-FUTURES": _ticker(symbol))
    monkeypatch.setattr(service, "fetch_candles", lambda symbol, granularity="1m", limit=100, product_type="USDT-FUTURES": _candles(symbol))
    monkeypatch.setattr(service, "_private_request", lambda method, path, **kwargs: {"code": "00000", "msg": "success", "data": {"orderId": "ord_live_auto_preview"}})

    assert service.last_dry_run_preview is None

    order = service.place_order(_order(), required_mode=TradeMode.LIVE)

    assert order["bitget_order_id"] == "ord_live_auto_preview"
    assert service.last_dry_run_preview is not None
    assert service.last_dry_run_preview["would_place_order"] == "YES"
    assert service.blocked_orders == []


def _service() -> BitgetEnvironmentService:
    from arjiobot.api.dependencies import get_state

    return get_state().bitget_environment


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
        "last_price": "100",
        "bid_price": "99.9",
        "ask_price": "100.1",
        "mark_price": "100",
        "index_price": "100",
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


def _error(response) -> str:
    payload = response.json()
    detail = payload.get("detail", payload)
    if isinstance(detail, dict):
        return str(detail.get("error", {}).get("message") or detail)
    return str(detail)
