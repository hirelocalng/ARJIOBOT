"""Test client for the local FastAPI shim."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class Response:
    status_code: int
    _payload: Any

    def json(self) -> Any:
        return self._payload


class TestClient:
    def __init__(self, app) -> None:
        self.app = app

    def get(self, path: str) -> Response:
        status, payload = self.app.handle("GET", path)
        return Response(status, payload)

    def post(self, path: str, json: Any = None, files: Any = None) -> Response:
        status, payload = self.app.handle("POST", path, json_body=json, files=files)
        return Response(status, payload)

    def patch(self, path: str, json: Any = None) -> Response:
        status, payload = self.app.handle("PATCH", path, json_body=json)
        return Response(status, payload)

    def delete(self, path: str) -> Response:
        status, payload = self.app.handle("DELETE", path)
        return Response(status, payload)
