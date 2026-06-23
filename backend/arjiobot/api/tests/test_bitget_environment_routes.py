"""Live-only Bitget Futures environment route tests."""

from __future__ import annotations

import re
from decimal import Decimal

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
    # entry=100/stop=101/risk=100 would make required_leverage (100) exactly
    # equal max_leverage (100) under the old notional/leverage-only sizing -
    # but the MMR-safe cap (calculate_max_safe_leverage) now caps it to 61x
    # here (default maintenance_margin_rate/close_fee_rate/target_mmr), so
    # margin is bigger than the bare risk amount, not equal to it.
    # expected_loss_at_sl_excluding_fees still exactly equals the configured
    # risk amount - the MMR-safe cap changes leverage/margin, never position
    # size (calculate_required_margin's quantity is leverage-independent).
    assert preview["required_leverage"] == "61"
    assert preview["effective_max_leverage"] == "61"
    assert Decimal(preview["applied_margin_amount"]) == Decimal("10000") / Decimal("61")
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
    # entry=100/stop=101 caps required_leverage to 61x here (the MMR-safe cap
    # - see test_dry_run_preview_builds_payload_without_submission), not the
    # configured 100x, so margin is notional/61, bigger than the bare risk
    # amount. L_max is independent of risk_per_trade (Q/N/MM_stop all scale
    # linearly with it, so the ratio does not), which is exactly why
    # required_leverage stays 61x for every risk amount below.
    # expected_loss_at_sl_excluding_fees/size still scale exactly with risk -
    # fees/slippage are additional, and leverage/margin are decoupled from
    # position size entirely (calculate_required_margin).
    assert [Decimal(item["applied_margin_amount"]) for item in previews] == [Decimal("1000") / Decimal("61"), Decimal("2500") / Decimal("61"), Decimal("10000") / Decimal("61")]
    assert [item["expected_loss_at_sl_excluding_fees"] for item in previews] == ["10.000", "25.000", "100.000"]
    assert [item["size"] for item in previews] == ["10.000", "25.000", "100.000"]
    assert all(item["required_leverage"] == "61" for item in previews)


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


def test_stale_bullish_take_profit_below_current_price_is_rejected_before_bitget(monkeypatch) -> None:
    """Reproduces Bitget error 40830 ("take profit price of the long position
    should be greater than the current price") - a BULLISH setup whose target
    the live price has since passed must be blocked here, not sent to Bitget."""
    api = client()
    api.post("/api/bitget/credentials", json=_credentials())
    api.post("/api/bitget/mode", json={"mode": "DRY_RUN_PREVIEW"})
    service = _service()
    monkeypatch.setattr(service, "fetch_contract_config", lambda symbol, product_type="USDT-FUTURES": _contract(symbol))
    monkeypatch.setattr(service, "fetch_ticker", lambda symbol, product_type="USDT-FUTURES": _ticker(symbol))  # last_price = 100
    monkeypatch.setattr(service, "fetch_candles", lambda symbol, granularity="1m", limit=100, product_type="USDT-FUTURES": _candles(symbol))

    blocked = api.post("/api/bitget/orders/dry-run-preview", json=_order_with(side="BUY", entry="95", stop="93", target="99")).json()["data"]
    at_current_price = api.post("/api/bitget/orders/dry-run-preview", json=_order_with(side="BUY", entry="95", stop="93", target="100")).json()["data"]
    still_valid = api.post("/api/bitget/orders/dry-run-preview", json=_order_with(side="BUY", entry="95", stop="93", target="101")).json()["data"]

    assert blocked["would_place_order"] == "NO"
    assert "STALE_SETUP_TP_INVALID" in blocked["blocked_reason"]
    assert at_current_price["would_place_order"] == "NO", "strict inequality - equal to current price must also be rejected"
    assert "STALE_SETUP_TP_INVALID" in at_current_price["blocked_reason"]
    assert still_valid["would_place_order"] == "YES"


