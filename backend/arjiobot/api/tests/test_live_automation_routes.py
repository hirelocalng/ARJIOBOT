"""Live automation route tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from dataclasses import replace

from decimal import Decimal

from arjiobot.api.dependencies import get_state
from arjiobot.api.tests.helpers import client
from arjiobot.exchange.bitget_environment import BitgetCredentialConfig, TradeMode
from arjiobot.live_automation import _position_notional, _real_time_open_positions
from arjiobot.setup_tracker.setup_models import InvalidationReason, SetupState, SetupStatus
from arjiobot.strategy.demo_strategy import make_entry_ready_setup


def test_position_notional_computes_real_dollar_value_not_a_flat_sentinel() -> None:
    """The actual fix for max_symbol_exposure being meaningless: an existing
    $5,000 position must read as $5,000 of exposure, not a flat "1"."""
    assert _position_notional({"symbol": "BTCUSDT", "total": "50", "markPrice": "100"}) == Decimal("5000")


def test_position_notional_falls_back_to_a_large_sentinel_when_unparseable() -> None:
    """If Bitget's position fields cannot be parsed, exposure must fail
    toward blocking an additional trade (a large sentinel), never toward
    understating real exposure to something tiny like "1"."""
    assert _position_notional({"symbol": "BTCUSDT"}) > Decimal("1000000000")
    assert _position_notional({"symbol": "BTCUSDT", "total": "not-a-number", "markPrice": "100"}) > Decimal("1000000000")


def test_real_time_open_positions_sums_real_notional_per_symbol() -> None:
    from types import SimpleNamespace

    state = SimpleNamespace(
        bitget_environment=SimpleNamespace(
            fetch_positions=lambda: {
                "positions": (
                    {"symbol": "BTCUSDT", "total": "1", "markPrice": "90000"},
                    {"symbol": "ETHUSDT", "total": "10", "markPrice": "3000"},
                )
            }
        )
    )
    count, exposure = _real_time_open_positions(state)
    assert count == 2
    assert exposure["BTCUSDT"] == Decimal("90000")
    assert exposure["ETHUSDT"] == Decimal("30000")


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


def test_real_open_position_for_same_symbol_blocks_a_new_one(monkeypatch) -> None:
    """The actual fix for "the bot opens multiple live trades simultaneously
    with no limit": a real, currently-open BTCUSDT position (queried live
    from Bitget, not the old broken in-memory open_positions counter - which
    is deliberately left at 0 here, simulating a process restart) must block
    a new BTCUSDT setup, even with a generous global max_open_trades."""
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
    service.last_account_payload = {"total_equity": "1000", "available_margin": "1000", "margin_mode": "isolated"}
    assert service.open_positions == 0, "simulating a fresh restart - the broken counter has forgotten the real open position"
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
    state.market_polls["BTCUSDT"] = {"symbol": "BTCUSDT", "poll_success": "YES", "poll_status": "READY", "last_live_price": "90"}
    setup = make_entry_ready_setup(latest_price="90")
    state.setups[setup.setup_id] = setup

    def routed_private_request(method: str, path: str, **kwargs: object) -> dict[str, object]:
        if path == "/api/v2/mix/position/all-position":
            return {"code": "00000", "msg": "success", "data": [{"symbol": "BTCUSDT", "holdSide": "long", "total": "1"}]}
        return {"code": "00000", "msg": "success", "data": {"orderId": "ord_should_never_be_placed"}}

    monkeypatch.setattr(service, "fetch_contract_config", lambda symbol, product_type="USDT-FUTURES": _contract(symbol))
    monkeypatch.setattr(service, "fetch_ticker", lambda symbol, product_type="USDT-FUTURES": _ticker(symbol))
    monkeypatch.setattr(service, "fetch_candles", lambda symbol, granularity="1m", limit=100, product_type="USDT-FUTURES": _candles(symbol))
    monkeypatch.setattr(service, "_private_request", routed_private_request)

    result = api.post("/api/live-automation/run-once").json()["data"]

    assert result["status"] == "BLOCKED"
    assert "SAME_SYMBOL_EXPOSURE_BLOCKED" in result["attempts"][0]["reason"]
    assert service.orders == []


def test_daily_loss_limit_blocks_a_new_trade_once_real_losses_consumed_the_cap(monkeypatch) -> None:
    """The actual fix for daily/weekly loss limits being non-functional:
    _live_risk_context now sums real realized PnL from Bitget's closed-
    position history (last 24h) instead of always treating current_daily_pnl
    as 0. A $460 real loss today against a $500 daily cap leaves only $40 of
    capacity - not enough for a $100 risk-per-trade setup, so it must block."""
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
    service.last_account_payload = {"total_equity": "1000", "available_margin": "1000", "margin_mode": "isolated"}
    state.settings.update(
        {
            "adapter_mode": "BITGET_LIVE",
            "live_trading_enabled": True,
            "trading_mode": "LIVE",
            "active_strategy_profile": "PROFILE_2",
            "selected_rr_profile": "LEG_TARGET_RESEARCH",
            "risk_amount_per_trade": "100",
            "max_leverage": "100",
            "max_daily_loss": "500",
            "max_weekly_loss": "1500",
            "max_open_trades": 5,
        }
    )
    state.monitoring.update({"active": True, "session_id": "test", "source": "LIVE_MARKET_DATA"})
    state.market_polls["BTCUSDT"] = {"symbol": "BTCUSDT", "poll_success": "YES", "poll_status": "READY", "last_live_price": "90"}
    setup = make_entry_ready_setup(latest_price="90")
    state.setups[setup.setup_id] = setup
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)

    def routed_private_request(method: str, path: str, **kwargs: object) -> dict[str, object]:
        if path == "/api/v2/mix/position/all-position":
            return {"code": "00000", "msg": "success", "data": []}
        if path == "/api/v2/mix/position/history-position":
            return {"code": "00000", "msg": "success", "data": {"list": [{"symbol": "BTCUSDT", "netProfit": "-460", "uTime": str(now_ms)}]}}
        return {"code": "00000", "msg": "success", "data": {"orderId": "ord_should_never_be_placed"}}

    monkeypatch.setattr(service, "fetch_contract_config", lambda symbol, product_type="USDT-FUTURES": _contract(symbol))
    monkeypatch.setattr(service, "fetch_ticker", lambda symbol, product_type="USDT-FUTURES": _ticker(symbol))
    monkeypatch.setattr(service, "fetch_candles", lambda symbol, granularity="1m", limit=100, product_type="USDT-FUTURES": _candles(symbol))
    monkeypatch.setattr(service, "_private_request", routed_private_request)

    result = api.post("/api/live-automation/run-once").json()["data"]

    assert result["status"] == "BLOCKED"
    assert "DAILY_LOSS_LIMIT_REACHED" in result["attempts"][0]["reason"]
    assert service.orders == []


def test_old_realized_losses_outside_the_24_hour_window_do_not_count(monkeypatch) -> None:
    """A loss closed more than 24 hours ago must not count against today's
    daily loss cap - only real-time realized PnL within the rolling window
    reduces capacity."""
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
    service.last_account_payload = {"total_equity": "1000", "available_margin": "1000", "margin_mode": "isolated"}
    state.settings.update(
        {
            "adapter_mode": "BITGET_LIVE",
            "live_trading_enabled": True,
            "trading_mode": "LIVE",
            "active_strategy_profile": "PROFILE_2",
            "selected_rr_profile": "LEG_TARGET_RESEARCH",
            "risk_amount_per_trade": "100",
            "max_leverage": "100",
            "max_daily_loss": "500",
            "max_weekly_loss": "1500",
            "max_open_trades": 5,
        }
    )
    state.monitoring.update({"active": True, "session_id": "test", "source": "LIVE_MARKET_DATA"})
    state.market_polls["BTCUSDT"] = {"symbol": "BTCUSDT", "poll_success": "YES", "poll_status": "READY", "last_live_price": "90"}
    setup = make_entry_ready_setup(latest_price="90")
    state.setups[setup.setup_id] = setup
    old_ms = int((datetime.now(timezone.utc) - timedelta(days=2)).timestamp() * 1000)

    def routed_private_request(method: str, path: str, **kwargs: object) -> dict[str, object]:
        if path == "/api/v2/mix/position/all-position":
            return {"code": "00000", "msg": "success", "data": []}
        if path == "/api/v2/mix/position/history-position":
            return {"code": "00000", "msg": "success", "data": {"list": [{"symbol": "BTCUSDT", "netProfit": "-460", "uTime": str(old_ms)}]}}
        return {"code": "00000", "msg": "success", "data": {"orderId": "ord_old_loss_does_not_block"}}

    monkeypatch.setattr(service, "fetch_contract_config", lambda symbol, product_type="USDT-FUTURES": _contract(symbol))
    monkeypatch.setattr(service, "fetch_ticker", lambda symbol, product_type="USDT-FUTURES": _ticker(symbol))
    monkeypatch.setattr(service, "fetch_candles", lambda symbol, granularity="1m", limit=100, product_type="USDT-FUTURES": _candles(symbol))
    monkeypatch.setattr(service, "_private_request", routed_private_request)

    result = api.post("/api/live-automation/run-once").json()["data"]

    assert result["status"] == "SUBMITTED"
    assert service.orders[0]["bitget_order_id"] == "ord_old_loss_does_not_block"


def test_max_open_trades_uses_real_position_count_surviving_a_simulated_restart(monkeypatch) -> None:
    """Mirror of the same-symbol test for the global cap: a real open
    position on a DIFFERENT symbol must still count toward max_open_trades,
    even with the broken in-memory counter left at 0 (simulated restart)."""
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
    service.last_account_payload = {"total_equity": "1000", "available_margin": "1000", "margin_mode": "isolated"}
    assert service.open_positions == 0, "simulating a fresh restart - the broken counter has forgotten the real open position"
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
            "max_open_trades": 1,
        }
    )
    state.monitoring.update({"active": True, "session_id": "test", "source": "LIVE_MARKET_DATA"})
    state.market_polls["BTCUSDT"] = {"symbol": "BTCUSDT", "poll_success": "YES", "poll_status": "READY", "last_live_price": "90"}
    setup = make_entry_ready_setup(latest_price="90")
    state.setups[setup.setup_id] = setup

    def routed_private_request(method: str, path: str, **kwargs: object) -> dict[str, object]:
        if path == "/api/v2/mix/position/all-position":
            return {"code": "00000", "msg": "success", "data": [{"symbol": "ETHUSDT", "holdSide": "short", "total": "1"}]}
        return {"code": "00000", "msg": "success", "data": {"orderId": "ord_should_never_be_placed"}}

    monkeypatch.setattr(service, "fetch_contract_config", lambda symbol, product_type="USDT-FUTURES": _contract(symbol))
    monkeypatch.setattr(service, "fetch_ticker", lambda symbol, product_type="USDT-FUTURES": _ticker(symbol))
    monkeypatch.setattr(service, "fetch_candles", lambda symbol, granularity="1m", limit=100, product_type="USDT-FUTURES": _candles(symbol))
    monkeypatch.setattr(service, "_private_request", routed_private_request)

    result = api.post("/api/live-automation/run-once").json()["data"]

    assert result["status"] == "BLOCKED"
    assert "MAX_OPEN_TRADES_REACHED" in result["attempts"][0]["reason"]
    assert service.orders == []


def test_per_pair_leverage_overrides_global_max_leverage_end_to_end(monkeypatch) -> None:
    """Proves the full chain, not just the helper in isolation: a pair-
    specific leverage configured on state.monitored_pairs reaches both the
    margin calculation and the actual set_leverage call sent to Bitget,
    overriding the global max_leverage setting for that symbol."""
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
    service.last_account_payload = {"total_equity": "1000", "available_margin": "1000", "margin_mode": "isolated"}
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
    state.monitored_pairs["BTCUSDT"] = {"symbol": "BTCUSDT", "enabled": True, "leverage": 120}
    state.monitoring.update({"active": True, "session_id": "test", "source": "LIVE_MARKET_DATA"})
    state.market_polls["BTCUSDT"] = {"symbol": "BTCUSDT", "poll_success": "YES", "poll_status": "READY", "last_live_price": "90"}
    setup = make_entry_ready_setup(latest_price="90")
    state.setups[setup.setup_id] = setup

    calls: list[tuple[str, dict[str, object]]] = []

    def recording_private_request(method: str, path: str, **kwargs: object) -> dict[str, object]:
        calls.append((path, dict(kwargs.get("body") or {})))
        return {"code": "00000", "msg": "success", "data": {"orderId": "ord_per_pair_leverage"}}

    monkeypatch.setattr(service, "fetch_contract_config", lambda symbol, product_type="USDT-FUTURES": _contract(symbol))
    monkeypatch.setattr(service, "fetch_ticker", lambda symbol, product_type="USDT-FUTURES": _ticker(symbol))
    monkeypatch.setattr(service, "fetch_candles", lambda symbol, granularity="1m", limit=100, product_type="USDT-FUTURES": _candles(symbol))
    monkeypatch.setattr(service, "_private_request", recording_private_request)

    result = api.post("/api/live-automation/run-once").json()["data"]

    assert result["status"] == "SUBMITTED"
    leverage_calls = [body for path, body in calls if path == "/api/v2/mix/account/set-leverage"]
    assert len(leverage_calls) == 1
    assert leverage_calls[0]["leverage"] == "120", "must use the pair-specific leverage, not the global max_leverage=100"
    attempt = result["attempts"][0]
    assert attempt["status"] == "SUBMITTED"
    plan = state.trade_plans[attempt["trade_plan_id"]]
    assert str(plan.max_allowed_leverage) == "120"


def test_live_automation_isolates_one_failing_setup_from_others(monkeypatch) -> None:
    """A setup that raises while being processed must not block other, healthy
    ENTRY_READY setups in the same cycle - including ones from the other trade
    direction - from being attempted. See live_automation.run_live_automation_once."""
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
    state.market_polls["BTCUSDT"] = {"symbol": "BTCUSDT", "poll_success": "YES", "poll_status": "READY", "last_live_price": "90"}
    state.market_polls["ETHUSDT"] = {"symbol": "ETHUSDT", "poll_success": "YES", "poll_status": "READY", "last_live_price": "90"}

    failing_setup = make_entry_ready_setup(symbol="BTCUSDT", suffix="1", created_at=datetime(2026, 1, 1, tzinfo=timezone.utc), latest_price="90")
    healthy_setup = make_entry_ready_setup(symbol="ETHUSDT", suffix="2", created_at=datetime(2026, 1, 1, 1, tzinfo=timezone.utc), latest_price="90")
    state.setups[failing_setup.setup_id] = failing_setup
    state.setups[healthy_setup.setup_id] = healthy_setup

    real_generate_signal = state.strategy_engine.generate_signal_from_setup

    def flaky_generate_signal(setup, *args, **kwargs):
        if setup.setup_id == failing_setup.setup_id:
            raise RuntimeError("simulated corrupt setup")
        return real_generate_signal(setup, *args, **kwargs)

    monkeypatch.setattr(state.strategy_engine, "generate_signal_from_setup", flaky_generate_signal)
    monkeypatch.setattr(service, "fetch_contract_config", lambda symbol, product_type="USDT-FUTURES": _contract(symbol))
    monkeypatch.setattr(service, "fetch_ticker", lambda symbol, product_type="USDT-FUTURES": _ticker(symbol))
    monkeypatch.setattr(service, "fetch_candles", lambda symbol, granularity="1m", limit=100, product_type="USDT-FUTURES": _candles(symbol))
    monkeypatch.setattr(service, "_private_request", lambda method, path, **kwargs: {"code": "00000", "msg": "success", "data": {"orderId": "ord_live_1"}})

    result = api.post("/api/live-automation/run-once").json()["data"]

    assert result["status"] == "SUBMITTED"
    attempts_by_setup = {attempt["setup_id"]: attempt for attempt in result["attempts"]}
    assert attempts_by_setup[failing_setup.setup_id]["status"] == "ERROR"
    assert "simulated corrupt setup" in attempts_by_setup[failing_setup.setup_id]["reason"]
    assert attempts_by_setup[healthy_setup.setup_id]["status"] == "SUBMITTED"
    assert len(service.orders) == 1


def test_setup_blocked_downstream_of_signal_generation_can_be_retried_on_a_later_poll(monkeypatch) -> None:
    """The DUPLICATE_SIGNAL stuck-forever bug: a setup whose signal generation
    succeeds but is then blocked further downstream (here, the live Bitget
    order itself failing) must not be permanently rejected as a duplicate on
    every later poll once whatever blocked it is fixed. Confirms
    clear_generated_signal_for_setup actually runs at the point of failure."""
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
    service.last_account_payload = {"total_equity": "1000", "available_margin": "1000", "margin_mode": "isolated"}
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
    state.market_polls["BTCUSDT"] = {"symbol": "BTCUSDT", "poll_success": "YES", "poll_status": "READY", "last_live_price": "90"}

    setup = make_entry_ready_setup(symbol="BTCUSDT", suffix="1", created_at=datetime(2026, 1, 1, tzinfo=timezone.utc), latest_price="90")
    state.setups[setup.setup_id] = setup

    monkeypatch.setattr(service, "fetch_contract_config", lambda symbol, product_type="USDT-FUTURES": _contract(symbol))
    monkeypatch.setattr(service, "fetch_ticker", lambda symbol, product_type="USDT-FUTURES": _ticker(symbol))
    monkeypatch.setattr(service, "fetch_candles", lambda symbol, granularity="1m", limit=100, product_type="USDT-FUTURES": _candles(symbol))

    real_place_order = service.place_order
    call_count = {"n": 0}

    def flaky_place_order(payload, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            from arjiobot.exchange.bitget_environment import EnvironmentLockError

            raise EnvironmentLockError("simulated exchange-side rejection (e.g. the real tradeSide/40774 bug)")
        return real_place_order(payload, **kwargs)

    monkeypatch.setattr(service, "place_order", flaky_place_order)
    monkeypatch.setattr(service, "_private_request", lambda method, path, **kwargs: {"code": "00000", "msg": "success", "data": {"orderId": "ord_retry_1"}})

    first = api.post("/api/live-automation/run-once").json()["data"]
    assert first["attempts"][0]["status"] == "BLOCKED"
    assert first["attempts"][0]["stage"] == "BITGET_LIVE_ORDER"
    # The whole point of the fix: the stale "already generated" marker must
    # be gone immediately after the downstream block, not just eventually.
    assert state.strategy_engine.store.get_generated_by_setup_id(setup.setup_id) is None
    assert setup.setup_id in state.setups, "still ENTRY_READY - never marked processed since nothing was submitted"

    second = api.post("/api/live-automation/run-once").json()["data"]

    assert second["status"] == "SUBMITTED"
    assert second["attempts"][0]["status"] == "SUBMITTED", f"got blocked again instead of retrying cleanly: {second['attempts'][0]}"
    assert second["attempts"][0].get("reason") not in ("signal rejected: DUPLICATE_SIGNAL",)
    assert len(service.orders) == 1
    assert service.orders[0]["bitget_order_id"] == "ord_retry_1"


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


def test_stale_entry_ready_setup_is_expired_not_executed() -> None:
    """A setup that reached ENTRY_READY more than 24 minutes (2 closed 12M
    candles) ago and was never submitted - automation paused, Bitget
    unreachable, restart, etc. - must never be executed: the current market
    price has very likely moved away from its entry zone. It must be skipped
    and moved into Setup Radar's invalidated_setups as EXPIRED instead."""
    from datetime import timedelta

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

    stale_setup = make_entry_ready_setup(latest_price="90", completed_at=datetime.now(timezone.utc) - timedelta(minutes=30))
    state.setups[stale_setup.setup_id] = stale_setup

    result = api.post("/api/live-automation/run-once").json()["data"]

    assert state.bitget_environment.orders == [], "a stale setup must never be executed"
    assert stale_setup.setup_id not in state.setups, "an expired setup must leave the uncapped in-progress pool"
    expired = state.invalidated_setups[stale_setup.setup_id]
    assert expired.current_state is SetupState.EXPIRED
    assert expired.status is SetupStatus.EXPIRED
    assert expired.last_valid_stage == "ENTRY_READY"
    expired_attempts = [attempt for attempt in result["attempts"] if attempt.get("status") == "EXPIRED"]
    assert expired_attempts, f"expected an EXPIRED attempt record, got: {result}"
    assert expired_attempts[0]["setup_id"] == stale_setup.setup_id
    assert expired_attempts[0]["stage"] == "STALENESS_GATE"


