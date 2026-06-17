"""Storage models for local JSON persistence."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass(slots=True)
class AppStorageState:
    monitored_pairs: list[dict[str, Any]] = field(default_factory=list)
    dashboard_settings: dict[str, Any] = field(default_factory=dict)
    risk_settings: dict[str, Any] = field(default_factory=dict)
    exchange_accounts_metadata: list[dict[str, Any]] = field(default_factory=list)
    backtest_run_metadata: list[dict[str, Any]] = field(default_factory=list)
    report_metadata: list[dict[str, Any]] = field(default_factory=list)
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_record(self) -> dict[str, Any]:
        return {
            "monitored_pairs": self.monitored_pairs,
            "dashboard_settings": self.dashboard_settings,
            "risk_settings": self.risk_settings,
            "exchange_accounts_metadata": self.exchange_accounts_metadata,
            "backtest_run_metadata": self.backtest_run_metadata,
            "report_metadata": self.report_metadata,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_record(cls, record: dict[str, Any]) -> "AppStorageState":
        return cls(
            monitored_pairs=list(record.get("monitored_pairs", [])),
            dashboard_settings=dict(record.get("dashboard_settings", {})),
            risk_settings=dict(record.get("risk_settings", {})),
            exchange_accounts_metadata=list(record.get("exchange_accounts_metadata", [])),
            backtest_run_metadata=list(record.get("backtest_run_metadata", [])),
            report_metadata=list(record.get("report_metadata", [])),
            updated_at=str(record.get("updated_at", datetime.now(timezone.utc).isoformat())),
        )