def test_stale_bearish_take_profit_above_current_price_is_rejected_before_bitget(monkeypatch) -> None:
    """Mirror of the BULLISH case for SHORT positions."""
    api = client()
    api.post("/api/bitget/credentials", json=_credentials())
    api.post("/api/bitget/mode", json={"mode": "DRY_RUN_PREVIEW"})
    service = _service()
    monkeypatch.setattr(service, "fetch_contract_config", lambda symbol, product_type="USDT-FUTURES": _contract(symbol))
    monkeypatch.setattr(service, "fetch_ticker", lambda symbol, product_type="USDT-FUTURES": _ticker(symbol))  # last_price = 100
    monkeypatch.setattr(service, "fetch_candles", lambda symbol, granularity="1m", limit=100, product_type="USDT-FUTURES": _candles(symbol))

    blocked = api.post("/api/bitget/orders/dry-run-preview", json=_order_with(side="SELL", entry="105", stop="107", target="101")).json()["data"]
    still_valid = api.post("/api/bitget/orders/dry-run-preview", json=_order_with(side="SELL", entry="105", stop="107", target="99")).json()["data"]

    assert blocked["would_place_order"] == "NO"
    assert "STALE_SETUP_TP_INVALID" in blocked["blocked_reason"]
    assert still_valid["would_place_order"] == "YES"


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

    # stop=101.2/101 are both close enough to entry that the MMR-safe cap
    # (54x/61x respectively) stays looser than the exchange cap (50x), so
    # the exchange cap remains what actually binds in both cases here - see
    # test_mmr_safe_cap_overrides_exchange_cap_when_tighter for the case
    # where the MMR-safe cap itself is the tightest of the three.
    # available_margin covers the position at the exchange-capped leverage (50x) for the wider
    # stop (allowed) but not for the tighter stop (blocked), proving the exchange cap (not the
    # user-selected 100x) is what actually drives the required-margin calculation.
    allowed_payload = {**_order_with(entry="100", stop="101.2", max_leverage="100"), "selected_starting_balance": "170"}
    blocked_payload = {**_order_with(entry="100", stop="101", max_leverage="100"), "selected_starting_balance": "170"}
    allowed = api.post("/api/bitget/orders/dry-run-preview", json=allowed_payload).json()["data"]
    blocked = api.post("/api/bitget/orders/dry-run-preview", json=blocked_payload).json()["data"]

    assert allowed["would_place_order"] == "YES"
    assert allowed["exchange_max_leverage"] == "50"
    assert allowed["effective_max_leverage"] == "50"
    assert blocked["would_place_order"] == "NO"
    assert blocked["blocked_reason"] == "BLOCKED_INSUFFICIENT_AVAILABLE_MARGIN"


def test_mmr_safe_cap_overrides_exchange_cap_when_tighter(monkeypatch) -> None:
    """A stop wide enough relative to entry (here 2%) makes the MMR-safe cap
    itself the tightest of the three (user-selected/exchange/MMR-safe) -
    even tighter than the exchange's own 50x cap from
    test_required_leverage_uses_exchange_cap_not_user_selected_cap."""
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

    payload = {**_order_with(entry="100", stop="102", max_leverage="100"), "selected_starting_balance": "1000"}
    preview = api.post("/api/bitget/orders/dry-run-preview", json=payload).json()["data"]

    assert preview["would_place_order"] == "YES"
    assert preview["selected_max_leverage"] == "100"
    assert preview["exchange_max_leverage"] == "50"
    assert preview["effective_max_leverage"] == "38", "the MMR-safe cap (38x), tighter than the exchange cap (50x), must be what actually binds"


