"""API dependency and in-memory service wiring."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from arjiobot.exchange.bitget_adapter import BitgetExchangeAdapter
from arjiobot.exchange.bitget_environment import BitgetEnvironmentService, TradeMode
from arjiobot.exchange.exchange_models import ExchangeMode
from arjiobot.execution.execution_service import ExecutionService
from arjiobot.backtesting.research_profiles import get_strategy_profiles
from arjiobot.exchange.account_vault import load_vault
from arjiobot.risk.risk_engine import RiskEngine
from arjiobot.risk.rr_profiles import SUPPORTED_TP_MODELS
from arjiobot.strategy.strategy_engine import StrategyEngine

ROOT = Path(__file__).resolve().parents[3]
SETTINGS_PATH = ROOT / "data" / "runtime_settings.json"
PAIRS_PATH = ROOT / "data" / "runtime_pairs.json"
FROZEN_VISIBLE_PROFILE_ID = "PROFILE_RECOVERED_HIGH_WINRATE"
FROZEN_VISIBLE_PROFILE_IDS = {"PROFILE_RECOVERED_HIGH_WINRATE", "PROFILE_2"}

# Allowed values for each profile setting (used in load_settings validation).
ALLOWED_STRATEGY_PROFILES = {profile.profile_id for profile in get_strategy_profiles()}
ALLOWED_TIMEFRAME_PROFILES = {"DEFAULT_16_12_8", "PROFILE_15_10_5"}
ALLOWED_RR_PROFILES = {*SUPPORTED_TP_MODELS, "TIME_BASED_EXIT"}

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
    "max_leverage": "",
    "risk_amount_per_trade": "",
    "adapter_mode": ExchangeMode.MOCK.value,
    "live_trading_enabled": False,
    "trading_mode": TradeMode.OFF.value,
    "environment_lock_verified": "NO",
    "active_account_id": "",
}


def load_settings() -> dict[str, object]:
    if not SETTINGS_PATH.exists():
        return dict(DEFAULT_SETTINGS)
    try:
        saved = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return dict(DEFAULT_SETTINGS)
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
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(json.dumps(settings, indent=2), encoding="utf-8")


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
