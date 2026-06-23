"""Live setup-to-order orchestration.

This module connects already-detected ENTRY_READY setups to the live execution
guard. It does not weaken strategy, risk, profile, or exchange locks.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from arjiobot.exchange.bitget_environment import EnvironmentLockError, LIVE_CONFIRMATION_TEXT, TradeMode
from arjiobot.live_setup_detection import expire_stale_setup, move_setup_to_completed
from arjiobot.risk.isolated_margin import DEFAULT_FEE_RATE, DEFAULT_SLIPPAGE_BUFFER_RATE
from arjiobot.risk.risk_models import AccountSnapshot, OpenRiskState, RiskConfig, RiskRejectionReason, TradePlanStatus
from arjiobot.setup_tracker.setup_models import SetupState, SetupStatus
from arjiobot.strategy.strategy_models import SignalAction, SignalRejectionReason, SignalStatus

logger = logging.getLogger(__name__)

# A real ENTRY_READY setup's completed_at is the trade's entry-candle
# timestamp (see _setup_from_trade), not when automation happens to process
# it - normally near-zero apart (see _seconds_since_detected) since detection
# and execution run in the same poll cycle, but if automation was paused,
# Bitget was unreachable, or the process restarted, an ENTRY_READY setup can
# sit unsubmitted for a long time. The current market price has very likely
# moved away from its entry zone by then, so it must not be executed late -
# 2 closed 12M candles (24 minutes) is the staleness limit.
STALE_ENTRY_READY_MAX_AGE = timedelta(minutes=24)


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
    logger.info("Live automation run-once triggered (source=%s)", source)
    try:
        blocked = _preflight_blocker(state)
        if blocked:
            automation["last_status"] = "BLOCKED"
            automation["last_blocked_reason"] = blocked
            record = {"source": source, "status": "BLOCKED", "stage": "PREFLIGHT", "reason": blocked, "created_at": _now()}
            _append_attempt(automation, record)
            # Preflight blockers are almost always "is Bitget actually connected
            # and armed for live trading" questions (live_trading_enabled, LIVE
            # mode armed, adapter_mode, exchange environment lock) - log at
            # warning so this is impossible to miss in the server log.
            logger.warning("Live automation blocked at preflight (source=%s): %s", source, blocked)
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
            # DEBUG, not INFO: this is the expected outcome on the vast majority
            # of polling cycles (most cycles find nothing to trade) - logging it
            # at INFO would drown out the rare cycles that actually matter.
            logger.debug("Live automation: no ENTRY_READY setup found this cycle (source=%s)", source)
            return record

        logger.info(
            "Live automation: %d ENTRY_READY setup(s) found this cycle: %s",
            len(entry_ready_setups),
            ", ".join(f"{setup.symbol}/{setup.direction.value}/{setup.setup_id}" for setup in entry_ready_setups),
        )
        for setup in sorted(entry_ready_setups, key=lambda item: item.updated_at):
            expired_attempt = _expire_if_stale(state, automation, setup, source=source)
            if expired_attempt is not None:
                attempts.append(expired_attempt)
                continue
            try:
                attempts.append(_process_setup(state, automation, setup, source=source))
            except Exception as exc:
                # One setup's failure (malformed field, transient order-placement
                # error, etc.) must not block every other ENTRY_READY setup in this
                # cycle - including ones from the other trade direction - from being
                # attempted. Without this, a single bad setup at the front of the
                # sort order would silently and permanently starve all later ones,
                # every cycle, forever.
                # An unexpected exception here can happen after signal generation
                # already succeeded (e.g. a bug between trade-plan creation and
                # order submission) - clear the generated-signal marker so this
                # setup_id is not also permanently stuck rejecting as
                # DUPLICATE_SIGNAL on every later poll. No-op if no signal was
                # generated for it yet.
                state.strategy_engine.clear_generated_signal_for_setup(setup.setup_id)
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
        logger.info(
            "Live automation cycle complete (source=%s): %d submitted, %d not submitted. Submitted orders: %s",
            source,
            len(submitted),
            len(attempts) - len(submitted),
            ", ".join(f"{attempt.get('symbol')}/{attempt.get('bitget_order_id')}" for attempt in submitted) or "none",
        )
        return {"source": source, "status": automation["last_status"], "attempts": tuple(attempts), "created_at": _now()}
    except Exception as exc:  # Defensive: never kill the monitoring thread.
        automation["last_status"] = "ERROR"
        automation["last_error"] = str(exc)
        automation["last_blocked_reason"] = str(exc)
        record = {"source": source, "status": "ERROR", "stage": "AUTOMATION", "reason": str(exc), "created_at": _now()}
        _append_attempt(automation, record)
        logger.exception("Live automation cycle failed (source=%s)", source)
        return record


def _expire_if_stale(state: Any, automation: dict[str, Any], setup: Any, *, source: str) -> dict[str, Any] | None:
    """Gate against executing a setup whose entry zone is likely long stale.

    Returns the skipped attempt record (and marks the setup EXPIRED in Setup
    Radar via expire_stale_setup) if completed_at is missing or older than
    STALE_ENTRY_READY_MAX_AGE; returns None if the setup is fresh enough to
    proceed to _process_setup unchanged."""
    now = datetime.now(timezone.utc)
    age = (now - setup.completed_at) if setup.completed_at is not None else None
    if age is not None and age <= STALE_ENTRY_READY_MAX_AGE:
        return None
    expire_stale_setup(state, setup, expired_at=now)
    # Self-healing, same reason as the DUPLICATE_SIGNAL branch in
    # _process_setup: this setup never reached SUBMITTED, so any earlier
    # generated-signal marker for it would otherwise persist for no reason.
    state.strategy_engine.clear_generated_signal_for_setup(setup.setup_id)
    reason = (
        f"setup expired before execution - completed_at is {age} old, exceeds the {STALE_ENTRY_READY_MAX_AGE} staleness limit (2 closed 12M candles)"
        if age is not None
        else "setup expired before execution - completed_at missing, cannot verify freshness"
    )
    record = {
        "source": source,
        "setup_id": setup.setup_id,
        "symbol": setup.symbol,
        "stage": "STALENESS_GATE",
        "status": "EXPIRED",
        "reason": reason,
        "created_at": _now(),
    }
    logger.warning("Live automation: setup %s skipped and marked EXPIRED (%s)", setup.setup_id, reason)
    _append_attempt(automation, record)
    return record


def _resolve_rejected_setup(state: Any, setup: Any, *, execution_status: str, reason: str) -> None:
    """Move a real ENTRY_READY setup out of IN PROGRESS the moment execution
    explicitly rejects it (signal-level or risk-level - see
    should_leave_in_progress's TERMINAL_EXECUTION_STATES), tagging it so Setup
    Radar's COMPLETED tab shows *why* rather than presenting it as a
    successful trade. Deliberately NOT used for BITGET_DRY_RUN_PREVIEW/
    BITGET_LIVE_ORDER blocks - those represent the live exchange call itself
    failing, which can be transient (network, momentary exchange-side
    rejection), so that setup must keep retrying on a later poll exactly as
    before (see test_setup_blocked_downstream_of_signal_generation_can_be_retried_on_a_later_poll)."""
    resolved = replace(setup, execution_status=execution_status, updated_at=datetime.now(timezone.utc))
    move_setup_to_completed(state, resolved)
    logger.warning("[EXECUTION] %s REJECTED - reason: %s | setup stays in history as completed/rejected", setup.setup_id, reason)


def _process_setup(state: Any, automation: dict[str, Any], setup: Any, *, source: str) -> dict[str, Any]:
    attempt: dict[str, Any] = {
        "source": source,
        "setup_id": setup.setup_id,
        "symbol": setup.symbol,
        "stage": "SIGNAL",
        "created_at": _now(),
    }
    detection_to_execution_seconds = _seconds_since_detected(setup)
    logger.info(
        "Live automation: processing ENTRY_READY setup %s %s/%s (source=%s) - %s after detection",
        setup.setup_id,
        setup.symbol,
        setup.direction.value,
        source,
        f"{detection_to_execution_seconds:.3f}s" if detection_to_execution_seconds is not None else "unknown",
    )
    signal = state.strategy_engine.generate_signal_from_setup(setup)
    state.signals[signal.signal_id] = signal
    attempt["signal_id"] = signal.signal_id
    attempt["signal_status"] = signal.status.value
    if signal.status is not SignalStatus.GENERATED:
        attempt.update({"status": "BLOCKED", "reason": f"signal rejected: {signal.rejection_reason.value if signal.rejection_reason else 'UNKNOWN'}"})
        if signal.rejection_reason is SignalRejectionReason.DUPLICATE_SIGNAL:
            # Self-healing safety net, NOT a terminal rejection: this setup is
            # still ENTRY_READY and reachable here at all only because it was
            # never actually submitted (processed_setup_ids would have
            # filtered it out otherwise) - so an earlier poll's signal
            # succeeded but the setup was then blocked further downstream,
            # leaving a stale "already generated" marker that would
            # otherwise reject this exact setup_id forever. Clear it now so
            # the *next* poll gets a clean signal-generation attempt instead
            # of repeating this - the setup must stay in state.setups for
            # that retry to even be possible.
            state.strategy_engine.clear_generated_signal_for_setup(setup.setup_id)
        else:
            # Every other SignalRejectionReason is structural to this exact
            # setup's own fields (direction, stop/target relationship, a
            # missing required field, ...) - retrying the identical setup on
            # a later poll can never resolve it differently, so it leaves
            # IN PROGRESS now instead of sitting there until the 24-minute
            # staleness gate eventually catches it.
            _resolve_rejected_setup(state, setup, execution_status="rejected", reason=attempt["reason"])
        _append_attempt(automation, attempt)
        logger.warning("Live automation: setup %s blocked at SIGNAL stage: %s", setup.setup_id, attempt["reason"])
        return attempt

    attempt["stage"] = "RISK"
    try:
        risk_config, account_snapshot, open_state = _live_risk_context(state, setup.symbol)
    except ValueError as exc:
        state.strategy_engine.clear_generated_signal_for_setup(setup.setup_id)
        attempt.update({"status": "BLOCKED", "reason": str(exc)})
        _append_attempt(automation, attempt)
        logger.warning("Live automation: setup %s blocked at RISK stage (could not build risk context - check Bitget account/connection): %s", setup.setup_id, exc)
        return attempt

    plan = state.risk_engine.create_trade_plan(signal, risk_config, account_snapshot, open_state)
    state.trade_plans[plan.trade_plan_id] = plan
    attempt["trade_plan_id"] = plan.trade_plan_id
    attempt["trade_plan_status"] = plan.approval_status.value
    if plan.approval_status is not TradePlanStatus.APPROVED:
        state.strategy_engine.clear_generated_signal_for_setup(setup.setup_id)
        attempt.update({"status": "BLOCKED", "reason": "risk rejected: " + ",".join(reason.value for reason in plan.rejection_reasons)})
        # INSUFFICIENT_AVAILABLE_MARGIN gets its own execution_status
        # (no_margin) rather than the generic risk_blocked, so Setup Radar's
        # COMPLETED tab can distinguish "blocked on account margin" from
        # every other risk rejection at a glance.
        execution_status = "no_margin" if RiskRejectionReason.INSUFFICIENT_AVAILABLE_MARGIN in plan.rejection_reasons else "risk_blocked"
        _resolve_rejected_setup(state, setup, execution_status=execution_status, reason=attempt["reason"])
        _append_attempt(automation, attempt)
        logger.warning("Live automation: setup %s / trade plan %s blocked at RISK stage: %s", setup.setup_id, plan.trade_plan_id, attempt["reason"])
        return attempt

    if plan.trade_plan_id in set(automation.get("executed_trade_plan_ids", [])):
        # A genuine duplicate, not a stuck state - this trade plan really was
        # already submitted - so the generated-signal marker must NOT be
        # cleared here, unlike every other branch above/below.
        attempt.update({"status": "SKIPPED", "reason": "trade plan already executed"})
        _append_attempt(automation, attempt)
        logger.info("Live automation: setup %s / trade plan %s skipped - already executed", setup.setup_id, plan.trade_plan_id)
        return attempt

    attempt["stage"] = "BITGET_DRY_RUN_PREVIEW"
    payload = _order_payload_from_plan(state, plan)
    preview = state.bitget_environment.dry_run_preview(payload)
    attempt["dry_run_would_place_order"] = preview.get("would_place_order")
    if preview.get("would_place_order") != "YES":
        state.strategy_engine.clear_generated_signal_for_setup(setup.setup_id)
        attempt.update({"status": "BLOCKED", "reason": str(preview.get("blocked_reason") or "dry-run preview rejected")})
        _append_attempt(automation, attempt)
        logger.warning("Live automation: setup %s / trade plan %s blocked at BITGET_DRY_RUN_PREVIEW stage: %s", setup.setup_id, plan.trade_plan_id, attempt["reason"])
        return attempt

    attempt["stage"] = "BITGET_LIVE_ORDER"
    logger.info("Live automation: setup %s / trade plan %s passed dry-run preview, submitting live order to Bitget for %s", setup.setup_id, plan.trade_plan_id, plan.symbol)
    try:
        order = state.bitget_environment.place_order(payload, required_mode=TradeMode.LIVE)
    except EnvironmentLockError as exc:
        state.strategy_engine.clear_generated_signal_for_setup(setup.setup_id)
        attempt.update({"status": "BLOCKED", "reason": f"Bitget order placement failed: {exc}"})
        _append_attempt(automation, attempt)
        logger.warning("Live automation: setup %s / trade plan %s order REJECTED by Bitget: %s", setup.setup_id, plan.trade_plan_id, exc)
        return attempt
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
    # This setup's Setup Radar lifecycle is done - it is now a live trade.
    # Move it out of the uncapped in-progress pool into completed_setups
    # (capped at 100) so it shows up in Setup Radar's COMPLETED history with
    # this attempt's bitget_order_id/trade_plan_id (see radar.py's
    # _related_execution), and stops being listed as "in progress".
    move_setup_to_completed(state, replace(setup, execution_status="trade_opened", updated_at=datetime.now(timezone.utc)))
    _append_attempt(automation, attempt)
    logger.info(
        "Live automation: order PLACED on Bitget for setup %s (%s) - bitget_order_id=%s trade_plan_id=%s",
        setup.setup_id,
        plan.symbol,
        attempt["bitget_order_id"],
        plan.trade_plan_id,
    )
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


def _effective_max_leverage(state: Any, symbol: str) -> Decimal:
    """Per-pair leverage (state.monitored_pairs[symbol]["leverage"], stored
    alongside that pair's symbol/enabled config) overrides the global
    max_leverage setting whenever one is configured for this symbol - this
    value flows untouched through the existing chain (RiskConfig ->
    risk_validation.calculate_required_margin -> plan.max_allowed_leverage ->
    _order_payload_from_plan -> bitget_environment._build_order_plan's
    effective_max_leverage), so both the margin calculation and the
    set_leverage call already use whatever this resolves to. Falls back to
    the global setting for any pair with no specific value set.
    """
    pair = state.monitored_pairs.get(symbol.upper()) or {}
    pair_leverage = pair.get("leverage")
    if pair_leverage not in (None, "", 0, "0"):
        try:
            return _positive_decimal(pair_leverage, f"{symbol} leverage")
        except ValueError:
            pass
    return _positive_decimal(state.settings.get("max_leverage"), "max leverage")


_UNPARSEABLE_POSITION_EXPOSURE = Decimal("999999999999")  # see _position_notional


def _real_time_open_positions(state: Any) -> tuple[int, dict[str, Decimal]]:
    """Query Bitget directly for currently-open positions, replacing the
    in-memory open_positions counter on BitgetEnvironmentService - that
    counter only ever increments (on a successful place_order), never
    decrements when a position closes, and resets to 0 on every process
    restart, so it could never reflect reality: a restart while a position
    was open would silently let a new one open right alongside it.

    open_symbol_exposure is each symbol's real notional value (position size
    * mark price), not a flat sentinel - so max_symbol_exposure
    (risk_validation.py) is an enforceable cap once
    allow_multiple_positions_same_symbol is enabled, not a no-op (a flat "1"
    per symbol previously made an existing $5,000 position read as "$1" of
    exposure). has_same_symbol_exposure (risk/exposure.py) only checks > 0,
    which a real notional value still satisfies.
    """
    try:
        record = state.bitget_environment.fetch_positions()
    except EnvironmentLockError as exc:
        raise ValueError(f"could not verify currently-open positions before placing a new order: {exc}") from exc
    positions = record.get("positions") or ()
    exposure: dict[str, Decimal] = {}
    for position in positions:
        position_symbol = str(position.get("symbol", "")).upper()
        if not position_symbol:
            continue
        exposure[position_symbol] = exposure.get(position_symbol, Decimal("0")) + _position_notional(position)
    return len(positions), exposure


def _position_notional(position: dict[str, object]) -> Decimal:
    """Real notional value of an open position from Bitget's raw position
    fields (same field names trades.py's live trades tab already reads).
    Bitget's exact field names have not been verified against a real
    authenticated response anywhere in this codebase - if notional cannot be
    parsed, the position is treated as fully exposed (a large sentinel)
    rather than understated, so max_symbol_exposure fails toward blocking an
    additional trade, never toward silently allowing one."""
    size = _decimal_or_none(position.get("total") or position.get("available"))
    mark_price = _decimal_or_none(position.get("markPrice"))
    if size is not None and mark_price is not None and size > 0 and mark_price > 0:
        return size * mark_price
    return _UNPARSEABLE_POSITION_EXPOSURE


def _decimal_or_none(value: object) -> Decimal | None:
    if value in (None, "", "N/A"):
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None


def _realized_pnl_since(state: Any, *, since: datetime) -> Decimal:
    """Sum of real, realized PnL (from Bitget's closed-position history) for
    positions closed at or after `since` - the same data trades.py's PnL tab
    already sums (netProfit/pnl), just windowed by close time here for the
    daily/weekly loss-limit checks. Returns Decimal("0") if history cannot be
    fetched (e.g. credentials not yet connected) rather than blocking risk
    assessment entirely on a transient/missing connection - the existing
    open-trade-count/margin checks already require a live connection to
    proceed this far, so a real account context normally already exists."""
    try:
        record = state.bitget_environment.fetch_position_history()
    except EnvironmentLockError:
        return Decimal("0")
    total = Decimal("0")
    for row in record.get("closed_positions", ()):
        closed_at = _parse_bitget_close_time(row.get("uTime") or row.get("utime"))
        if closed_at is None or closed_at < since:
            continue
        pnl = _decimal_or_none(row.get("netProfit") or row.get("pnl"))
        if pnl is not None:
            total += pnl
    return total


def _parse_bitget_close_time(value: object) -> datetime | None:
    """Same convention as live_setup_detection.py's _parse_bitget_timestamp:
    Bitget returns epoch milliseconds as a numeric string for most
    timestamp fields, with an ISO-string fallback."""
    if value in (None, "", "N/A"):
        return None
    try:
        numeric = int(str(value))
    except ValueError:
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    try:
        if numeric > 10_000_000_000:
            return datetime.fromtimestamp(numeric / 1000, tz=timezone.utc)
        return datetime.fromtimestamp(numeric, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


def _live_risk_context(state: Any, symbol: str) -> tuple[RiskConfig, AccountSnapshot, OpenRiskState]:
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
    max_leverage = _effective_max_leverage(state, symbol)
    open_trade_count, open_symbol_exposure = _real_time_open_positions(state)
    now = datetime.now(timezone.utc)
    # Real realized PnL from Bitget's closed-position history (same data
    # trades.py's PnL tab already sums), windowed to the last 24h/7d - without
    # this, daily_loss_capacity_remaining/weekly_loss_capacity_remaining
    # (loss_limits.py) always computed against zero realized loss, so
    # DAILY_LOSS_LIMIT_REACHED/WEEKLY_LOSS_LIMIT_REACHED could never fire
    # from real trading activity, no matter how much had actually been lost.
    current_daily_pnl = _realized_pnl_since(state, since=now - timedelta(hours=24))
    current_weekly_pnl = _realized_pnl_since(state, since=now - timedelta(days=7))
    config = RiskConfig(
        account_equity=equity,
        fixed_risk_amount=risk_amount,
        selected_rr_profile=str(state.settings.get("selected_rr_profile") or "RR_1_5"),
        max_leverage=max_leverage,
        max_open_trades=int(str(state.settings.get("max_open_trades") or "1")),
        max_daily_loss=Decimal(str(state.settings.get("max_daily_loss") or "0")),
        # max_weekly_loss was never read from settings before this fix - it
        # silently used RiskConfig's class default (1500) regardless of what
        # was configured.
        max_weekly_loss=Decimal(str(state.settings.get("max_weekly_loss") or "0")),
    )
    snapshot = AccountSnapshot(account_currency="USDT", account_equity=equity, available_margin=available, captured_at=now)
    open_state = OpenRiskState(
        open_trade_count=open_trade_count,
        open_symbol_exposure=open_symbol_exposure,
        current_daily_pnl=current_daily_pnl,
        current_weekly_pnl=current_weekly_pnl,
    )
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
        "fee_rate": str(DEFAULT_FEE_RATE),
        "slippage_rate": str(DEFAULT_SLIPPAGE_BUFFER_RATE),
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


def _seconds_since_detected(setup: Any) -> float | None:
    """Wall-clock seconds between _setup_from_trade creating this setup
    (live_setup_detection.py stamps metadata["detected_at_wallclock"] at that
    moment) and this exact call processing it. Detection and execution
    already run in the same poll cycle/function call chain - this makes that
    near-zero gap observable in logs instead of just asserted from reading
    the code."""
    raw = getattr(setup, "metadata", {}).get("detected_at_wallclock") if getattr(setup, "metadata", None) else None
    if not raw:
        return None
    try:
        detected_at = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None
    return (datetime.now(timezone.utc) - detected_at).total_seconds()
