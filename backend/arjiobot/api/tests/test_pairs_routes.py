"""Pair route tests."""

import json

from arjiobot.api import dependencies
from arjiobot.api.dependencies import DEFAULT_MONITORED_PAIRS, load_pairs
from arjiobot.api.tests.helpers import client


def test_pair_add_remove_enable_disable_and_import() -> None:
    api = client()

    assert api.post("/api/pairs", json={"symbol": "ethusdt"}).json()["data"]["symbol"] == "ETHUSDT"
    assert not api.patch("/api/pairs/ETHUSDT", json={"enabled": False}).json()["data"]["enabled"]
    imported = api.post("/api/pairs/import", json={"symbols": ["solusdt", "xrpusdt"]}).json()["data"]["imported"]
    assert imported == ["SOLUSDT", "XRPUSDT"]
    assert api.delete("/api/pairs/ETHUSDT").json()["data"]["deleted"]
    assert len(api.get("/api/pairs").json()["data"]) >= 2


def test_default_pairs_are_seeded_when_the_pairs_file_is_missing_unreadable_or_empty(tmp_path, monkeypatch) -> None:
    """A fresh start, a Railway redeploy with no persistent volume, or a
    corrupted pairs file must never leave the bot with zero (or the old
    single hardcoded BTCUSDT) monitored pairs - it must seed the full
    configured default set every time."""
    missing_path = tmp_path / "does_not_exist.json"
    monkeypatch.setattr(dependencies, "PAIRS_PATH", missing_path)
    assert set(load_pairs().keys()) == set(DEFAULT_MONITORED_PAIRS)
    assert all(pair["enabled"] for pair in load_pairs().values())

    corrupted_path = tmp_path / "corrupted.json"
    corrupted_path.write_text("not valid json{{{", encoding="utf-8")
    monkeypatch.setattr(dependencies, "PAIRS_PATH", corrupted_path)
    assert set(load_pairs().keys()) == set(DEFAULT_MONITORED_PAIRS)

    empty_list_path = tmp_path / "empty.json"
    empty_list_path.write_text(json.dumps([]), encoding="utf-8")
    monkeypatch.setattr(dependencies, "PAIRS_PATH", empty_list_path)
    assert set(load_pairs().keys()) == set(DEFAULT_MONITORED_PAIRS)

    real_pairs_path = tmp_path / "real.json"
    real_pairs_path.write_text(json.dumps([{"symbol": "ETHUSDT", "enabled": True}]), encoding="utf-8")
    monkeypatch.setattr(dependencies, "PAIRS_PATH", real_pairs_path)
    assert set(load_pairs().keys()) == {"ETHUSDT"}, "genuinely saved pairs must not be overridden by the defaults"
