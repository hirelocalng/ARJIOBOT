"""Simple testable rate-limit guard."""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import DefaultDict, Deque

from arjiobot.exchange.exchange_errors import ExchangeAdapterError, ExchangeErrorCode
from arjiobot.market_data.candle_models import ensure_utc


@dataclass(slots=True)
class RateLimitGuard:
    max_calls: int = 20
    window_seconds: int = 60
    _calls: DefaultDict[str, Deque[datetime]] = field(default_factory=lambda: defaultdict(deque))

    def check(self, account_id: str, now: datetime | None = None) -> bool:
        timestamp = ensure_utc(now or datetime.now(timezone.utc))
        calls = self._calls[account_id]
        window_start = timestamp - timedelta(seconds=self.window_seconds)
        while calls and calls[0] <= window_start:
            calls.popleft()
        return len(calls) < self.max_calls

    def acquire(self, account_id: str, now: datetime | None = None) -> None:
        timestamp = ensure_utc(now or datetime.now(timezone.utc))
        if not self.check(account_id, timestamp):
            raise ExchangeAdapterError(ExchangeErrorCode.RATE_LIMITED, "rate limit exceeded")
        self._calls[account_id].append(timestamp)

    def reset(self, account_id: str | None = None) -> None:
        if account_id is None:
            self._calls.clear()
        else:
            self._calls.pop(account_id, None)
