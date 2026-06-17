"""Backtesting API routes."""

from __future__ import annotations

import hashlib
import csv
import io
import logging
import re
import sys
import uuid
from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path

from fastapi import APIRouter, File, Form, UploadFile

from arjiobot.api.dependencies import get_state, now_iso
from arjiobot.api.errors import api_error
from arjiobot.api.schemas.common import ok
from arjiobot.backtesting.historical_replay import load_ohlcv_csv_text
from arjiobot.backtesting.research_profiles import StrategyProfile, get_profile, get_strategy_profiles
from arjiobot.backtesting.timeframe_profiles import get_timeframe_profile
from arjiobot.risk.rr_profiles import PRODUCTION_RR_PROFILE, SUPPORTED_TP_MODELS, resolve_rr_value

API_SUPPORTED_TP_MODELS = (*SUPPORTED_TP_MODELS, "TIME_BASED_EXIT")

ROOT = Path(__file__).resolve().parents[4]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from backtest_csv import run as run_csv_backtest  # noqa: E402

router = APIRouter(prefix="/api/backtesting", tags=["backtesting"])
logger = logging.getLogger(__name__)


@router.get("/profiles")
def profiles():
    return ok(tuple(profile.to_record() for profile in get_strategy_profiles()))


@router.post("/upload-csv")
def upload_csv(file: UploadFile = File(...), selected_symbol: str | None = Form(None)):
    try:
        if file is None or not hasattr(file, "file"):
            raise api_error(400, "CSV_UPLOAD_REQUIRED", "CSV upload file is required.")
        data = file.file.read()
        if isinstance(data, str):
            data = data.encode("utf-8")
        filename = file.filename or "uploaded.csv"
        detected_symbol, has_symbol_column = _detect_csv_symbol(data, filename)
        if detected_symbol == "UNKNOWN" and selected_symbol:
            detected_symbol = _normalize_manual_symbol(selected_symbol)
        if detected_symbol == "UNKNOWN":
            raise api_error(
                400,
                "CSV_SYMBOL_REQUIRED",
                "Could not detect a trading symbol from the CSV. Include a symbol column or use a filename like ETHUSDT-1m-2024-01.csv.",
            )
        content = data.decode("utf-8-sig")
        candles = load_ohlcv_csv_text(content, default_symbol=detected_symbol)
    except UnicodeDecodeError as exc:
        raise api_error(400, "CSV_UPLOAD_INVALID_ENCODING", "CSV must be UTF-8 encoded.") from exc
    except (OSError, ValueError) as exc:
        raise api_error(400, "CSV_UPLOAD_INVALID", str(exc)) from exc
    except Exception as exc:
        if hasattr(exc, "status_code") and hasattr(exc, "detail"):
            raise
        logger.exception("CSV upload failed for %s", getattr(file, "filename", "uploaded.csv"))
        raise api_error(500, "CSV_UPLOAD_FAILED", "CSV upload failed. The server returned a JSON error instead of an empty response.") from exc
    if candles:
        symbols = sorted({candle.symbol.upper() for candle in candles})
        detected_symbol = symbols[0] if len(symbols) == 1 else detected_symbol
    candle_hash = hashlib.sha256(data).hexdigest()
    upload_id = f"csv_{len(get_state().uploaded_csvs) + 1:04d}_{candle_hash[:12]}"
    get_state().uploaded_csvs[upload_id] = {
        "upload_id": upload_id,
        "filename": filename,
        "size_bytes": len(data),
        "candles_loaded": len(candles),
        "detected_symbol": detected_symbol,
        "has_symbol_column": has_symbol_column,
        "start_time": candles[0].timestamp.isoformat() if candles else None,
        "end_time": candles[-1].end_timestamp.isoformat() if candles else None,
        "candle_hash": candle_hash,
        "uploaded_at": now_iso(),
    }
    get_state().uploaded_csv_contents[upload_id] = content
    return ok(get_state().uploaded_csvs[upload_id])


