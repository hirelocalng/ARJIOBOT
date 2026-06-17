"""Risk route tests."""

from arjiobot.api.tests.helpers import client, seed_entry_ready_setup


def test_risk_assessment_and_trade_plan_routes() -> None:
    api = client()
    seed_entry_ready_setup()
    setup_id = api.get("/api/setups/entry-ready").json()["data"][0]["setup_id"]
    signal_id = api.post(f"/api/signals/generate/{setup_id}").json()["data"]["signal_id"]

    assessment = api.post(f"/api/risk/assess/{signal_id}").json()["data"]
    plan = api.post(f"/api/risk/trade-plan/{signal_id}").json()["data"]

    assert assessment["validation_passed"]
    assert plan["approval_status"] == "APPROVED"
    assert api.get("/api/risk/trade-plans").json()["data"][0]["trade_plan_id"] == plan["trade_plan_id"]
    assert api.get(f"/api/risk/trade-plans/{plan['trade_plan_id']}").json()["data"]["trade_plan_id"] == plan["trade_plan_id"]