def test_mmr_safe_cap_does_not_reduce_leverage_already_below_it(monkeypatch, caplog) -> None:
    """Long where the configured leverage is already under L_max: no
    reduction happens, and the conditional "[MMR-SAFE] ... reduced" warning
    must not fire - only the always-printed Task 3 audit line should."""
    import logging

    api = client()
    api.post("/api/bitget/credentials", json=_credentials())
    api.post("/api/bitget/mode", json={"mode": "DRY_RUN_PREVIEW"})
    service = _service()
    monkeypatch.setattr(service, "fetch_contract_config", lambda symbol, product_type="USDT-FUTURES": _contract(symbol))
    monkeypatch.setattr(service, "fetch_ticker", lambda symbol, product_type="USDT-FUTURES": _ticker(symbol))
    monkeypatch.setattr(service, "fetch_candles", lambda symbol, granularity="1m", limit=100, product_type="USDT-FUTURES": _candles(symbol))

    # entry=100/stop=101/default rates -> MMR-safe cap is 61x (see
    # test_dry_run_preview_builds_payload_without_submission) - 10x configured
    # leverage is comfortably under that, so it must pass through unchanged.
    with caplog.at_level(logging.INFO, logger="arjiobot.exchange.bitget_environment"):
        preview = api.post("/api/bitget/orders/dry-run-preview", json=_order_with(max_leverage="10")).json()["data"]

    assert preview["would_place_order"] == "YES"
    assert preview["effective_max_leverage"] == "10"
    assert not any("leverage reduced" in record.message for record in caplog.records), "no reduction occurred, so the reduction warning must not fire"
    audit_lines = [record.message for record in caplog.records if "[MMR-SAFE]" in record.message and "leverage reduced" not in record.message]
    assert len(audit_lines) == 1, "the Task 3 audit line must always print, even when leverage was not reduced"
    assert "configured=10x" in audit_lines[0]
    assert "final=10x" in audit_lines[0]


def test_mmr_safe_audit_log_line_is_always_printed_with_expected_fields(monkeypatch, caplog) -> None:
    """[MMR-SAFE] <symbol> <LONG|SHORT> | Q=... N=... MM_stop=... M_required=...
    L_max=...x configured=...x final=...x | MMR@stop=...% - printed for every
    trade (not just when leverage is reduced), so every trade is auditable in
    Railway's log stream."""
    import logging

    api = client()
    api.post("/api/bitget/credentials", json=_credentials())
    api.post("/api/bitget/mode", json={"mode": "DRY_RUN_PREVIEW"})
    service = _service()
    monkeypatch.setattr(service, "fetch_contract_config", lambda symbol, product_type="USDT-FUTURES": _contract(symbol))
    monkeypatch.setattr(service, "fetch_ticker", lambda symbol, product_type="USDT-FUTURES": _ticker(symbol))
    monkeypatch.setattr(service, "fetch_candles", lambda symbol, granularity="1m", limit=100, product_type="USDT-FUTURES": _candles(symbol))

    with caplog.at_level(logging.INFO, logger="arjiobot.exchange.bitget_environment"):
        api.post("/api/bitget/orders/dry-run-preview", json=_order_with(side="SELL"))

    audit_lines = [record.message for record in caplog.records if record.message.startswith("[MMR-SAFE] BTCUSDT SHORT")]
    assert len(audit_lines) == 1
    line = audit_lines[0]
    for field in ("Q=", "N=", "MM_stop=", "M_required=", "L_max=61x", "configured=100x", "final=61x", "MMR@stop=70.00%"):
        assert field in line, f"{field!r} missing from audit log line: {line!r}"


