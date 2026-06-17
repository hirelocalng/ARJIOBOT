"""Historical candle replay helpers."""

from __future__ import annotations

import csv
import io
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import DefaultDict, Sequence

from arjiobot.market_data.candle_models import Candle, CandleStatus, Timeframe, build_synthetic_candle


REQUIRED_CSV_COLUMNS = ("timestamp", "open", "high", "low", "close", "volume")
BINANCE_KLINE_COLUMNS = (
    "open_time",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "close_time",
    "quote_asset_volume",
    "number_of_trades",
    "taker_buy_base_asset_volume",
    "taker_buy_quote_asset_volume",
    "ignore",
)
CSV_COLUMN_ALIASES = {
    "timestamp": "timestamp",
    "time": "timestamp",
    "date": "timestamp",
    "datetime": "timestamp",
    "open_time": "timestamp",
    "opentime": "timestamp",
    "open time": "timestamp",
    "open": "open",
    "high": "high",
    "low": "low",
    "close": "close",
    "volume": "volume",
    "symbol": "symbol",
    "timeframe": "timeframe",
}


def order_historical_candles(candles: Sequence[Candle]) -> tuple[Candle, ...]:
    """Validate closed candles and return deterministic chronological order."""
    ordered = tuple(sorted(candles, key=lambda candle: (candle.timestamp, candle.symbol, candle.timeframe.minutes)))
    seen: set[tuple[str, Timeframe, datetime]] = set()
    for candle in ordered:
        if candle.status is not CandleStatus.CLOSED:
            raise ValueError("backtester only replays closed candles")
        key = (candle.symbol, candle.timeframe, candle.timestamp)
        if key in seen:
            raise ValueError("duplicate candle timestamp for symbol/timeframe")
        seen.add(key)
    return ordered


def group_candles_by_symbol(candles: Sequence[Candle]) -> dict[str, tuple[Candle, ...]]:
    """Group ordered candles by symbol."""
    grouped: DefaultDict[str, list[Candle]] = defaultdict(list)
    for candle in order_historical_candles(candles):
        grouped[candle.symbol].append(candle)
    return {symbol: tuple(values) for symbol, values in grouped.items()}


def build_timeframe_profile(candles_1m: Sequence[Candle], timeframe_minutes: int) -> tuple[Candle, ...]:
    """Build deterministic synthetic candles for one timeframe."""
    timeframe = Timeframe(timeframe_minutes)
    if timeframe.minutes == 1:
        return tuple(candles_1m)
    ordered = order_historical_candles(candles_1m)
    output: list[Candle] = []
    index = 0
    while index + timeframe.minutes <= len(ordered):
        window = ordered[index : index + timeframe.minutes]
        if window[0].timeframe.minutes != 1:
            raise ValueError("synthetic profiles require 1M source candles")
        if not timeframe.is_aligned(window[0].timestamp):
            index += 1
            continue
        try:
            output.append(build_synthetic_candle(symbol=window[0].symbol, timeframe=timeframe, candles=window))
        except ValueError:
            pass
        index += timeframe.minutes
    return tuple(output)


def load_ohlcv_csv(
    path: str | Path,
    *,
    default_symbol: str,
    default_timeframe: int | str | Timeframe = 1,
) -> tuple[Candle, ...]:
    """Load historical OHLCV CSV rows into normalized Candle objects."""
    csv_path = Path(path)
    return load_ohlcv_csv_text(csv_path.read_text(encoding="utf-8-sig"), default_symbol=default_symbol, default_timeframe=default_timeframe)


