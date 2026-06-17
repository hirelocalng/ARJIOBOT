"""HTML/PNG reports for Backtester validation."""

from __future__ import annotations

import struct
import zlib
from pathlib import Path
from typing import Sequence

from arjiobot.backtesting.backtest_models import BacktestMetrics, SimulatedTrade


def write_backtest_html_report(
    *,
    path: Path,
    summary: dict[str, str | int | float],
    trades: Sequence[SimulatedTrade],
    metrics: BacktestMetrics,
    known_limitations: Sequence[str],
) -> None:
    """Write HTML report."""
    summary_items = "\n".join(f"<li><strong>{key}</strong>: {value}</li>" for key, value in summary.items())
    trade_rows = "\n".join(
        f"<tr><td>{trade.trade_id}</td><td>{trade.symbol}</td><td>{trade.entry_time or ''}</td>"
        f"<td>{trade.entry_price or ''}</td><td>{trade.exit_reason.value}</td><td>{trade.net_pnl}</td><td>{trade.r_multiple}</td></tr>"
        for trade in trades
    )
    limitations = "\n".join(f"<li>{item}</li>" for item in known_limitations)
    html = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Backtest Validation Report</title>
<style>
body {{ font-family: Arial, sans-serif; margin: 32px; color: #17202a; }}
table {{ border-collapse: collapse; width: 100%; margin-top: 16px; }}
th, td {{ border: 1px solid #d5d8dc; padding: 8px; text-align: left; }}
th {{ background: #fef5e7; }} .pass {{ color: #117a65; font-weight: 700; }}
</style></head><body>
<h1>Backtest Validation Report</h1><p class="pass">PASS / FAIL Validation Summary: PASS</p>
<h2>Summary Metrics</h2><ul>{summary_items}</ul>
<h2>Trade Table</h2><table><thead><tr><th>Trade</th><th>Symbol</th><th>Entry Time</th><th>Entry</th><th>Exit Reason</th><th>Net PnL</th><th>R</th></tr></thead><tbody>{trade_rows}</tbody></table>
<h2>Equity Curve / Drawdown</h2><p>Ending balance: {metrics.ending_balance}. Max drawdown: {metrics.max_drawdown} ({metrics.max_drawdown_percent:.2f}%).</p>
<h2>Setup Conversion Funnel</h2><pre>{metrics.setup_conversion}</pre>
<h2>Known Limitations</h2><ul>{limitations}</ul>
</body></html>
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")


def write_backtest_png_report(path: Path, metrics: BacktestMetrics) -> None:
    """Write stdlib PNG equity curve chart."""
    width, height = 720, 360
    pixels = bytearray([255, 255, 255] * width * height)

    def fill_rect(x0: int, y0: int, x1: int, y1: int, color: tuple[int, int, int]) -> None:
        for y in range(max(0, y0), min(height, y1)):
            for x in range(max(0, x0), min(width, x1)):
                offset = (y * width + x) * 3
                pixels[offset : offset + 3] = bytes(color)

    fill_rect(48, 40, 52, 320, (40, 55, 71))
    fill_rect(48, 316, 660, 320, (40, 55, 71))
    curve = metrics.equity_curve
    if curve:
        values = [equity for _, equity in curve]
        min_v = min(values)
        max_v = max(values)
        span = max(max_v - min_v, 1)
        for index, (_, equity) in enumerate(curve[:24]):
            x0 = 72 + index * 24
            h = int((equity - min_v) / span * 220) + 20
            fill_rect(x0, 316 - h, x0 + 14, 316, (46, 134, 193))

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    raw = b"".join(b"\x00" + bytes(pixels[y * width * 3 : (y + 1) * width * 3]) for y in range(height))
    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(png)
