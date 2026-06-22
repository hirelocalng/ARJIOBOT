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


def test_per_pair_leverage_is_settable_and_survives_re_add_update_and_import() -> None:
    api = client()

    created = api.post("/api/pairs", json={"symbol": "btcusdt", "leverage": 120}).json()["data"]
    assert created["leverage"] == 120

    # Re-adding the same symbol with no leverage in the payload must not wipe it.
    re_added = api.post("/api/pairs", json={"symbol": "btcusdt"}).json()["data"]
    assert re_added["leverage"] == 120

    # PATCH without "leverage" in the payload must not wipe it either.
    patched_enabled_only = api.patch("/api/pairs/BTCUSDT", json={"enabled": False}).json()["data"]
    assert patched_enabled_only["leverage"] == 120

    patched_leverage = api.patch("/api/pairs/BTCUSDT", json={"leverage": 90}).json()["data"]
    assert patched_leverage["leverage"] == 90

    # Re-importing must preserve whatever leverage was already set.
    reimported = api.post("/api/pairs/import", json={"symbols": ["btcusdt"]}).json()
    assert reimported["data"]["imported"] == ["BTCUSDT"]
    assert api.get("/api/pairs").json()["data"]
    pairs_by_symbol = {pair["symbol"]: pair for pair in api.get("/api/pairs").json()["data"]}
    assert pairs_by_symbol["BTCUSDT"]["leverage"] == 90

    # A brand-new pair with no leverage specified falls back to None (global setting).
    new_pair = api.post("/api/pairs", json={"symbol": "newusdt"}).json()["data"]
    assert new_pair["leverage"] is None


def test_default_pairs_are_seeded_when_the_pairs_file_is_missing_unreadable_or_empty(tmp_path, monkeypatch) -> None:
    """A fresh start, a Railway redeploy with no persistent volume, or a
    corrupted pairs file must never leave the bot with zero (or the old
    single hardcoded BTCUSDT) monitored pairs - it must seed the full
    configured default set every time."""
    missing_path = tmp_path / "does_not_exist.json"
    monkeypatch.setattr(dependencies, "PAIRS_PATH", missing_path)
    seeded = load_pairs()
    assert set(seeded.keys()) == set(DEFAULT_MONITORED_PAIRS)
    assert all(pair["enabled"] for pair in seeded.values())
    assert seeded["BTCUSDT"]["leverage"] == 120
    assert seeded["TAOUSDT"]["leverage"] == 50
    assert seeded["SOLUSDT"]["leverage"] == 80
    assert seeded["1INCHUSDT"]["leverage"] == 75

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
    real_pairs = load_pairs()
    assert set(real_pairs.keys()) == {"ETHUSDT"}, "genuinely saved pairs must not be overridden by the defaults"
    assert real_pairs["ETHUSDT"]["leverage"] is None, "a pair with no saved leverage must fall back to global max_leverage"

    saved_leverage_path = tmp_path / "saved_leverage.json"
    saved_leverage_path.write_text(json.dumps([{"symbol": "BTCUSDT", "enabled": True, "leverage": 60}]), encoding="utf-8")
    monkeypatch.setattr(dependencies, "PAIRS_PATH", saved_leverage_path)
    assert load_pairs()["BTCUSDT"]["leverage"] == 60, "an explicitly saved per-pair leverage must be preserved on load"
