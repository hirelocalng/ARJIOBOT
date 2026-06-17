"""Service facade for Execution Engine."""

from __future__ import annotations

from arjiobot.execution.execution_engine import ExecutionEngine


class ExecutionService(ExecutionEngine):
    """Authoritative execution service API."""

