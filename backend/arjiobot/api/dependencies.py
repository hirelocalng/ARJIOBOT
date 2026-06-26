"""API dependency and in-memory service wiring."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

from arjiobot.database.store import read_all_settings, write_settings
from arjiobot.exchange.bitget_adapter import BitgetExchangeAdapter
from arjiobot.exchange.bitget_environment import BitgetEnvironmentService, TradeMode
from arjiobot.exchange.exchange_models import ExchangeMode
from arjiobot.execution.execution_service import ExecutionService
from arjiobot.fvg.fvg import FVGDetectionEngine
from arjiobot.backtesting.research_profiles import get_strategy_profiles
from arjiobot.backtesting.timeframe_profiles import get_timeframe_profiles
from arjiobot.exchange.account_vault import load_vault
from arjiobot.risk.risk_engine import RiskEngine
from arjiobot.risk.rr_profiles import SUPPORTED_TP_MODELS
from arjiobot.strategy.strategy_engine import StrategyEngine

# parents[2] = the directory containing arjiobot/ ("backend" locally, "/app"
# in the Docker image, which is built from the backend/ directory only - see
# the Dockerfile). Using a deeper parents[N] here previously resolved to one
# level *above* that (the monorepo root locally; filesystem root in the
# container), where data/ may not even be writable.
ROOT = Path(__file__).resolve().parents[2]
SETTINGS_PATH = ROOT / "data" / "runtime_settings.json"
PAIRS_PATH = ROOT / "data" / "runtime_pairs.json"
# Seeded whenever the persisted pairs file is missing, unreadable, or ends
# up empty - a fresh start, a Railway redeploy with no persistent volume,
# or a corrupted file must never leave the bot with zero (or just one)
# monitored pair.
DEFAULT_MONITORED_PAIRS: dict[str, int] = {
    "BTCUSDT": 120,
    "ATOMUSDT": 75,
    "APTUSDT": 75,
    "SUIUSDT": 75,
    "EIGENUSDT": 75,
    "TAOUSDT": 50,
    "SOLUSDT": 80,
    "AAVEUSDT": 75,
    "BCHUSDT": 75,
    "1INCHUSDT": 75,
}
FROZEN_VISIBLE_PROFILE_ID = "PROFILE_RECOVERED_HIGH_WINRATE"
FROZEN_VISIBLE_PROFILE_IDS = {"PROFILE_RECOVERED_HIGH_WINRATE", "PROFILE_2"}

# Allowed values for each profile setting (used in load_settings validation).
# Each set must mirror the full registered set, not a hand-picked subset - a
# narrower allowlist here than what PATCH /api/settings (and the frontend
# dropdown) actually accepts causes a silent revert-to-default on the next
# load_settings() call (e.g. after a Railway restart/redeploy), since a
# previously-saved, validly-accepted value would no longer pass this check.
ALLOWED_STRATEGY_PROFILES = {profile.profile_id for profile in get_strategy_profiles()}
ALLOWED_TIMEFRAME_PROFILES = {profile.profile_id for profile in get_timeframe_profiles()}
ALLOWED_RR_PROFILES = {*SUPPORTED_TP_MODELS, "TIME_BASED_EXIT"}
ALLOWED_ADAPTER_MODES = {"MOCK", "BITGET_LIVE"}


def _adapter_mode_from_env() -> str:
    """Startup default for adapter_mode, read from ADAPTER_MODE. Dashboard
    changes via PATCH /api/settings still apply on top of this for the life
    of the running process."""
    raw = os.getenv("ADAPTER_MODE", "").strip().upper()
    if not raw:
        return ExchangeMode.MOCK.value
    if raw not in ALLOWED_ADAPTER_MODES:
        logger.warning("ADAPTER_MODE=%r is not one of %s; defaulting to MOCK", raw, sorted(ALLOWED_ADAPTER_MODES))
        return ExchangeMode.MOCK.value
    return raw


def _positive_number_from_env(env_var: str, default: str = "") -> str:
    """Startup default for a positive-number setting (risk_amount_per_trade,
    max_leverage, ...), read from env_var. Same validation PATCH /api/settings
    already applies (must be a number > 0); falls back to default if unset or
    invalid. A dashboard PATCH /api/settings still overrides this for the
    life of the running process."""
    raw = os.getenv(env_var, "").strip()
    if not raw:
        return default
    try:
        if float(raw) <= 0:
            raise ValueError
    except ValueError:
        logger.warning("%s=%r is not a positive number; ignoring", env_var, raw)
        return default
    return raw


DEFAULT_SETTINGS = {
    "default_timeframe_profile": "DEFAULT_16_12_8",
    "default_backtesting_profile": FROZEN_VISIBLE_PROFILE_ID,
    # active_strategy_profile controls all live/backtest execution.
    # Persists across restarts. Must be one of the allowed strategy profiles.
    "active_strategy_profile": FROZEN_VISIBLE_PROFILE_ID,
    "selected_rr_profile": "RR_1_5",
    "time_exit_minutes": "30",
    "refresh_interval_seconds": "15",
    "paper_mode_display": True,
    "api_base_url": "",
    "monitored_timeframes": ["16M", "12M", "8M", "1M"],
    "max_open_trades": 1,
    "starting_balance": "",
    "max_daily_loss": "500",
    "max_weekly_loss": "1500",
    "max_leverage": _positive_number_from_env("MAX_LEVERAGE"),
    "risk_amount_per_trade": _positive_number_from_env("DEFAULT_RISK_AMOUNT"),
    "adapter_mode": _adapter_mode_from_env(),
    "live_trading_enabled": False,
    "trading_mode": TradeMode.OFF.value,
    "environment_lock_verified": "NO",
    "active_account_id": "",
    # Persists the user's intent ("Start Monitoring" was clicked and not yet
    # stopped) across process restarts/redeploys, so the polling loop can be
    # auto-resumed on boot instead of silently staying off until someone
    # notices and clicks Start again. See bootstrap_live_trading_from_env /
    # resume_monitoring_if_enabled in monitoring.py.
    "monitoring_enabled": False,
}


def _reapply_env_overrides(loaded: dict[str, object]) -> dict[str, object]:
    """ADAPTER_MODE, when explicitly set, always wins over whatever is
    persisted (database row or JSON file) and is re-applied on every
    process start - not just the very first time a row is seeded.

    Without this, a value written before ADAPTER_MODE was set (or before
    it was changed) permanently shadows it: {**DEFAULT_SETTINGS, **saved}
    always prefers the persisted value once any row exists, so setting
    e.g. ADAPTER_MODE=BITGET_LIVE in Railway after the database already
    had an adapter_mode=MOCK row from an earlier deploy did nothing -
    confirmed by reproducing exactly that sequence locally. ADAPTER_MODE
    is treated as an infrastructure-level baseline that should always win,
    by design - this is the one exception, not the general pattern.

    DEFAULT_RISK_AMOUNT / MAX_LEVERAGE used to be re-applied here the same
    way, every load, every restart - which meant a dashboard PATCH
    /api/settings change to risk_amount_per_trade or max_leverage could
    never survive a restart as long as the matching env var stayed set: it
    got silently overwritten back to the env var's value and that
    overwritten value was then written back to the database, destroying
    the user's saved choice rather than just shadowing it for one process
    lifetime. DEFAULT_SETTINGS already seeds both of these from their env
    vars on the very first run (before any row exists) via
    _positive_number_from_env() above - that's the only place they should
    apply. A dashboard-saved value must win after that, including a
    dashboard-saved value that happens to equal the env var's default.
    """
    adapter_mode_env = os.getenv("ADAPTER_MODE", "").strip().upper()
    if adapter_mode_env in ALLOWED_ADAPTER_MODES and loaded.get("adapter_mode") != adapter_mode_env:
        logger.info("ADAPTER_MODE=%s overrides persisted adapter_mode=%r", adapter_mode_env, loaded.get("adapter_mode"))
        loaded["adapter_mode"] = adapter_mode_env
    return loaded


def load_settings() -> dict[str, object]:
    db_settings = read_all_settings()
    if db_settings is not None:
        logger.info("load_settings: read %d row(s) from the database; adapter_mode=%r", len(db_settings), db_settings.get("adapter_mode"))
        if not db_settings:
            # Database reachable but empty: first run. Seed from
            # DEFAULT_SETTINGS, which already incorporates ADAPTER_MODE /
            # DEFAULT_RISK_AMOUNT / MAX_LEVERAGE env vars where set.
            seeded = _reapply_env_overrides(dict(DEFAULT_SETTINGS))
            write_settings(seeded)
            logger.info("load_settings: first run, seeded adapter_mode=%r", seeded["adapter_mode"])
            return seeded
        result = _reapply_env_overrides(_validated_settings(db_settings))
        if result != db_settings:
            write_settings(result)
        logger.info("load_settings: final adapter_mode=%r (source=database, ADAPTER_MODE env=%r)", result["adapter_mode"], os.getenv("ADAPTER_MODE"))
        return result
    logger.info("load_settings: database unavailable, falling back to %s", SETTINGS_PATH)
    if not SETTINGS_PATH.exists():
        return _reapply_env_overrides(dict(DEFAULT_SETTINGS))
    try:
        saved = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _reapply_env_overrides(dict(DEFAULT_SETTINGS))
    result = _reapply_env_overrides(_validated_settings(saved))
    logger.info("load_settings: final adapter_mode=%r (source=json file, ADAPTER_MODE env=%r)", result["adapter_mode"], os.getenv("ADAPTER_MODE"))
    return result


def _validated_settings(saved: dict[str, object]) -> dict[str, object]:
    loaded = {**DEFAULT_SETTINGS, **{key: value for key, value in saved.items() if key in DEFAULT_SETTINGS}}
    # Validate strategy profile selections — reject unknown values.
    if loaded["default_backtesting_profile"] not in ALLOWED_STRATEGY_PROFILES:
        loaded["default_backtesting_profile"] = FROZEN_VISIBLE_PROFILE_ID
    if loaded["active_strategy_profile"] not in ALLOWED_STRATEGY_PROFILES:
        loaded["active_strategy_profile"] = FROZEN_VISIBLE_PROFILE_ID
    if loaded["default_backtesting_profile"] not in FROZEN_VISIBLE_PROFILE_IDS:
        loaded["default_backtesting_profile"] = FROZEN_VISIBLE_PROFILE_ID
    if loaded["active_strategy_profile"] not in FROZEN_VISIBLE_PROFILE_IDS:
        loaded["active_strategy_profile"] = FROZEN_VISIBLE_PROFILE_ID
    if loaded["default_timeframe_profile"] not in ALLOWED_TIMEFRAME_PROFILES:
        loaded["default_timeframe_profile"] = "DEFAULT_16_12_8"
    if loaded["selected_rr_profile"] not in ALLOWED_RR_PROFILES:
        loaded["selected_rr_profile"] = "RR_1_5"
    return loaded


def save_settings(settings: dict[str, object]) -> None:
    if write_settings(settings):
        return
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(json.dumps(settings, indent=2), encoding="utf-8")


def bootstrap_live_trading_from_env(state: "ApiState") -> None:
    """If LIVE_TRADING_ENABLED=true, run the same checks
    settings.py:_validate_live_trading_candidate requires before a dashboard
    PATCH /api/settings would accept live_trading_enabled=true, and only set
    it if every one passes. This does NOT arm live execution - that still
    requires the separate, explicit POST /api/bitget/mode "ENABLE LIVE"
    confirmation flow (bitget_environment.live_armed). Never raises - a
    startup convenience, not a requirement for the app to come up."""
    if os.getenv("LIVE_TRADING_ENABLED", "").strip().lower() != "true":
        return
    try:
        if state.bitget_environment.last_connection_result is None:
            try:
                state.bitget_environment.test_connection(symbol="BTCUSDT")
            except Exception as exc:
                logger.warning("LIVE_TRADING_ENABLED=true but the startup Bitget connection check failed: %s", exc)
                return
        if not any(pair.get("enabled") for pair in state.monitored_pairs.values()):
            logger.warning("LIVE_TRADING_ENABLED=true but no monitored pair is enabled; leaving live_trading_enabled=False")
            return
        try:
            if float(str(state.settings.get("risk_amount_per_trade", "0") or "0")) <= 0:
                raise ValueError
        except ValueError:
            logger.warning("LIVE_TRADING_ENABLED=true but risk_amount_per_trade is not set; leaving live_trading_enabled=False until it is configured")
            return
        state.settings["live_trading_enabled"] = True
        save_settings(state.settings)
        logger.info("LIVE_TRADING_ENABLED=true and all live-trading preconditions passed; live_trading_enabled is now True")
    except Exception:
        logger.exception("bootstrap_live_trading_from_env failed unexpectedly; leaving live_trading_enabled=False")


def _default_pairs() -> dict[str, dict[str, object]]:
    return {
        symbol: {"symbol": symbol, "enabled": True, "leverage": leverage}
        for symbol, leverage in DEFAULT_MONITORED_PAIRS.items()
    }


def load_pairs() -> dict[str, dict[str, object]]:
    if not PAIRS_PATH.exists():
        return _default_pairs()
    try:
        saved = json.loads(PAIRS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _default_pairs()
    pairs: dict[str, dict[str, object]] = {}
    for item in saved if isinstance(saved, list) else saved.values():
        symbol = str(item.get("symbol", "")).upper()
        if symbol:
            # leverage is None for any pair with no per-pair value ever saved -
            # that's the signal live_automation.py's _effective_max_leverage
            # uses to fall back to the global max_leverage setting.
            pairs[symbol] = {"symbol": symbol, "enabled": bool(item.get("enabled", True)), "leverage": item.get("leverage")}
    return pairs or _default_pairs()


def load_live_accounts() -> dict[str, dict[str, object]]:
    accounts, _, _ = load_vault()
    return accounts


def load_encrypted_live_credentials() -> dict[str, dict[str, str]]:
    _, encrypted, _ = load_vault()
    return encrypted


def load_active_live_account_id() -> str | None:
    _, _, active_account_id = load_vault()
    return active_account_id


def save_pairs(pairs: dict[str, dict[str, object]]) -> None:
    PAIRS_PATH.parent.mkdir(parents=True, exist_ok=True)
    PAIRS_PATH.write_text(json.dumps(tuple(pairs.values()), indent=2), encoding="utf-8")


def require_local_access() -> bool:
    """Placeholder dependency for future authentication middleware."""
    return True


@dataclass(slots=True)
class ApiState:
    exchange_adapter: BitgetExchangeAdapter = field(default_factory=BitgetExchangeAdapter)
    bitget_environment: BitgetEnvironmentService = field(default_factory=BitgetEnvironmentService)
    strategy_engine: StrategyEngine = field(default_factory=StrategyEngine)
    risk_engine: RiskEngine = field(default_factory=RiskEngine)
    execution_service: ExecutionService = field(default_factory=ExecutionService)
    monitored_pairs: dict[str, dict[str, object]] = field(default_factory=load_pairs)
    settings: dict[str, object] = field(default_factory=load_settings)
    # In-progress (ACTIVE) and pending-execution (ENTRY_READY) setups only -
    # capped at MAX_IN_PROGRESS_SETUPS by live_setup_detection.py. A setup
    # leaves this dict the moment it resolves: into invalidated_setups, into
    # completed_setups, or (for a real ENTRY_READY trade) into completed_setups
    # once live automation actually submits it (see live_automation.py
    # _process_setup).
    setups: dict[str, object] = field(default_factory=dict)
    # Append-only, newest-first ordered lists (see live_setup_detection.py's
    # _append_resolved_setup) - a setup is only ever inserted once (index 0),
    # and only ever removed by capping at MAX_TRACKED_SETUP_ATTEMPTS (the
    # oldest, at the end of the list). Never re-sorted or rebuilt on a poll
    # cycle - the list is byte-for-byte identical between polls unless a new
    # completion/invalidation just happened. Kept apart from `setups` so a
    # burst of in-progress attempts can never push completed/invalidated
    # history out, and vice versa.
    invalidated_setups: list[object] = field(default_factory=list)
    completed_setups: list[object] = field(default_factory=list)
    # Every setup_id that has ever resolved (moved into completed_setups or
    # invalidated_setups) for the life of this process - never shrinks except
    # via the manual Clear History endpoint (setup_history_store.wipe_setup_history).
    # Deliberately NOT capped at 100 like the visible lists above: once a
    # setup_id is evicted from the visible list it must still be permanently
    # blocked from being re-created by the live detection funnel re-deriving
    # the same swing from its rolling candle buffer on a later poll - see
    # live_setup_detection.py's _apply_one_attempt_trace.
    resolved_setup_ids: set[str] = field(default_factory=set)
    # Permanent swing-level dedup cache (symbol+direction+swing timestamp -
    # see setup_models.build_swing_dedup_key), checked BEFORE the live
    # detection funnel ever runs for a swing (live_setup_detection.py's
    # detect_live_setups_for_symbol). Starts empty on every process boot and
    # is cleared on every manual admin history clear
    # (setup_history_store.wipe_setup_history), so fresh signal is never
    # silently blocked by a prior session's resolved keys.
    resolved_swing_keys: set[str] = field(default_factory=set)
    # UTC timestamp when each resolved_swing_keys entry was added, keyed by
    # the same dedup string. Used by live_setup_detection._is_resolved_swing_key
    # to expire entries after RESOLVED_KEY_EXPIRY_MINUTES so a swing is not
    # permanently blocked within a long-running session.
    resolved_swing_key_timestamps: dict[str, datetime] = field(default_factory=dict)
    # Restored from setup_history_store.json on process boot when present, and
    # set by the manual Clear History endpoint.
    history_cleared_at: datetime | None = None
    setup_history: dict[str, list[dict[str, object]]] = field(default_factory=dict)
    # Keyed by swing_16m_id so Setup Radar can correlate a COMPLETED attempt
    # row to the matching real trade candidate that the shared strategy
    # funnel found but live_setup_detection.py skipped for no longer being
    # fresh (see _stale_trade_candidates / _record_stale_skip). Capped the
    # same way state.setups is - see _evict_oldest_stale_skips.
    stale_trade_skips: dict[str, dict[str, object]] = field(default_factory=dict)
    signals: dict[str, object] = field(default_factory=dict)
    trade_plans: dict[str, object] = field(default_factory=dict)
    uploaded_csvs: dict[str, dict[str, object]] = field(default_factory=dict)
    uploaded_csv_contents: dict[str, str] = field(default_factory=dict)
    backtest_runs: dict[str, dict[str, object]] = field(default_factory=dict)
    market_polls: dict[str, dict[str, object]] = field(default_factory=dict)
    live_candles: dict[str, tuple[object, ...]] = field(default_factory=dict)
    live_timeframe_candles: dict[str, dict[int, tuple[object, ...]]] = field(default_factory=dict)
    # One persistent FVGDetectionEngine per (symbol, timeframe minutes), keyed
    # "SYMBOL:MINUTES" - reused across every monitoring poll instead of a fresh
    # engine per call, so each FVG (deterministic fvg_id) is only ever new to
    # its engine's store once. See live_setup_detection.py's _fvg_engine_for.
    live_fvg_engines: dict[str, FVGDetectionEngine] = field(default_factory=dict)
    live_setup_detection: dict[str, object] = field(
        default_factory=lambda: {
            "last_run_at": "None",
            "last_status": "IDLE",
            "last_blocked_reason": "None",
            "last_error": "None",
            "created_setup_count": 0,
            "processed_trade_keys": [],
            "latest_funnel": {},
            "latest_trade_candidate": {},
            # Observability for trade candidates the shared strategy funnel
            # found but the live freshness gate discarded as stale (swing
            # timestamp older than STALENESS_WINDOW_MINUTES) - e.g. after a
            # monitoring outage. This makes the gap visible instead of silent.
            "stale_trade_candidates_skipped_total": 0,
            "last_stale_skip": {},
        }
    )
    live_automation: dict[str, object] = field(
        default_factory=lambda: {
            "enabled": True,
            "last_run_at": "None",
            "last_status": "IDLE",
            "last_blocked_reason": "None",
            "last_error": "None",
            "processed_setup_ids": [],
            "executed_trade_plan_ids": [],
            "attempts": [],
        }
    )
    encrypted_live_credentials: dict[str, dict[str, str]] = field(default_factory=load_encrypted_live_credentials)
    live_accounts: dict[str, dict[str, object]] = field(default_factory=load_live_accounts)
    active_live_account_id: str | None = field(default_factory=load_active_live_account_id)
    monitoring: dict[str, object] = field(
        default_factory=lambda: {
            "active": False,
            "session_id": "None",
            "started_at": "None",
            "stopped_at": "None",
            "last_error": "None",
            "source": "NONE",
        }
    )

    def seed(self) -> None:
        return

    def report_paths(self) -> dict[str, Path]:
        root = Path(__file__).resolve().parents[2]
        return {
            "execution_validation_report.html": root / "arjiobot" / "execution" / "reports" / "execution_validation_report.html",
            "exchange_adapter_validation_report.html": root / "arjiobot" / "exchange" / "reports" / "exchange_adapter_validation_report.html",
            "backend_api_validation_report.html": root / "arjiobot" / "api" / "reports" / "backend_api_validation_report.html",
        }


state = ApiState()


def get_state() -> ApiState:
    return state


def reset_state() -> ApiState:
    global state
    state = ApiState()
    return state


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
