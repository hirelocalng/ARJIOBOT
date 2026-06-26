"""Unit tests for BitgetEnvironmentService.backfill_candles pagination."""

from __future__ import annotations

from arjiobot.exchange.bitget_environment import BitgetEnvironmentService

ONE_MINUTE_MS = 60_000


def _page(start_ms: int, count: int) -> list[list[str]]:
    return [[str(start_ms + index * ONE_MINUTE_MS), "1", "1", "1", "1", "1"] for index in range(count)]


def test_backfill_candles_pages_backward_past_single_request_cap() -> None:
    """A single Bitget request caps at ~1000 rows; backfill_candles must page twice to reach 2000."""
    service = BitgetEnvironmentService()
    newest_page = _page(1_000_000_000_000, 1000)
    oldest_page = _page(1_000_000_000_000 - 1000 * ONE_MINUTE_MS, 1000)
    calls: list[object] = []

    def fake_public_request(path: str, *, query: dict[str, object]) -> dict[str, object]:
        calls.append(query.get("endTime"))
        if "endTime" not in query:
            return {"data": newest_page}
        return {"data": oldest_page}

    service._public_request = fake_public_request  # type: ignore[method-assign]
    result = service.backfill_candles("BTCUSDT", total=2000, page_size=1000)

    assert result["candle_count"] == 2000
    assert len(calls) == 2
    assert calls[0] is None
    timestamps = [int(row[0]) for row in result["rows"]]
    assert timestamps == sorted(timestamps)
    assert len(set(timestamps)) == 2000


def test_fetch_candles_caps_single_request_at_bitget_limit() -> None:
    service = BitgetEnvironmentService()
    limits: list[object] = []

    def fake_public_request(path: str, *, query: dict[str, object]) -> dict[str, object]:
        limits.append(query["limit"])
        return {"data": []}

    service._public_request = fake_public_request  # type: ignore[method-assign]
    service.fetch_candles("BTCUSDT", "1m", 2000)

    assert limits == ["1000"]


def test_backfill_candles_stops_when_exchange_has_no_more_history() -> None:
    service = BitgetEnvironmentService()
    only_page = _page(1_000_000_000_000, 500)

    def fake_public_request(path: str, *, query: dict[str, object]) -> dict[str, object]:
        return {"data": only_page if "endTime" not in query else []}

    service._public_request = fake_public_request  # type: ignore[method-assign]
    result = service.backfill_candles("BTCUSDT", total=2000, page_size=1000)

    assert result["candle_count"] == 500