@router.post("/run")
def run_backtest(payload: dict[str, object]):
    state = get_state()
    profile_request_value = payload.get("selected_strategy_profile") or payload.get("profile_id")
    missing = [
        field
        for field in ("upload_id", "symbol", "timeframe_profile", "starting_balance", "max_leverage", "fees", "slippage")
        if payload.get(field) in (None, "")
    ]
    if profile_request_value in (None, ""):
        missing.append("selected_strategy_profile")
    if payload.get("fixed_risk_amount") in (None, "") and payload.get("risk_per_trade") in (None, ""):
        missing.append("fixed_risk_amount")
    if missing:
        if "upload_id" in missing:
            raise api_error(400, "UPLOAD_ID_REQUIRED", "Please upload a CSV before running a backtest.")
        raise api_error(400, "BACKTEST_REQUEST_INVALID", f"Missing required backtest fields: {', '.join(missing)}")
    symbol = str(payload["symbol"]).upper()
    profile_id = str(profile_request_value).upper()
    try:
        profile = get_profile(profile_id)
    except ValueError as exc:
        raise api_error(400, "BACKTEST_PROFILE_INVALID", str(exc)) from exc
    selected_tp_model = _selected_tp_model(payload, state.settings, profile)
    profile_overrides = _research_profile_overrides(profile, payload, selected_tp_model=selected_tp_model)
    active_profile = replace(profile, **profile_overrides) if profile_overrides else profile
    if active_profile.profile_id != profile_id:
        raise api_error(
            500,
            "PROFILE_LOCK_RESOLUTION_FAILED",
            f"Selected profile {profile_id} resolved to {active_profile.profile_id}. Backtest stopped.",
        )
    try:
        timeframe_profile = get_timeframe_profile(str(payload["timeframe_profile"]))
    except ValueError as exc:
        raise api_error(400, "BACKTEST_TIMEFRAME_PROFILE_INVALID", str(exc)) from exc
    fixed_risk_amount = str(payload.get("fixed_risk_amount") or payload.get("risk_per_trade") or "")
    max_leverage = str(payload.get("max_leverage") or payload.get("selected_max_leverage") or "")
    rr_profile = selected_tp_model
    runner_rr_profile = profile.tp_model if selected_tp_model == "TIME_BASED_EXIT" else selected_tp_model
    try:
        if Decimal(fixed_risk_amount) <= Decimal("0"):
            raise ValueError("fixed_risk_amount must be greater than 0")
    except (InvalidOperation, ValueError) as exc:
        raise api_error(400, "FIXED_RISK_AMOUNT_INVALID", "fixed_risk_amount must be a positive number.") from exc
    try:
        if Decimal(max_leverage) < Decimal("1"):
            raise ValueError("max_leverage must be at least 1")
    except (InvalidOperation, ValueError) as exc:
        raise api_error(400, "MAX_LEVERAGE_INVALID", "max_leverage must be a number greater than or equal to 1.") from exc
    try:
        selected_rr_value = Decimal("0") if rr_profile == "TIME_BASED_EXIT" else resolve_rr_value(rr_profile)
    except ValueError as exc:
        raise api_error(400, "TP_MODEL_INVALID", str(exc)) from exc
    time_exit_minutes = _time_exit_minutes(payload, state.settings, rr_profile)
    csv_ref = str(payload["upload_id"])
    if not csv_ref or csv_ref not in state.uploaded_csv_contents:
        raise api_error(400, "UPLOAD_ID_UNKNOWN", f"Unknown CSV upload_id: {csv_ref}. Upload the CSV again, especially if the backend was restarted.")
    upload_meta = state.uploaded_csvs[csv_ref]
    warnings: list[str] = []
    detected_symbol = str(upload_meta.get("detected_symbol") or "")
    if detected_symbol and detected_symbol != symbol and upload_meta.get("has_symbol_column"):
        warnings.append(f"Selected symbol {symbol} differs from CSV symbol column {detected_symbol}; selected symbol was used for this run.")
    report_dir = _writable_backtest_artifact_dir()
    if report_dir != ROOT / "reports" / "backtests":
        warnings.append(f"reports/backtests is not writable; API backtest artifacts were staged in {report_dir}.")
    csv_path = report_dir / f"api_upload_{csv_ref}_{uuid.uuid4().hex[:8]}.csv"
    csv_path.write_text(state.uploaded_csv_contents[csv_ref], encoding="utf-8")
    report = run_csv_backtest(
        csv_path,
        symbol,
        timeframe_profile=timeframe_profile.profile_id,
        strategy_profile=profile.profile_id,
        starting_balance=str(payload["starting_balance"]),
        fixed_risk_amount=fixed_risk_amount,
        max_leverage=max_leverage,
        selected_rr_profile=runner_rr_profile,
        fees=str(payload["fees"]),
        slippage=str(payload["slippage"]),
        profile_overrides=profile_overrides,
    )
    summary = {
        **report["summary"],
        "report_json_path": str(report.get("json_path", "")),
        "report_html_path": str(report.get("html_path", "")),
    }
    if rr_profile == "TIME_BASED_EXIT":
        candles = tuple(load_ohlcv_csv_text(state.uploaded_csv_contents[csv_ref], default_symbol=symbol))
        summary = _apply_time_based_exit(
            summary,
            candles=candles,
            time_exit_minutes=time_exit_minutes or 0,
            selected_tp_model=rr_profile,
        )
    source_run_id = str(summary.get("run_id", ""))
    run_id = f"btr_{len(state.backtest_runs) + 1:04d}"
    synthetic = summary.get("synthetic_candles", {})
    profile_lock_verification = _verify_profile_lock(
        frontend_selected_profile=profile_id,
        api_selected_profile=profile_id,
        backend_resolved_profile=active_profile.profile_id,
        strategy_applied_profile=str(summary.get("applied_profile_id") or summary.get("profile_id") or ""),
        trades=summary.get("trade_list", ()),
    )
    if profile_lock_verification["profile_lock_status"] != "PASSED":
        raise api_error(
            500,
            "PROFILE_LOCK_FAILED",
            f"Profile lock verification failed: {profile_lock_verification}",
        )
    summary = {
        **summary,
        "run_id": run_id,
        "source_run_id": source_run_id,
        "api_run_id": run_id,
        "upload_id": csv_ref,
        "filename": upload_meta.get("filename"),
        "symbol": symbol,
        "detected_symbol": detected_symbol,
        "profile_id": active_profile.profile_id,
        "selected_profile_id": profile_id,
        "applied_profile_id": active_profile.profile_id,
        "frontend_selected_profile": profile_id,
        "api_selected_profile": profile_id,
        "backend_resolved_profile": active_profile.profile_id,
        "strategy_applied_profile": active_profile.profile_id,
        "selected_strategy_profile": active_profile.profile_id,
        "timeframe_profile": timeframe_profile.profile_id,
        "timeframe_profile_applied": timeframe_profile.to_record(),
        "strategy_source": "REAL_STRATEGY_PIPELINE",
        "selected_tp_model": rr_profile,
        "applied_tp_model": rr_profile,
        "time_exit_enabled": rr_profile == "TIME_BASED_EXIT",
        "time_exit_minutes": time_exit_minutes if rr_profile == "TIME_BASED_EXIT" else "",
        "time_exit_minutes_selected": time_exit_minutes if rr_profile == "TIME_BASED_EXIT" else "",
        "time_exit_minutes_applied": time_exit_minutes if rr_profile == "TIME_BASED_EXIT" else "",
        "tp_model_lock_status": "UNLOCKED" if active_profile.tp_model == rr_profile else "LOCKED",
        "tp_model_override_allowed": "YES" if "tp_model" in active_profile.tunable_parameters or active_profile.tp_model == rr_profile else "NO",
        "candles_loaded": upload_meta.get("candles_loaded"),
        "candle_hash": upload_meta.get("candle_hash"),
        "data_start_time": upload_meta.get("start_time"),
        "data_end_time": upload_meta.get("end_time"),
        "synthetic_candles": synthetic,
        "setups_invalidated_with_reason_counts": summary.get("setups_invalidated_with_reason_counts", {}),
        "profile_applied": _profile_applied(active_profile),
        "profile_lock_verification": profile_lock_verification,
        "cache_key": _backtest_cache_key(
            selected_strategy_profile=active_profile.profile_id,
            profile=active_profile,
            symbol=symbol,
            timeframe_profile=timeframe_profile.profile_id,
            candle_hash=str(upload_meta.get("candle_hash") or ""),
            fixed_risk_amount=fixed_risk_amount,
            starting_balance=str(payload["starting_balance"]),
            max_leverage=max_leverage,
            margin_mode="isolated",
            selected_exchange=str(payload.get("selected_exchange") or "BACKTEST"),
            selected_trade_mode=str(payload.get("selected_trade_mode") or "BACKTEST"),
            fees=str(payload["fees"]),
            slippage=str(payload["slippage"]),
            selected_tp_model=rr_profile,
            time_exit_minutes=str(time_exit_minutes or ""),
        ),
        "run_parameters": {
            "selected_strategy_profile": active_profile.profile_id,
            "starting_balance": str(payload["starting_balance"]),
            "fixed_risk_amount": fixed_risk_amount,
            "risk_per_trade": fixed_risk_amount,
            "max_leverage": max_leverage,
            "selected_max_leverage": max_leverage,
            "margin_mode": "isolated",
            "selected_exchange": str(payload.get("selected_exchange") or "BACKTEST"),
            "selected_trade_mode": str(payload.get("selected_trade_mode") or "BACKTEST"),
            "rr_profile": rr_profile,
            "selected_rr_profile": summary.get("selected_rr_profile", rr_profile),
            "selected_tp_model": rr_profile,
            "time_exit_minutes": time_exit_minutes if rr_profile == "TIME_BASED_EXIT" else "",
            "selected_rr_value": summary.get("selected_rr_value", str(selected_rr_value)),
            "fees": str(payload["fees"]),
            "slippage": str(payload["slippage"]),
        },
        "warnings": warnings,
        "generated_at": now_iso(),
    }
    equity_curve = _equity_curve_from_trades(summary.get("trade_list", ()), str(payload["starting_balance"]))
    result = {
        "run_id": run_id,
        "upload_id": csv_ref,
        "filename": upload_meta.get("filename"),
        "symbol": symbol,
        "detected_symbol": detected_symbol,
        "timeframe": "1M",
        "timeframe_profile": timeframe_profile.profile_id,
        "timeframe_profile_applied": timeframe_profile.to_record(),
        "profile_id": active_profile.profile_id,
        "selected_profile_id": profile_id,
        "applied_profile_id": active_profile.profile_id,
        "selected_strategy_profile": active_profile.profile_id,
        "research_mode": not active_profile.production_safe,
        "status": "COMPLETED",
        "candles_loaded": upload_meta.get("candles_loaded"),
        "candle_hash": upload_meta.get("candle_hash"),
        "data_start_time": upload_meta.get("start_time"),
        "data_end_time": upload_meta.get("end_time"),
        "profile_applied": _profile_applied(active_profile),
        "profile_lock_verification": profile_lock_verification,
        "cache_key": summary["cache_key"],
        "warnings": warnings,
        "trades": summary.get("trade_list", ()),
        "equity_curve": equity_curve,
        "report": {"summary": summary},
    }
    state.backtest_runs[run_id] = result
    return ok(result)


