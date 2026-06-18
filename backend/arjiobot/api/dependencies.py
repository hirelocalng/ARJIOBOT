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
from arjiobot.backtesting.research_profiles import get_strategy_profiles
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
FROZEN_VISIBLE_PROFILE_ID = "PROFILE_RECOVERED_HIGH_WINRATE"
FROZEN_VISIBLE_PROFILE_IDS = {"PROFILE_RECOVERED_HIGH_WINRATE", "PROFILE_2"}

# Allowed values for each profile setting (used in load_settings validation).
ALLOWED_STRATEGY_PROFILES = {profile.profile_id for profile in get_strategy_profiles()}
ALLOWED_TIMEFRAME_PROFILES = {"DEFAULT_16_12_8", "PROFILE_15_10_5"}
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
}


def _reapply_env_overrides(loaded: dict[str, object]) -> dict[str, object]:
    """ADAPTER_MODE / DEFAULT_RISK_AMOUNT / MAX_LEVERAGE, when explicitly
    set, always win over whatever is persisted (database row or JSON file)
    and are re-applied on every process start - not just the very first
    time a row is seeded.

    Without this, a value written before one of these env vars was set (or
    before it was changed) permanently shadows it: {**DEFAULT_SETTINGS,
    **saved} always prefers the persisted value once any row exists, so
    setting e.g. ADAPTER_MODE=BITGET_LIVE in Railway after the database
    already had an adapter_mode=MOCK row from an earlier deploy did
    nothing - confirmed by reproducing exactly that sequence locally.

    Trade-off, stated plainly: a dashboard PATCH /api/settings change to
    one of these three keys only lasts for the life of the running
    process if the matching env var is set - the env var reasserts itself
    on every restart. Treating these specific env vars as the
    infrastructure-level baseline (re-applied every boot) is what actually
    fixes "I set the env var but it's stuck on the old value."
    """
    adapter_mode_env = os.getenv("ADAPTER_MODE", "").strip().upper()
    if adapter_mode_env in ALLOWED_ADAPTER_MODES and loaded.get("adapter_mode") != adapter_mode_env:
        logger.info("ADAPTER_MODE=%s overrides persisted adapter_mode=%r", adapter_mode_env, loaded.get("adapter_mode"))
        loaded["adapter_mode"] = adapter_mode_env
    risk_env = _positive_number_from_env("DEFAULT_RISK_AMOUNT")
    if risk_env and loaded.get("risk_amount_per_trade") != risk_env:
        logger.info("DEFAULT_RISK_AMOUNT=%s overrides persisted risk_amount_per_trade=%r", risk_env, loaded.get("risk_amount_per_trade"))
        loaded["risk_amount_per_trade"] = risk_env
    leverage_env = _positive_number_from_env("MAX_LEVERAGE")
    if leverage_env and loaded.get("max_leverage") != leverage_env:
        logger.info("MAX_LEVERAGE=%s overrides persisted max_leverage=%r", leverage_env, loaded.get("max_leverage"))
        loaded["max_leverage"] = leverage_env
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


def load_pairs() -> dict[str, dict[str, object]]:
    if not PAIRS_PATH.exists():
        return {"BTCUSDT": {"symbol": "BTCUSDT", "enabled": True}}
    try:
        saved = json.loads(PAIRS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"BTCUSDT": {"symbol": "BTCUSDT", "enabled": True}}
    pairs: dict[str, dict[str, object]] = {}
    for item in saved if isinstance(saved, list) else saved.values():
        symbol = str(item.get("symbol", "")).upper()
        if symbol:
            pairs[symbol] = {"symbol": symbol, "enabled": bool(item.get("enabled", True))}
    return pairs or {"BTCUSDT": {"symbol": "BTCUSDT", "enabled": True}}


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
    setups: dict[str, object] = field(default_factory=dict)
    setup_history: dict[str, list[dict[str, object]]] = field(default_factory=dict)
    signals: dict[str, object] = field(default_factory=dict)
    trade_plans: dict[str, object] = field(default_factory=dict)
    uploaded_csvs: dict[str, dict[str, object]] = field(default_factory=dict)
    uploaded_csv_contents: dict[str, str] = field(default_factory=dict)
    backtest_runs: dict[str, dict[str, object]] = field(default_factory=dict)
    market_polls: dict[str, dict[str, object]] = field(default_factory=dict)
    live_candles: dict[str, tuple[object, ...]] = field(default_factory=dict)
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
