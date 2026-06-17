"""Bot settings routes."""

from __future__ import annotations

from fastapi import APIRouter

from arjiobot.api.dependencies import FROZEN_VISIBLE_PROFILE_IDS, get_state, save_settings
from arjiobot.api.errors import api_error
from arjiobot.api.schemas.common import ok
from arjiobot.backtesting.research_profiles import get_profile
from arjiobot.backtesting.timeframe_profiles import get_timeframe_profile
from arjiobot.exchange.account_vault import save_vault
from arjiobot.exchange.bitget_environment import EnvironmentLockError, TradeMode
from arjiobot.risk.rr_profiles import resolve_rr_value

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("")
def get_settings():
    return ok(get_state().settings)


@router.patch("")
def update_settings(payload: dict[str, object]):
    state = get_state()
    candidate = dict(state.settings)
    active_account_touched = "active_account_id" in payload
    for key, value in payload.items():
        if key in candidate and value is not None:
            if key in ("default_backtesting_profile", "active_strategy_profile"):
                try:
                    value = get_profile(str(value)).profile_id
                except ValueError as exc:
                    raise api_error(400, "STRATEGY_PROFILE_INVALID", str(exc)) from exc
                if value not in FROZEN_VISIBLE_PROFILE_IDS:
                    raise api_error(
                        400,
                        "PROFILE_FROZEN",
                        "Strategy profile is frozen. Trade connection and risk settings can be changed, but profile logic cannot be edited.",
                    )
            if key == "default_timeframe_profile":
                try:
                    value = get_timeframe_profile(str(value)).profile_id
                except ValueError as exc:
                    raise api_error(400, "TIMEFRAME_PROFILE_INVALID", str(exc)) from exc
            if key == "selected_rr_profile":
                if str(value).upper() != "TIME_BASED_EXIT":
                    try:
                        resolve_rr_value(str(value))
                    except ValueError as exc:
                        raise api_error(400, "RR_PROFILE_INVALID", str(exc)) from exc
            if key == "time_exit_minutes":
                value = _validate_time_exit_minutes(value)
            if key == "adapter_mode":
                value = str(value).upper()
                if value not in {"MOCK", "BITGET_LIVE"}:
                    raise api_error(400, "ADAPTER_MODE_INVALID", "adapter_mode must be MOCK or BITGET_LIVE.")
            if key == "trading_mode":
                try:
                    value = TradeMode(str(value).upper()).value
                except ValueError as exc:
                    raise api_error(400, "TRADING_MODE_INVALID", "trading_mode must be OFF, DRY_RUN_PREVIEW, or LIVE.") from exc
            if key == "active_account_id":
                value = str(value or "")
                if value and value not in state.live_accounts:
                    raise api_error(400, "ACTIVE_ACCOUNT_INVALID", "selected active account does not exist")
            if key in {"starting_balance", "risk_amount_per_trade", "max_leverage", "max_daily_loss", "max_weekly_loss"} and value != "":
                try:
                    if float(str(value)) <= 0:
                        raise ValueError
                except ValueError as exc:
                    raise api_error(400, "RISK_SETTING_INVALID", f"{key} must be a positive number.") from exc
            candidate[key] = value
    if str(candidate.get("trading_mode", "OFF")).upper() == "LIVE":
        try:
            state.bitget_environment.verify_environment_lock(TradeMode.LIVE, order_environment="LIVE")
        except EnvironmentLockError as exc:
            raise api_error(400, "LIVE_TRADING_ENVIRONMENT_LOCK_FAILED", str(exc)) from exc
    if str(candidate.get("trading_mode", "OFF")).upper() == "DRY_RUN_PREVIEW":
        try:
            state.bitget_environment.verify_environment_lock(TradeMode.DRY_RUN_PREVIEW, order_environment="DRY_RUN_PREVIEW")
        except EnvironmentLockError as exc:
            raise api_error(400, "DRY_RUN_ENVIRONMENT_LOCK_FAILED", str(exc)) from exc
    if bool(candidate.get("live_trading_enabled")):
        _validate_live_trading_candidate(candidate)
    state.settings.update(candidate)
    if active_account_touched:
        _apply_active_account_id(str(candidate.get("active_account_id") or ""))
    save_settings(state.settings)
    return ok(state.settings)


def _apply_active_account_id(account_id: str) -> None:
    state = get_state()
    if not account_id:
        return
    for existing in state.live_accounts.values():
        existing["is_default"] = False
        existing["is_active"] = False
    account = state.live_accounts[account_id]
    account["is_default"] = True
    account["is_active"] = True
    state.active_live_account_id = account_id
    save_vault(state.live_accounts, state.encrypted_live_credentials, state.active_live_account_id)


def _validate_live_trading_candidate(settings: dict[str, object]) -> None:
    state = get_state()
    if state.bitget_environment.last_connection_result is None:
        raise api_error(400, "LIVE_TRADING_ACCOUNT_REQUIRED", "Live trading requires a successful signed Bitget account check.")
    if not any(pair.get("enabled") for pair in state.monitored_pairs.values()):
        raise api_error(400, "LIVE_TRADING_PAIR_REQUIRED", "Live trading requires at least one enabled trading pair.")
    get_timeframe_profile(str(settings.get("default_timeframe_profile")))
    if str(settings.get("selected_rr_profile", "")).upper() != "TIME_BASED_EXIT":
        resolve_rr_value(str(settings.get("selected_rr_profile")))
    if str(settings.get("selected_rr_profile", "")).upper() == "TIME_BASED_EXIT":
        _validate_time_exit_minutes(settings.get("time_exit_minutes"))
    try:
        if float(str(settings.get("risk_amount_per_trade", "0"))) <= 0:
            raise ValueError
    except ValueError as exc:
        raise api_error(400, "LIVE_TRADING_RISK_INVALID", "Live trading requires a positive fixed risk amount.") from exc


def _validate_time_exit_minutes(value: object) -> str:
    try:
        minutes = int(str(value))
    except (TypeError, ValueError) as exc:
        raise api_error(400, "TIME_EXIT_MINUTES_INVALID", "time_exit_minutes must be an integer from 1 to 120.") from exc
    if minutes < 1 or minutes > 120:
        raise api_error(400, "TIME_EXIT_MINUTES_INVALID", "time_exit_minutes must be between 1 and 120.")
    return str(minutes)