def test_fresh_entry_ready_setup_within_staleness_window_still_executes(monkeypatch) -> None:
    """The 24-minute staleness gate must not block a setup that is still
    well within the window - only setups older than 2 closed 12M candles."""
    from datetime import timedelta

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
    service.last_account_payload = {"total_equity": "1000", "available_margin": "1000", "margin_mode": "isolated"}
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
    state.market_polls["BTCUSDT"] = {"symbol": "BTCUSDT", "poll_success": "YES", "poll_status": "READY", "last_live_price": "90"}

    setup = make_entry_ready_setup(latest_price="90", completed_at=datetime.now(timezone.utc) - timedelta(minutes=10))
    state.setups[setup.setup_id] = setup

    monkeypatch.setattr(service, "fetch_contract_config", lambda symbol, product_type="USDT-FUTURES": _contract(symbol))
    monkeypatch.setattr(service, "fetch_ticker", lambda symbol, product_type="USDT-FUTURES": _ticker(symbol))
    monkeypatch.setattr(service, "fetch_candles", lambda symbol, granularity="1m", limit=100, product_type="USDT-FUTURES": _candles(symbol))
    monkeypatch.setattr(service, "_private_request", lambda method, path, **kwargs: {"code": "00000", "msg": "success", "data": {"orderId": "ord_fresh_1"}})

    result = api.post("/api/live-automation/run-once").json()["data"]

    assert result["status"] == "SUBMITTED", f"expected a submitted order, got: {result}"
    assert setup.setup_id in state.completed_setups
    assert setup.setup_id not in state.invalidated_setups


