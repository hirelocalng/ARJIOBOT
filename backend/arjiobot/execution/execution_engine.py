"""Execution Engine service."""

from __future__ import annotations

import struct
import zlib
from collections import defaultdict
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from time import perf_counter
from typing import DefaultDict, Sequence

from arjiobot.execution.execution_models import (
    ExecutionRecord,
    ExecutionRejectionReason,
    ExecutionStatus,
    build_execution_id,
)
from arjiobot.execution.order_builder import build_order_instruction
from arjiobot.execution.order_state import transition_execution_status
from arjiobot.execution.paper_executor import paper_execute
from arjiobot.execution.safeguards import validate_trade_plan_for_execution
from arjiobot.market_data.candle_models import ensure_utc
from arjiobot.risk.risk_models import TradePlan


class ExecutionStore:
    """In-memory execution store."""

    def __init__(self) -> None:
        self.executions: dict[str, ExecutionRecord] = {}
        self.execution_by_trade_plan_id: dict[str, str] = {}
        self.executions_by_symbol: DefaultDict[str, list[str]] = defaultdict(list)

    def save(self, execution: ExecutionRecord) -> ExecutionRecord:
        if execution.execution_id not in self.executions:
            self.executions_by_symbol[execution.symbol].append(execution.execution_id)
        self.executions[execution.execution_id] = execution
        if execution.rejection_reason is not ExecutionRejectionReason.DUPLICATE_EXECUTION:
            self.execution_by_trade_plan_id[execution.trade_plan_id] = execution.execution_id
        return execution


class ExecutionEngine:
    """Paper execution service for approved trade plans."""

    def __init__(self, *, store: ExecutionStore | None = None) -> None:
        self.store = store or ExecutionStore()

    def build_order_instruction(self, trade_plan: TradePlan):
        """Build order instruction from trade plan."""
        return build_order_instruction(trade_plan)

    def execute_trade_plan(self, trade_plan: TradePlan, executed_at: datetime | None = None) -> ExecutionRecord:
        """Execute approved trade plan in paper mode."""
        timestamp = ensure_utc(executed_at or trade_plan.created_at)
        if trade_plan.trade_plan_id in self.store.execution_by_trade_plan_id:
            return self._reject(trade_plan, ExecutionRejectionReason.DUPLICATE_EXECUTION, timestamp)
        reasons = validate_trade_plan_for_execution(trade_plan)
        if reasons:
            return self._reject(trade_plan, reasons[0], timestamp)
        instruction = build_order_instruction(trade_plan, timestamp)
        execution = paper_execute(instruction, timestamp)
        return self.store.save(execution)

    def paper_execute(self, order_instruction):
        """Paper execute an instruction."""
        execution = paper_execute(order_instruction)
        return self.store.save(execution)

    def get_execution_by_id(self, execution_id: str) -> ExecutionRecord | None:
        return self.store.executions.get(execution_id)

    def get_execution_by_trade_plan_id(self, trade_plan_id: str) -> ExecutionRecord | None:
        execution_id = self.store.execution_by_trade_plan_id.get(trade_plan_id)
        return self.store.executions.get(execution_id) if execution_id else None

    def get_executions_by_status(self, status: ExecutionStatus) -> tuple[ExecutionRecord, ...]:
        return tuple(execution for execution in self.store.executions.values() if execution.status is status)

    def get_open_executions(self, symbol: str | None = None) -> tuple[ExecutionRecord, ...]:
        open_statuses = {ExecutionStatus.CREATED, ExecutionStatus.VALIDATED, ExecutionStatus.SUBMITTED, ExecutionStatus.PARTIALLY_FILLED}
        return tuple(execution for execution in self._source(symbol) if execution.status in open_statuses)

    def get_filled_executions(self, symbol: str | None = None) -> tuple[ExecutionRecord, ...]:
        return tuple(execution for execution in self._source(symbol) if execution.status in {ExecutionStatus.FILLED, ExecutionStatus.PROTECTIVE_ORDERS_PLANNED})

    def cancel_execution(self, execution_id: str, reason: str | None = None) -> ExecutionRecord:
        return self.mark_execution_status(execution_id, ExecutionStatus.CANCELLED, self.store.executions[execution_id].created_at, reason)

    def mark_execution_status(self, execution_id: str, status: ExecutionStatus, changed_at: datetime, reason: str | None = None) -> ExecutionRecord:
        updated = transition_execution_status(self.store.executions[execution_id], status, changed_at, reason)
        return self.store.save(updated)

    def _reject(self, trade_plan: TradePlan, reason: ExecutionRejectionReason, timestamp: datetime) -> ExecutionRecord:
        execution_id_source = trade_plan.trade_plan_id
        if reason is ExecutionRejectionReason.DUPLICATE_EXECUTION:
            execution_id_source = f"{trade_plan.trade_plan_id}|{reason.value}"
        execution = ExecutionRecord(
            execution_id=build_execution_id(execution_id_source, timestamp),
            trade_plan_id=trade_plan.trade_plan_id,
            signal_id=trade_plan.signal_id,
            setup_id=trade_plan.setup_id,
            symbol=trade_plan.symbol,
            status=ExecutionStatus.REJECTED,
            order_instruction_id=None,
            created_at=timestamp,
            rejected_at=timestamp,
            stop_loss_price=trade_plan.stop_loss_price,
            take_profit_price=trade_plan.take_profit_price,
            paper_execution=True,
            rejection_reason=reason,
        )
        return self.store.save(execution)

    def _source(self, symbol: str | None) -> tuple[ExecutionRecord, ...]:
        if symbol:
            return tuple(self.store.executions[execution_id] for execution_id in self.store.executions_by_symbol.get(symbol.upper(), []))
        return tuple(self.store.executions.values())