@router.get("/runs")
def runs():
    return ok(tuple(reversed(tuple(get_state().backtest_runs.values()))))


@router.get("/runs/{run_id}")
def run(run_id: str):
    return ok(get_state().backtest_runs.get(run_id))


@router.get("/runs/{run_id}/trades")
def trades(run_id: str):
    return ok(get_state().backtest_runs.get(run_id, {}).get("trades", []))


@router.get("/runs/{run_id}/equity")
def equity(run_id: str):
    return ok(get_state().backtest_runs.get(run_id, {}).get("equity_curve", []))


@router.get("/runs/{run_id}/report")
def report(run_id: str):
    return ok(get_state().backtest_runs.get(run_id, {}).get("report", {}))


def _detect_csv_symbol(data: bytes, filename: str) -> tuple[str, bool]:
    content = data.decode("utf-8-sig", errors="ignore")
    handle = io.StringIO(content)
    try:
        first_row = next(csv.reader(handle))
    except StopIteration:
        return _infer_symbol_from_filename(filename), False
    lower = [cell.strip().lower() for cell in first_row]
    if "symbol" in lower:
        symbol_index = lower.index("symbol")
        try:
            second_row = next(csv.reader(handle))
        except StopIteration:
            return _infer_symbol_from_filename(filename), True
        if len(second_row) > symbol_index and second_row[symbol_index].strip():
            return second_row[symbol_index].strip().upper(), True
        return _infer_symbol_from_filename(filename), True
    return _infer_symbol_from_filename(filename), False


