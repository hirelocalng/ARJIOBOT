"""Execution route tests."""

from arjiobot.api.tests.helpers import client, create_signal_and_plan


def test_paper_execution_routes_only() -> None:
    api = client()
    _, trade_plan_id = create_signal_and_plan(api)
    execution = api.post(f"/api/execution/paper/{trade_plan_id}").json()["data"]

    assert execution["status"] == "PROTECTIVE_ORDERS_PLANNED"
    assert api.get("/api/execution/records").json()["data"][0]["execution_id"] == execution["execution_id"]
    assert api.get(f"/api/execution/records/{execution['execution_id']}").json()["data"]["execution_id"] == execution["execution_id"]
    assert api.post(f"/api/execution/cancel/{execution['execution_id']}").json()["data"]["status"] == "CANCELLED"
    assert api.post(f"/api/execution/live/{trade_plan_id}").status_code == 404