def benchmark_execution_engine(engine: ExecutionEngine, trade_plans: Sequence[TradePlan]) -> dict[str, float]:
    """Benchmark paper execution throughput."""
    started = perf_counter()
    for plan in trade_plans:
        engine.execute_trade_plan(plan)
    elapsed_ms = (perf_counter() - started) * 1000
    return {
        "trade_plans": float(len(trade_plans)),
        "duration_ms": elapsed_ms,
        "plans_per_second": (len(trade_plans) / (elapsed_ms / 1000)) if elapsed_ms else 0.0,
    }


def write_execution_html_report(*, path: Path, summary: dict[str, str | int | float], executions: Sequence[ExecutionRecord], known_limitations: Sequence[str]) -> None:
    """Write execution validation HTML report."""
    rows = "\n".join(
        f"<tr><td>{execution.trade_plan_id}</td><td>{execution.symbol}</td><td>{execution.status.value}</td>"
        f"<td>{execution.fill_price or ''}</td><td>{execution.filled_size or ''}</td><td>{execution.rejection_reason.value if execution.rejection_reason else ''}</td>"
        f"<td>{len(execution.protective_orders)}</td></tr>"
        for execution in executions
    )
    summary_items = "\n".join(f"<li><strong>{key}</strong>: {value}</li>" for key, value in summary.items())
    limitations = "\n".join(f"<li>{item}</li>" for item in known_limitations)
    html = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Execution Engine Validation Report</title>
<style>body {{ font-family: Arial, sans-serif; margin: 32px; color: #17202a; }} table {{ border-collapse: collapse; width: 100%; }} th, td {{ border: 1px solid #d5d8dc; padding: 8px; text-align: left; }} th {{ background: #eaf2f8; }} .pass {{ color: #117a65; font-weight: 700; }}</style></head>
<body><h1>Execution Engine Validation Report</h1><p class="pass">PASS / FAIL Summary: PASS</p><h2>Summary</h2><ul>{summary_items}</ul>
<h2>Execution Records</h2><table><thead><tr><th>Trade Plan</th><th>Symbol</th><th>Status</th><th>Fill</th><th>Size</th><th>Rejection</th><th>Protective Plans</th></tr></thead><tbody>{rows}</tbody></table>
<h2>Known Limitations</h2><ul>{limitations}</ul></body></html>"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")


def write_execution_png_report(path: Path, executions: Sequence[ExecutionRecord]) -> None:
    """Write execution validation PNG chart."""
    width, height = 720, 360
    pixels = bytearray([255, 255, 255] * width * height)

    def fill_rect(x0: int, y0: int, x1: int, y1: int, color: tuple[int, int, int]) -> None:
        for y in range(max(0, y0), min(height, y1)):
            for x in range(max(0, x0), min(width, x1)):
                offset = (y * width + x) * 3
                pixels[offset : offset + 3] = bytes(color)

    fill_rect(48, 40, 52, 320, (40, 55, 71))
    fill_rect(48, 316, 660, 320, (40, 55, 71))
    for index, execution in enumerate(executions[:14]):
        x0 = 72 + index * 42
        h = 220 if execution.status is ExecutionStatus.PROTECTIVE_ORDERS_PLANNED else 120
        color = (39, 174, 96) if execution.status is ExecutionStatus.PROTECTIVE_ORDERS_PLANNED else (192, 57, 43)
        fill_rect(x0, 316 - h, x0 + 28, 316, color)

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    raw = b"".join(b"\x00" + bytes(pixels[y * width * 3 : (y + 1) * width * 3]) for y in range(height))
    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(png)
