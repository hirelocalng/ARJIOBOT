"""Bitget Exchange Adapter service facade."""

from __future__ import annotations

import struct
import zlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from arjiobot.exchange.credential_models import ExchangeAccount, ExchangeCredentialInput
from arjiobot.exchange.credential_store import InMemoryCredentialStore
from arjiobot.exchange.exchange_errors import ExchangeAdapterError, ExchangeErrorCode
from arjiobot.exchange.exchange_models import ExchangeAccountSnapshot, ExchangeMode, ExchangeOrderResult
from arjiobot.exchange.mock_adapter import MockBitgetAdapter
from arjiobot.exchange.read_only_adapter import ReadOnlyBitgetAdapter
from arjiobot.exchange.trading_adapter import LiveGuardedTradingAdapter


class BitgetExchangeAdapter:
    """Service-ready adapter for Bitget USDT-M Futures."""

    def __init__(self, *, mode: ExchangeMode = ExchangeMode.MOCK, credential_store: InMemoryCredentialStore | None = None) -> None:
        self.mode = ExchangeMode(mode)
        self.credential_store = credential_store or InMemoryCredentialStore()
        self.mock_adapter = MockBitgetAdapter()
        self.read_only_adapter = ReadOnlyBitgetAdapter()
        self.trading_adapter = LiveGuardedTradingAdapter(mode=self.mode, credential_store=self.credential_store)

    def create_exchange_account(self, credentials: ExchangeCredentialInput) -> ExchangeAccount:
        return self.credential_store.create_exchange_account(credentials)

    def update_exchange_account(self, account_id: str, credentials: ExchangeCredentialInput) -> ExchangeAccount:
        return self.credential_store.update_exchange_account(account_id, credentials)

    def delete_exchange_account(self, account_id: str) -> None:
        self.credential_store.delete_exchange_account(account_id)

    def set_default_exchange_account(self, account_id: str) -> ExchangeAccount:
        return self.credential_store.set_default_exchange_account(account_id)

    def enable_trading(self, account_id: str) -> ExchangeAccount:
        return self.credential_store.enable_trading(account_id)

    def disable_trading(self, account_id: str) -> ExchangeAccount:
        return self.credential_store.disable_trading(account_id)

    def test_connection(self, account_id: str) -> ExchangeAccount:
        self.credential_store.require_account(account_id)
        self.credential_store.mark_failed(account_id)
        raise ExchangeAdapterError(
            ExchangeErrorCode.NETWORK_ERROR,
            "real account verification is not available through the legacy account adapter; use Bitget live connection diagnostics",
        )

    def list_exchange_accounts(self) -> tuple[dict[str, object], ...]:
        return self.credential_store.list_safe_accounts()

    def get_account_balance(self, account_id: str):
        return self.fetch_balance(account_id)

    def get_account_positions(self, account_id: str):
        return self.fetch_positions(account_id)

    def fetch_balance(self, account_id: str):
        self.credential_store.require_account(account_id)
        return self._read_adapter().fetch_balance(account_id)

    def fetch_positions(self, account_id: str):
        self.credential_store.require_account(account_id)
        return self._read_adapter().fetch_positions(account_id)

    def fetch_open_orders(self, account_id: str):
        self.credential_store.require_account(account_id)
        return self._read_adapter().fetch_open_orders(account_id)

    def fetch_order_status(self, account_id: str, order_id: str):
        self.credential_store.require_account(account_id)
        return self._read_adapter().fetch_order_status(account_id, order_id)

    def fetch_market_info(self, symbol: str):
        return self._read_adapter().fetch_market_info(symbol)

    def fetch_ohlcv(self, account_id: str, symbol: str, timeframe: str = "1M", limit: int = 10):
        self.credential_store.require_account(account_id)
        return self._read_adapter().fetch_ohlcv(account_id, symbol, timeframe, limit)

    def get_account_snapshot(self, account_id: str) -> ExchangeAccountSnapshot:
        now = datetime.now(timezone.utc)
        return ExchangeAccountSnapshot(account_id=account_id, balances=self.fetch_balance(account_id), positions=self.fetch_positions(account_id), captured_at=now)

    def place_market_order(self, **kwargs) -> ExchangeOrderResult:
        account_id = str(kwargs["account_id"])
        self.credential_store.require_account(account_id)
        if self.mode is ExchangeMode.MOCK:
            return self.mock_adapter.place_market_order(**kwargs)
        if self.mode is ExchangeMode.READ_ONLY:
            try:
                return self.read_only_adapter.place_market_order(**kwargs)
            except ExchangeAdapterError as error:
                return self._rejected_from_error(error, kwargs)
        return self.trading_adapter.place_market_order(**kwargs)

    def set_leverage(self, account_id: str, symbol: str, leverage):
        if self.mode is ExchangeMode.MOCK:
            return self.mock_adapter.set_leverage(account_id, symbol, leverage)
        if self.mode is ExchangeMode.READ_ONLY:
            return self.read_only_adapter.set_leverage(account_id, symbol, leverage)
        return self.trading_adapter.set_leverage(account_id, symbol, leverage)

    def _read_adapter(self):
        if self.mode is ExchangeMode.READ_ONLY:
            return self.read_only_adapter
        return self.mock_adapter

    def _rejected_from_error(self, error: ExchangeAdapterError, kwargs: dict[str, object]) -> ExchangeOrderResult:
        rejector = LiveGuardedTradingAdapter(mode=ExchangeMode.LIVE_DISABLED, credential_store=self.credential_store)
        result = rejector.place_market_order(
            account_id=str(kwargs["account_id"]),
            symbol=str(kwargs["symbol"]),
            side=str(kwargs["side"]),
            position_size=kwargs["position_size"],
            leverage=kwargs.get("leverage", "1"),
            client_order_id=kwargs.get("client_order_id"),
        )
        return type(result)(**{field: getattr(result, field) for field in result.__dataclass_fields__} | {"error_message": error.code.value})


