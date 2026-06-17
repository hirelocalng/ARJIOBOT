"""Small Pydantic-compatible schema base for local validation."""

from __future__ import annotations


class BaseModel:
    def __init__(self, **data):
        annotations = getattr(self, "__annotations__", {})
        for key, default in self.__class__.__dict__.items():
            if not key.startswith("_") and key not in annotations and not callable(default):
                setattr(self, key, default)
        for key in annotations:
            if key in data:
                setattr(self, key, data[key])
            elif not hasattr(self, key):
                setattr(self, key, None)
        for key, value in data.items():
            if key not in annotations:
                setattr(self, key, value)

    def model_dump(self):
        return dict(self.__dict__)