def test_moderate_fee_slippage_does_not_shrink_position_size(monkeypatch) -> None:
    """fixed_sl_loss sizes the position from the SL distance alone now -
    fee_rate/slippage_rate no longer shrink it (that was the bug: a $2 risk
    setting only producing a real ~$1.69 loss at stop loss). A realistic
    fee/slippage rate must produce the exact same size as zero fee/slippage,
    with fees/slippage only adding an informational cost on top."""
    api = client()
    api.post("/api/bitget/credentials", json=_credentials())
    api.post("/api/bitget/mode", json={"mode": "DRY_RUN_PREVIEW"})
    service = _service()
    monkeypatch.setattr(service, "fetch_contract_config", lambda symbol, product_type="USDT-FUTURES": _contract(symbol))
    monkeypatch.setattr(service, "fetch_ticker", lambda symbol, product_type="USDT-FUTURES": _ticker(symbol))
    monkeypatch.setattr(service, "fetch_candles", lambda symbol, granularity="1m", limit=100, product_type="USDT-FUTURES": _candles(symbol))

    baseline = api.post("/api/bitget/orders/dry-run-preview", json={**_order_with(risk="10"), "fee_rate": "0", "slippage_rate": "0"}).json()["data"]
    moderate_cost = api.post("/api/bitget/orders/dry-run-preview", json={**_order_with(risk="10"), "fee_rate": "0.001", "slippage_rate": "0.001"}).json()["data"]

    assert moderate_cost["would_place_order"] == "YES"
    assert moderate_cost["risk_within_limit"] == "YES"
    assert moderate_cost["size"] == baseline["size"], "fee_rate/slippage_rate must not change position size"
    assert moderate_cost["applied_margin_amount"] == baseline["applied_margin_amount"]
    assert moderate_cost["expected_loss_at_sl_excluding_fees"] == "10.000"
    assert Decimal(moderate_cost["estimated_fee"]) > Decimal("0")
    assert Decimal(moderate_cost["estimated_slippage_buffer"]) > Decimal("0")
    assert Decimal(moderate_cost["estimated_total_worst_case_loss"]) > Decimal("10"), "fees/slippage are additional on top of the exact SL-distance loss"


def test_extreme_fee_slippage_is_blocked_as_a_sanity_check(monkeypatch) -> None:
    """An unreasonably large fee_rate/slippage_rate (here 2% each - far above
    any real exchange's fees) would mean the real cost on top of the
    configured risk balloons past the risk amount itself - still blocked, as
    a sanity guard against a misconfigured rate, not by shrinking the
    position to silently absorb it."""
    api = client()
    api.post("/api/bitget/credentials", json=_credentials())
    api.post("/api/bitget/mode", json={"mode": "DRY_RUN_PREVIEW"})
    service = _service()
    monkeypatch.setattr(service, "fetch_contract_config", lambda symbol, product_type="USDT-FUTURES": _contract(symbol))
    monkeypatch.setattr(service, "fetch_ticker", lambda symbol, product_type="USDT-FUTURES": _ticker(symbol))
    monkeypatch.setattr(service, "fetch_candles", lambda symbol, granularity="1m", limit=100, product_type="USDT-FUTURES": _candles(symbol))

    high_cost = api.post("/api/bitget/orders/dry-run-preview", json={**_order_with(risk="10"), "fee_rate": "0.02", "slippage_rate": "0.02"}).json()["data"]

    assert high_cost["would_place_order"] == "NO"
    assert high_cost["blocked_reason"] == "ESTIMATED_FEE_AND_SLIPPAGE_EXCEED_FIXED_RISK_AMOUNT"


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


def test_place_order_sets_leverage_on_bitget_before_submitting_the_order() -> None:
    """Margin is computed server-side by Bitget from whatever leverage is
    already set on the account for the symbol - this confirms the bot
    actually tells Bitget to use effective_max_leverage immediately before
    submitting, rather than relying on however the account happens to be
    configured, and that it does so BEFORE the order itself goes out."""
    service = BitgetEnvironmentService()
    service.runtime_credentials = BitgetCredentialConfig(api_key="key", api_secret="secret", passphrase="pass")
    service.mode = TradeMode.LIVE
    service.live_armed = True
    service.fetch_contract_config = lambda symbol, product_type="USDT-FUTURES": _contract(symbol)
    service.fetch_ticker = lambda symbol, product_type="USDT-FUTURES": _ticker(symbol)
    service.fetch_candles = lambda symbol, granularity="1m", limit=100, product_type="USDT-FUTURES": _candles(symbol)

    calls: list[tuple[str, str, dict[str, object]]] = []

    def recording_private_request(method: str, path: str, **kwargs: object) -> dict[str, object]:
        calls.append((method, path, dict(kwargs.get("body") or {})))
        return {"code": "00000", "msg": "success", "data": {"orderId": "ord_leverage_check"}}

    service._private_request = recording_private_request

    order = service.place_order(_order(), required_mode=TradeMode.LIVE)

    assert [path for _, path, _ in calls] == ["/api/v2/mix/account/set-leverage", "/api/v2/mix/order/place-order"], (
        "set-leverage must be called once, and before the order itself is placed"
    )
    leverage_call = calls[0]
    assert leverage_call[0] == "POST"
    assert leverage_call[2]["symbol"] == "BTCUSDT"
    # _order()'s entry=100/stop=101/risk=100 caps effective_max_leverage to
    # 61x via the MMR-safe cap (see test_dry_run_preview_builds_payload_without_submission),
    # not the configured 100x - what matters here is that whatever that
    # final leverage is, it is what actually gets set on Bitget.
    assert leverage_call[2]["leverage"] == order["effective_max_leverage"] == "61"
    assert order["leverage_set_to"] == "61"
    assert order["leverage_set_response_code"] == "00000"


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