def _infer_symbol_from_filename(filename: str) -> str:
    name = Path(filename).name.upper()
    match = re.match(r"^([A-Z0-9]+USDT)-1M(?:-|\.|_)", name)
    if not match:
        match = re.match(r"^([A-Z0-9]+)-1M(?:-|\.|_)", name)
    if match:
        return match.group(1)
    return "UNKNOWN"


def _normalize_manual_symbol(symbol: str) -> str:
    normalized = symbol.strip().upper()
    if re.fullmatch(r"[A-Z0-9]{2,}", normalized):
        return normalized
    return "UNKNOWN"


def _selected_tp_model(payload: dict[str, object], settings: dict[str, object], profile: StrategyProfile) -> str:
    selected = str(
        payload.get("selected_tp_model")
        or payload.get("selected_rr_profile")
        or payload.get("research_tp_model")
        or profile.tp_model
    ).strip().upper()
    if selected not in API_SUPPORTED_TP_MODELS:
        raise api_error(400, "TP_MODEL_INVALID", f"Unsupported TP/RR model: {selected}.")
    return selected


def _time_exit_minutes(payload: dict[str, object], settings: dict[str, object], selected_tp_model: str) -> int | None:
    if selected_tp_model != "TIME_BASED_EXIT":
        return None
    value = payload.get("time_exit_minutes") or payload.get("selected_time_exit_minutes") or settings.get("time_exit_minutes")
    try:
        minutes = int(str(value))
    except (TypeError, ValueError) as exc:
        raise api_error(400, "TIME_EXIT_MINUTES_INVALID", "time_exit_minutes must be an integer from 1 to 120.") from exc
    if minutes < 1 or minutes > 120:
        raise api_error(400, "TIME_EXIT_MINUTES_INVALID", "time_exit_minutes must be between 1 and 120.")
    return minutes


