"""Live/closed trade and PnL routes for the Execution page.

LIVE TRADES and CLOSED TRADES are built from real Bitget data
(fetch_positions / fetch_position_history) - both make a real network call
to the exchange, so (like AccountStatus's existing "Refresh Positions"
button) these are meant to be triggered on demand, not the main 5s dashboard
poll - calling either one automatically every few seconds would hammer a
real account for no reason.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from fastapi import APIRouter

from arjiobot.api.dependencies import ApiState, get_state
from arjiobot.api.errors import api_error
from arjiobot.api.schemas.common import ok
from arjiobot.exchange.bitget_environment import EnvironmentLockError

router = APIRouter(prefix="/api/trades", tags=["trades"])

# Execution page spec names these exact paths. Same handlers/data as the
# /api/trades/* routes above (kept as-is since the frontend already calls
# them) - this is a second router exposing identical responses at the paths
# the spec asks for, not a duplicate implementation.
execution_trades_router = APIRouter(prefix="/api/execution", tags=["execution-trades"])


def _decimal(value: object, default: str = "0") -> Decimal:
    try:
        return Decimal(str(value if value not in (None, "") else default))
    except InvalidOperation:
        return Decimal(default)


def _matching_order(state: ApiState, symbol: str, hold_side: str) -> dict[str, object] | None:
    """Best-effort link from a real open position back to the locally
    recorded order that opened it, for stop loss/take profit/risk amount -
    fields the raw Bitget position payload does not carry. Newest match
    first, since service.orders only ever grows."""
    side = "BUY" if hold_side.lower() == "long" else "SELL"
    for order in reversed(state.bitget_environment.orders):
        if str(order.get("symbol", "")).upper() == symbol.upper() and str(order.get("side", "")).upper() == side:
            return order
    return None


@router.get("/live")
def live_trades():
    """Currently open positions - real Bitget data, enriched with the
    locally-recorded order's stop loss/take profit/risk amount where a
    match is found by symbol+side."""
    state = get_state()
    try:
        record = state.bitget_environment.fetch_positions()
    except EnvironmentLockError as exc:
        raise api_error(400, "BITGET_POSITIONS_FETCH_FAILED", str(exc)) from exc
    trades = []
    for row in record.get("positions", ()):
        symbol = str(row.get("symbol", "")).upper()
        hold_side = str(row.get("holdSide", ""))
        order = _matching_order(state, symbol, hold_side)
        trades.append(
            {
                "symbol": symbol,
                "direction": "BUY" if hold_side.lower() == "long" else "SELL",
                "entry_price": row.get("openPriceAvg") or row.get("averageOpenPrice"),
                "market_price": row.get("markPrice"),
                "margin": row.get("marginSize") or row.get("margin"),
                "leverage": row.get("leverage"),
                "stop_loss": (order or {}).get("stop_reference"),
                "take_profit": (order or {}).get("target_reference"),
                "risk_amount": (order or {}).get("risk_amount"),
                "floating_pnl": row.get("unrealizedPL") or row.get("unrealizedPl"),
                "position_size": row.get("total") or row.get("available"),
                "opened_time": row.get("cTime") or row.get("ctime"),
                "opened_at": row.get("cTime") or row.get("ctime"),
                "bitget_order_id": (order or {}).get("bitget_order_id"),
                "exchange_order_id": (order or {}).get("bitget_order_id"),
            }
        )
    return ok({"trades": trades, "count": len(trades), "fetched_at": record.get("fetched_at")})


@router.get("/closed")
def closed_trades():
    """Closed positions - real Bitget data (fetch_position_history). Field
    names are based on Bitget's documented V2 Mix API and have not been
    verified against a real authenticated response in this environment (no
    live credentials/network access here) - every lookup below is
    defensive (multiple fallback key names, defaulting to None) so a
    naming mismatch degrades to a blank column instead of an error."""
    state = get_state()
    try:
        record = state.bitget_environment.fetch_position_history()
    except EnvironmentLockError as exc:
        raise api_error(400, "BITGET_POSITION_HISTORY_FETCH_FAILED", str(exc)) from exc
    trades = []
    for row in record.get("closed_positions", ()):
        hold_side = str(row.get("holdSide", ""))
        trades.append(
            {
                "symbol": str(row.get("symbol", "")).upper(),
                "direction": "BUY" if hold_side.lower() == "long" else "SELL",
                "entry_price": row.get("openPriceAvg") or row.get("openAvgPrice"),
                "exit_price": row.get("closeAvgPrice") or row.get("closePriceAvg"),
                "margin": row.get("marginSize") or row.get("margin"),
                "leverage": row.get("leverage"),
                "realized_pnl": row.get("netProfit") or row.get("pnl"),
                "fees": row.get("totalFee") or row.get("openFee"),
                "close_reason": row.get("closeReason") or row.get("exitReason") or "N/A",
                "opened_time": row.get("cTime") or row.get("ctime"),
                "opened_at": row.get("cTime") or row.get("ctime"),
                "closed_time": row.get("uTime") or row.get("utime"),
                "closed_at": row.get("uTime") or row.get("utime"),
                "bitget_order_id": row.get("orderId") or row.get("positionId"),
                "exchange_order_id": row.get("orderId") or row.get("positionId"),
            }
        )
    return ok({"trades": trades, "count": len(trades), "fetched_at": record.get("fetched_at")})


@execution_trades_router.get("/live-trades")
def execution_live_trades():
    return live_trades()


@execution_trades_router.get("/closed-trades")
def execution_closed_trades():
    return closed_trades()


@execution_trades_router.get("/pnl")
def execution_pnl_summary():
    return pnl_summary()


@router.get("/pnl")
def pnl_summary():
    """Aggregate performance stats derived from the same two real Bitget
    calls live_trades/closed_trades use - not a separately tracked ledger,
    so it can never drift out of sync with what those two tabs show."""
    state = get_state()
    try:
        closed_record = state.bitget_environment.fetch_position_history()
        open_record = state.bitget_environment.fetch_positions()
    except EnvironmentLockError as exc:
        raise api_error(400, "BITGET_PNL_FETCH_FAILED", str(exc)) from exc

    realized = [_decimal(row.get("netProfit") or row.get("pnl")) for row in closed_record.get("closed_positions", ())]
    wins = [value for value in realized if value > 0]
    losses = [value for value in realized if value < 0]
    floating = sum((_decimal(row.get("unrealizedPL") or row.get("unrealizedPl")) for row in open_record.get("positions", ())), Decimal("0"))
    total_profit = sum(wins, Decimal("0"))
    total_loss = sum(losses, Decimal("0"))
    net_profit = total_profit + total_loss
    total_trades = len(realized)
    return ok(
        {
            "total_profit": str(total_profit),
            "total_loss": str(total_loss),
            "net_profit": str(net_profit),
            "win_count": len(wins),
            "loss_count": len(losses),
            "win_ratio": (len(wins) / total_trades) if total_trades else 0.0,
            "win_percentage": (len(wins) / total_trades * 100) if total_trades else 0.0,
            "win_pct": (len(wins) / total_trades * 100) if total_trades else 0.0,
            "average_win": str(total_profit / len(wins)) if wins else "0",
            "avg_win": str(total_profit / len(wins)) if wins else "0",
            "average_loss": str(total_loss / len(losses)) if losses else "0",
            "avg_loss": str(total_loss / len(losses)) if losses else "0",
            "total_trades": total_trades,
            "open_floating_pnl": str(floating),
            "realized_pnl": str(net_profit),
        }
    )
