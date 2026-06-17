"""Pair route tests."""

from arjiobot.api.tests.helpers import client


def test_pair_add_remove_enable_disable_and_import() -> None:
    api = client()

    assert api.post("/api/pairs", json={"symbol": "ethusdt"}).json()["data"]["symbol"] == "ETHUSDT"
    assert not api.patch("/api/pairs/ETHUSDT", json={"enabled": False}).json()["data"]["enabled"]
    imported = api.post("/api/pairs/import", json={"symbols": ["solusdt", "xrpusdt"]}).json()["data"]["imported"]
    assert imported == ["SOLUSDT", "XRPUSDT"]
    assert api.delete("/api/pairs/ETHUSDT").json()["data"]["deleted"]
    assert len(api.get("/api/pairs").json()["data"]) >= 2