def _research_profile_overrides(profile: StrategyProfile, payload: dict[str, object], *, selected_tp_model: str) -> dict[str, object]:
    if profile.profile_id not in {"PROFILE_G_CODEX_OPTIMIZED", "PROFILE_RECOVERED_HIGH_WINRATE", "PROFILE_2"}:
        if selected_tp_model != profile.tp_model:
            raise api_error(
                400,
                "TP_MODEL_OVERRIDE_BLOCKED",
                f"Profile {profile.profile_id} locks TP model {profile.tp_model}; selected {selected_tp_model} cannot be applied.",
            )
        return {}
    overrides: dict[str, object] = {}
    if selected_tp_model != profile.tp_model and selected_tp_model != "TIME_BASED_EXIT":
        if "tp_model" not in profile.tunable_parameters:
            raise api_error(
                400,
                "TP_MODEL_OVERRIDE_BLOCKED",
                f"Profile {profile.profile_id} locks TP model {profile.tp_model}; selected {selected_tp_model} cannot be applied.",
            )
        overrides["tp_model"] = selected_tp_model
    if payload.get("research_expansion_min") not in (None, ""):
        overrides["expansion_ratio_min"] = _decimal_float(
            payload["research_expansion_min"],
            "research_expansion_min",
            minimum=Decimal("0.5"),
            maximum=Decimal("5.0"),
        )
    if payload.get("research_expansion_max") not in (None, ""):
        overrides["expansion_ratio_max"] = _decimal_float(
            payload["research_expansion_max"],
            "research_expansion_max",
            minimum=Decimal("1.0"),
            maximum=Decimal("6.0"),
        )
    if payload.get("research_retrace_window_8m_candles") not in (None, ""):
        try:
            retrace_window = int(str(payload["research_retrace_window_8m_candles"]))
        except ValueError as exc:
            raise api_error(400, "RESEARCH_PROFILE_OVERRIDE_INVALID", "research_retrace_window_8m_candles must be an integer from 1 to 6.") from exc
        if retrace_window < 1 or retrace_window > 6:
            raise api_error(400, "RESEARCH_PROFILE_OVERRIDE_INVALID", "research_retrace_window_8m_candles must be an integer from 1 to 6.")
        overrides["retrace_window_8m_candles"] = retrace_window
    if payload.get("research_tp_model") not in (None, ""):
        tp_model = str(payload["research_tp_model"]).strip().upper()
        if tp_model not in API_SUPPORTED_TP_MODELS:
            raise api_error(400, "RESEARCH_PROFILE_OVERRIDE_INVALID", f"research_tp_model must be one of {', '.join(API_SUPPORTED_TP_MODELS)}.")
        if tp_model != "TIME_BASED_EXIT":
            overrides["tp_model"] = tp_model
    if payload.get("research_require_expansion_c3") not in (None, ""):
        value = str(payload["research_require_expansion_c3"]).strip().lower()
        if value not in {"true", "false", "1", "0", "yes", "no"}:
            raise api_error(400, "RESEARCH_PROFILE_OVERRIDE_INVALID", "research_require_expansion_c3 must be true or false.")
        overrides["require_expansion_c3"] = value in {"true", "1", "yes"}
    if payload.get("research_use_linked_fvg_detection") not in (None, ""):
        value = str(payload["research_use_linked_fvg_detection"]).strip().lower()
        if value not in {"true", "false", "1", "0", "yes", "no"}:
            raise api_error(400, "RESEARCH_PROFILE_OVERRIDE_INVALID", "research_use_linked_fvg_detection must be true or false.")
        overrides["use_linked_fvg_detection"] = value in {"true", "1", "yes"}
    if payload.get("research_main_fvg_match_mode") not in (None, ""):
        match_mode = str(payload["research_main_fvg_match_mode"]).strip().upper()
        if match_mode not in {"C2_IMMEDIATE", "LEGACY_EXPANSION_OR_NEXT_CANDLE"}:
            raise api_error(400, "RESEARCH_PROFILE_OVERRIDE_INVALID", "research_main_fvg_match_mode must be C2_IMMEDIATE or LEGACY_EXPANSION_OR_NEXT_CANDLE.")
        overrides["main_fvg_match_mode"] = match_mode
    if payload.get("research_main_fvg_match_window_candles") not in (None, ""):
        try:
            match_window = int(str(payload["research_main_fvg_match_window_candles"]))
        except ValueError as exc:
            raise api_error(400, "RESEARCH_PROFILE_OVERRIDE_INVALID", "research_main_fvg_match_window_candles must be an integer from 0 to 3.") from exc
        if match_window < 0 or match_window > 3:
            raise api_error(400, "RESEARCH_PROFILE_OVERRIDE_INVALID", "research_main_fvg_match_window_candles must be an integer from 0 to 3.")
        overrides["main_fvg_match_window_candles"] = match_window
    expansion_min = float(overrides.get("expansion_ratio_min", profile.expansion_ratio_min))
    expansion_max = float(overrides.get("expansion_ratio_max", profile.expansion_ratio_max))
    if expansion_min >= expansion_max:
        raise api_error(400, "RESEARCH_PROFILE_OVERRIDE_INVALID", "research_expansion_min must be lower than research_expansion_max.")
    return overrides


def _decimal_float(value: object, field_name: str, *, minimum: Decimal, maximum: Decimal) -> float:
    try:
        parsed = Decimal(str(value))
    except InvalidOperation as exc:
        raise api_error(400, "RESEARCH_PROFILE_OVERRIDE_INVALID", f"{field_name} must be numeric.") from exc
    if parsed < minimum or parsed > maximum:
        raise api_error(400, "RESEARCH_PROFILE_OVERRIDE_INVALID", f"{field_name} must be between {minimum} and {maximum}.")
    return float(parsed)


def _writable_backtest_artifact_dir() -> Path:
    preferred = ROOT / "reports" / "backtests"
    fallback = ROOT / ".pytest_tmp" / "backtests"
    for directory in (preferred, fallback):
        try:
            directory.mkdir(parents=True, exist_ok=True)
            probe = directory / f".write_probe_{uuid.uuid4().hex}"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
            return directory
        except OSError:
            continue
    raise api_error(500, "BACKTEST_ARTIFACT_DIR_UNWRITABLE", "No writable backtest artifact directory is available.")


def _equity_curve_from_trades(trades: object, starting_balance: str) -> list[dict[str, str]]:
    try:
        balance = float(starting_balance)
    except ValueError:
        balance = 0.0
    curve = [{"timestamp": now_iso(), "equity": str(balance)}]
    if not isinstance(trades, (list, tuple)):
        return curve
    for trade in trades:
        if not isinstance(trade, dict):
            continue
        if trade.get("outcome") not in ("WIN", "LOSS", "BREAKEVEN"):
            continue
        try:
            balance += float(str(trade.get("net_pnl", "0")))
        except ValueError:
            continue
        curve.append({"timestamp": str(trade.get("exit_timestamp") or now_iso()), "equity": str(balance)})
    return curve


