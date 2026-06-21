"""Execution page trade/PnL route tests."""

from __future__ import annotations

from arjiobot.api.dependencies import get_state
from arjiobot.api.tests.helpers import client
from arjiobot.exchange.bitget_environment import EnvironmentLockError


def test_live_trades_starts_empty_without_open_positions(monkeypatch) -> None:
    api = client()
    state = get_state()
    monkeypatch.setattr(state.bitget_environment, "fetch_positions", lambda: {"positions": (), "fetched_at": "2026-06-15T00:00:00+00:00"})

    data = api.get("/api/trades/live").json()["data"]

    assert data == {"trades": [], "count": 0, "fetched_at": "2026-06-15T00:00:00+00:00"}


def test_live_trades_enriches_real_position_with_locally_recorded_order_fields(monkeypatch) -> None:
    api = client()
    state = get_state()
    state.bitget_environment.orders.append(
        {
            "symbol": "BTCUSDT",
            "side": "BUY",
            "stop_reference": "85",
            "target_reference": "110",
            "risk_amount": "10",
            "bitget_order_id": "ord_live_1",
        }
    )
    monkeypatch.setattr(
        state.bitget_environment,
        "fetch_positions",
        lambda: {
            "positions": ({"symbol": "BTCUSDT", "holdSide": "long", "openPriceAvg": "90", "markPrice": "92", "unrealizedPL": "2", "total": "1", "leverage": "10"},),
            "fetched_at": "2026-06-15T00:00:00+00:00",
        },
    )

    data = api.get("/api/trades/live").json()["data"]

    assert data["count"] == 1
    trade = data["trades"][0]
    assert trade["symbol"] == "BTCUSDT"
    assert trade["direction"] == "BUY"
    assert trade["entry_price"] == "90"
    assert trade["market_price"] == "92"
    assert trade["stop_loss"] == "85"
    assert trade["take_profit"] == "110"
    assert trade["risk_amount"] == "10"
    assert trade["bitget_order_id"] == "ord_live_1"


def test_live_trades_surfaces_a_clean_error_when_bitget_call_fails(monkeypatch) -> None:
    api = client()
    state = get_state()

    def fail():
        raise EnvironmentLockError("LIVE credentials are missing")

    monkeypatch.setattr(state.bitget_environment, "fetch_positions", fail)

    response = api.get("/api/trades/live")

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "BITGET_POSITIONS_FETCH_FAILED"


def test_closed_trades_maps_real_position_history_fields(monkeypatch) -> None:
    api = client()
    state = get_state()
    monkeypatch.setattr(
        state.bitget_environment,
        "fetch_position_history",
        lambda: {
            "closed_positions": (
                {
                    "symbol": "ETHUSDT",
                    "holdSide": "short",
                    "openPriceAvg": "2000",
                    "closeAvgPrice": "1950",
                    "netProfit": "50",
                    "totalFee": "1.5",
                    "cTime": "1750000000000",
                    "uTime": "1750000600000",
                    "positionId": "pos_1",
                },
            ),
            "fetched_at": "2026-06-15T00:00:00+00:00",
        },
    )

    data = api.get("/api/trades/closed").json()["data"]

    assert data["count"] == 1
    trade = data["trades"][0]
    assert trade["symbol"] == "ETHUSDT"
    assert trade["direction"] == "SELL"
    assert trade["entry_price"] == "2000"
    assert trade["exit_price"] == "1950"
    assert trade["realized_pnl"] == "50"
    assert trade["fees"] == "1.5"
    assert trade["bitget_order_id"] == "pos_1"


def test_pnl_summary_computes_aggregate_stats_from_real_closed_and_open_data(monkeypatch) -> None:
    api = client()
    state = get_state()
    monkeypatch.setattr(
        state.bitget_environment,
        "fetch_position_history",
        lambda: {
            "closed_positions": (
                {"netProfit": "50"},
                {"netProfit": "-20"},
                {"netProfit": "30"},
            )
        },
    )
    monkeypatch.setattr(state.bitget_environment, "fetch_positions", lambda: {"positions": ({"unrealizedPL": "5"}, {"unrealizedPL": "-2"})})

    data = api.get("/api/trades/pnl").json()["data"]

    assert data["win_count"] == 2
    assert data["loss_count"] == 1
    assert data["total_profit"] == "80"
    assert data["total_loss"] == "-20"
    assert data["net_profit"] == "60"
    assert data["total_trades"] == 3
    assert data["open_floating_pnl"] == "3"
    assert abs(data["win_percentage"] - 66.66666666666667) < 0.001
