"""Execution state transition helpers."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime

from arjiobot.execution.execution_models import ExecutionRecord, ExecutionStatus
from arjiobot.market_data.candle_models import ensure_utc


def transition_execution_status(execution: ExecutionRecord, status: ExecutionStatus, changed_at: datetime, reason: str | None = None) -> ExecutionRecord:
    """Return execution with updated status and timestamp metadata."""
    timestamp = ensure_utc(changed_at)
    values = {"status": status}
    metadata = dict(execution.metadata)
    if reason:
        metadata["status_reason"] = reason
    if status is ExecutionStatus.CANCELLED:
        values["cancelled_at"] = timestamp
    if status is ExecutionStatus.REJECTED:
        values["rejected_at"] = timestamp
    return replace(execution, **values, metadata=metadata)