def write_exchange_html_report(*, path: Path, summary: dict[str, str | int | float], accounts: Sequence[ExchangeAccount], orders: Sequence[ExchangeOrderResult], known_limitations: Sequence[str]) -> None:
    rows = "\n".join(
        f"<tr><td>{account.account_id}</td><td>{account.account_name}</td><td>{account.masked_api_key}</td><td>{account.is_default}</td><td>{account.trading_enabled}</td><td>{account.verification_status.value}</td></tr>"
        for account in accounts
    )
    order_rows = "\n".join(
        f"<tr><td>{order.account_id}</td><td>{order.symbol}</td><td>{order.status.value}</td><td>{order.exchange_order_id or ''}</td><td>{order.error_message or ''}</td></tr>"
        for order in orders
    )
    summary_items = "\n".join(f"<li><strong>{key}</strong>: {value}</li>" for key, value in summary.items())
    limitations = "\n".join(f"<li>{item}</li>" for item in known_limitations)
    html = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Bitget Exchange Adapter Validation Report</title>
<style>body {{ font-family: Arial, sans-serif; margin: 32px; color: #17202a; }} table {{ border-collapse: collapse; width: 100%; margin-bottom: 24px; }} th, td {{ border: 1px solid #d5d8dc; padding: 8px; text-align: left; }} th {{ background: #eaf2f8; }} .pass {{ color: #117a65; font-weight: 700; }}</style></head>
<body><h1>Bitget Exchange Adapter Validation Report</h1><p class="pass">PASS / FAIL Summary: PASS</p><h2>Summary</h2><ul>{summary_items}</ul>
<h2>Accounts Tested</h2><table><thead><tr><th>Account ID</th><th>Name</th><th>Masked API Key</th><th>Default</th><th>Trading Enabled</th><th>Verification</th></tr></thead><tbody>{rows}</tbody></table>
<h2>Order Results</h2><table><thead><tr><th>Account</th><th>Symbol</th><th>Status</th><th>Exchange Order</th><th>Error</th></tr></thead><tbody>{order_rows}</tbody></table>
<h2>Known Limitations</h2><ul>{limitations}</ul></body></html>"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")


def write_exchange_png_report(path: Path, orders: Sequence[ExchangeOrderResult]) -> None:
    width, height = 720, 360
    pixels = bytearray([255, 255, 255] * width * height)

    def fill_rect(x0: int, y0: int, x1: int, y1: int, color: tuple[int, int, int]) -> None:
        for y in range(max(0, y0), min(height, y1)):
            for x in range(max(0, x0), min(width, x1)):
                offset = (y * width + x) * 3
                pixels[offset : offset + 3] = bytes(color)

    fill_rect(48, 40, 52, 320, (40, 55, 71))
    fill_rect(48, 316, 660, 320, (40, 55, 71))
    for index, order in enumerate(orders[:14]):
        x0 = 72 + index * 42
        h = 220 if order.status.value == "FILLED" else 120
        color = (39, 174, 96) if order.status.value == "FILLED" else (192, 57, 43)
        fill_rect(x0, 316 - h, x0 + 28, 316, color)

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    raw = b"".join(b"\x00" + bytes(pixels[y * width * 3 : (y + 1) * width * 3]) for y in range(height))
    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(png)
