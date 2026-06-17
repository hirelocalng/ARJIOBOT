"""Signal route tests."""

from arjiobot.api.tests.helpers import client, seed_entry_ready_setup


def test_signal_generation_and_error_response() -> None:
    api = client()
    seed_entry_ready_setup()
    setup_id = api.get("/api/setups/entry-ready").json()["data"][0]["setup_id"]
    signal = api.post(f"/api/signals/generate/{setup_id}").json()["data"]

    assert signal["setup_id"] == setup_id
    assert api.get(f"/api/signals/{signal['signal_id']}").json()["data"]["signal_id"] == signal["signal_id"]
    assert isinstance(api.get("/api/signals/rejected").json()["data"], list)
    error = api.get("/api/signals/missing").json()
    assert error["success"] is False
    assert error["error"]["code"] == "SIGNAL_NOT_FOUND"