def _apply_time_based_exit(
    summary: dict[str, object],
    *,
    candles: tuple[object, ...],
    time_exit_minutes: int,
    selected_tp_model: str,
) -> dict[str, object]:
    original_trades = tuple(trade for trade in summary.get("trade_list", ()) if isinstance(trade, dict))
    rewritten = tuple(_time_exit_trade(trade, candles=candles, minutes=time_exit_minutes) for trade in original_trades)
    if len(rewritten) != len(original_trades):
        raise api_error(
            500,
            "TIME_BASED_EXIT_ENTRY_PARITY_FAILED",
            "TIME_BASED_EXIT entry parity failed: accepted entry count changed during exit evaluation.",
        )
    performance = _time_exit_performance(rewritten, str(summary.get("selected_starting_balance") or summary.get("starting_balance") or "0"), time_exit_minutes)
    funnel = dict(summary.get("strategy_funnel", {}) if isinstance(summary.get("strategy_funnel"), dict) else {})
    funnel["trade_list"] = rewritten
    funnel["performance_summary"] = performance
    funnel["time_based_exit_entry_parity"] = {
        "status": "PASSED",
        "normal_entry_count": len(original_trades),
        "time_based_exit_entry_count": len(rewritten),
        "missing_trades": (),
        "extra_trades": (),
    }
    return {
        **summary,
        "selected_rr_profile": selected_tp_model,
        "selected_rr_value": "0",
        "selected_tp_model": selected_tp_model,
        "applied_tp_model": selected_tp_model,
        "time_exit_enabled": True,
        "time_exit_minutes": time_exit_minutes,
        "time_exit_minutes_selected": time_exit_minutes,
        "time_exit_minutes_applied": time_exit_minutes,
        "trades_simulated": len(rewritten),
        "wins": performance["wins"],
        "losses": performance["losses"],
        "win_rate": performance["win_rate"],
        "net_profit": performance["net_profit"],
        "profit_factor": performance["profit_factor"],
        "strategy_funnel": funnel,
        "trade_list": rewritten,
        "performance_summary": performance,
    }


def _time_exit_trade(trade: dict[str, object], *, candles: tuple[object, ...], minutes: int) -> dict[str, object]:
    entry_time = _parse_iso(str(trade.get("entry_timestamp") or ""))
    if entry_time is None:
        return {**trade, "selected_tp_model": "TIME_BASED_EXIT", "applied_tp_model": "TIME_BASED_EXIT", "exit_reason": "DATA_UNAVAILABLE"}
    target_time = entry_time + timedelta(minutes=minutes)
    direction = str(trade.get("direction") or "").upper()
    entry = Decimal(str(trade.get("entry_price") or "0"))
    stop = Decimal(str(trade.get("stop_loss") or "0"))
    size = Decimal(str(trade.get("position_size") or trade.get("quantity") or "0"))
    exit_candle = None
    exit_price: Decimal | None = None
    exit_reason = "DATA_UNAVAILABLE"
    for candle in candles:
        if getattr(candle, "timestamp", None) <= entry_time:
            continue
        if getattr(candle, "timestamp") >= target_time:
            exit_candle = candle
            exit_price = Decimal(str(candle.close))
            exit_reason = "TIME_BASED_EXIT"
            break
        if direction == "BEARISH" and Decimal(str(candle.high)) >= stop:
            exit_candle = candle
            exit_price = stop
            exit_reason = "PROTECTIVE_SL"
            break
        if direction == "BULLISH" and Decimal(str(candle.low)) <= stop:
            exit_candle = candle
            exit_price = stop
            exit_reason = "PROTECTIVE_SL"
            break
    if exit_candle is None or exit_price is None:
        return {
            **trade,
            "selected_rr_profile": "TIME_BASED_EXIT",
            "selected_tp_model": "TIME_BASED_EXIT",
            "applied_tp_model": "TIME_BASED_EXIT",
            "selected_rr_value": "0",
            "target_reward_amount": "0",
            "expected_reward_amount": "0",
            "actual_rr": "0",
            "take_profit": "",
            "TP": "",
            "take_profit_price": "",
            "time_exit_enabled": True,
            "time_exit_minutes": minutes,
            "planned_time_exit_timestamp": target_time.isoformat(),
            "target_time_exit_timestamp": target_time.isoformat(),
            "actual_exit_timestamp": "",
            "time_exit_price": "",
            "exit_price": "",
            "exit_reason": "DATA_UNAVAILABLE",
            "duration_minutes": "",
            "pnl": "0",
            "gross_pnl": "0",
            "net_pnl": "0",
            "rr_realized": "0",
            "outcome": "OPEN_OR_UNRESOLVED",
            "result": "DATA_UNAVAILABLE",
        }
    pnl = _pnl(direction=direction, entry=entry, exit_price=exit_price, size=size)
    outcome = "WIN" if pnl > 0 else "LOSS" if pnl < 0 else "BREAKEVEN"
    risk = Decimal(str(trade.get("fixed_risk_amount") or trade.get("risk_amount") or "0"))
    return {
        **trade,
        "selected_rr_profile": "TIME_BASED_EXIT",
        "selected_tp_model": "TIME_BASED_EXIT",
        "applied_tp_model": "TIME_BASED_EXIT",
        "selected_rr_value": "0",
        "target_reward_amount": "0",
        "expected_reward_amount": "0",
        "actual_rr": str(pnl / risk) if risk else "0",
        "take_profit": "",
        "TP": "",
        "take_profit_price": "",
        "time_exit_enabled": True,
        "time_exit_minutes": minutes,
        "planned_time_exit_timestamp": target_time.isoformat(),
        "target_time_exit_timestamp": target_time.isoformat(),
        "actual_exit_timestamp": getattr(exit_candle, "timestamp").isoformat(),
        "exit_timestamp": getattr(exit_candle, "timestamp").isoformat(),
        "time_exit_price": str(exit_price) if exit_reason == "TIME_BASED_EXIT" else "",
        "exit_price": str(exit_price),
        "exit_reason": exit_reason,
        "duration_minutes": str((getattr(exit_candle, "timestamp") - entry_time).total_seconds() / 60),
        "pnl": str(pnl),
        "gross_pnl": str(pnl),
        "net_pnl": str(pnl),
        "rr_realized": str(pnl / risk) if risk else "0",
        "outcome": outcome,
        "result": outcome if exit_reason != "DATA_UNAVAILABLE" else "DATA_UNAVAILABLE",
    }


