"""Backtesting route tests."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

from arjiobot.api.routes import backtesting as backtesting_routes
from arjiobot.api.tests.helpers import client

REPO_DATA_DIR = Path(__file__).resolve().parents[4] / "data"


def test_csv_upload_rejects_files_over_the_size_limit(monkeypatch) -> None:
    monkeypatch.setattr(backtesting_routes, "MAX_CSV_UPLOAD_BYTES", 10)
    api = client()
    csv = "timestamp,open,high,low,close,volume\n2026-01-01T00:00:00Z,1,2,1,2,10\n"

    response = api.post("/api/backtesting/upload-csv", files={"file": ("BTCUSDT-1m-2026-01.csv", csv, "text/csv")})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "CSV_UPLOAD_TOO_LARGE"
    assert "exceeds" in response.json()["error"]["message"]


def test_csv_upload_and_backtest_run_routes() -> None:
    api = client()
    profiles = api.get("/api/backtesting/profiles").json()["data"]
    csv = "timestamp,open,high,low,close,volume\n2026-01-01T00:00:00Z,1,2,1,2,10\n"
    upload = api.post("/api/backtesting/upload-csv", files={"file": ("BTCUSDT-1m-2026-01.csv", csv, "text/csv")}).json()["data"]
    run = api.post("/api/backtesting/run", json=_run_payload(upload["upload_id"], symbol="BTCUSDT", profile_id="PROFILE_F_VOLUME")).json()["data"]

    assert {profile["profile_id"] for profile in profiles} == {
        "STRICT_PROFILE",
        "PROFILE_F_VOLUME",
        "PROFILE_F_BALANCED",
        "PROFILE_F_SELECTIVE",
        "PROFILE_G_CODEX_OPTIMIZED",
        "PROFILE_RECOVERED_HIGH_WINRATE",
        "PROFILE_2",
    }
    assert upload["filename"] == "BTCUSDT-1m-2026-01.csv"
    assert upload["candles_loaded"] == 1
    assert upload["detected_symbol"] == "BTCUSDT"
    assert upload["candle_hash"]
    assert run["run_id"] == "btr_0001"
    assert run["upload_id"] == upload["upload_id"]
    assert run["profile_id"] == "PROFILE_F_VOLUME"
    assert run["selected_strategy_profile"] == "PROFILE_F_VOLUME"
    assert run["symbol"] == "BTCUSDT"
    assert run["status"] == "COMPLETED"
    assert run["report"]["summary"]["api_run_id"] == run["run_id"]
    assert run["report"]["summary"]["source_run_id"]
    assert run["report"]["summary"]["strategy_source"] == "REAL_STRATEGY_PIPELINE"
    assert run["report"]["summary"]["profile_applied"]["expansion_min"] == 1.0
    assert run["report"]["summary"]["selected_strategy_profile"] == "PROFILE_F_VOLUME"
    assert run["cache_key"]
    assert api.get("/api/backtesting/runs").json()["data"][0]["run_id"] == run["run_id"]
    assert api.get(f"/api/backtesting/runs/{run['run_id']}/trades").json()["success"]
    assert api.get(f"/api/backtesting/runs/{run['run_id']}/equity").json()["data"]
    assert api.get(f"/api/backtesting/runs/{run['run_id']}/report").json()["data"]["summary"]


def test_selected_tp_model_is_applied_to_backtest_report() -> None:
    api = client()
    csv = "timestamp,open,high,low,close,volume\n2026-01-01T00:00:00Z,1,2,1,2,10\n"
    upload = api.post("/api/backtesting/upload-csv", files={"file": ("BTCUSDT-1m.csv", csv, "text/csv")}).json()["data"]

    rr_run = api.post(
        "/api/backtesting/run",
        json={**_run_payload(upload["upload_id"], symbol="BTCUSDT", profile_id="PROFILE_2", timeframe_profile="PROFILE_15_10_5"), "selected_tp_model": "RR_1_5"},
    ).json()["data"]
    leg_run = api.post(
        "/api/backtesting/run",
        json={**_run_payload(upload["upload_id"], symbol="BTCUSDT", profile_id="PROFILE_2", timeframe_profile="PROFILE_15_10_5"), "selected_tp_model": "LEG_TARGET_RESEARCH"},
    ).json()["data"]

    assert rr_run["profile_applied"]["selected_tp_model"] == "RR_1_5"
    assert rr_run["profile_applied"]["applied_tp_model"] == "RR_1_5"
    assert leg_run["profile_applied"]["selected_tp_model"] == "LEG_TARGET_RESEARCH"
    assert leg_run["profile_applied"]["applied_tp_model"] == "LEG_TARGET_RESEARCH"
    assert leg_run["report"]["summary"]["selected_tp_model"] == "LEG_TARGET_RESEARCH"
    assert leg_run["report"]["summary"]["applied_tp_model"] == "LEG_TARGET_RESEARCH"


def test_all_selectable_profiles_stay_profile_locked() -> None:
    api = client()
    csv = "timestamp,open,high,low,close,volume\n2026-01-01T00:00:00Z,1,2,1,2,10\n"
    upload = api.post("/api/backtesting/upload-csv", files={"file": ("BTCUSDT-1m.csv", csv, "text/csv")}).json()["data"]

    for profile_id in (
        "STRICT_PROFILE",
        "PROFILE_F_VOLUME",
        "PROFILE_F_BALANCED",
        "PROFILE_F_SELECTIVE",
        "PROFILE_G_CODEX_OPTIMIZED",
        "PROFILE_RECOVERED_HIGH_WINRATE",
        "PROFILE_2",
    ):
        timeframe_profile = "PROFILE_15_10_5" if profile_id in {"PROFILE_RECOVERED_HIGH_WINRATE", "PROFILE_2"} else "DEFAULT_16_12_8"
        payload = {
            **_run_payload(upload["upload_id"], symbol="BTCUSDT", profile_id=profile_id, timeframe_profile=timeframe_profile),
            "selected_strategy_profile": profile_id,
        }
        response = api.post("/api/backtesting/run", json=payload)

        assert response.status_code == 200, profile_id
        run = response.json()["data"]
        lock = run["profile_lock_verification"]
        summary_lock = run["report"]["summary"]["profile_lock_verification"]
        assert run["profile_id"] == profile_id
        assert run["selected_profile_id"] == profile_id
        assert run["applied_profile_id"] == profile_id
        assert lock["profile_lock_status"] == "PASSED"
        assert lock["selected_profile_actively_used_by_backend"] == "YES"
        assert summary_lock["profile_lock_status"] == "PASSED"
        assert run["cache_key"] != ""


def test_csv_upload_accepts_native_binance_kline_export() -> None:
    api = client()
    csv = "1767225600000,100,110,90,105,12,1767225659999,1200,8,6,600,0\n"

    upload = api.post("/api/backtesting/upload-csv", files={"file": ("BTCUSDT-1m.csv", csv, "text/csv")}).json()["data"]

    assert upload["filename"] == "BTCUSDT-1m.csv"
    assert upload["candles_loaded"] == 1
    assert upload["detected_symbol"] == "BTCUSDT"


def test_csv_upload_accepts_pair_agnostic_binance_headerless_exports() -> None:
    api = client()
    csv = "1767225600000,100,110,90,105,12,1767225659999,1200,8,6,600,0\n"

    for symbol in ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "BNBUSDT", "DOGEUSDT", "ADAUSDT", "TONUSDT", "PEPEUSDT"):
        upload = api.post("/api/backtesting/upload-csv", files={"file": (f"{symbol}-1m-2024-01.csv", csv, "text/csv")}).json()["data"]

        assert upload["detected_symbol"] == symbol
        assert upload["candles_loaded"] == 1


def test_csv_upload_normalizes_lowercase_binance_filename() -> None:
    api = client()
    csv = "1767225600000,100,110,90,105,12,1767225659999,1200,8,6,600,0\n"

    upload = api.post("/api/backtesting/upload-csv", files={"file": ("ethusdt-1m-2024-01.csv", csv, "text/csv")}).json()["data"]

    assert upload["detected_symbol"] == "ETHUSDT"


def test_csv_upload_accepts_microsecond_epoch_binance_export() -> None:
    api = client()
    csv = "1775001600000000,2105.43,2106.88,2103.63,2104.11,886.0327,1775001659999999,1865485.82,5178,651.44,1371681.89,0\n"

    upload = api.post("/api/backtesting/upload-csv", files={"file": ("ETHUSDT-1m-2026-04.csv", csv, "text/csv")}).json()["data"]

    assert upload["detected_symbol"] == "ETHUSDT"
    assert upload["candles_loaded"] == 1
    assert upload["start_time"] == "2026-04-01T00:00:00+00:00"


def test_csv_upload_uses_selected_symbol_when_csv_and_filename_have_no_symbol() -> None:
    api = client()
    csv = "timestamp,open,high,low,close,volume\n2026-01-01T00:00:00Z,1,2,1,2,10\n"

    upload = api.post(
        "/api/backtesting/upload-csv",
        files={"file": ("candles.csv", csv, "text/csv"), "__form": {"selected_symbol": "solusdt"}},
    ).json()["data"]

    assert upload["detected_symbol"] == "SOLUSDT"


def test_backtest_run_uses_profile_f() -> None:
    api = client()
    csv = "timestamp,open,high,low,close,volume\n2026-01-01T00:00:00Z,1,2,1,2,10\n"
    upload = api.post("/api/backtesting/upload-csv", files={"file": ("BTCUSDT-1m-2026-01.csv", csv, "text/csv")}).json()["data"]

    run = api.post("/api/backtesting/run", json=_run_payload(upload["upload_id"], symbol="BTCUSDT", profile_id="PROFILE_F_VOLUME")).json()["data"]

    assert run["profile_id"] == "PROFILE_F_VOLUME"
    assert run["research_mode"] is False
    assert run["run_id"] == "btr_0001"
    assert run["report"]["summary"]["profile_id"] == "PROFILE_F_VOLUME"
    assert run["report"]["summary"]["api_run_id"] == run["run_id"]
    assert run["report"]["summary"]["strategy_funnel"]
    assert api.get("/api/backtesting/runs").json()["data"][0]["profile_id"] == "PROFILE_F_VOLUME"
    assert api.get(f"/api/backtesting/runs/{run['run_id']}").json()["data"]["report"]["summary"]["profile_id"] == "PROFILE_F_VOLUME"
    assert api.get(f"/api/backtesting/runs/{run['run_id']}/report").json()["data"]["summary"]["strategy_funnel"]


def test_backtest_run_includes_bullish_trades_not_just_bearish() -> None:
    """Live monitoring evaluates both directions every poll (live_setup_detection.py
    runs the bearish AND bullish funnels), but this backtest entry point used to only
    ever call the bearish funnel - a backtest could never show a single BUY-side
    trade no matter what data or profile was used. Uses a real month of 1-minute
    candles (not a tiny synthetic fixture) because the synthetic CSVs used elsewhere
    in this file have no real swing/expansion/FVG structure for either direction."""
    api = client()
    csv_text = (REPO_DATA_DIR / "ADAUSDT-1m-2026-04.csv").read_text(encoding="utf-8")
    upload = api.post("/api/backtesting/upload-csv", files={"file": ("ADAUSDT-1m-2026-04.csv", csv_text, "text/csv")}).json()["data"]

    run = api.post("/api/backtesting/run", json=_run_payload(upload["upload_id"], symbol="ADAUSDT", profile_id="PROFILE_2")).json()["data"]
    summary = run["report"]["summary"]

    breakdown = summary["direction_breakdown"]
    assert breakdown["BEARISH"]["trades"] > 0
    assert breakdown["BULLISH"]["trades"] > 0, "bullish trades must appear in the backtest report, matching live monitoring"
    trade_directions = {trade["direction"] for trade in summary["trade_list"]}
    assert trade_directions == {"BEARISH", "BULLISH"}
    assert len(summary["trade_list"]) == breakdown["BEARISH"]["trades"] + breakdown["BULLISH"]["trades"]
    # Combined trade list must be one real chronological account history, not
    # two directions concatenated out of order.
    timestamps = [trade["entry_timestamp"] for trade in summary["trade_list"]]
    assert timestamps == sorted(timestamps)
    assert summary["wins"] + summary["losses"] <= len(summary["trade_list"])


def test_upload_detects_symbols_from_filename_and_symbol_column() -> None:
    api = client()
    btc_csv = "timestamp,open,high,low,close,volume\n2026-01-01T00:00:00Z,1,2,1,2,10\n"
    eth_csv = "timestamp,symbol,open,high,low,close,volume\n2026-01-01T00:00:00Z,ETHUSDT,1,2,1,2,10\n"

    btc = api.post("/api/backtesting/upload-csv", files={"file": ("BTCUSDT-1m-2024-01.csv", btc_csv, "text/csv")}).json()["data"]
    eth = api.post("/api/backtesting/upload-csv", files={"file": ("anything.csv", eth_csv, "text/csv")}).json()["data"]

    assert btc["detected_symbol"] == "BTCUSDT"
    assert eth["detected_symbol"] == "ETHUSDT"
    assert btc["candle_hash"] != eth["candle_hash"]


def test_run_uses_selected_upload_symbol_and_profile_f() -> None:
    api = client()
    eth_csv = "timestamp,open,high,low,close,volume\n2026-01-01T00:00:00Z,10,12,9,11,10\n"
    upload = api.post("/api/backtesting/upload-csv", files={"file": ("ETHUSDT-1m-2024-01.csv", eth_csv, "text/csv")}).json()["data"]

    run = api.post("/api/backtesting/run", json=_run_payload(upload["upload_id"], symbol="ETHUSDT", profile_id="PROFILE_F_VOLUME")).json()["data"]
    detail = api.get(f"/api/backtesting/runs/{run['run_id']}").json()["data"]

    assert run["symbol"] == "ETHUSDT"
    assert run["detected_symbol"] == "ETHUSDT"
    assert run["profile_id"] == "PROFILE_F_VOLUME"
    assert detail["report"]["summary"]["strategy_funnel"]
    assert detail["report"]["summary"]["profile_applied"]["expansion_max"] == 4.0


def test_selected_strategy_profile_overrides_legacy_profile_id_field() -> None:
    api = client()
    csv = "timestamp,open,high,low,close,volume\n2026-01-01T00:00:00Z,1,2,1,2,10\n"
    upload = api.post("/api/backtesting/upload-csv", files={"file": ("BTCUSDT-1m.csv", csv, "text/csv")}).json()["data"]
    payload = _run_payload(upload["upload_id"], symbol="BTCUSDT", profile_id="STRICT_PROFILE")
    payload["selected_strategy_profile"] = "PROFILE_F_BALANCED"

    run = api.post("/api/backtesting/run", json=payload).json()["data"]

    assert run["profile_id"] == "PROFILE_F_BALANCED"
    assert run["selected_strategy_profile"] == "PROFILE_F_BALANCED"
    assert run["profile_applied"]["expansion_min"] == 1.5
    assert run["report"]["summary"]["profile_applied"]["expansion_min"] == 1.5


def test_profile_g_is_selectable_research_backtest_profile() -> None:
    api = client()
    csv = "timestamp,open,high,low,close,volume\n2026-01-01T00:00:00Z,1,2,1,2,10\n"
    upload = api.post("/api/backtesting/upload-csv", files={"file": ("BTCUSDT-1m.csv", csv, "text/csv")}).json()["data"]

    run = api.post(
        "/api/backtesting/run",
        json={
            **_run_payload(upload["upload_id"], symbol="BTCUSDT", profile_id="PROFILE_G_CODEX_OPTIMIZED"),
            "research_expansion_min": "1.2",
            "research_expansion_max": "3.8",
            "research_retrace_window_8m_candles": "4",
            "research_tp_model": "RR_1_0_RESEARCH",
        },
    ).json()["data"]

    assert run["profile_id"] == "PROFILE_G_CODEX_OPTIMIZED"
    assert run["selected_strategy_profile"] == "PROFILE_G_CODEX_OPTIMIZED"
    assert run["research_mode"] is True
    assert run["profile_applied"]["research_only"] is True
    assert run["profile_applied"]["expansion_min"] == 1.2
    assert run["profile_applied"]["expansion_max"] == 3.8
    assert run["profile_applied"]["retrace_window_8m_candles"] == 4
    assert run["profile_applied"]["tp_model"] == "RR_1_0_RESEARCH"
    assert run["report"]["summary"]["profile_applied"]["selected_rr_profile"] == "RR_1_0_RESEARCH"


def test_recovered_high_winrate_profile_is_selectable_and_uses_leg_target_model() -> None:
    api = client()
    csv = "timestamp,open,high,low,close,volume\n2026-01-01T00:00:00Z,1,2,1,2,10\n"
    upload = api.post("/api/backtesting/upload-csv", files={"file": ("BTCUSDT-1m.csv", csv, "text/csv")}).json()["data"]

    run = api.post(
        "/api/backtesting/run",
        json={
            **_run_payload(upload["upload_id"], symbol="BTCUSDT", profile_id="PROFILE_RECOVERED_HIGH_WINRATE", timeframe_profile="PROFILE_15_10_5"),
            "research_expansion_min": "1.0",
            "research_expansion_max": "3.0",
            "research_retrace_window_8m_candles": "3",
            "research_tp_model": "LEG_TARGET_RESEARCH",
            "research_require_expansion_c3": "false",
            "research_use_linked_fvg_detection": "false",
            "research_main_fvg_match_mode": "LEGACY_EXPANSION_OR_NEXT_CANDLE",
            "research_main_fvg_match_window_candles": "1",
        },
    ).json()["data"]

    assert run["profile_id"] == "PROFILE_RECOVERED_HIGH_WINRATE"
    assert run["research_mode"] is True
    assert run["timeframe_profile"] == "PROFILE_15_10_5"
    assert run["profile_applied"]["expansion_min"] == 1.0
    assert run["profile_applied"]["expansion_max"] == 3.0
    assert run["profile_applied"]["tp_model"] == "LEG_TARGET_RESEARCH"
    assert run["profile_applied"]["selected_rr_profile"] == "LEG_TARGET_RESEARCH"
    assert run["profile_applied"]["selected_rr_value"] == "VARIABLE"
    assert run["profile_applied"]["require_expansion_c3"] is False
    assert run["profile_applied"]["use_linked_fvg_detection"] is False
    assert run["profile_applied"]["main_fvg_match_mode"] == "LEGACY_EXPANSION_OR_NEXT_CANDLE"
    assert run["profile_applied"]["main_fvg_match_window_candles"] == 1


def test_backtest_cache_key_includes_profile_variant_and_expansion_range() -> None:
    api = client()
    csv = "timestamp,open,high,low,close,volume\n2026-01-01T00:00:00Z,1,2,1,2,10\n"
    upload = api.post("/api/backtesting/upload-csv", files={"file": ("BTCUSDT-1m.csv", csv, "text/csv")}).json()["data"]

    volume = api.post("/api/backtesting/run", json=_run_payload(upload["upload_id"], symbol="BTCUSDT", profile_id="PROFILE_F_VOLUME")).json()["data"]
    selective = api.post("/api/backtesting/run", json=_run_payload(upload["upload_id"], symbol="BTCUSDT", profile_id="PROFILE_F_SELECTIVE")).json()["data"]

    assert volume["cache_key"] != selective["cache_key"]
    assert volume["profile_applied"]["expansion_min"] == 1.0
    assert selective["profile_applied"]["expansion_min"] == 2.0


def test_run_requires_upload_and_valid_profile() -> None:
    api = client()

    missing_upload = api.post("/api/backtesting/run", json={**_run_payload("", symbol="BTCUSDT", profile_id="PROFILE_F_VOLUME"), "upload_id": ""})
    invalid_profile = api.post("/api/backtesting/run", json=_run_payload("csv_missing", symbol="BTCUSDT", profile_id="NOPE"))
    unknown_upload = api.post("/api/backtesting/run", json=_run_payload("csv_missing", symbol="BTCUSDT", profile_id="PROFILE_F_VOLUME"))

    assert missing_upload.status_code == 400
    assert _error_payload(missing_upload)["error"]["code"] == "UPLOAD_ID_REQUIRED"
    assert _error_payload(missing_upload)["error"]["message"] == "Please upload a CSV before running a backtest."
    assert invalid_profile.status_code == 400
    assert _error_payload(invalid_profile)["error"]["code"] == "BACKTEST_PROFILE_INVALID"
    assert unknown_upload.status_code == 400
    assert _error_payload(unknown_upload)["error"]["code"] == "UPLOAD_ID_UNKNOWN"


def test_strict_profile_is_accepted_as_backtest_profile() -> None:
    api = client()
    csv = "timestamp,open,high,low,close,volume\n2026-01-01T00:00:00Z,1,2,1,2,10\n"
    upload = api.post("/api/backtesting/upload-csv", files={"file": ("BTCUSDT-1m.csv", csv, "text/csv")}).json()["data"]

    response = api.post(
        "/api/backtesting/run",
        json=_run_payload(upload["upload_id"], symbol="BTCUSDT", profile_id="STRICT_PROFILE"),
    )

    assert response.status_code == 200
    assert response.json()["data"]["profile_id"] == "STRICT_PROFILE"


def test_removed_profiles_are_rejected() -> None:
    api = client()
    csv = "timestamp,open,high,low,close,volume\n2026-01-01T00:00:00Z,1,2,1,2,10\n"
    upload = api.post("/api/backtesting/upload-csv", files={"file": ("BTCUSDT-1m.csv", csv, "text/csv")}).json()["data"]

    removed_old_profile = "PROFILE_" + "F"
    for invalid in ("PROFILE_G", "RESEARCH_PROFILE_A", removed_old_profile, "NOPE"):
        response = api.post(
            "/api/backtesting/run",
            json=_run_payload(upload["upload_id"], symbol="BTCUSDT", profile_id=invalid),
        )
        assert response.status_code == 400, f"expected 400 for {invalid}"
        assert _error_payload(response)["error"]["code"] == "BACKTEST_PROFILE_INVALID"


def test_backtest_run_respects_timeframe_profile() -> None:
    api = client()
    rows = ["timestamp,open,high,low,close,volume"]
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for index in range(120):
        rows.append(f"{(start + timedelta(minutes=index)).isoformat()},1,2,1,2,10")
    csv = "\n".join(rows)
    upload = api.post("/api/backtesting/upload-csv", files={"file": ("BTCUSDT-1m.csv", csv, "text/csv")}).json()["data"]

    default_run = api.post("/api/backtesting/run", json=_run_payload(upload["upload_id"], symbol="BTCUSDT", profile_id="PROFILE_F_VOLUME", timeframe_profile="DEFAULT_16_12_8")).json()["data"]
    profile_20 = api.post("/api/backtesting/run", json=_run_payload(upload["upload_id"], symbol="BTCUSDT", profile_id="PROFILE_F_VOLUME", timeframe_profile="PROFILE_20_15_10"))
    profile_15 = api.post("/api/backtesting/run", json=_run_payload(upload["upload_id"], symbol="BTCUSDT", profile_id="PROFILE_F_VOLUME", timeframe_profile="PROFILE_15_10_5")).json()["data"]

    assert default_run["timeframe_profile_applied"]["swing_timeframe"] == 16
    assert profile_20.status_code == 400
    assert profile_15["timeframe_profile_applied"]["swing_timeframe"] == 15
    assert "16M" in default_run["report"]["summary"]["synthetic_candles"]
    assert "15M" in profile_15["report"]["summary"]["synthetic_candles"]
    assert "candidate_15m_swing_highs" in profile_15["report"]["summary"]["strategy_funnel"]
    assert "passed_5m_fvg" in profile_15["report"]["summary"]["strategy_funnel"]


def test_invalid_timeframe_profile_returns_json_error() -> None:
    api = client()
    csv = "timestamp,open,high,low,close,volume\n2026-01-01T00:00:00Z,1,2,1,2,10\n"
    upload = api.post("/api/backtesting/upload-csv", files={"file": ("BTCUSDT-1m.csv", csv, "text/csv")}).json()["data"]

    response = api.post("/api/backtesting/run", json=_run_payload(upload["upload_id"], symbol="BTCUSDT", profile_id="PROFILE_F_VOLUME", timeframe_profile="NOPE"))

    assert response.status_code == 400
    assert _error_payload(response)["error"]["code"] == "BACKTEST_TIMEFRAME_PROFILE_INVALID"


def test_csv_upload_fails_with_json_error_when_symbol_cannot_be_detected() -> None:
    api = client()
    csv = "timestamp,open,high,low,close,volume\n2026-01-01T00:00:00Z,1,2,1,2,10\n"

    response = api.post("/api/backtesting/upload-csv", files={"file": ("candles.csv", csv, "text/csv")})
    payload = _error_payload(response)

    assert response.status_code == 400
    assert payload["success"] is False
    assert payload["error"]["code"] == "CSV_SYMBOL_REQUIRED"
    assert "ETHUSDT-1m-2024-01.csv" in payload["error"]["message"]


def test_csv_upload_invalid_csv_returns_nonempty_json_error() -> None:
    api = client()

    response = api.post("/api/backtesting/upload-csv", files={"file": ("ETHUSDT-1m-2024-01.csv", "not,a,candle\n", "text/csv")})
    payload = _error_payload(response)

    assert response.status_code == 400
    assert payload["success"] is False
    assert payload["error"]["code"] == "CSV_UPLOAD_INVALID"
    assert payload["error"]["message"]


def test_run_source_has_no_demo_or_sample_fallback() -> None:
    from pathlib import Path

    root = Path(__file__).resolve().parents[4]
    source = (root / "backend" / "arjiobot" / "api" / "routes" / "backtesting.py").read_text(encoding="utf-8")

    assert "build_demo_signal" not in source
    assert "DEMO_SIGNAL_INJECTION" not in source
    assert "PLACEHOLDER_SUMMARY" not in source
    assert "sample_ohlcv.csv" not in source


def _run_payload(upload_id: str, *, symbol: str, profile_id: str, timeframe_profile: str = "DEFAULT_16_12_8") -> dict[str, object]:
    return {
        "upload_id": upload_id,
        "symbol": symbol,
        "profile_id": profile_id,
        "timeframe_profile": timeframe_profile,
        "starting_balance": "10000",
        "fixed_risk_amount": "100",
        "max_leverage": "10",
        "rr_profile": "RR_1_5",
        "risk_per_trade": "100",
        "fees": "0",
        "slippage": "0",
    }


def _error_payload(response):
    payload = response.json()
    return payload.get("detail", payload)