def test_live_automation_executes_only_the_entry_ready_setup_not_in_progress_or_invalidated(monkeypatch) -> None:
    """Direct proof of the explicit requirement: a real ENTRY_READY setup gets
    executed; an in-progress (ACTIVE) one and an invalidated one - sitting in
    their own separate stores - are never touched, even when present in the
    same run-once call."""
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
    service.last_account_payload = {"total_equity": "1000", "available_margin": "1000", "margin_mode": "isolated"}
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
    state.market_polls["BTCUSDT"] = {"symbol": "BTCUSDT", "poll_success": "YES", "poll_status": "READY", "last_live_price": "90"}

    entry_ready = make_entry_ready_setup(latest_price="90")
    state.setups[entry_ready.setup_id] = entry_ready
    in_progress = replace(entry_ready, setup_id="set_in_progress_test", symbol="ETHUSDT", current_state=SetupState.SWING_16M_CONFIRMED, progress_percent=20.0, status=SetupStatus.ACTIVE)
    state.setups[in_progress.setup_id] = in_progress
    invalidated = replace(
        entry_ready,
        setup_id="set_invalidated_test",
        symbol="SOLUSDT",
        current_state=SetupState.INVALIDATED,
        status=SetupStatus.INVALIDATED,
        progress_percent=35.0,
        invalidated_at=entry_ready.created_at,
        invalidation_reason=InvalidationReason.EXPANSION_NOT_CONFIRMED,
    )
    state.invalidated_setups[invalidated.setup_id] = invalidated

    monkeypatch.setattr(service, "fetch_contract_config", lambda symbol, product_type="USDT-FUTURES": _contract(symbol))
    monkeypatch.setattr(service, "fetch_ticker", lambda symbol, product_type="USDT-FUTURES": _ticker(symbol))
    monkeypatch.setattr(service, "fetch_candles", lambda symbol, granularity="1m", limit=100, product_type="USDT-FUTURES": _candles(symbol))
    monkeypatch.setattr(service, "_private_request", lambda method, path, **kwargs: {"code": "00000", "msg": "success", "data": {"orderId": "ord_live_2"}})

    result = api.post("/api/live-automation/run-once").json()["data"]

    assert result["status"] == "SUBMITTED"
    assert len(service.orders) == 1
    automation = get_state().live_automation
    submitted_setup_ids = {attempt.get("setup_id") for attempt in automation["attempts"] if attempt.get("status") == "SUBMITTED"}
    assert submitted_setup_ids == {entry_ready.setup_id}
    # Untouched - still exactly where they started, never considered for execution.
    assert state.setups[in_progress.setup_id].status is SetupStatus.ACTIVE
    assert state.invalidated_setups[invalidated.setup_id].status is SetupStatus.INVALIDATED
    # The executed setup left the in-progress pool for completed_setups.
    assert entry_ready.setup_id not in state.setups
    assert entry_ready.setup_id in state.completed_setups


