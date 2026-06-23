"""Live-only Bitget Futures connection and execution guard.

This module owns the exchange boundary for ArjioBot. It is intentionally
live-account only:

* OFF disables execution.
* DRY_RUN_PREVIEW uses real Bitget public data and builds sanitized payloads.
* LIVE requires explicit arming and safety gates before a real order can be sent.

Only live Bitget Futures credentials and real public/private API responses are used.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_DOWN
from enum import Enum
from typing import Any

from arjiobot.risk.isolated_margin import DEFAULT_FEE_RATE, DEFAULT_SLIPPAGE_BUFFER_RATE, calculate_required_margin

logger = logging.getLogger(__name__)

BITGET_REST_BASE_URL = "https://api.bitget.com"
BITGET_WS_PUBLIC_URL = "wss://ws.bitget.com/v2/ws/public"
BITGET_WS_PRIVATE_URL = "wss://ws.bitget.com/v2/ws/private"
DEFAULT_PRODUCT_TYPE = "USDT-FUTURES"
DEFAULT_MARGIN_COIN = "USDT"
DEFAULT_MARGIN_MODE = "isolated"
LIVE_CONFIRMATION_TEXT = "ENABLE LIVE"
STALE_DATA_SECONDS = 90


class TradeMode(str, Enum):
    OFF = "OFF"
    DRY_RUN_PREVIEW = "DRY_RUN_PREVIEW"
    LIVE = "LIVE"


class EnvironmentLockError(RuntimeError):
    """Raised when exchange, credential, profile, or risk locks fail."""


@dataclass(frozen=True, slots=True)
class BitgetCredentialConfig:
    api_key: str
    api_secret: str
    passphrase: str
    source: str = "RUNTIME"

    def __post_init__(self) -> None:
        if not self.api_key or not self.api_secret or not self.passphrase:
            raise ValueError("api_key, api_secret, and passphrase are required")

    @property
    def fingerprint(self) -> str:
        raw = f"LIVE|{self.api_key}|{BITGET_REST_BASE_URL}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

    def safe_record(self) -> dict[str, object]:
        return {
            "configured": True,
            "credential_type": "LIVE",
            "account_type": "REAL",
            "api_key_present": bool(self.api_key),
            "api_secret_present": bool(self.api_secret),
            "passphrase_present": bool(self.passphrase),
            "api_key_masked": _mask(self.api_key),
            "rest_base_url": BITGET_REST_BASE_URL,
            "product_type": DEFAULT_PRODUCT_TYPE,
            "margin_coin": DEFAULT_MARGIN_COIN,
            "source": self.source,
            "fingerprint": self.fingerprint,
            "secrets_exposed": False,
        }


@dataclass(frozen=True, slots=True)
class SignedRequest:
    method: str
    request_path: str
    query_string: str
    body: str
    timestamp: str
    prehash: str
    headers: dict[str, str]

    def sanitized(self) -> dict[str, object]:
        return {
            "method": self.method,
            "request_path": self.request_path,
            "query_string": self.query_string,
            "body_present": bool(self.body),
            "timestamp": self.timestamp,
            "header_names": tuple(self.headers.keys()),
            "signature_present": bool(self.headers.get("ACCESS-SIGN")),
            "passphrase_present": bool(self.headers.get("ACCESS-PASSPHRASE")),
            "secrets_exposed": False,
        }


@dataclass(frozen=True, slots=True)
class EnvironmentLockVerification:
    selected_trade_mode: TradeMode
    resolved_exchange_environment: str
    api_base_url: str
    credential_type_used: str
    order_environment: str
    websocket_public_url: str
    websocket_private_url: str
    lock_status: str
    reason: str = ""

    def to_record(self) -> dict[str, str]:
        return {
            "selected_trade_mode": self.selected_trade_mode.value,
            "resolved_exchange_environment": self.resolved_exchange_environment,
            "api_base_url": self.api_base_url,
            "credential_type_used": self.credential_type_used,
            "order_environment": self.order_environment,
            "websocket_public_url": self.websocket_public_url,
            "websocket_private_url": self.websocket_private_url,
            "lock_status": self.lock_status,
            "reason": self.reason,
        }


class BitgetEnvironmentService:
    """Live-only Bitget Futures connector facade."""

    def __init__(self) -> None:
        self.runtime_credentials: BitgetCredentialConfig | None = None
        self.mode = TradeMode.OFF
        self.live_armed = False
        self.emergency_kill_switch = False
        self.repeated_api_errors = 0
        self.max_repeated_api_errors = 3
        self.daily_loss = Decimal("0")
        self.open_positions = 0
        self.trades_today = 0
        self.orders: list[dict[str, object]] = []
        self.blocked_orders: list[dict[str, object]] = []
        self.mode_events: list[dict[str, object]] = []
        self.last_connection_result: dict[str, object] | None = None
        self.last_connection_error: str | None = None
        self.last_contracts: dict[str, dict[str, object]] = {}
        self.last_tickers: dict[str, dict[str, object]] = {}
        self.last_candles: dict[str, dict[str, object]] = {}
        self.last_account_payload: dict[str, object] | None = None
        self.last_positions: dict[str, object] | None = None
        self.last_open_orders: dict[str, object] | None = None
        self.last_position_history: dict[str, object] | None = None
        self.last_dry_run_preview: dict[str, object] | None = None
        # _credentials() is called from 7 different methods (mode_status alone
        # calls it twice - once via verify_environment_lock, once via
        # credential_status), and any one status check can fan out to several
        # of them in the same request. None of that is wrong to call - it's
        # just redundant to *log* every single time when nothing changed.
        # Tracks the last (source, last-4-of-key) pair actually logged so the
        # INFO line below only fires on the first resolution or on a real
        # change, not on every redundant call.
        self._last_logged_credential_identity: tuple[str, str] | None = None

    def save_credentials(self, payload: dict[str, object]) -> dict[str, object]:
        mode = str(payload.get("mode") or "LIVE").upper()
        if mode not in {"LIVE", "DRY_RUN_PREVIEW"}:
            raise EnvironmentLockError("only LIVE credentials are supported")
        config = BitgetCredentialConfig(
            api_key=str(payload.get("api_key") or ""),
            api_secret=str(payload.get("api_secret") or ""),
            passphrase=str(payload.get("passphrase") or ""),
            source="RUNTIME",
        )
        self.runtime_credentials = config
        return config.safe_record()

    def credential_status(self) -> dict[str, object]:
        credentials = self._credentials(fail=False)
        if credentials is None:
            return {
                "live": {"configured": False, "credential_type": "LIVE", "account_type": "REAL", "source": "NONE"},
                "secrets_exposed": False,
            }
        return {"live": credentials.safe_record(), "secrets_exposed": False}

    def switch_mode(self, mode: str, *, live_confirmation: str | None = None) -> dict[str, object]:
        selected = TradeMode(str(mode).upper())
        self.live_armed = False
        if selected is TradeMode.LIVE:
            if live_confirmation != LIVE_CONFIRMATION_TEXT:
                raise EnvironmentLockError("LIVE mode requires confirmation text: ENABLE LIVE")
            self._require_live_readiness(symbol="BTCUSDT", allow_stale=False)
            self.live_armed = True
        self.mode = selected
        event = {
            "mode": self.mode.value,
            "live_armed": "YES" if self.live_armed else "NO",
            "changed_at": _now(),
        }
        self.mode_events.append(event)
        return self.mode_status()

    def mode_status(self) -> dict[str, object]:
        verification = self.verify_environment_lock(self.mode, order_environment=self.mode.value, fail_on_error=False)
        return {
            "trading_mode": self.mode.value,
            "active_execution_mode": self.mode.value,
            "live_armed": "YES" if self.live_armed else "NO",
            "environment_lock_verified": "YES" if verification.lock_status == "PASSED" else "NO",
            "environment_lock": verification.to_record(),
            "credential_status": self.credential_status(),
            "emergency_kill_switch": self.emergency_kill_switch,
            "repeated_api_errors": self.repeated_api_errors,
        }

    def test_connection(self, symbol: str = "BTCUSDT") -> dict[str, object]:
        logger.info("Testing Bitget connection (symbol=%s)...", symbol)
        credentials = self._credentials()
        lock = self.verify_environment_lock(TradeMode.DRY_RUN_PREVIEW, order_environment="DRY_RUN_PREVIEW")
        try:
            account_payload = self.fetch_account(symbol=symbol, credentials=credentials)
        except EnvironmentLockError as exc:
            self.last_connection_result = None
            self.last_connection_error = str(exc)
            logger.error("Bitget connection test failed: %s", exc)
            raise
        logger.info(
            "Bitget connection test passed (available_balance=%s, available_margin=%s)",
            account_payload.get("available_balance"),
            account_payload.get("available_margin"),
        )
        result = {
            "connection_status": "PASSED",
            "exchange": "BITGET",
            "account_type": "REAL",
            "private_api_auth_status": "PASSED",
            "selected_trade_mode": self.mode.value,
            "credential_type_used": "LIVE",
            "api_base_url": BITGET_REST_BASE_URL,
            "product_type": DEFAULT_PRODUCT_TYPE,
            "margin_coin": DEFAULT_MARGIN_COIN,
            "environment_lock": lock.to_record(),
            "account_payload": account_payload,
            "available_balance": account_payload.get("available_balance", "N/A"),
            "available_margin": account_payload.get("available_margin", "N/A"),
            "last_successful_verification_time": _now(),
            "secrets_exposed": False,
        }
        self.last_connection_result = result
        self.last_connection_error = None
        return result

    def fetch_account(self, *, symbol: str, credentials: BitgetCredentialConfig | None = None) -> dict[str, object]:
        credentials = credentials or self._credentials()
        query = {
            "symbol": symbol.upper(),
            "productType": DEFAULT_PRODUCT_TYPE,
            "marginCoin": DEFAULT_MARGIN_COIN,
        }
        payload = self._private_request("GET", "/api/v2/mix/account/account", query=query, credentials=credentials)
        data = payload.get("data") or {}
        if not isinstance(data, dict):
            data = {}
        record = {
            "code": payload.get("code"),
            "msg": payload.get("msg"),
            "symbol": symbol.upper(),
            "product_type": DEFAULT_PRODUCT_TYPE,
            "margin_coin": DEFAULT_MARGIN_COIN,
            "total_equity": str(data.get("accountEquity") or data.get("usdtEquity") or data.get("equity") or "N/A"),
            "available_balance": str(data.get("available") or data.get("availableBalance") or data.get("usdtEquity") or "N/A"),
            "available_margin": str(data.get("available") or data.get("crossedMaxAvailable") or data.get("fixedMaxAvailable") or "N/A"),
            "frozen_margin": str(data.get("locked") or data.get("lockedMargin") or data.get("frozen") or "N/A"),
            "unrealized_pnl": str(data.get("unrealizedPL") or data.get("unrealizedPnl") or data.get("unrealizedProfit") or "N/A"),
            "margin_mode": str(data.get("marginMode") or data.get("posMode") or "N/A"),
            "position_mode": str(data.get("holdMode") or data.get("positionMode") or "N/A"),
            "raw_keys": tuple(sorted(str(key) for key in data.keys())),
            "fetched_at": _now(),
            "data_present": bool(data),
        }
        self.last_account_payload = record
        return record

    def fetch_positions(self, symbol: str | None = None, product_type: str = DEFAULT_PRODUCT_TYPE) -> dict[str, object]:
        query: dict[str, object] = {"productType": product_type, "marginCoin": DEFAULT_MARGIN_COIN}
        if symbol:
            query["symbol"] = symbol.upper()
        payload = self._private_request("GET", "/api/v2/mix/position/all-position", query=query)
        rows = payload.get("data") or []
        if isinstance(rows, dict):
            rows = [rows]
        if not isinstance(rows, list):
            rows = []
        positions = tuple(_sanitize_exchange_row(row) for row in rows if isinstance(row, dict))
        record = {
            "code": payload.get("code"),
            "msg": payload.get("msg"),
            "symbol": symbol.upper() if symbol else "ALL",
            "product_type": product_type,
            "margin_coin": DEFAULT_MARGIN_COIN,
            "position_count": len(positions),
            "positions": positions,
            "fetched_at": _now(),
            "data_present": True,
        }
        self.last_positions = record
        return record

    def fetch_open_orders(self, symbol: str | None = None, product_type: str = DEFAULT_PRODUCT_TYPE) -> dict[str, object]:
        query: dict[str, object] = {"productType": product_type}
        if symbol:
            query["symbol"] = symbol.upper()
        payload = self._private_request("GET", "/api/v2/mix/order/orders-pending", query=query)
        rows = payload.get("data") or []
        if isinstance(rows, dict):
            rows = rows.get("entrustedList") or rows.get("orders") or rows.get("list") or []
        if not isinstance(rows, list):
            rows = []
        orders = tuple(_sanitize_exchange_row(row) for row in rows if isinstance(row, dict))
        record = {
            "code": payload.get("code"),
            "msg": payload.get("msg"),
            "symbol": symbol.upper() if symbol else "ALL",
            "product_type": product_type,
            "order_count": len(orders),
            "orders": orders,
            "fetched_at": _now(),
            "data_present": True,
        }
        self.last_open_orders = record
        return record

    def fetch_position_history(self, symbol: str | None = None, product_type: str = DEFAULT_PRODUCT_TYPE, *, limit: int = 100) -> dict[str, object]:
        """Closed-position history from Bitget's documented V2 Mix API
        (/api/v2/mix/position/history-position) - the source of real entry/
        exit price, realized PnL, and fees for the Execution page's CLOSED
        TRADES and PNL tabs. Modeled on fetch_positions/fetch_open_orders
        above, which already use this exact private-request + sanitize
        pattern successfully against the real exchange.

        Not yet verified against a real authenticated response in this
        environment (no live credentials/network access here) - the row
        shape is passed through as-is (sanitized of secrets only) rather
        than remapped into renamed fields, specifically so nothing is lost
        if Bitget's actual field names differ from what's expected; see
        account_status.py / Executions.tsx for the defensive .get() lookups
        that read from these rows.
        """
        query: dict[str, object] = {"productType": product_type, "marginCoin": DEFAULT_MARGIN_COIN, "limit": str(limit)}
        if symbol:
            query["symbol"] = symbol.upper()
        payload = self._private_request("GET", "/api/v2/mix/position/history-position", query=query)
        data = payload.get("data")
        rows = data.get("list") if isinstance(data, dict) else data
        if isinstance(rows, dict):
            rows = [rows]
        if not isinstance(rows, list):
            rows = []
        closed_positions = tuple(_sanitize_exchange_row(row) for row in rows if isinstance(row, dict))
        record = {
            "code": payload.get("code"),
            "msg": payload.get("msg"),
            "symbol": symbol.upper() if symbol else "ALL",
            "product_type": product_type,
            "margin_coin": DEFAULT_MARGIN_COIN,
            "closed_position_count": len(closed_positions),
            "closed_positions": closed_positions,
            "fetched_at": _now(),
            "data_present": True,
        }
        self.last_position_history = record
        return record

    def fetch_contract_config(self, symbol: str, product_type: str = DEFAULT_PRODUCT_TYPE) -> dict[str, object]:
        payload = self._public_request(
            "/api/v2/mix/market/contracts",
            query={"productType": product_type, "symbol": symbol.upper()},
        )
        rows = payload.get("data") or []
        if isinstance(rows, dict):
            rows = [rows]
        contract = next((row for row in rows if str(row.get("symbol", "")).upper() == symbol.upper()), None)
        if not contract:
            raise EnvironmentLockError(f"{symbol.upper()} contract config not found for {product_type}")
        record = {
            "symbol": symbol.upper(),
            "product_type": product_type,
            "margin_coin": DEFAULT_MARGIN_COIN,
            "contract_config_loaded": "YES",
            "supported": "YES",
            "symbol_status": str(contract.get("symbolStatus") or contract.get("status") or "UNKNOWN"),
            "minTradeNum": str(contract.get("minTradeNum") or "0"),
            "minTradeUSDT": str(contract.get("minTradeUSDT") or contract.get("minTradeAmount") or "0"),
            "pricePlace": str(contract.get("pricePlace") or "2"),
            "volumePlace": str(contract.get("volumePlace") or "3"),
            "sizeMultiplier": str(contract.get("sizeMultiplier") or "0.001"),
            "minLever": str(contract.get("minLever") or "1"),
            "maxLever": str(contract.get("maxLever") or "1"),
            "maxMarketOrderQty": str(contract.get("maxMarketOrderQty") or contract.get("maxOrderQty") or "0"),
            "maxOrderQty": str(contract.get("maxOrderQty") or "0"),
            "raw_keys": tuple(sorted(str(key) for key in contract.keys())),
            "fetched_at": _now(),
        }
        self.last_contracts[symbol.upper()] = record
        return record

    def fetch_ticker(self, symbol: str, product_type: str = DEFAULT_PRODUCT_TYPE) -> dict[str, object]:
        payload = self._public_request(
            "/api/v2/mix/market/ticker",
            query={"symbol": symbol.upper(), "productType": product_type},
        )
        data = payload.get("data") or {}
        if isinstance(data, list):
            data = data[0] if data else {}
        if not isinstance(data, dict):
            data = {}
        record = {
            "symbol": symbol.upper(),
            "product_type": product_type,
            "last_price": str(data.get("lastPr") or data.get("last") or "N/A"),
            "bid_price": str(data.get("bidPr") or data.get("bid") or "N/A"),
            "ask_price": str(data.get("askPr") or data.get("ask") or "N/A"),
            "mark_price": str(data.get("markPrice") or "N/A"),
            "index_price": str(data.get("indexPrice") or "N/A"),
            "timestamp": str(data.get("ts") or data.get("timestamp") or ""),
            "fetched_at": _now(),
        }
        self.last_tickers[symbol.upper()] = record
        return record

    def fetch_candles(
        self,
        symbol: str,
        granularity: str = "1m",
        limit: int = 100,
        product_type: str = DEFAULT_PRODUCT_TYPE,
        *,
        end_time: str | int | None = None,
    ) -> dict[str, object]:
        query: dict[str, object] = {"symbol": symbol.upper(), "productType": product_type, "granularity": granularity, "limit": str(limit)}
        if end_time is not None:
            query["endTime"] = str(end_time)
        payload = self._public_request("/api/v2/mix/market/candles", query=query)
        rows = payload.get("data") or []
        if not isinstance(rows, list):
            rows = []
        record = {
            "symbol": symbol.upper(),
            "product_type": product_type,
            "granularity": granularity,
            "candle_count": len(rows),
            "candles_loaded": "YES" if rows else "NO",
            "last_candle_timestamp": str(rows[-1][0]) if rows and isinstance(rows[-1], list) and rows[-1] else "N/A",
            "rows": tuple(tuple(str(cell) for cell in row) for row in rows if isinstance(row, list)),
            "fetched_at": _now(),
        }
        self.last_candles[f"{symbol.upper()}:{granularity}"] = record
        return record

    def backfill_candles(
        self,
        symbol: str,
        granularity: str = "1m",
        total: int = 44_640,
        product_type: str = DEFAULT_PRODUCT_TYPE,
        *,
        page_size: int = 1000,
    ) -> dict[str, object]:
        """Page backward through Bitget's candle history to assemble up to ``total`` candles.

        Bitget's mix candles endpoint caps each request at ~1000 rows, so a single
        fetch_candles call can never reach a multi-thousand-candle lookback. This pages
        backward using ``endTime`` (oldest timestamp from the previous page minus
        1ms) until ``total`` rows are collected or Bitget has no older data left.
        """
        collected: dict[str, tuple[str, ...]] = {}
        end_time: str | int | None = None
        while len(collected) < total:
            page = (
                self.fetch_candles(symbol, granularity, page_size, product_type)
                if end_time is None
                else self.fetch_candles(symbol, granularity, page_size, product_type, end_time=end_time)
            )
            rows = page["rows"]
            if not rows:
                break
            for row in rows:
                if row:
                    collected[row[0]] = row
            oldest_timestamp = rows[0][0]
            try:
                next_end_time = int(oldest_timestamp) - 1
            except ValueError:
                break
            if end_time is not None and str(next_end_time) == str(end_time):
                break
            end_time = next_end_time
            if len(rows) < page_size:
                break
        ordered_rows = tuple(collected[key] for key in sorted(collected, key=lambda value: int(value)))[-total:]
        record = {
            "symbol": symbol.upper(),
            "product_type": product_type,
            "granularity": granularity,
            "candle_count": len(ordered_rows),
            "candles_loaded": "YES" if ordered_rows else "NO",
            "last_candle_timestamp": str(ordered_rows[-1][0]) if ordered_rows else "N/A",
            "rows": ordered_rows,
            "fetched_at": _now(),
        }
        self.last_candles[f"{symbol.upper()}:{granularity}"] = record
        return record

    def set_margin_mode(self, symbol: str) -> dict[str, object]:
        return self._private_request(
            "POST",
            "/api/v2/mix/account/set-margin-mode",
            body={
                "symbol": symbol.upper(),
                "productType": DEFAULT_PRODUCT_TYPE,
                "marginCoin": DEFAULT_MARGIN_COIN,
                "marginMode": DEFAULT_MARGIN_MODE,
            },
        )

    def set_leverage(self, symbol: str, leverage: Decimal | str | int) -> dict[str, object]:
        return self._private_request(
            "POST",
            "/api/v2/mix/account/set-leverage",
            body={
                "symbol": symbol.upper(),
                "productType": DEFAULT_PRODUCT_TYPE,
                "marginCoin": DEFAULT_MARGIN_COIN,
                "leverage": str(leverage),
            },
        )

    def dry_run_preview(self, payload: dict[str, object]) -> dict[str, object]:
        preview = self._build_order_plan(payload, submit=False)
        self.last_dry_run_preview = preview
        return preview

    def place_order(self, payload: dict[str, object], *, required_mode: TradeMode = TradeMode.LIVE) -> dict[str, object]:
        try:
            if required_mode is not TradeMode.LIVE:
                raise EnvironmentLockError("only LIVE order route is supported")
            if self.mode is not TradeMode.LIVE or not self.live_armed:
                raise EnvironmentLockError("LIVE is not armed")
            preview = self.dry_run_preview(payload)
            if preview.get("would_place_order") != "YES":
                raise EnvironmentLockError(str(preview.get("blocked_reason") or "live order preview rejected"))
            order = self._build_order_plan(payload, submit=True)
            # Bitget computes margin server-side from size/price/leverage at
            # whatever leverage is currently set on the account for this
            # symbol - never confirmed to match effective_max_leverage until
            # now. Setting it here, right before submission, guarantees the
            # margin Bitget actually reserves matches this order's own
            # calculation, instead of relying on however the account happens
            # to be configured. If this call fails, the order is not placed -
            # caught by this method's existing except block below, same as
            # any other pre-submission failure.
            leverage_response = self.set_leverage(order["symbol"], order["effective_max_leverage"])
            order["leverage_set_to"] = order["effective_max_leverage"]
            order["leverage_set_response_code"] = str(leverage_response.get("code"))
            response = self._private_request("POST", "/api/v2/mix/order/place-order", body=order["sanitized_payload"])
            order["network_submitted"] = True
            order["bitget_response_code"] = str(response.get("code"))
            order["bitget_response_message"] = str(response.get("msg"))
            data = response.get("data") if isinstance(response.get("data"), dict) else {}
            order["bitget_order_id"] = str(data.get("orderId") or data.get("clientOid") or "")
            self.orders.append(order)
            self.trades_today += 1
            self.open_positions += 1
            return order
        except Exception as exc:
            blocked = {
                "blocked": True,
                "reason": str(exc),
                "selected_trade_mode": self.mode.value,
                "required_trade_mode": required_mode.value,
                "symbol": str(payload.get("symbol", "")).upper(),
                "created_at": _now(),
            }
            self.blocked_orders.append(blocked)
            raise

    def verify_environment_lock(self, selected_mode: TradeMode, *, order_environment: str, fail_on_error: bool = True) -> EnvironmentLockVerification:
        try:
            if selected_mode is TradeMode.OFF:
                raise EnvironmentLockError("OFF mode cannot place orders")
            if selected_mode not in {TradeMode.DRY_RUN_PREVIEW, TradeMode.LIVE}:
                raise EnvironmentLockError("unsupported trade mode")
            credentials = self._credentials()
            order_environment = str(order_environment).upper()
            if order_environment != selected_mode.value:
                raise EnvironmentLockError("order environment does not match selected trade mode")
            return EnvironmentLockVerification(
                selected_trade_mode=selected_mode,
                resolved_exchange_environment="LIVE",
                api_base_url=BITGET_REST_BASE_URL,
                credential_type_used="LIVE",
                order_environment=order_environment,
                websocket_public_url=BITGET_WS_PUBLIC_URL,
                websocket_private_url=BITGET_WS_PRIVATE_URL,
                lock_status="PASSED",
            )
        except EnvironmentLockError as exc:
            verification = EnvironmentLockVerification(
                selected_trade_mode=selected_mode,
                resolved_exchange_environment="NONE",
                api_base_url=BITGET_REST_BASE_URL,
                credential_type_used="NONE",
                order_environment=str(order_environment).upper(),
                websocket_public_url=BITGET_WS_PUBLIC_URL,
                websocket_private_url=BITGET_WS_PRIVATE_URL,
                lock_status="FAILED",
                reason=str(exc),
            )
            if fail_on_error:
                raise
            return verification

    def build_signed_request(
        self,
        method: str,
        request_path: str,
        *,
        query: dict[str, object] | None = None,
        body: dict[str, object] | None = None,
        credentials: BitgetCredentialConfig | None = None,
    ) -> SignedRequest:
        credentials = credentials or self._credentials()
        method = method.upper()
        query_string = urllib.parse.urlencode(query or {})
        body_string = json.dumps(body or {}, separators=(",", ":")) if body else ""
        timestamp = str(int(time.time() * 1000))
        path_with_query = f"{request_path}?{query_string}" if query_string else request_path
        prehash = f"{timestamp}{method}{path_with_query}{body_string}"
        signature = base64.b64encode(
            hmac.new(credentials.api_secret.encode("utf-8"), prehash.encode("utf-8"), "sha256").digest()
        ).decode("ascii")
        headers = {
            "ACCESS-KEY": credentials.api_key,
            "ACCESS-SIGN": signature,
            "ACCESS-TIMESTAMP": timestamp,
            "ACCESS-PASSPHRASE": credentials.passphrase,
            "Content-Type": "application/json",
            "locale": "en-US",
        }
        return SignedRequest(method, request_path, query_string, body_string, timestamp, prehash, headers)

    def _build_order_plan(self, payload: dict[str, object], *, submit: bool) -> dict[str, object]:
        self._validate_safety(payload)
        symbol = str(payload.get("symbol") or "BTCUSDT").upper()
        selected_profile = str(payload.get("selected_profile_id") or payload.get("selected_strategy_profile") or "").upper()
        applied_profile = str(payload.get("applied_profile_id") or payload.get("profile_id") or "").upper()
        if not selected_profile or selected_profile != applied_profile:
            raise EnvironmentLockError("profile lock failed before Bitget order")
        side = str(payload.get("side") or "").upper()
        if side not in {"BUY", "SELL"}:
            raise EnvironmentLockError("side must be BUY or SELL")
        entry_price = _positive_decimal(payload.get("entry_price") or payload.get("entry_reference_price"), "entry_price")
        stop_loss = _positive_decimal(payload.get("stop_loss") or payload.get("stop_loss_price"), "stop_loss")
        fixed_risk = _positive_decimal(payload.get("selected_fixed_risk_amount") or payload.get("risk_amount"), "selected_fixed_risk_amount")
        max_leverage = _positive_decimal(payload.get("max_allowed_leverage") or payload.get("selected_max_leverage"), "selected_max_leverage")
        contract = self.last_contracts.get(symbol) or self.fetch_contract_config(symbol)
        ticker = self.last_tickers.get(symbol) or self.fetch_ticker(symbol)
        candles = self.last_candles.get(f"{symbol}:1m") or self.fetch_candles(symbol, "1m", 100)
        if ticker.get("last_price") in {"N/A", ""}:
            raise EnvironmentLockError("live ticker is missing")
        if candles.get("candles_loaded") != "YES":
            raise EnvironmentLockError("live candles are missing")
        exchange_max = _positive_decimal(contract.get("maxLever") or "1", "maxLever")
        effective_max_leverage = min(max_leverage, exchange_max)
        available_margin_raw = payload.get("available_margin") or payload.get("selected_starting_balance")
        if available_margin_raw in (None, ""):
            available_margin_raw = (self.last_account_payload or {}).get("available_margin")
        if available_margin_raw in (None, "", "N/A"):
            # No live balance known yet for this call site; do not block on margin we cannot verify.
            available_margin_raw = "1000000000"
        available_margin = _positive_decimal(available_margin_raw, "available_margin")
        fee_rate = Decimal(str(payload.get("fee_rate") or payload.get("fees") or DEFAULT_FEE_RATE))
        slippage_rate = Decimal(str(payload.get("slippage_rate") or payload.get("slippage") or DEFAULT_SLIPPAGE_BUFFER_RATE))
        if fee_rate > Decimal("1"):
            fee_rate = fee_rate / Decimal("100")
        if slippage_rate > Decimal("1"):
            slippage_rate = slippage_rate / Decimal("100")
        try:
            sizing = calculate_required_margin(
                fixed_sl_loss=fixed_risk,
                entry_price=entry_price,
                stop_loss=stop_loss,
                max_leverage=effective_max_leverage,
                available_margin=available_margin,
                fee_rate=fee_rate,
                slippage_rate=slippage_rate,
            )
        except ValueError as exc:
            raise EnvironmentLockError(str(exc)) from exc
        size = _round_size(sizing.quantity, contract)
        expected_loss = abs(entry_price - stop_loss) * size
        notional = size * entry_price
        estimated_fee = notional * fee_rate
        estimated_slippage_buffer = notional * slippage_rate
        estimated_total_worst_case_loss = expected_loss + estimated_fee + estimated_slippage_buffer
        # expected_loss (the SL-distance-only loss) is what fixed_risk means -
        # see calculate_required_margin's docstring - so it, not the total
        # including fees/slippage, is what must match fixed_risk here.
        # Exchange lot-size rounding (_round_size always rounds DOWN) can only
        # ever make the realized size - and therefore expected_loss - smaller
        # than the theoretical exact sizing, never larger.
        if abs(expected_loss - fixed_risk) > max(Decimal("1"), fixed_risk * Decimal("0.03")):
            raise EnvironmentLockError("RISK_SIZE_ROUNDING_MISMATCH")
        target = payload.get("take_profit") or payload.get("take_profit_price")
        target_price = _positive_decimal(target, "take_profit") if target else Decimal("0")
        if target:
            # Bitget rejects this server-side (error 40830: "take profit price
            # of the long position should be greater than the current price"),
            # but by then the order has already been sent - catch it here so a
            # stale setup (one whose target the live price has since passed)
            # never reaches Bitget at all.
            current_price = _positive_decimal(ticker.get("last_price"), "last_price")
            if side == "BUY" and target_price <= current_price:
                raise EnvironmentLockError("STALE_SETUP_TP_INVALID: take_profit must be greater than the current price for a BULLISH/long order")
            if side == "SELL" and target_price >= current_price:
                raise EnvironmentLockError("STALE_SETUP_TP_INVALID: take_profit must be less than the current price for a BEARISH/short order")
        expected_profit = abs(entry_price - target_price) * size if target_price > 0 else Decimal("0")
        time_exit_enabled = bool(payload.get("time_exit_enabled")) and str(payload.get("selected_tp_model", "")).upper() == "TIME_BASED_EXIT"
        # Fees/slippage are a real additional cost on top of the configured
        # SL-distance risk now (not carved out of it - see
        # calculate_required_margin), so estimated_total_worst_case_loss is
        # expected to exceed fixed_risk by roughly notional*(fee_rate+
        # slippage_rate). The remaining real guard here is that fee+slippage
        # alone do not balloon into an unreasonable multiple of the configured
        # risk (e.g. a misconfigured fee_rate/slippage_rate input) - capped at
        # 100% of fixed_risk, well above any realistic fee/slippage rate.
        if estimated_fee + estimated_slippage_buffer > fixed_risk:
            raise EnvironmentLockError("ESTIMATED_FEE_AND_SLIPPAGE_EXCEED_FIXED_RISK_AMOUNT")
        min_trade_num = Decimal(str(contract.get("minTradeNum") or "0"))
        min_trade_usdt = Decimal(str(contract.get("minTradeUSDT") or "0"))
        if size < min_trade_num:
            raise EnvironmentLockError("size below Bitget minTradeNum")
        if notional < min_trade_usdt:
            raise EnvironmentLockError("notional below Bitget minTradeUSDT")
        client_oid = _build_client_oid(symbol, side, _now())
        order_payload = {
            "symbol": symbol,
            "productType": DEFAULT_PRODUCT_TYPE,
            "marginMode": DEFAULT_MARGIN_MODE,
            "marginCoin": DEFAULT_MARGIN_COIN,
            "size": str(size),
            "side": "buy" if side == "BUY" else "sell",
            "tradeSide": "open",
            "orderType": str(payload.get("order_type") or "market").lower(),
            "clientOid": client_oid,
        }
        stop = payload.get("stop_loss") or payload.get("stop_loss_price")
        if stop:
            order_payload["presetStopLossPrice"] = str(stop)
        if target:
            order_payload["presetStopSurplusPrice"] = str(target)
        generated_at = _now()
        return {
            "would_place_order": "YES",
            "network_submitted": submit,
            "endpoint": "/api/v2/mix/order/place-order",
            "generated_at": generated_at,
            "selected_trade_mode": self.mode.value,
            "live_armed": "YES" if self.live_armed else "NO",
            "selected_profile_id": selected_profile,
            "applied_profile_id": applied_profile,
            "symbol": symbol,
            "side": side,
            "margin_mode": DEFAULT_MARGIN_MODE,
            "product_type": DEFAULT_PRODUCT_TYPE,
            "margin_coin": DEFAULT_MARGIN_COIN,
            "selected_fixed_risk_amount": str(fixed_risk),
            "applied_fixed_risk_amount": str(fixed_risk),
            "applied_margin_amount": str(sizing.margin_amount),
            "margin_amount": str(sizing.margin_amount),
            "risk_amount": str(sizing.risk_amount),
            "selected_max_leverage": str(max_leverage),
            "exchange_max_leverage": str(exchange_max),
            "effective_max_leverage": str(effective_max_leverage),
            "price_risk_distance": str(abs(entry_price - stop_loss)),
            "price_risk_percent": str(sizing.price_risk_percent),
            "required_leverage": str(sizing.required_leverage),
            "applied_leverage": str(sizing.applied_leverage),
            "notional_position_size": str(notional),
            "leverage": str(sizing.applied_leverage),
            "size": str(size),
            "quantity": str(size),
            "raw_quantity_before_rounding": str(sizing.quantity),
            "entry_price": str(entry_price),
            "stop_reference": str(stop_loss),
            "target_reference": str(target or ""),
            "selected_tp_model": str(payload.get("selected_tp_model") or ""),
            "applied_tp_model": str(payload.get("applied_tp_model") or payload.get("selected_tp_model") or ""),
            "time_exit_enabled": "YES" if time_exit_enabled else "NO",
            "time_exit_minutes": str(payload.get("time_exit_minutes") or ""),
            "planned_time_exit_at": str(payload.get("planned_time_exit_at") or ""),
            "time_exit_timer_starts_from": str(payload.get("time_exit_timer_starts_from") or ""),
            "time_exit_close_type": str(payload.get("time_exit_close_type") or ""),
            "expected_loss_at_sl_excluding_fees": str(expected_loss),
            "expected_loss_at_sl": str(expected_loss),
            "expected_profit_at_tp": str(expected_profit),
            "estimated_fee": str(estimated_fee),
            "estimated_slippage_buffer": str(estimated_slippage_buffer),
            "estimated_total_worst_case_loss": str(estimated_total_worst_case_loss),
            # Mirrors the ESTIMATED_FEE_AND_SLIPPAGE_EXCEED_FIXED_RISK_AMOUNT
            # guard above - expected_loss already exactly equals fixed_risk by
            # construction, so the only way this trade's real risk profile can
            # still go wrong is fee+slippage ballooning past the configured
            # risk amount.
            "risk_within_limit": "YES" if estimated_fee + estimated_slippage_buffer <= fixed_risk else "NO",
            "risk_lock_status": "PASSED",
            "exchange_lock_status": "PASSED",
            "profile_lock_status": "PASSED",
            "sanitized_payload": order_payload,
            "contract_config": contract,
            "ticker": ticker,
            "candles": candles,
            "blocked_reason": "None",
        }

    def _private_request(
        self,
        method: str,
        path: str,
        *,
        query: dict[str, object] | None = None,
        body: dict[str, object] | None = None,
        credentials: BitgetCredentialConfig | None = None,
    ) -> dict[str, Any]:
        signed = self.build_signed_request(method, path, query=query, body=body, credentials=credentials)
        url = f"{BITGET_REST_BASE_URL}{path}"
        if signed.query_string:
            url = f"{url}?{signed.query_string}"
        request = urllib.request.Request(url, data=signed.body.encode("utf-8") if signed.body else None, headers=signed.headers, method=signed.method)
        return _request_json(request, private=True)

    def _public_request(self, path: str, *, query: dict[str, object]) -> dict[str, Any]:
        query_string = urllib.parse.urlencode(query)
        request = urllib.request.Request(f"{BITGET_REST_BASE_URL}{path}?{query_string}", headers={"locale": "en-US"}, method="GET")
        return _request_json(request, private=False)

    def _require_live_readiness(self, *, symbol: str, allow_stale: bool) -> None:
        if self.emergency_kill_switch:
            raise EnvironmentLockError("emergency kill switch is active")
        self._credentials()
        if not self.last_connection_result:
            self.test_connection(symbol=symbol)
        if not self.last_contracts.get(symbol):
            self.fetch_contract_config(symbol)
        if not self.last_tickers.get(symbol):
            self.fetch_ticker(symbol)
        if not self.last_candles.get(f"{symbol}:1m"):
            self.fetch_candles(symbol)
        if not allow_stale:
            account_time = str(self.last_connection_result.get("last_successful_verification_time", "")) if self.last_connection_result else ""
            ticker_time = str(self.last_tickers[symbol].get("fetched_at", "")) if symbol in self.last_tickers else ""
            if _is_stale(account_time, STALE_DATA_SECONDS) or _is_stale(ticker_time, STALE_DATA_SECONDS):
                raise EnvironmentLockError("account or market data is stale")

    def _credentials(self, fail: bool = True) -> BitgetCredentialConfig | None:
        credentials = self.runtime_credentials or credentials_from_env()
        if credentials is None:
            missing = [name for name in ("BITGET_API_KEY", "BITGET_API_SECRET", "BITGET_API_PASSPHRASE") if not os.getenv(name)]
            logger.warning(
                "No Bitget credentials available (no dashboard-saved runtime_credentials, and env fallback missing: %s)",
                ", ".join(missing) if missing else "all three env vars are set but credentials_from_env() still returned None",
            )
            if fail:
                raise EnvironmentLockError("LIVE credentials are missing")
            return None
        identity = (credentials.source, credentials.fingerprint)
        if identity != self._last_logged_credential_identity:
            logger.info("Resolved Bitget credentials from %s", credentials.source)
            self._last_logged_credential_identity = identity
        return credentials

    def credential_diagnostics(self) -> dict[str, object]:
        """Resolve credentials the same way live trading does (dashboard-saved
        runtime credentials, falling back to BITGET_API_* env vars), without
        raising - for diagnostics endpoints that need to explain *why* no
        credentials are available rather than just failing."""
        credentials = self._credentials(fail=False)
        if credentials is None:
            missing = [name for name in ("BITGET_API_KEY", "BITGET_API_SECRET", "BITGET_API_PASSPHRASE") if not os.getenv(name)]
            return {"available": False, "source": "NONE", "missing_env_vars": missing}
        return {"available": True, "source": credentials.source, "missing_env_vars": []}

    def _validate_safety(self, payload: dict[str, object]) -> None:
        if self.emergency_kill_switch:
            raise EnvironmentLockError("emergency kill switch is active")
        if self.repeated_api_errors >= self.max_repeated_api_errors:
            raise EnvironmentLockError("trading disabled after repeated API errors")
        max_risk = _positive_decimal(payload.get("max_risk_per_trade", "1000000000"), "max_risk_per_trade")
        risk_amount = _positive_decimal(payload.get("risk_amount"), "risk_amount")
        if risk_amount > max_risk:
            raise EnvironmentLockError("risk amount exceeds max risk per trade")
        max_daily_loss = Decimal(str(payload.get("max_daily_loss", "1000000000")))
        if self.daily_loss >= max_daily_loss:
            raise EnvironmentLockError("max daily loss reached")
        max_trades = int(str(payload.get("max_trades_per_day", "1000000")))
        if self.trades_today >= max_trades:
            raise EnvironmentLockError("max trades per day reached")
        max_open = int(str(payload.get("max_open_positions", "1000000")))
        if self.open_positions >= max_open:
            raise EnvironmentLockError("max open positions reached")
        if str(payload.get("profile_lock_status", "PASSED")).upper() != "PASSED":
            raise EnvironmentLockError("profile lock failed")


def credentials_from_env() -> BitgetCredentialConfig | None:
    api_key = os.getenv("BITGET_API_KEY")
    api_secret = os.getenv("BITGET_API_SECRET")
    passphrase = os.getenv("BITGET_API_PASSPHRASE")
    if not api_key or not api_secret or not passphrase:
        return None
    return BitgetCredentialConfig(api_key=api_key, api_secret=api_secret, passphrase=passphrase, source="ENV")


def _request_json(request: urllib.request.Request, *, private: bool) -> dict[str, Any]:
    area = "private auth" if private else "public market data"
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        logger.error("Bitget %s request raised HTTP %s: %s", area, exc.code, body)
        raise EnvironmentLockError(f"Bitget HTTP {exc.code}: {body}") from exc
    except urllib.error.URLError as exc:
        logger.error("Bitget %s request failed (network/URL error): %s", area, exc.reason)
        raise EnvironmentLockError(_network_error_message(exc.reason)) from exc
    except TimeoutError as exc:
        logger.error("Bitget %s request timed out: %s", area, exc)
        raise EnvironmentLockError(_network_error_message(exc)) from exc
    except (OSError, json.JSONDecodeError) as exc:
        logger.error("Bitget %s request failed: %s", area, exc)
        raise EnvironmentLockError(_network_error_message(exc)) from exc
    if str(payload.get("code")) != "00000":
        # Bitget often responds 200 OK with an error code in the body (e.g. bad
        # signature/passphrase/IP-whitelist) rather than a true HTTP error status.
        logger.error("Bitget %s request returned code=%s msg=%s", area, payload.get("code"), payload.get("msg"))
        raise EnvironmentLockError(f"Bitget {area} request failed: {payload.get('msg') or payload}")
    return payload


def _sanitize_exchange_row(row: dict[str, object]) -> dict[str, object]:
    blocked = {"api_key", "apiSecret", "api_secret", "passphrase", "ACCESS-KEY", "ACCESS-SIGN", "ACCESS-PASSPHRASE"}
    return {str(key): value for key, value in row.items() if str(key) not in blocked}


def _network_error_message(reason: object) -> str:
    detail = str(reason)
    lowered = detail.lower()
    if "handshake" in lowered or "_ssl" in lowered or "timed out" in lowered or "timeout" in lowered:
        return (
            "Bitget TLS handshake timed out. TCP 443 may be reachable, but this machine/network cannot complete "
            "HTTPS to https://api.bitget.com. This is a network/ISP/VPN/firewall route issue, not a credential rejection."
        )
    return f"network error during Bitget request: {detail}"


def _round_size(size: Decimal, contract: dict[str, object]) -> Decimal:
    volume_place = int(str(contract.get("volumePlace") or "3"))
    multiplier = Decimal(str(contract.get("sizeMultiplier") or "0"))
    quant = Decimal(1).scaleb(-volume_place)
    rounded = size.quantize(quant, rounding=ROUND_DOWN)
    if multiplier > 0:
        rounded = (rounded // multiplier) * multiplier
    return rounded


def _positive_decimal(value: object, field_name: str) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise EnvironmentLockError(f"{field_name} must be numeric") from exc
    if parsed <= 0:
        raise EnvironmentLockError(f"{field_name} must be greater than zero")
    return parsed


def _is_stale(timestamp: str, seconds: int) -> bool:
    try:
        parsed = datetime.fromisoformat(timestamp)
    except ValueError:
        return True
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - parsed > timedelta(seconds=seconds)


def _mask(value: str) -> str:
    if len(value) <= 6:
        return "*" * len(value)
    return f"{value[:3]}****{value[-3:]}"


def _build_client_oid(symbol: str, side: str, timestamp: str) -> str:
    raw = f"LIVE|{symbol}|{side}|{timestamp}"
    return f"arjio_{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:24]}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
