"""Rate-limit tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from arjiobot.exchange.exchange_errors import ExchangeAdapterError, ExchangeErrorCode
from arjiobot.exchange.rate_limits import RateLimitGuard


def test_rate_limit_allows_calls_within_window() -> None:
    guard = RateLimitGuard(max_calls=2, window_seconds=60)
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)

    guard.acquire("acct", now)
    guard.acquire("acct", now + timedelta(seconds=1))

    assert not guard.check("acct", now + timedelta(seconds=2))


def test_rate_limit_rejects_excess_calls_and_recovers_after_window() -> None:
    guard = RateLimitGuard(max_calls=1, window_seconds=60)
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    guard.acquire("acct", now)

    try:
        guard.acquire("acct", now + timedelta(seconds=1))
    except ExchangeAdapterError as error:
        assert error.code is ExchangeErrorCode.RATE_LIMITED
    else:
        raise AssertionError("rate limit should reject excess calls")

    assert guard.check("acct", now + timedelta(seconds=61))