def test_fetch_position_history_parses_closed_positions_and_sanitizes_secrets(monkeypatch) -> None:
    service = BitgetEnvironmentService()
    captured: dict[str, object] = {}

    def fake_private_request(method: str, path: str, *, query=None, body=None, credentials=None):
        captured["method"] = method
        captured["path"] = path
        captured["query"] = query
        return {
            "code": "00000",
            "msg": "success",
            "data": {
                "list": [
                    {
                        "symbol": "BTCUSDT",
                        "holdSide": "long",
                        "openPriceAvg": "90",
                        "closeAvgPrice": "95",
                        "netProfit": "50",
                        "totalFee": "1.2",
                        "openTotalPos": "1",
                        "closeTotalPos": "1",
                        "ctime": "1750000000000",
                        "utime": "1750000600000",
                        "api_key": "should-never-appear",
                    }
                ]
            },
        }

    monkeypatch.setattr(service, "_private_request", fake_private_request)

    record = service.fetch_position_history("BTCUSDT")

    assert captured["method"] == "GET"
    assert captured["path"] == "/api/v2/mix/position/history-position"
    assert captured["query"]["symbol"] == "BTCUSDT"
    assert record["closed_position_count"] == 1
    closed = record["closed_positions"][0]
    assert closed["symbol"] == "BTCUSDT"
    assert closed["netProfit"] == "50"
    assert "api_key" not in closed, "secrets must be stripped even if echoed back by the exchange"
    assert service.last_position_history is record


def test_fetch_position_history_tolerates_missing_or_malformed_data(monkeypatch) -> None:
    service = BitgetEnvironmentService()
    monkeypatch.setattr(service, "_private_request", lambda method, path, **kwargs: {"code": "00000", "msg": "success", "data": None})

    record = service.fetch_position_history()

    assert record["closed_position_count"] == 0
    assert record["closed_positions"] == ()


def test_credential_resolution_only_logs_once_for_the_same_identity(caplog) -> None:
    """_credentials() is called from 7 different methods (mode_status alone
    calls it twice), and any one status check can fan out to several of
    them in a single request - this is exactly what was flooding Railway's
    logs with repeated "Resolved Bitget credentials from VAULT" lines, fast
    enough to hit its 500 logs/sec rate limit. Logging must only happen on
    the first resolution or on a real change, not on every redundant call."""
    import logging

    service = BitgetEnvironmentService()
    service.runtime_credentials = BitgetCredentialConfig(api_key="key_one", api_secret="secret", passphrase="pass", source="VAULT")

    with caplog.at_level(logging.INFO, logger="arjiobot.exchange.bitget_environment"):
        for _ in range(5):
            service._credentials()
        resolved_messages = [record.message for record in caplog.records if "Resolved Bitget credentials" in record.message]
        assert len(resolved_messages) == 1, f"expected exactly one log line for 5 identical calls, got {len(resolved_messages)}"

        # A real credential change must still be logged - the cache is keyed
        # by (source, fingerprint), not just "have we ever logged anything".
        service.runtime_credentials = BitgetCredentialConfig(api_key="key_two", api_secret="secret", passphrase="pass", source="VAULT")
        service._credentials()
        resolved_messages = [record.message for record in caplog.records if "Resolved Bitget credentials" in record.message]
        assert len(resolved_messages) == 2