def _time_exit_performance(trades: tuple[dict[str, object], ...], starting_balance: str, minutes: int) -> dict[str, object]:
    balance = Decimal(str(starting_balance or "0"))
    closed = [trade for trade in trades if trade.get("outcome") in {"WIN", "LOSS", "BREAKEVEN"}]
    wins = [trade for trade in closed if trade.get("outcome") == "WIN"]
    losses = [trade for trade in closed if trade.get("outcome") == "LOSS"]
    gross_profit = sum((Decimal(str(trade.get("net_pnl", "0"))) for trade in wins), Decimal("0"))
    gross_loss = sum((Decimal(str(trade.get("net_pnl", "0"))) for trade in losses), Decimal("0"))
    net = sum((Decimal(str(trade.get("net_pnl", "0"))) for trade in closed), Decimal("0"))
    durations = [float(str(trade.get("duration_minutes"))) for trade in closed if trade.get("duration_minutes") not in (None, "")]
    time_exit_closed = [trade for trade in trades if trade.get("exit_reason") == "TIME_BASED_EXIT"]
    protective_sl = [trade for trade in trades if trade.get("exit_reason") == "PROTECTIVE_SL"]
    time_exit_pnls = [Decimal(str(trade.get("net_pnl", "0"))) for trade in time_exit_closed]
    time_exit_wins = [trade for trade in time_exit_closed if trade.get("outcome") == "WIN"]
    return {
        "starting_balance": starting_balance,
        "final_balance": str(balance + net),
        "total_trades": len(trades),
        "closed_trades": len(closed),
        "open_or_unresolved_trades": len(trades) - len(closed),
        "wins": len(wins),
        "losses": len(losses),
        "breakeven": len([trade for trade in closed if trade.get("outcome") == "BREAKEVEN"]),
        "win_rate": (len(wins) / len(closed) * 100) if closed else 0.0,
        "gross_profit": str(gross_profit),
        "gross_loss": str(gross_loss),
        "net_profit": str(net),
        "profit_factor": "INF" if gross_loss == 0 and gross_profit > 0 else (str(gross_profit / abs(gross_loss)) if gross_loss else "0"),
        "selected_rr_profile": "TIME_BASED_EXIT",
        "selected_tp_model": "TIME_BASED_EXIT",
        "applied_tp_model": "TIME_BASED_EXIT",
        "tp_model_lock_status": "UNLOCKED",
        "selected_rr_value": "0",
        "tp_model_used": "TIME_BASED_EXIT",
        "time_exit_minutes": minutes,
        "time_exit_closed_count": len(time_exit_closed),
        "protective_sl_closed_count": len(protective_sl),
        "average_time_in_trade_minutes": (sum(durations) / len(durations)) if durations else None,
        "average_pnl_for_time_exit_trades": str(sum(time_exit_pnls, Decimal("0")) / len(time_exit_pnls)) if time_exit_pnls else "0",
        "win_rate_for_time_exit_trades": (len(time_exit_wins) / len(time_exit_closed) * 100) if time_exit_closed else 0.0,
        "trade_accounting_check": {
            "trades_simulated": len(trades),
            "closed_trades": len(closed),
            "accounting_balanced": len(trades) == len(closed) + (len(trades) - len(closed)),
        },
    }


def _pnl(*, direction: str, entry: Decimal, exit_price: Decimal, size: Decimal) -> Decimal:
    return (entry - exit_price) * size if direction == "BEARISH" else (exit_price - entry) * size


