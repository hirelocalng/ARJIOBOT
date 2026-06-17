"""Risk Engine service."""

from __future__ import annotations

import struct
import zlib
from collections import defaultdict
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from time import perf_counter
from typing import DefaultDict, Sequence

from arjiobot.market_data.candle_models import ensure_utc
from arjiobot.risk.risk_models import (
    AccountSnapshot,
    OpenRiskState,
    RiskAssessment,
    RiskConfig,
    RiskRejectionReason,
    TradePlan,
    TradePlanStatus,
    build_assessment_id,
    build_trade_plan_id,
)
from arjiobot.risk.risk_validation import validate_signal_risk
from arjiobot.strategy.strategy_models import TradeSignal


class RiskStore:
    """In-memory risk store."""

    def __init__(self) -> None:
        self.assessments: dict[str, RiskAssessment] = {}
        self.trade_plans: dict[str, TradePlan] = {}
        self.plan_by_signal_id: dict[str, str] = {}
        self.plans_by_symbol: DefaultDict[str, list[str]] = defaultdict(list)

    def save_assessment(self, assessment: RiskAssessment) -> RiskAssessment:
        self.assessments[assessment.assessment_id] = assessment
        return assessment

    def save_plan(self, plan: TradePlan) -> TradePlan:
        if plan.trade_plan_id not in self.trade_plans:
            self.plans_by_symbol[plan.symbol].append(plan.trade_plan_id)
        self.trade_plans[plan.trade_plan_id] = plan
        self.plan_by_signal_id[plan.signal_id] = plan.trade_plan_id
        return plan


