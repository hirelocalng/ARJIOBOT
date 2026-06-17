"""JSON store tests."""

from __future__ import annotations

import pytest

from arjiobot.storage.json_store import JsonAppStore
from arjiobot.storage.storage_models import AppStorageState


def test_json_store_round_trip(tmp_path) -> None:
    store = JsonAppStore(tmp_path / "app_state.json")
    state = AppStorageState(monitored_pairs=[{"symbol": "BTCUSDT", "enabled": True}], dashboard_settings={"adapter_mode": "MOCK"})

    store.save(state)
    loaded = store.load()

    assert loaded.monitored_pairs[0]["symbol"] == "BTCUSDT"
    assert loaded.dashboard_settings["adapter_mode"] == "MOCK"


def test_json_store_rejects_raw_secret_fields(tmp_path) -> None:
    store = JsonAppStore(tmp_path / "app_state.json")
    state = AppStorageState(exchange_accounts_metadata=[{"account_name": "main", "api_secret": "raw"}])

    with pytest.raises(ValueError, match="raw secret"):
        store.save(state)