def load_ohlcv_csv_text(
    content: str,
    *,
    default_symbol: str,
    default_timeframe: int | str | Timeframe = 1,
) -> tuple[Candle, ...]:
    """Load historical OHLCV CSV text into normalized Candle objects.

    Accepted inputs are canonical OHLCV headers, Binance-style ``open_time``
    headers, and native Binance kline rows without headers.
    """
    candles: list[Candle] = []
    handle = io.StringIO(content)
    sample_reader = csv.reader(handle)
    try:
        first_row = next(sample_reader)
    except StopIteration as exc:
        raise ValueError("CSV file is empty") from exc

    handle.seek(0)
    if _row_is_header(first_row):
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError("CSV file must include headers or native Binance kline rows")
        field_map = {field: _canonical_csv_column(field) for field in reader.fieldnames}
        normalized_fields = {column for column in field_map.values() if column is not None}
        missing = [column for column in REQUIRED_CSV_COLUMNS if column not in normalized_fields]
        if missing:
            raise ValueError(f"CSV missing required columns: {', '.join(missing)}")
        for row in reader:
            candles.append(
                _candle_from_row(
                    _normalize_csv_row(row, field_map),
                    default_symbol=default_symbol,
                    default_timeframe=default_timeframe,
                )
            )
    else:
        reader = csv.reader(handle)
        for row in reader:
            if not any(cell.strip() for cell in row):
                continue
            candles.append(
                _candle_from_row(
                    _normalize_binance_kline_row(row),
                    default_symbol=default_symbol,
                    default_timeframe=default_timeframe,
                )
            )
    return order_historical_candles(candles)


def _candle_from_row(
    normalized_row: dict[str, str],
    *,
    default_symbol: str,
    default_timeframe: int | str | Timeframe,
) -> Candle:
    symbol = normalized_row.get("symbol") or default_symbol
    timeframe = normalized_row.get("timeframe") or default_timeframe
    return Candle(
        symbol=symbol,
        timeframe=_parse_csv_timeframe(timeframe),
        timestamp=_parse_csv_timestamp(normalized_row["timestamp"]),
        open=Decimal(normalized_row["open"]),
        high=Decimal(normalized_row["high"]),
        low=Decimal(normalized_row["low"]),
        close=Decimal(normalized_row["close"]),
        volume=Decimal(normalized_row["volume"]),
        status=CandleStatus.CLOSED,
    )


def _canonical_csv_column(column: str) -> str | None:
    return CSV_COLUMN_ALIASES.get(column.strip().lower())


def _normalize_csv_row(row: dict[str, str], field_map: dict[str, str | None]) -> dict[str, str]:
    normalized: dict[str, str] = {}
    for key, value in row.items():
        if key is None:
            continue
        canonical = field_map.get(key)
        if canonical is not None and canonical not in normalized:
            normalized[canonical] = value
    return normalized


def _normalize_binance_kline_row(row: Sequence[str]) -> dict[str, str]:
    if len(row) < 6:
        raise ValueError("native Binance kline rows require at least 6 columns")
    return {
        "timestamp": row[0],
        "open": row[1],
        "high": row[2],
        "low": row[3],
        "close": row[4],
        "volume": row[5],
    }


def _row_is_header(row: Sequence[str]) -> bool:
    canonical_columns = {_canonical_csv_column(column) for column in row}
    if all(column in canonical_columns for column in REQUIRED_CSV_COLUMNS):
        return True
    return any(any(character.isalpha() for character in column) for column in row)


def _parse_csv_timeframe(value: str | int | Timeframe) -> Timeframe:
    """Parse CSV timeframe values such as 1, 1M, or 60M."""
    if isinstance(value, Timeframe):
        return value
    if isinstance(value, int):
        return Timeframe(value)
    stripped = str(value).strip().upper()
    if stripped.endswith("M"):
        return Timeframe.parse(stripped)
    return Timeframe(int(stripped))


def _parse_csv_timestamp(value: str) -> datetime:
    """Parse ISO or epoch timestamp values from CSV."""
    stripped = value.strip()
    if stripped.isdigit():
        numeric = int(stripped)
        if numeric > 10_000_000_000_000_000:
            return datetime.fromtimestamp(numeric / 1_000_000_000, tz=timezone.utc)
        if numeric > 10_000_000_000_000:
            return datetime.fromtimestamp(numeric / 1_000_000, tz=timezone.utc)
        if numeric > 10_000_000_000:
            return datetime.fromtimestamp(numeric / 1000, tz=timezone.utc)
        return datetime.fromtimestamp(numeric, tz=timezone.utc)
    return datetime.fromisoformat(stripped.replace("Z", "+00:00"))