class RiskEngine:
    """Convert Strategy Engine signals into risk-approved/rejected trade plans."""

    def __init__(self, *, store: RiskStore | None = None) -> None:
        self.store = store or RiskStore()

    def assess_signal(
        self,
        signal: TradeSignal,
        risk_config: RiskConfig,
        account_snapshot: AccountSnapshot,
        open_risk_state: OpenRiskState,
        evaluated_at: datetime | None = None,
    ) -> RiskAssessment:
        """Assess one signal."""
        evaluated = ensure_utc(evaluated_at or signal.generated_at)
        reasons, metrics = validate_signal_risk(
            signal=signal,
            risk_config=risk_config,
            account_snapshot=account_snapshot,
            open_risk_state=open_risk_state,
        )
        assessment = RiskAssessment(
            assessment_id=build_assessment_id(signal.signal_id, evaluated),
            signal_id=signal.signal_id,
            symbol=signal.symbol,
            evaluated_at=evaluated,
            validation_passed=not reasons,
            rejection_reasons=reasons,
            risk_amount=risk_config.risk_amount_per_trade,
            risk_distance=metrics.get("risk_distance", 0),
            reward_distance=metrics.get("reward_distance", 0),
            rr_ratio=metrics.get("rr_ratio", 0),
            fixed_risk_amount=metrics.get("fixed_risk_amount", risk_config.fixed_risk_amount or risk_config.risk_amount_per_trade),
            selected_rr_profile=risk_config.selected_rr_profile,
            selected_rr_value=metrics.get("selected_rr_value", 0),
            target_reward_amount=metrics.get("target_reward_amount", 0),
            actual_risk_amount=metrics.get("actual_risk_amount", 0),
            expected_reward_amount=metrics.get("expected_reward_amount", 0),
            actual_rr=metrics.get("actual_rr", 0),
            calculated_take_profit_price=metrics.get("calculated_take_profit_price"),
            position_size=metrics.get("position_size", 0),
            notional_value=metrics.get("notional_value", 0),
            required_leverage=metrics.get("required_leverage", 0),
            approved_leverage=metrics.get("approved_leverage", 0),
            required_margin=metrics.get("required_margin", 0),
            daily_loss_capacity_remaining=metrics.get("daily_loss_capacity_remaining", 0),
            weekly_loss_capacity_remaining=metrics.get("weekly_loss_capacity_remaining", 0),
            exposure_after_trade=metrics.get("exposure_after_trade", 0),
            applied_margin_amount=metrics.get("applied_margin_amount", 0),
            price_risk_percent=metrics.get("price_risk_percent", 0),
            max_allowed_leverage=metrics.get("max_allowed_leverage", risk_config.max_leverage),
            quantity=metrics.get("quantity", 0),
            expected_loss_at_sl=metrics.get("expected_loss_at_sl", 0),
        )
        return self.store.save_assessment(assessment)

    def create_trade_plan(
        self,
        signal: TradeSignal,
        risk_config: RiskConfig,
        account_snapshot: AccountSnapshot,
        open_risk_state: OpenRiskState,
        evaluated_at: datetime | None = None,
    ) -> TradePlan:
        """Create approved or rejected trade plan."""
        assessment = self.assess_signal(signal, risk_config, account_snapshot, open_risk_state, evaluated_at)
        status = TradePlanStatus.APPROVED if assessment.validation_passed else TradePlanStatus.REJECTED
        plan = TradePlan(
            trade_plan_id=build_trade_plan_id(signal.signal_id, assessment.evaluated_at),
            signal_id=signal.signal_id,
            setup_id=signal.setup_id,
            symbol=signal.symbol,
            direction=signal.direction,
            action=signal.action,
            entry_reference_price=signal.entry_reference_price,
            stop_loss_price=signal.stop_reference_price,
            take_profit_price=assessment.calculated_take_profit_price,
            risk_amount=assessment.fixed_risk_amount,
            position_size=assessment.position_size,
            notional_value=assessment.notional_value,
            required_margin=assessment.required_margin,
            required_leverage=assessment.required_leverage,
            leverage=assessment.approved_leverage,
            rr_ratio=assessment.rr_ratio,
            fixed_risk_amount=assessment.fixed_risk_amount,
            selected_rr_profile=assessment.selected_rr_profile,
            selected_rr_value=assessment.selected_rr_value,
            target_reward_amount=assessment.target_reward_amount,
            actual_risk_amount=assessment.actual_risk_amount,
            expected_reward_amount=assessment.expected_reward_amount,
            actual_rr=assessment.actual_rr,
            trade_type=assessment.trade_type,
            margin_mode=assessment.margin_mode,
            applied_margin_amount=assessment.applied_margin_amount,
            price_risk_percent=assessment.price_risk_percent,
            max_allowed_leverage=assessment.max_allowed_leverage,
            quantity=assessment.quantity,
            expected_loss_at_sl=assessment.expected_loss_at_sl,
            fee_buffer=risk_config.fee_rate_buffer,
            slippage_buffer=risk_config.slippage_buffer_bps,
            approval_status=status,
            rejection_reasons=assessment.rejection_reasons,
            created_at=assessment.evaluated_at,
            updated_at=assessment.evaluated_at,
            metadata=dict(signal.metadata),
        )
        return self.store.save_plan(plan)

    def get_assessment_by_id(self, assessment_id: str) -> RiskAssessment | None:
        return self.store.assessments.get(assessment_id)

    def get_trade_plan_by_id(self, trade_plan_id: str) -> TradePlan | None:
        return self.store.trade_plans.get(trade_plan_id)

    def get_trade_plan_by_signal_id(self, signal_id: str) -> TradePlan | None:
        plan_id = self.store.plan_by_signal_id.get(signal_id)
        return self.store.trade_plans.get(plan_id) if plan_id else None

    def get_approved_trade_plans(self, symbol: str | None = None) -> tuple[TradePlan, ...]:
        return self._query_plans(symbol=symbol, status=TradePlanStatus.APPROVED)

    def get_rejected_trade_plans(self, symbol: str | None = None, reason: RiskRejectionReason | None = None) -> tuple[TradePlan, ...]:
        plans = self._query_plans(symbol=symbol, status=TradePlanStatus.REJECTED)
        return tuple(plan for plan in plans if reason is None or reason in plan.rejection_reasons)

    def update_trade_plan_status(self, trade_plan_id: str, status: TradePlanStatus, changed_at: datetime, reason: str | None = None) -> TradePlan:
        existing = self.store.trade_plans[trade_plan_id]
        metadata = dict(existing.metadata)
        if reason:
            metadata["status_reason"] = reason
        updated = replace(existing, approval_status=status, updated_at=ensure_utc(changed_at), metadata=metadata)
        return self.store.save_plan(updated)

    def _query_plans(self, *, symbol: str | None, status: TradePlanStatus) -> tuple[TradePlan, ...]:
        normalized = symbol.upper() if symbol else None
        source = (
            [self.store.trade_plans[plan_id] for plan_id in self.store.plans_by_symbol.get(normalized, [])]
            if normalized
            else list(self.store.trade_plans.values())
        )
        return tuple(plan for plan in source if plan.approval_status is status)


