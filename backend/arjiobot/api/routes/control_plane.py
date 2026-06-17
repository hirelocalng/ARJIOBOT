"""Unified trading control-plane snapshot."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter

from arjiobot.api.dependencies import FROZEN_VISIBLE_PROFILE_ID, get_state
from arjiobot.api.schemas.common import ok
from arjiobot.backtesting.research_profiles import get_profile
from arjiobot.exchange.account_vault import CredentialVaultError, decrypt_credentials
from arjiobot.exchange.bitget_environment import BITGET_REST_BASE_URL
from arjiobot.live_automation import live_automation_status
from arjiobot.live_setup_detection import live_setup_detection_status

router = APIRouter(prefix="/api/control-plane", tags=["control-plane"])


@router.get("")
def control_plane_snapshot():
    state = get_state()
    settings = dict(state.settings)
    _activate_selected_account_credentials()
    mode_status = state.bitget_environment.mode_status()
    accounts = tuple(state.live_accounts.values())
    default_account = next((account for account in accounts if account.get("is_default")), None)
    active_profile_id = str(settings.get("active_strategy_profile") or settings.get("default_backtesting_profile") or FROZEN_VISIBLE_PROFILE_ID)
    profile = get_profile(active_profile_id)
    selected_tp_model = str(settings.get("selected_rr_profile") or profile.tp_model)
    time_exit_minutes = str(settings.get("time_exit_minutes") or "30")
    override_allowed = selected_tp_model == profile.tp_model or "tp_model" in profile.tunable_parameters
    enabled_pairs = [pair for pair in state.monitored_pairs.values() if pair.get("enabled")]
    account_status = _account_status(default_account, mode_status)
    # The control plane must be a fast snapshot endpoint. Live Bitget polling is
    # intentionally kept out of dashboard startup so a slow exchange/network
    # route cannot leave the frontend stuck on the loading screen.
    pair_status = tuple(_pair_control_record(pair, settings, account_status) for pair in state.monitored_pairs.values())
    profile_lock_status = "PASSED" if active_profile_id == profile.profile_id else "FAILED"
    exchange_ready = str(settings.get("adapter_mode", "MOCK")).upper() != "MOCK"
    account_ready = account_status["connection_status"] == "CONNECTED" or mode_status.get("trading_mode") == "OFF"
    pairs_ready = (
        bool(state.monitoring.get("active"))
        and bool(enabled_pairs)
        and any(pair["monitoring_status"] == "ACTIVE" and int(pair.get("live_candle_count") or 0) > 0 for pair in pair_status if pair["enabled"])
    )
    risk_ready = _positive(settings.get("risk_amount_per_trade")) and _positive(settings.get("max_leverage"))
    environment_ready = mode_status.get("environment_lock_verified") == "YES" or mode_status.get("trading_mode") == "OFF"
    execution_ready = all((profile_lock_status == "PASSED", exchange_ready, account_ready, pairs_ready, risk_ready, environment_ready))
    readiness_checklist = _live_execution_readiness_checklist(
        profile_lock_status=profile_lock_status,
        exchange_ready=exchange_ready,
        account_status=account_status,
        pairs_ready=pairs_ready,
        risk_ready=risk_ready,
        environment_ready=environment_ready,
        mode_status=mode_status,
    )
    best_run = _best_profitable_backtest(state.backtest_runs.values())
    preview_status = _last_order_preview_status()
    return ok(
        {
            "generated_at": _now(),
            "source_of_truth": "BACKEND_CONTROL_PLANE",
            "active_strategy": {
                "selected_profile": active_profile_id,
                "visible_profile": profile.profile_id,
                "profile_label": profile.label,
                "profile_lock_status": profile_lock_status,
                "profile_hash_freeze_status": "FROZEN",
                "strategy_ready": "YES" if profile_lock_status == "PASSED" else "NO",
                "selected_tp_model": selected_tp_model,
                "saved_tp_model": settings.get("selected_rr_profile", "RR_1_5"),
                "applied_tp_model": selected_tp_model if override_allowed else profile.tp_model,
                "time_exit_enabled": "YES" if selected_tp_model == "TIME_BASED_EXIT" and override_allowed else "NO",
                "time_exit_minutes_selected": time_exit_minutes if selected_tp_model == "TIME_BASED_EXIT" else "N/A",
                "time_exit_minutes_saved": time_exit_minutes,
                "time_exit_minutes_applied": time_exit_minutes if selected_tp_model == "TIME_BASED_EXIT" and override_allowed else "N/A",
                "tp_model_override_allowed": "YES" if override_allowed else "NO",
                "tp_model_lock_status": "UNLOCKED" if override_allowed else "LOCKED",
                "tp_model_lock_reason": "Override allowed by profile tunable_parameters" if override_allowed else f"Profile {profile.profile_id} locks TP model {profile.tp_model}",
                "profile_parameters": profile.to_record(),
            },
            "active_exchange_mode": {
                "selected_exchange": "BITGET",
                "adapter_mode": settings.get("adapter_mode", "MOCK"),
                "selected_trade_mode": mode_status.get("trading_mode", "OFF"),
                "live_trading_enabled": "YES" if settings.get("live_trading_enabled") else "NO",
                "exchange_lock_status": "PASSED" if exchange_ready else "FAILED",
                "environment_lock_status": "PASSED" if environment_ready else "FAILED",
                "environment_lock_verified": mode_status.get("environment_lock_verified", "NO"),
                "active_execution_mode": mode_status.get("active_execution_mode", "OFF"),
                "rest_base_url": BITGET_REST_BASE_URL,
                "rest_base_url_auto_managed": "YES",
                "websocket_public_url": mode_status.get("environment_lock", {}).get("websocket_public_url", ""),
                "websocket_private_url": mode_status.get("environment_lock", {}).get("websocket_private_url", ""),
                "credential_type_used": mode_status.get("environment_lock", {}).get("credential_type_used", "NONE"),
                "live_armed": mode_status.get("live_armed", "NO"),
                "mock_mode_warning": "MOCK MODE ACTIVE - NOT REAL EXCHANGE DATA" if str(settings.get("adapter_mode", "MOCK")).upper() == "MOCK" else "None",
            },
            "active_account": account_status,
            "active_pairs": pair_status,
            "active_risk_settings": {
                "starting_balance": settings.get("starting_balance", ""),
                "fixed_risk_amount": settings.get("risk_amount_per_trade", ""),
                "trade_type": "ISOLATED_MARGIN",
                "margin_amount": settings.get("risk_amount_per_trade", ""),
                "max_leverage": settings.get("max_leverage", ""),
                "daily_loss_cap": settings.get("max_daily_loss", ""),
                "max_trades_per_day": settings.get("max_open_trades", 1),
                "kill_switch_status": "ACTIVE" if state.bitget_environment.emergency_kill_switch else "INACTIVE",
                "risk_lock_status": "PASSED" if risk_ready else "FAILED",
            },
            "execution_readiness": {
                "profile_ready": "YES" if profile_lock_status == "PASSED" else "NO",
                "exchange_ready": "YES" if exchange_ready else "NO",
                "account_ready": "YES" if account_ready else "NO",
                "pairs_monitoring": "YES" if pairs_ready else "NO",
                "risk_ready": "YES" if risk_ready else "NO",
                "execution_ready": "YES" if execution_ready else "NO",
            },
            "live_execution_readiness_checklist": readiness_checklist,
            "backtest_to_live_config": best_run,
            "connection_diagnostics": {
                "api_credentials_present": _credentials_present(mode_status),
                "connection_test_passed": account_status["connection_status"] == "CONNECTED",
                "account_fetched": "YES" if default_account else "NO",
                "pair_subscription_active": "YES" if pairs_ready else "NO",
                "live_mode_locked": mode_status.get("environment_lock_verified", "NO"),
                "last_error": _last_bitget_error(),
                "last_successful_heartbeat": account_status.get("last_successful_api_ping_time") or "None",
                "last_successful_market_poll": _last_successful_market_poll(),
                "last_market_price_fetch": _last_successful_market_poll() or "N/A",
                "polling_interval": settings.get("refresh_interval_seconds", "15"),
                "active_polling_jobs_count": 0,
                "monitoring_session_id": state.monitoring.get("session_id", "None"),
                "monitoring_active": "YES" if state.monitoring.get("active") else "NO",
            },
            "execution_pathway_trace": {
                "pair_selected": enabled_pairs[0]["symbol"] if enabled_pairs else "None",
                "stream_active": "YES" if pairs_ready else "NO",
                "signal_engine_active": "NO" if not pairs_ready else "YES",
                "live_setup_detection_status": live_setup_detection_status(state).get("last_status", "IDLE"),
                "live_setup_detection_last_blocked_reason": live_setup_detection_status(state).get("last_blocked_reason", "None"),
                "signal_generated": "YES" if state.signals else "NO",
                "trade_plan_created": "YES" if state.trade_plans else "NO",
                "live_automation_status": live_automation_status(state).get("last_status", "IDLE"),
                "live_automation_last_blocked_reason": live_automation_status(state).get("last_blocked_reason", "None"),
                "execution_eligible": "YES" if execution_ready else "NO",
                "blocked_reason": "None" if execution_ready else _blocked_reason(profile_lock_status, exchange_ready, account_ready, pairs_ready, risk_ready, environment_ready),
            },
            "live_setup_detection": live_setup_detection_status(state),
            "live_automation": live_automation_status(state),
            "last_order_preview": preview_status,
            "settings": settings,
            "system_health": {
                "backend_online": "YES",
                "exchange_adapter_selected": "BITGET",
                "adapter_mode": settings.get("adapter_mode", "MOCK"),
                "last_heartbeat_time": _now(),
                "last_successful_market_poll": _last_successful_market_poll(),
                "last_successful_account_poll": account_status.get("last_successful_api_ping_time") or "None",
                "last_error": _last_error(),
                "polling_interval": settings.get("refresh_interval_seconds", "15"),
                "active_polling_jobs_count": 0,
            },
        }
    )


def _pair_control_record(pair: dict[str, object], settings: dict[str, object], account_status: dict[str, object]) -> dict[str, object]:
    state = get_state()
    enabled = bool(pair.get("enabled"))
    symbol = str(pair.get("symbol", "")).upper()
    poll = state.market_polls.get(symbol, {})
    poll_success = poll.get("poll_success") == "YES"
    poll_status = str(poll.get("poll_status") or "")
    supported = "YES" if symbol.endswith("USDT") else "NO"
    monitoring_session_active = bool(state.monitoring.get("active"))
    monitoring = enabled and monitoring_session_active and poll_success
    monitoring_status = "ACTIVE" if monitoring else ("POLLING" if poll_status == "POLLING" else ("ERROR" if poll.get("last_error") and poll_status == "ERROR" else "NOT MONITORING"))
    last_error = "" if poll_success else poll.get("last_error") or ("Monitoring has not been started." if not monitoring_session_active else ("Unsupported pair format" if supported == "NO" else "No successful live market poll yet."))
    return {
        "symbol": symbol,
        "enabled": enabled,
        "exchange_selected": "BITGET",
        "detected_by_exchange": supported,
        "supported_by_exchange": supported,
        "monitoring_enabled": "YES" if enabled else "NO",
        "market_data_stream_active": "YES" if monitoring else "NO",
        "product_type": poll.get("product_type", "USDT-FUTURES"),
        "contract_config_loaded": poll.get("contract_config_loaded", "NO"),
        "symbol_status": poll.get("symbol_status", "N/A"),
        "minTradeNum": poll.get("minTradeNum", "N/A"),
        "minTradeUSDT": poll.get("minTradeUSDT", "N/A"),
        "max_leverage": poll.get("maxLever", "N/A"),
        "last_price": poll.get("last_live_price", "N/A") if monitoring else "N/A",
        "bid_price": poll.get("bid_price", "N/A") if monitoring else "N/A",
        "ask_price": poll.get("ask_price", "N/A") if monitoring else "N/A",
        "mark_price": poll.get("mark_price", "N/A") if monitoring else "N/A",
        "last_price_update_time": poll.get("last_poll_completed", "N/A") if monitoring else "N/A",
        "refresh_interval_seconds": settings.get("refresh_interval_seconds", "15"),
        "next_scheduled_refresh_time": poll.get("next_scheduled_refresh_time", "N/A"),
        "monitoring_status": monitoring_status,
        "timeframe_subscription_status": "ACTIVE" if monitoring else "INACTIVE",
        "active_timeframes": settings.get("monitored_timeframes", ["16M", "12M", "8M", "1M"]),
        "last_poll_started": poll.get("last_poll_started", "N/A"),
        "last_poll_completed": poll.get("last_poll_completed", "N/A"),
        "poll_success": poll.get("poll_success", "NO"),
        "live_candle_count": poll.get("live_candle_count", len(state.live_candles.get(symbol, ()))),
        "last_live_price_received": poll.get("last_live_price", "N/A"),
        "last_candle_timeframe_update": poll.get("last_candle_timeframe_update", "N/A"),
        "last_error": last_error,
    }


def _account_status(default_account: dict[str, object] | None, mode_status: dict[str, object]) -> dict[str, object]:
    service = get_state().bitget_environment
    connection = service.last_connection_result
    saved_status = str(default_account.get("connection_status") or "NOT CONNECTED") if default_account else "NOT CONNECTED"
    verified = bool(default_account and saved_status == "CONNECTED" and connection and connection.get("connection_status") == "PASSED")
    if not default_account:
        return {
            "account_id": "BITGET_LIVE_RUNTIME" if verified else "None",
            "account_name": "Runtime Bitget LIVE credentials" if verified else "None",
            "connection_status": "CONNECTED" if verified else "NOT CONNECTED",
            "credential_type": "LIVE",
            "account_type": "REAL",
            "product_type": "USDT-FUTURES",
            "margin_coin": "USDT",
            "last_successful_api_ping_time": connection.get("last_successful_verification_time") if verified else "None",
            "balance": connection.get("available_balance", "N/A") if verified else "N/A",
            "available_margin": connection.get("available_margin", "N/A") if verified else "N/A",
            "private_api_auth_status": "PASSED" if verified else "NOT VERIFIED",
            "margin_mode_confirmation": "ISOLATED SUPPORTED" if verified else "NOT CONFIRMED",
            "leverage_support_confirmation": "SUPPORTED" if verified else "NOT CONFIRMED",
            "endpoint_reachable": "YES" if verified else "NO",
            "last_connection_error": service.last_connection_error or "None",
        }
    return {
        "account_id": default_account.get("account_id", "None"),
        "account_name": default_account.get("account_name", "None"),
        "connection_status": "CONNECTED" if verified else saved_status,
        "credential_type": "LIVE",
        "account_type": "REAL",
        "product_type": "USDT-FUTURES",
        "margin_coin": "USDT",
        "last_successful_api_ping_time": connection.get("last_successful_verification_time") if verified else "None",
        "balance": connection.get("available_balance", "N/A") if verified else "N/A",
        "available_margin": connection.get("available_margin", "N/A") if verified else "N/A",
        "private_api_auth_status": "PASSED" if verified else "NOT VERIFIED",
        "margin_mode_confirmation": "ISOLATED SUPPORTED" if verified else "NOT CONFIRMED",
        "leverage_support_confirmation": "SUPPORTED" if verified else "NOT CONFIRMED",
        "endpoint_reachable": "YES" if verified else "NO",
        "last_connection_error": service.last_connection_error or "None",
    }


def _best_profitable_backtest(runs) -> dict[str, object]:
    profitable: list[dict[str, object]] = []
    for run in runs:
        summary = (run.get("report") or {}).get("summary") if isinstance(run.get("report"), dict) else {}
        performance = summary.get("performance_summary", {}) if isinstance(summary, dict) else {}
        if _decimal(performance.get("net_profit")) > Decimal("0"):
            profitable.append(run)
    if not profitable:
        return {
            "status": "NOT AVAILABLE",
            "last_profitable_profile": "None",
            "profitable_risk_setting": "None",
            "profitable_leverage_setting": "None",
            "profitable_pair": "None",
            "profitable_timeframe_stack": "None",
            "average_time_to_tp": "N/A",
            "currently_active_in_live": "NO",
        }
    best = max(
        profitable,
        key=lambda item: _decimal(((((item.get("report") or {}).get("summary") or {}).get("performance_summary") or {}).get("net_profit"))),
    )
    summary = (best.get("report") or {}).get("summary") or {}
    performance = summary.get("performance_summary", {})
    return {
        "status": "AVAILABLE",
        "run_id": best.get("run_id"),
        "last_profitable_profile": best.get("profile_id") or summary.get("profile_id"),
        "profitable_risk_setting": performance.get("fixed_risk_amount", "None"),
        "profitable_leverage_setting": summary.get("max_leverage", "None"),
        "profitable_pair": best.get("symbol") or summary.get("symbol"),
        "profitable_timeframe_stack": best.get("timeframe_profile") or summary.get("timeframe_profile"),
        "average_time_to_tp": performance.get("average_time_to_hit_tp_human", "N/A"),
        "currently_active_in_live": "NO",
    }


def _refresh_due_market_polls(settings: dict[str, object]) -> None:
    state = get_state()
    try:
        interval = max(15, int(str(settings.get("refresh_interval_seconds", "15"))))
    except ValueError:
        interval = 15
    now = datetime.now(timezone.utc)
    for pair in state.monitored_pairs.values():
        if not pair.get("enabled"):
            continue
        symbol = str(pair.get("symbol", "")).upper()
        existing = state.market_polls.get(symbol, {})
        next_due = _parse_iso(str(existing.get("next_scheduled_refresh_time") or ""))
        if next_due and now < next_due:
            continue
        started = _now()
        poll = {
            **existing,
            "last_poll_started": started,
            "next_scheduled_refresh_time": (now.replace(microsecond=0)).isoformat(),
        }
        try:
            contract = state.bitget_environment.fetch_contract_config(symbol)
            ticker = state.bitget_environment.fetch_ticker(symbol)
            candles = state.bitget_environment.fetch_candles(symbol, "1m", 100)
            completed = _now()
            poll.update(
                {
                    "last_poll_completed": completed,
                    "poll_success": "YES",
                    "product_type": contract.get("product_type", "USDT-FUTURES"),
                    "contract_config_loaded": contract.get("contract_config_loaded", "YES"),
                    "symbol_status": contract.get("symbol_status", "UNKNOWN"),
                    "minTradeNum": contract.get("minTradeNum", "N/A"),
                    "minTradeUSDT": contract.get("minTradeUSDT", "N/A"),
                    "maxLever": contract.get("maxLever", "N/A"),
                    "last_live_price": ticker.get("last_price", "N/A"),
                    "bid_price": ticker.get("bid_price", "N/A"),
                    "ask_price": ticker.get("ask_price", "N/A"),
                    "mark_price": ticker.get("mark_price", "N/A"),
                    "index_price": ticker.get("index_price", "N/A"),
                    "last_candle_timeframe_update": completed,
                    "live_candle_count": candles.get("candle_count", 0),
                    "last_error": "",
                    "next_scheduled_refresh_time": (now.timestamp() + interval),
                }
            )
            next_time = datetime.fromtimestamp(float(poll["next_scheduled_refresh_time"]), tz=timezone.utc)
            poll["next_scheduled_refresh_time"] = next_time.isoformat()
        except Exception as exc:
            completed = _now()
            poll.update(
                {
                    "last_poll_completed": completed,
                    "poll_success": "NO",
                    "last_live_price": "N/A",
                    "bid_price": "N/A",
                    "ask_price": "N/A",
                    "mark_price": "N/A",
                    "contract_config_loaded": "NO",
                    "last_error": str(exc),
                    "next_scheduled_refresh_time": datetime.fromtimestamp(now.timestamp() + interval, tz=timezone.utc).isoformat(),
                }
            )
        state.market_polls[symbol] = poll


def _credentials_present(mode_status: dict[str, object]) -> str:
    credentials = mode_status.get("credential_status", {})
    if not isinstance(credentials, dict):
        return "NO"
    live = credentials.get("live", {})
    return "YES" if isinstance(live, dict) and bool(live.get("configured")) else "NO"


def _blocked_reason(profile_lock: str, exchange_ready: bool, account_ready: bool, pairs_ready: bool, risk_ready: bool, environment_ready: bool) -> str:
    if profile_lock != "PASSED":
        return "PROFILE LOCK FAILED"
    if not exchange_ready:
        return "EXCHANGE NOT READY"
    if not account_ready:
        return "ACCOUNT NOT CONNECTED"
    if not pairs_ready:
        return "PAIRS NOT MONITORING"
    if not risk_ready:
        return "RISK SETTINGS NOT READY"
    if not environment_ready:
        return "ENVIRONMENT LOCK FAILED"
    return "BLOCKED"


def _activate_selected_account_credentials() -> None:
    state = get_state()
    account_id = state.active_live_account_id or str(state.settings.get("active_account_id") or "")
    encrypted = state.encrypted_live_credentials.get(account_id)
    if not encrypted:
        return
    try:
        state.bitget_environment.runtime_credentials = decrypt_credentials(encrypted)
    except CredentialVaultError as exc:
        account = state.live_accounts.get(account_id)
        if account is not None:
            account["connection_status"] = "NEEDS_RECONNECT"
            account["verification_status"] = "NEEDS_RECONNECT"
            account["last_error"] = str(exc)


def _live_execution_readiness_checklist(
    *,
    profile_lock_status: str,
    exchange_ready: bool,
    account_status: dict[str, object],
    pairs_ready: bool,
    risk_ready: bool,
    environment_ready: bool,
    mode_status: dict[str, object],
) -> dict[str, object]:
    state = get_state()
    market_ready = pairs_ready and _last_successful_market_poll() != "None"
    setup_radar_ready = market_ready and profile_lock_status == "PASSED"
    margin_mode = str((state.bitget_environment.last_account_payload or {}).get("margin_mode") or account_status.get("margin_mode_confirmation") or "").upper()
    margin_ready = "ISOLATED" in margin_mode
    leverage_ready = risk_ready and any(_positive(poll.get("maxLever")) for poll in state.market_polls.values())
    live_armed = mode_status.get("trading_mode") == "LIVE" and mode_status.get("live_armed") == "YES"
    buy_trigger_ready = setup_radar_ready and risk_ready and environment_ready
    sell_trigger_ready = setup_radar_ready and risk_ready and environment_ready
    order_preview_system_ready = risk_ready and environment_ready and live_armed
    checks = {
        "Account Ready": _check(account_status.get("connection_status") == "CONNECTED", "account not connected"),
        "Market Data Ready": _check(market_ready, "no fresh live market poll"),
        "Setup Radar Ready": _check(setup_radar_ready, "setup radar requires live market data and profile lock"),
        "BUY Trigger Ready": _check(buy_trigger_ready, "buy trigger requires setup radar, risk, and environment locks"),
        "SELL Trigger Ready": _check(sell_trigger_ready, "sell trigger requires setup radar, risk, and environment locks"),
        "Risk Engine Ready": _check(risk_ready, "risk amount or max leverage missing"),
        "Margin Mode Ready": _check(margin_ready, "isolated margin not confirmed"),
        "Leverage Ready": _check(leverage_ready, "leverage setting or exchange max leverage not confirmed"),
        "Order Preview System Ready": _check(order_preview_system_ready, "live automation generates a fresh preview per trade"),
        "Live Trading Armed": _check(live_armed, "LIVE mode not armed"),
    }
    blockers = [f"{name}: {record['reason']}" for name, record in checks.items() if record["ready"] == "NO"]
    return {
        "title": "LIVE EXECUTION READINESS CHECKLIST",
        "checks": checks,
        "overall_status": "READY" if not blockers else "BLOCKED",
        "blockers": tuple(blockers),
        "setup_radar_source": "LIVE_MARKET_DATA" if market_ready else "NO_ACTIVE_LIVE_SETUPS",
    }


def _check(condition: bool, reason: str) -> dict[str, str]:
    return {"ready": "YES" if condition else "NO", "reason": "None" if condition else reason}


def _last_order_preview_status() -> dict[str, object]:
    preview = get_state().bitget_environment.last_dry_run_preview or {}
    if not preview:
        return {
            "exists": "NO",
            "fresh": "NO",
            "would_place_order": "NO",
            "message": "No manual preview yet. Live automation creates a fresh preview when a real trade plan is ready.",
            "preview": {},
        }
    fresh = not _is_stale(str(preview.get("generated_at", "")), 90)
    return {
        "exists": "YES",
        "fresh": "YES" if fresh else "STALE",
        "would_place_order": preview.get("would_place_order", "NO"),
        "generated_at": preview.get("generated_at", "None"),
        "message": "Manual diagnostic preview is fresh." if fresh else "Manual diagnostic preview is stale. Automated live orders still create their own fresh preview.",
        "preview": preview,
    }


def _last_bitget_error() -> str:
    state = get_state()
    if state.bitget_environment.blocked_orders:
        return str(state.bitget_environment.blocked_orders[-1].get("reason", "Unknown"))
    return "None"


def _last_successful_market_poll() -> str:
    polls = [poll for poll in get_state().market_polls.values() if poll.get("poll_success") == "YES"]
    if not polls:
        return "None"
    return str(max(polls, key=lambda item: str(item.get("last_poll_completed") or "")).get("last_poll_completed") or "None")


def _last_error() -> str:
    errors = [str(poll.get("last_error")) for poll in get_state().market_polls.values() if poll.get("last_error")]
    bitget_error = get_state().bitget_environment.last_connection_error
    if bitget_error:
        errors.append(bitget_error)
    return errors[-1] if errors else "None"


def _parse_iso(value: str):
    if not value or value == "N/A":
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _is_stale(value: str, seconds: int) -> bool:
    parsed = _parse_iso(value)
    if parsed is None:
        return True
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - parsed).total_seconds() > seconds


def _positive(value: object) -> bool:
    return _decimal(value) > Decimal("0")


def _decimal(value: object) -> Decimal:
    try:
        return Decimal(str(value or "0"))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