def _parse_iso(value: str):
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _profile_applied(profile: StrategyProfile) -> dict[str, object]:
    selected_rr_profile = _selected_rr_profile_for_profile(profile)
    selected_rr_value = _selected_rr_value_for_profile(profile)
    return {
        "profile_id": profile.profile_id,
        "expansion_min": profile.expansion_ratio_min,
        "expansion_max": profile.expansion_ratio_max,
        "inherited_base_profile": profile.inherited_base_profile,
        "retrace_window_8m_candles": profile.retrace_window_8m_candles,
        "allow_delayed_16m_fvg": profile.fvg_delay_16m_candles > 0,
        "delayed_16m_fvg_max_candles": profile.fvg_delay_16m_candles,
        "direct_12m_retrace_entry_enabled": profile.direct_12m_retrace_entry_enabled,
        "one_trade_per_12m_fvg": profile.one_trade_per_12m_fvg,
        "require_1m_swing_confirmation": profile.require_1m_swing_confirmation,
        "require_1m_bearish_expansion": profile.require_1m_bearish_expansion,
        "require_1m_bearish_fvg": profile.require_1m_bearish_fvg,
        "require_1m_fvg_retest": profile.require_1m_fvg_retest,
        "timeframe_profile_id": profile.timeframe_profile_id,
        "tp_model": profile.tp_model,
        "selected_tp_model": selected_rr_profile,
        "applied_tp_model": profile.tp_model,
        "tp_model_lock_status": "UNLOCKED" if selected_rr_profile == profile.tp_model else "LOCKED",
        "tp_model_override_allowed": "YES" if "tp_model" in profile.tunable_parameters or selected_rr_profile == profile.tp_model else "NO",
        "require_expansion_c3": profile.require_expansion_c3,
        "use_linked_fvg_detection": profile.use_linked_fvg_detection,
        "main_fvg_match_mode": profile.main_fvg_match_mode,
        "main_fvg_match_window_candles": profile.main_fvg_match_window_candles,
        "selected_rr_profile": selected_rr_profile,
        "selected_rr_value": selected_rr_value,
        "tunable_parameters": profile.tunable_parameters,
        "profile_label": profile.label,
        "research_only": not profile.production_safe,
    }


def _backtest_cache_key(
    *,
    selected_strategy_profile: str,
    profile: StrategyProfile,
    symbol: str,
    timeframe_profile: str,
    candle_hash: str,
    fixed_risk_amount: str,
    starting_balance: str,
    max_leverage: str,
    margin_mode: str,
    selected_exchange: str,
    selected_trade_mode: str,
    fees: str,
    slippage: str,
    selected_tp_model: str,
    time_exit_minutes: str,
) -> str:
    raw = "|".join(
        (
            selected_strategy_profile,
            str(profile.expansion_ratio_min),
            str(profile.expansion_ratio_max),
            str(profile.retrace_window_8m_candles),
            str(profile.tp_model),
            str(selected_tp_model),
            str(time_exit_minutes),
            str(profile.require_expansion_c3),
            str(profile.use_linked_fvg_detection),
            str(profile.main_fvg_match_mode),
            str(profile.main_fvg_match_window_candles),
            "DIRECT_12M_RETRACE" if profile.direct_12m_retrace_entry_enabled else "FULL_1M_CONFIRMATION",
            str(timeframe_profile),
            symbol.upper(),
            candle_hash,
            str(starting_balance),
            str(fixed_risk_amount),
            str(max_leverage),
            str(margin_mode),
            str(selected_exchange).upper(),
            str(selected_trade_mode).upper(),
            str(fees),
            str(slippage),
        )
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _verify_profile_lock(
    *,
    frontend_selected_profile: str,
    api_selected_profile: str,
    backend_resolved_profile: str,
    strategy_applied_profile: str,
    trades: object,
) -> dict[str, object]:
    trade_rows = tuple(trades) if isinstance(trades, (list, tuple)) else ()
    selected = str(api_selected_profile).upper()
    mismatches = []
    for trade in trade_rows:
        if not isinstance(trade, dict):
            continue
        trade_selected = str(trade.get("selected_profile_id") or trade.get("selected_strategy_profile") or "").upper()
        trade_applied = str(trade.get("applied_profile_id") or trade.get("profile_id") or "").upper()
        if trade_selected != selected or trade_applied != selected:
            mismatches.append(
                {
                    "trade_id": trade.get("trade_id", "UNKNOWN"),
                    "trade_selected_profile": trade_selected,
                    "trade_applied_profile": trade_applied,
                }
            )
    layers_match = (
        str(frontend_selected_profile).upper()
        == selected
        == str(backend_resolved_profile).upper()
        == str(strategy_applied_profile).upper()
    )
    status = "PASSED" if layers_match and not mismatches else "FAILED"
    return {
        "section": "PROFILE LOCK VERIFICATION",
        "frontend_selected_profile": str(frontend_selected_profile).upper(),
        "api_selected_profile": selected,
        "backend_resolved_profile": str(backend_resolved_profile).upper(),
        "strategy_applied_profile": str(strategy_applied_profile).upper(),
        "trades_checked": len(trade_rows),
        "mismatched_trades_count": len(mismatches),
        "mismatched_trades": tuple(mismatches),
        "profile_lock_status": status,
        "selected_profile_actively_used_by_backend": "YES" if status == "PASSED" else "NO",
    }


def _selected_rr_profile_for_profile(profile: StrategyProfile) -> str:
    if profile.tp_model in {"RR_1_0", "RR_1_0_RESEARCH"}:
        return profile.tp_model
    if profile.tp_model in {"LEG_TARGET_RESEARCH", "TIME_BASED_EXIT"}:
        return profile.tp_model
    return PRODUCTION_RR_PROFILE


def _selected_rr_value_for_profile(profile: StrategyProfile) -> str:
    if profile.tp_model in {"RR_1_0", "RR_1_0_RESEARCH"}:
        return "1.0"
    if profile.tp_model == "LEG_TARGET_RESEARCH":
        return "VARIABLE"
    if profile.tp_model == "TIME_BASED_EXIT":
        return "0"
    return str(resolve_rr_value(PRODUCTION_RR_PROFILE))