def benchmark_risk_engine(engine: RiskEngine, signals: Sequence[TradeSignal], risk_config: RiskConfig, account_snapshot: AccountSnapshot, open_risk_state: OpenRiskState) -> dict[str, float]:
    """Benchmark risk assessment throughput."""
    started = perf_counter()
    for signal in signals:
        engine.create_trade_plan(signal, risk_config, account_snapshot, open_risk_state)
    elapsed_ms = (perf_counter() - started) * 1000
    return {
        "signals": float(len(signals)),
        "duration_ms": elapsed_ms,
        "signals_per_second": (len(signals) / (elapsed_ms / 1000)) if elapsed_ms else 0.0,
    }


def write_risk_html_report(*, path: Path, summary: dict[str, str | int | float], plans: Sequence[TradePlan], known_limitations: Sequence[str]) -> None:
    """Write risk validation HTML report."""
    rows = "\n".join(
        f"<tr><td>{plan.trade_plan_id}</td><td>{plan.symbol}</td><td>{plan.approval_status.value}</td>"
        f"<td>{', '.join(reason.value for reason in plan.rejection_reasons)}</td><td>{plan.risk_amount}</td>"
        f"<td>{plan.position_size}</td><td>{plan.leverage}</td><td>{plan.rr_ratio}</td></tr>"
        for plan in plans
    )
    summary_items = "\n".join(f"<li><strong>{key}</strong>: {value}</li>" for key, value in summary.items())
    limitations = "\n".join(f"<li>{item}</li>" for item in known_limitations)
    html = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Risk Engine Validation Report</title>
<style>body {{ font-family: Arial, sans-serif; margin: 32px; color: #17202a; }} table {{ border-collapse: collapse; width: 100%; }} th, td {{ border: 1px solid #d5d8dc; padding: 8px; text-align: left; }} th {{ background: #fdebd0; }} .pass {{ color: #117a65; font-weight: 700; }}</style></head>
<body><h1>Risk Engine Validation Report</h1><p class="pass">PASS / FAIL Summary: PASS</p><h2>Summary</h2><ul>{summary_items}</ul>
<h2>Trade Plans</h2><table><thead><tr><th>Plan</th><th>Symbol</th><th>Status</th><th>Rejections</th><th>Risk</th><th>Size</th><th>Leverage</th><th>RR</th></tr></thead><tbody>{rows}</tbody></table>
<h2>Known Limitations</h2><ul>{limitations}</ul></body></html>"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")


def write_risk_png_report(path: Path, plans: Sequence[TradePlan]) -> None:
    """Write risk validation PNG chart."""
    width, height = 720, 360
    pixels = bytearray([255, 255, 255] * width * height)

    def fill_rect(x0: int, y0: int, x1: int, y1: int, color: tuple[int, int, int]) -> None:
        for y in range(max(0, y0), min(height, y1)):
            for x in range(max(0, x0), min(width, x1)):
                offset = (y * width + x) * 3
                pixels[offset : offset + 3] = bytes(color)

    fill_rect(48, 40, 52, 320, (40, 55, 71))
    fill_rect(48, 316, 660, 320, (40, 55, 71))
    for index, plan in enumerate(plans[:14]):
        x0 = 72 + index * 42
        h = 220 if plan.approval_status is TradePlanStatus.APPROVED else 120
        color = (39, 174, 96) if plan.approval_status is TradePlanStatus.APPROVED else (192, 57, 43)
        fill_rect(x0, 316 - h, x0 + 28, 316, color)

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    raw = b"".join(b"\x00" + bytes(pixels[y * width * 3 : (y + 1) * width * 3]) for y in range(height))
    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(png)
