"""Simple JSON persistence layer for local app state."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from arjiobot.storage.storage_models import AppStorageState


SECRET_FIELD_NAMES = {"api_secret", "passphrase", "apiSecret", "api_secret_plain", "passphrase_plain"}


class JsonAppStore:
    """Persistence-ready JSON store.

    v1 stores metadata only. Production should replace this with encrypted DB
    storage before any persistent secret material is introduced.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def load(self) -> AppStorageState:
        if not self.path.exists():
            return AppStorageState()
        return AppStorageState.from_record(json.loads(self.path.read_text(encoding="utf-8")))

    def save(self, state: AppStorageState) -> AppStorageState:
        record = state.to_record()
        self._assert_no_raw_secrets(record)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(record, indent=2, sort_keys=True, default=str), encoding="utf-8")
        return state

    def update_section(self, section: str, value: Any) -> AppStorageState:
        state = self.load()
        if not hasattr(state, section):
            raise ValueError(f"unknown storage section: {section}")
        setattr(state, section, value)
        return self.save(state)

    def _assert_no_raw_secrets(self, value: Any) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if key in SECRET_FIELD_NAMES:
                    raise ValueError(f"raw secret field is not allowed in JSON storage: {key}")
                self._assert_no_raw_secrets(item)
        elif isinstance(value, list):
            for item in value:
                self._assert_no_raw_secrets(item)
