"""Health route tests."""

from arjiobot.api.tests.helpers import client


def test_health_and_status_routes() -> None:
    api = client()

    assert api.get("/api/health").json()["data"]["status"] == "healthy"
    status = api.get("/api/status").json()["data"]
    assert status["api_status"] == "online"
    assert status["adapter_mode"] == "MOCK"
