"""API test helpers."""

from __future__ import annotations

from fastapi.testclient import TestClient

from arjiobot.api.dependencies import get_state, reset_state
from arjiobot.main import create_app
from arjiobot.strategy.demo_strategy import make_entry_ready_setup


def client() -> TestClient:
    reset_state()
    return TestClient(create_app())


def create_account(api_client: TestClient) -> str:
    response = api_client.post(
        "/api/accounts",
        json={"account_name": "Main", "api_key": "abc123456xyz", "api_secret": "secret", "passphrase": "pass", "permissions": ["READ", "TRADE"]},
    )
    assert response.status_code == 200
    return response.json()["data"]["account_id"]


def seed_entry_ready_setup() -> str:
    setup = make_entry_ready_setup()
    get_state().setups[setup.setup_id] = setup
    return setup.setup_id


def create_signal_and_plan(api_client: TestClient) -> tuple[str, str]:
    seed_entry_ready_setup()
    setup_id = api_client.get("/api/setups/entry-ready").json()["data"][0]["setup_id"]
    signal_id = api_client.post(f"/api/signals/generate/{setup_id}").json()["data"]["signal_id"]
    trade_plan_id = api_client.post(f"/api/risk/trade-plan/{signal_id}").json()["data"]["trade_plan_id"]
    return signal_id, trade_plan_id
