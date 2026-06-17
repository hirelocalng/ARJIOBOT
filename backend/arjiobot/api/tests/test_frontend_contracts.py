"""Frontend integration contract checks for API-backed dashboard flows."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]


def test_frontend_backtesting_sends_selected_profile_and_fetches_run_details() -> None:
    source = (ROOT / "frontend" / "src" / "pages" / "Backtesting.tsx").read_text(encoding="utf-8")
    constants = (ROOT / "frontend" / "src" / "utils" / "constants.ts").read_text(encoding="utf-8")

    assert "profile_id: profile" in source
    assert "selected_strategy_profile: profile" in source
    assert "Profile Lock Verification" in source
    assert "selected_profile_actively_used_by_backend" in source
    assert "selected_profile_id" in source
    assert "applied_profile_id" in source
    assert "upload_id: uploadId" in source
    assert "timeframe_profile: timeframeProfile" in source
    assert "starting_balance: startingBalance" in source
    assert "risk_per_trade: risk" in source
    assert "research_expansion_min: researchExpansionMin" in source
    assert "research_expansion_max: researchExpansionMax" in source
    assert "research_retrace_window_8m_candles: researchRetraceWindow" in source
    assert "research_tp_model: researchTpModel" in source
    assert "research_main_fvg_match_mode: researchMainFvgMatchMode" in source
    assert "research_main_fvg_match_window_candles: researchMainFvgMatchWindow" in source
    assert "uploadCsv(file, selectedSymbol)" in source
    assert "getBacktestRun(run.run_id)" in source
    assert "row.profile_id ?? DEFAULT_PRODUCTION_PROFILE" in source
    assert "DEFAULT_PRODUCTION_PROFILE" in source
    assert "row.symbol" in source
    assert "strategy_funnel" in source
    assert "PROFILE_F_VOLUME" in constants
    assert "PROFILE_G_CODEX_OPTIMIZED" in constants
    assert "PROFILE_RECOVERED_HIGH_WINRATE" in constants
    assert "QUARANTINED_BACKTESTING_PROFILES" in constants
    assert "DEFAULT_PRODUCTION_PROFILE = 'PROFILE_RECOVERED_HIGH_WINRATE'" in constants
    assert "PROFILE_FREEZE_WARNING" in constants
    assert "PROFILE_FREEZE_WARNING" in source
    assert "DEFAULT_16_12_8" in constants
    assert "PROFILE_15_10_5" in constants
    assert "PROFILE_30_16_8" in constants
    assert "PROFILE_12_8_4" in constants
    assert "PROFILE_8_4_2" in constants
    assert "PROFILE_20_15_10" not in constants
    assert "RR_1_5" in constants
    assert "LEG_TARGET_RESEARCH" in source
    assert "LEGACY_EXPANSION_OR_NEXT_CANDLE" in source
    assert "setTimeframeProfile('PROFILE_15_10_5')" in source
    assert "RR_" + "1_1" not in constants


def test_frontend_settings_saves_persistent_fields_and_syncs_loaded_settings() -> None:
    source = (ROOT / "frontend" / "src" / "pages" / "Settings.tsx").read_text(encoding="utf-8")

    assert "default_backtesting_profile: backtestingProfile" in source
    assert "Trading Mode" in source
    assert "switchBitgetMode" in source
    assert "ENABLE LIVE" in source
    assert "Environment lock verified" in source
    assert "API credentials are managed only on the Accounts page" in source
    assert "testLiveConnection" in source
    assert "DRY_RUN_PREVIEW" in source
    assert "DEMO" not in source
    assert "paptrading" not in source
    assert "selected_rr_profile: tpModel" in source
    assert "refresh_interval_seconds: refreshInterval" in source
    assert "paper_mode_display: paperModeDisplay" in source
    assert "api_base_url: apiBaseUrl" in source
    assert "setBacktestingProfile(settings.default_backtesting_profile" in source


def test_trading_control_center_exposes_real_dry_run_preview_action() -> None:
    source = (ROOT / "frontend" / "src" / "pages" / "TradingControlCenter.tsx").read_text(encoding="utf-8")

    assert "dryRunPreview(previewPayload)" in source
    assert "Generate Dry-Run Preview" in source
    assert "selected_profile_id: selectedProfile" in source
    assert "applied_profile_id: selectedProfile" in source
    assert "risk_amount" in source
    assert "selected_max_leverage" in source
    assert "Sanitized Bitget Payload" in source


def test_frontend_api_client_handles_nonstandard_error_payloads() -> None:
    source = (ROOT / "frontend" / "src" / "api" / "client.ts").read_text(encoding="utf-8")

    assert "await response.text()" in source
    assert "Backend returned empty response" in source
    assert "Backend returned invalid JSON" in source
    assert "payload.error?.message" in source
    assert "nested.error?.message" in source
    assert "typeof payload.detail === 'string'" in source
    assert "timeoutMs" in source


def test_frontend_live_bitget_checks_use_longer_timeout() -> None:
    bitget = (ROOT / "frontend" / "src" / "api" / "bitget.ts").read_text(encoding="utf-8")
    accounts = (ROOT / "frontend" / "src" / "api" / "accounts.ts").read_text(encoding="utf-8")
    pairs = (ROOT / "frontend" / "src" / "api" / "pairs.ts").read_text(encoding="utf-8")

    assert "/api/bitget/connection/live" in bitget
    assert "timeoutMs: 35000" in bitget
    assert "/test-connection" in accounts
    assert "timeoutMs: 35000" in accounts
    assert "/api/monitoring/start" in pairs
    assert "timeoutMs: 35000" in pairs


def test_frontend_upload_sends_selected_symbol_form_field() -> None:
    source = (ROOT / "frontend" / "src" / "api" / "backtesting.ts").read_text(encoding="utf-8")

    assert "selected_symbol" in source
    assert "selectedSymbol.trim().toUpperCase()" in source


def test_frontend_backtest_run_uses_longer_timeout() -> None:
    source = (ROOT / "frontend" / "src" / "api" / "backtesting.ts").read_text(encoding="utf-8")

    assert "/api/backtesting/run" in source
    assert "timeoutMs: 120000" in source

