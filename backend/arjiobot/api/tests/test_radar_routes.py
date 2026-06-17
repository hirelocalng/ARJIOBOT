"""Radar/setup route tests."""

from arjiobot.api.tests.helpers import client


def test_radar_starts_empty_without_real_tracked_setup() -> None:
    api = client()
    radar = api.get("/api/radar").json()["data"]

    assert radar == []
    assert api.get("/api/setups").json()["data"] == []
    assert api.get("/api/setups/entry-ready").json()["data"] == []
    assert api.get("/api/setups/progress/50").json()["data"] == []