def test_real_detection_produces_a_setup_that_live_automation_submits_as_an_order() -> None:
    """End-to-end proof that execution is actually taking trades after this
    session's freshness-window fix: real candle data, fed through the real
    detect_live_setups_for_symbol pipeline (not a hand-built setup like
    make_entry_ready_setup), produces a genuine ENTRY_READY setup that
    run_live_automation_once then carries all the way to a submitted Bitget
    order. Before the freshness fix, detect_live_setups_for_symbol never
    produced a real ENTRY_READY setup from this fixture at all (every
    qualifying trade was discarded as "stale") - there was nothing for
    automation to ever act on, regardless of how correctly automation itself
    behaved."""
    from pathlib import Path

    from arjiobot.backtesting.historical_replay import load_ohlcv_csv
    from arjiobot.live_setup_detection import detect_live_setups_for_symbol

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
    service.last_account_payload = {"total_equity": "1000", "available_margin": "1000", "margin_mode": "isolated"}
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
    state.market_polls["ADAUSDT"] = {"symbol": "ADAUSDT", "poll_success": "YES", "poll_status": "READY", "last_live_price": "0.2444"}

    data_dir = Path(__file__).resolve().parents[4] / "data"
    candles_1m = load_ohlcv_csv(data_dir / "ADAUSDT-1m-2026-04.csv", default_symbol="ADAUSDT")
    state.live_candles["ADAUSDT"] = candles_1m[:150]

    detect_live_setups_for_symbol(state, "ADAUSDT")
    real_trades = [setup for setup in state.setups.values() if setup.current_state is SetupState.ENTRY_READY]
    assert real_trades, "fixture assumption: this window produces a real entry-ready ADAUSDT trade"
    setup = real_trades[0]
    # completed_at here is the CSV's historical entry-candle timestamp, not
    # actually recent - this test is about detection->execution wiring, not
    # the staleness gate (covered separately), so fast-forward it to now.
    setup = replace(setup, completed_at=datetime.now(timezone.utc))
    state.setups[setup.setup_id] = setup

    def fake_contract(symbol: str, product_type: str = "USDT-FUTURES") -> dict[str, object]:
        return _contract(symbol)

    def fake_ticker(symbol: str, product_type: str = "USDT-FUTURES") -> dict[str, object]:
        return {**_ticker(symbol), "last_price": "0.2444", "bid_price": "0.2443", "ask_price": "0.2445", "mark_price": "0.2444"}

    def fake_candles(symbol: str, granularity: str = "1m", limit: int = 100, product_type: str = "USDT-FUTURES") -> dict[str, object]:
        return _candles(symbol)

    service.fetch_contract_config = fake_contract
    service.fetch_ticker = fake_ticker
    service.fetch_candles = fake_candles
    service._private_request = lambda method, path, **kwargs: {"code": "00000", "msg": "success", "data": {"orderId": "ord_real_detection_1"}}

    result = api.post("/api/live-automation/run-once").json()["data"]

    assert result["status"] == "SUBMITTED", f"expected a submitted order, got: {result}"
    assert len(service.orders) == 1
    assert service.orders[0]["bitget_order_id"] == "ord_real_detection_1"
    assert setup.setup_id not in state.setups, "the executed setup must leave the in-progress pool"
    assert setup.setup_id in state.completed_setups


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
