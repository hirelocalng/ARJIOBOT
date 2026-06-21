"""Live setup-to-order orchestration.

This module connects already-detected ENTRY_READY setups to the live execution
guard. It does not weaken strategy, risk, profile, or exchange locks.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from arjiobot.exchange.bitget_environment import LIVE_CONFIRMATION_TEXT, TradeMode
from arjiobot.risk.risk_models import AccountSnapshot, OpenRiskState, RiskConfig, TradePlanStatus
from arjiobot.setup_tracker.setup_models import SetupState, SetupStatus
from arjiobot.strategy.strategy_models import SignalAction, SignalStatus

logger = logging.getLogger(__name__)


def ensure_live_automation_state(state: Any) -> dict[str, Any]:
    current = getattr(state, "live_automation", None)
    if isinstance(current, dict):
        return current
    current = {
        "enabled": True,
        "last_run_at": "None",
        "last_status": "IDLE",
        "last_blocked_reason": "None",
        "last_error": "None",
        "processed_setup_ids": [],
        "executed_trade_plan_ids": [],
        "attempts": [],
    }
    setattr(state, "live_automation", current)
    return current


def live_automation_status(state: Any) -> dict[str, Any]:
    automation = ensure_live_automation_state(state)
    return {
        "enabled": automation.get("enabled", True),
        "last_run_at": automation.get("last_run_at", "None"),
        "last_status": automation.get("last_status", "IDLE"),
        "last_blocked_reason": automation.get("last_blocked_reason", "None"),
        "last_error": automation.get("last_error", "None"),
        "processed_setup_count": len(automation.get("processed_setup_ids", [])),
        "executed_trade_plan_count": len(automation.get("executed_trade_plan_ids", [])),
        "latest_attempt": (automation.get("attempts") or [{}])[-1] if automation.get("attempts") else {},
    }


def run_live_automation_once(state: Any, *, source: str = "MANUAL") -> dict[str, Any]:
    """Process newly entry-ready setups through live Bitget execution.

    The function is intentionally idempotent. A setup/trade plan that has
    already been executed will not be submitted again.
    """

    automation = ensure_live_automation_state(state)
    automation["last_run_at"] = _now()
    automation["last_error"] = "None"
    attempts: list[dict[str, Any]] = []
    try:
        blocked = _preflight_blocker(state)
        if blocked:
            automation["last_status"] = "BLOCKED"
            automation["last_blocked_reason"] = blocked
            record = {"source": source, "status": "BLOCKED", "stage": "PREFLIGHT", "reason": blocked, "created_at": _now()}
            _append_attempt(automation, record)
            return record

        entry_ready_setups = [
            setup
            for setup in state.setups.values()
            if getattr(setup, "current_state", None) is SetupState.ENTRY_READY
            and getattr(setup, "status", None) is SetupStatus.ENTRY_READY
            and setup.setup_id not in set(automation.get("processed_setup_ids", []))
        ]
        if not entry_ready_setups:
            automation["last_status"] = "WAITING"
            automation["last_blocked_reason"] = "No ENTRY_READY setup found."
            record = {"source": source, "status": "WAITING", "stage": "SETUP_RADAR", "reason": "No ENTRY_READY setup found.", "created_at": _now()}
            _append_attempt(automation, record)
            return record

        for setup in sorted(entry_ready_setups, key=lambda item: item.updated_at):
            try:
                attempts.append(_process_setup(state, automation, setup, source=source))
            except Exception as exc:
                # One setup's failure (malformed field, transient order-placement
                # error, etc.) must not block every other ENTRY_READY setup in this
                # cycle - including ones from the other trade direction - from being
                # attempted. Without this, a single bad setup at the front of the
                # sort order would silently and permanently starve all later ones,
                # every cycle, forever.
                failed_attempt = {
                    "source": source,
                    "setup_id": setup.setup_id,
                    "symbol": setup.symbol,
                    "stage": "SETUP_PROCESSING",
                    "status": "ERROR",
                    "reason": str(exc),
                    "created_at": _now(),
                }
                logger.exception("Live automation failed to process setup %s; continuing with remaining setups", setup.setup_id)
                _append_attempt(automation, failed_attempt)
                attempts.append(failed_attempt)

        submitted = [attempt for attempt in attempts if attempt.get("status") == "SUBMITTED"]
        automation["last_status"] = "SUBMITTED" if submitted else "BLOCKED"
        automation["last_blocked_reason"] = "None" if submitted else attempts[-1].get("reason", "No order submitted.")
        return {"source": source, "status": automation["last_status"], "attempts": tuple(attempts), "created_at": _now()}
    except Exception as exc:  # Defensive: never kill the monitoring thread.
        automation["last_status"] = "ERROR"
        automation["last_error"] = str(exc)
        automation["last_blocked_reason"] = str(exc)
        record = {"source": source, "status": "ERROR", "stage": "AUTOMATION", "reason": str(exc), "created_at": _now()}
        _append_attempt(automation, record)
        return record


def _process_setup(state: Any, automation: dict[str, Any], setup: Any, *, source: str) -> dict[str, Any]:
    attempt: dict[str, Any] = {
        "source": source,
        "setup_id": setup.setup_id,
        "symbol": setup.symbol,
        "stage": "SIGNAL",
        "created_at": _now(),
    }
    signal = state.strategy_engine.generate_signal_from_setup(setup)
    state.signals[signal.signal_id] = signal
    attempt["signal_id"] = signal.signal_id
    attempt["signal_status"] = signal.status.value
    if signal.status is not SignalStatus.GENERATED:
        attempt.update({"status": "BLOCKED", "reason": f"signal rejected: {signal.rejection_reason.value if signal.rejection_reason else 'UNKNOWN'}"})
        _append_attempt(automation, attempt)
        return attempt

    attempt["stage"] = "RISK"
    try:
        risk_config, account_snapshot, open_state = _live_risk_context(state)
    except ValueError as exc:
        attempt.update({"status": "BLOCKED", "reason": str(exc)})
        _append_attempt(automation, attempt)
        return attempt

    plan = state.risk_engine.create_trade_plan(signal, risk_config, account_snapshot, open_state)
    state.trade_plans[plan.trade_plan_id] = plan
    attempt["trade_plan_id"] = plan.trade_plan_id
    attempt["trade_plan_status"] = plan.approval_status.value
    if plan.approval_status is not TradePlanStatus.APPROVED:
        attempt.update({"status": "BLOCKED", "reason": "risk rejected: " + ",".join(reason.value for reason in plan.rejection_reasons)})
        _append_attempt(automation, attempt)
        return attempt

    if plan.trade_plan_id in set(automation.get("executed_trade_plan_ids", [])):
        attempt.update({"status": "SKIPPED", "reason": "trade plan already executed"})
        _append_attempt(automation, attempt)
        return attempt

    attempt["stage"] = "BITGET_DRY_RUN_PREVIEW"
    payload = _order_payload_from_plan(state, plan)
    preview = state.bitget_environment.dry_run_preview(payload)
    attempt["dry_run_would_place_order"] = preview.get("would_place_order")
    if preview.get("would_place_order") != "YES":
        attempt.update({"status": "BLOCKED", "reason": str(preview.get("blocked_reason") or "dry-run preview rejected")})
        _append_attempt(automation, attempt)
        return attempt

    attempt["stage"] = "BITGET_LIVE_ORDER"
    order = state.bitget_environment.place_order(payload, required_mode=TradeMode.LIVE)
    time_exit_plan = _time_exit_management_record(plan, order)
    attempt.update(
        {
            "status": "SUBMITTED",
            "reason": "None",
            "bitget_order_id": order.get("bitget_order_id", ""),
            "client_oid": (order.get("sanitized_payload") or {}).get("clientOid", ""),
            "time_exit_management": time_exit_plan,
            "submitted_at": _now(),
        }
    )
    automation.setdefault("processed_setup_ids", []).append(setup.setup_id)
    automation.setdefault("executed_trade_plan_ids", []).append(plan.trade_plan_id)
    state.strategy_engine.mark_signal_status(signal.signal_id, SignalStatus.SENT_TO_EXECUTION, datetime.now(timezone.utc), reason="live automation submitted order")
    state.risk_engine.update_trade_plan_status(plan.trade_plan_id, TradePlanStatus.SENT_TO_EXECUTION, datetime.now(timezone.utc), reason="live automation submitted order")
    _append_attempt(automation, attempt)
    return attempt


def _preflight_blocker(state: Any) -> str | None:
    if not state.settings.get("live_trading_enabled"):
        return "live trading is disabled"
    if state.bitget_environment.mode is not TradeMode.LIVE or not state.bitget_environment.live_armed:
        return "LIVE mode is not armed"
    if state.settings.get("adapter_mode") != "BITGET_LIVE":
        return "adapter mode is not BITGET_LIVE"
    if not state.monitoring.get("active"):
        return "pair monitoring is not active"
    if not any(poll.get("poll_success") == "YES" for poll in state.market_polls.values()):
        return "no successful live market poll"
    if state.bitget_environment.verify_environment_lock(TradeMode.LIVE, order_environment="LIVE", fail_on_error=False).lock_status != "PASSED":
        return "exchange environment lock failed"
    return None


def _live_risk_context(state: Any) -> tuple[RiskConfig, AccountSnapshot, OpenRiskState]:
    account_payload = state.bitget_environment.last_account_payload or {}
    connection = state.bitget_environment.last_connection_result or {}
    equity = _positive_decimal(
        account_payload.get("total_equity")
        or connection.get("available_balance")
        or state.settings.get("starting_balance"),
        "account equity",
    )
    available = _positive_decimal(
        account_payload.get("available_margin")
        or connection.get("available_margin")
        or connection.get("available_balance"),
        "available margin",
    )
    risk_amount = _positive_decimal(state.settings.get("risk_amount_per_trade"), "risk amount per trade")
    max_leverage = _positive_decimal(state.settings.get("max_leverage"), "max leverage")
    config = RiskConfig(
        account_equity=equity,
        fixed_risk_amount=risk_amount,
        selected_rr_profile=str(state.settings.get("selected_rr_profile") or "RR_1_5"),
        max_leverage=max_leverage,
        max_open_trades=int(str(state.settings.get("max_open_trades") or "1")),
        max_daily_loss=Decimal(str(state.settings.get("max_daily_loss") or "0")),
    )
    snapshot = AccountSnapshot(account_currency="USDT", account_equity=equity, available_margin=available, captured_at=datetime.now(timezone.utc))
    open_state = OpenRiskState(open_trade_count=int(state.bitget_environment.open_positions))
    return config, snapshot, open_state


def _order_payload_from_plan(state: Any, plan: Any) -> dict[str, object]:
    selected_profile = str(state.settings.get("active_strategy_profile") or "")
    side = "SELL" if plan.action is SignalAction.MARKET_SELL_READY else "BUY"
    time_exit_enabled = str(plan.selected_rr_profile).upper() == "TIME_BASED_EXIT" or plan.metadata.get("time_exit_enabled") == "YES"
    time_exit_minutes = str(plan.metadata.get("time_exit_minutes") or state.settings.get("time_exit_minutes") or "")
    planned_time_exit_at = plan.metadata.get("planned_time_exit_at") or ""
    payload = {
        "symbol": plan.symbol,
        "side": side,
        "entry_price": str(plan.entry_reference_price),
        "stop_loss": str(plan.stop_loss_price),
        "selected_profile_id": selected_profile,
        "applied_profile_id": selected_profile,
        "profile_lock_status": "PASSED",
        "selected_tp_model": plan.selected_rr_profile,
        "applied_tp_model": plan.selected_rr_profile,
        "time_exit_enabled": time_exit_enabled,
        "time_exit_minutes": time_exit_minutes if time_exit_enabled else "",
        "planned_time_exit_at": planned_time_exit_at if time_exit_enabled else "",
        "time_exit_close_type": "MARKET" if time_exit_enabled else "",
        "time_exit_timer_starts_from": "REAL_EXCHANGE_FILL_TIMESTAMP" if time_exit_enabled else "",
        "risk_amount": str(plan.risk_amount),
        "selected_fixed_risk_amount": str(plan.risk_amount),
        "max_risk_per_trade": str(plan.risk_amount),
        "selected_max_leverage": str(plan.max_allowed_leverage),
        "max_allowed_leverage": str(plan.max_allowed_leverage),
        "max_daily_loss": str(state.settings.get("max_daily_loss") or "0"),
        "max_trades_per_day": str(state.settings.get("max_open_trades") or "1"),
        "max_open_positions": str(state.settings.get("max_open_trades") or "1"),
        "fee_rate": "0",
        "slippage_rate": "0",
        "live_confirmation": LIVE_CONFIRMATION_TEXT,
        "trade_plan_id": plan.trade_plan_id,
        "signal_id": plan.signal_id,
        "setup_id": plan.setup_id,
    }
    if not time_exit_enabled:
        payload["take_profit"] = str(plan.take_profit_price)
    return payload


def _time_exit_management_record(plan: Any, order: dict[str, Any]) -> dict[str, object]:
    enabled = str(plan.selected_rr_profile).upper() == "TIME_BASED_EXIT" or plan.metadata.get("time_exit_enabled") == "YES"
    if not enabled:
        return {"time_exit_enabled": False}
    minutes = int(str(plan.metadata.get("time_exit_minutes") or "0"))
    submitted_at = datetime.now(timezone.utc)
    return {
        "time_exit_enabled": True,
        "time_exit_minutes": minutes,
        "timer_status": "PENDING_ENTRY_FILL",
        "timer_starts_from": "REAL_EXCHANGE_FILL_TIMESTAMP",
        "planned_time_exit_at": (submitted_at + timedelta(minutes=minutes)).isoformat() if minutes else "",
        "default_close_type": "MARKET",
        "close_order_policy": "reduce-only opposite-side close after confirmed fill",
        "position_size_confirmation_required": "YES",
        "entry_order_id": order.get("bitget_order_id", ""),
        "close_exchange_order_id": "",
    }


def _append_attempt(automation: dict[str, Any], attempt: dict[str, Any]) -> None:
    attempts = automation.setdefault("attempts", [])
    attempts.append(dict(attempt))
    del attempts[:-50]


def _positive_decimal(value: object, label: str) -> Decimal:
    try:
        parsed = Decimal(str(value or "0"))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{label} is missing or invalid") from exc
    if parsed <= 0:
        raise ValueError(f"{label} must be greater than zero")
    return parsed


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
