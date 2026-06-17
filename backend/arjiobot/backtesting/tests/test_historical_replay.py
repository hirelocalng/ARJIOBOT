"""Historical replay tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from arjiobot.backtesting.historical_replay import build_timeframe_profile, group_candles_by_symbol, order_historical_candles
from arjiobot.backtesting.historical_replay import load_ohlcv_csv
from arjiobot.market_data.candle_models import Candle, CandleStatus, Timeframe


def make_candle(index: int, *, status: CandleStatus = CandleStatus.CLOSED, symbol: str = "BTCUSDT") -> Candle:
    return Candle(
        symbol=symbol,
        timeframe=Timeframe(1),
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(minutes=index),
        open=Decimal("1"),
        high=Decimal("2"),
        low=Decimal("1"),
        close=Decimal("2"),
        volume=Decimal("1"),
        status=status,
    )


def test_historical_candle_ordering_and_multi_symbol_grouping() -> None:
    candles = [make_candle(2), make_candle(0), make_candle(1), make_candle(0, symbol="ETHUSDT")]
    ordered = order_historical_candles(candles)
    grouped = group_candles_by_symbol(candles)

    assert ordered[0].timestamp <= ordered[-1].timestamp
    assert set(grouped) == {"BTCUSDT", "ETHUSDT"}


def test_incomplete_and_duplicate_candles_rejected() -> None:
    with pytest.raises(ValueError, match="closed"):
        order_historical_candles([make_candle(0, status=CandleStatus.OPEN)])
    with pytest.raises(ValueError, match="duplicate"):
        order_historical_candles([make_candle(0), make_candle(0)])


def test_synthetic_timeframe_profile() -> None:
    candles = [make_candle(index) for index in range(8)]
    synthetic = build_timeframe_profile(candles, 8)

    assert len(synthetic) == 1
    assert synthetic[0].timeframe == Timeframe(8)


def test_csv_loader_uses_defaults_and_normalizes_candles(tmp_path) -> None:
    csv_path = tmp_path / "candles.csv"
    csv_path.write_text(
        "timestamp,open,high,low,close,volume\n"
        "2026-01-01T00:00:00+00:00,1,2,1,2,10\n"
        "2026-01-01T00:01:00+00:00,2,3,2,3,11\n",
        encoding="utf-8",
    )

    candles = load_ohlcv_csv(csv_path, default_symbol="btcusdt", default_timeframe=1)

    assert len(candles) == 2
    assert candles[0].symbol == "BTCUSDT"
    assert candles[0].timeframe == Timeframe(1)
    assert candles[0].volume == Decimal("10")


def test_csv_loader_accepts_optional_symbol_and_timeframe(tmp_path) -> None:
    csv_path = tmp_path / "exchange_export.csv"
    csv_path.write_text(
        "timestamp,symbol,timeframe,open,high,low,close,volume\n"
        "2026-01-01T00:00:00Z,ETHUSDT,8M,1,2,1,2,10\n",
        encoding="utf-8",
    )

    candles = load_ohlcv_csv(csv_path, default_symbol="BTCUSDT")

    assert candles[0].symbol == "ETHUSDT"
    assert candles[0].timeframe == Timeframe(8)


def test_csv_loader_maps_binance_open_time_header(tmp_path) -> None:
    csv_path = tmp_path / "binance_header.csv"
    csv_path.write_text(
        "open_time,open,high,low,close,volume,close_time,quote_asset_volume,number_of_trades\n"
        "1767225600000,100,110,90,105,12,1767225659999,1200,8\n",
        encoding="utf-8",
    )

    candles = load_ohlcv_csv(csv_path, default_symbol="BTCUSDT")

    assert len(candles) == 1
    assert candles[0].timestamp == datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert candles[0].open == Decimal("100")
    assert candles[0].volume == Decimal("12")


def test_csv_loader_accepts_headerless_native_binance_kline_rows(tmp_path) -> None:
    csv_path = tmp_path / "BTCUSDT-1m-2026-01.csv"
    csv_path.write_text(
        "1767225600000,100,110,90,105,12,1767225659999,1200,8,6,600,0\n"
        "1767225660000,105,115,95,108,13,1767225719999,1404,9,7,756,0\n",
        encoding="utf-8",
    )

    candles = load_ohlcv_csv(csv_path, default_symbol="BTCUSDT")

    assert len(candles) == 2
    assert candles[0].timestamp == datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert candles[1].timestamp == datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc)
    assert candles[1].close == Decimal("108")


def test_csv_loader_accepts_microsecond_epoch_binance_rows(tmp_path) -> None:
    csv_path = tmp_path / "ETHUSDT-1m-2026-04.csv"
    csv_path.write_text(
        "1775001600000000,2105.43,2106.88,2103.63,2104.11,886.0327,1775001659999999,1865485.82,5178,651.44,1371681.89,0\n",
        encoding="utf-8",
    )

    candles = load_ohlcv_csv(csv_path, default_symbol="ETHUSDT")

    assert len(candles) == 1
    assert candles[0].symbol == "ETHUSDT"
    assert candles[0].timestamp == datetime(2026, 4, 1, tzinfo=timezone.utc)


def test_csv_loader_requires_ohlcv_columns(tmp_path) -> None:
    csv_path = tmp_path / "bad.csv"
    csv_path.write_text("timestamp,open,high,low,close\n2026-01-01T00:00:00Z,1,2,1,2\n", encoding="utf-8")

    with pytest.raises(ValueError, match="missing required columns"):
        load_ohlcv_csv(csv_path, default_symbol="BTCUSDT")
