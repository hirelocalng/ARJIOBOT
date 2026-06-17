"""Small FastAPI-compatible shim for local validation.

The project API is written against FastAPI/APIRouter concepts. The real
FastAPI package can replace this shim when dependencies are available.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, is_dataclass
from typing import Any, Callable


class HTTPException(Exception):
    def __init__(self, status_code: int, detail: Any) -> None:
        super().__init__(str(detail))
        self.status_code = status_code
        self.detail = detail


def Depends(dependency: Callable[..., Any] | None = None):
    return dependency


def File(default: Any = None):
    return default


def Form(default: Any = None):
    return default


class UploadFile:
    def __init__(self, filename: str, file) -> None:
        self.filename = filename
        self.file = file

    async def read(self) -> bytes:
        data = self.file.read()
        return data if isinstance(data, bytes) else data.encode("utf-8")


class APIRouter:
    def __init__(self, *, prefix: str = "", tags: list[str] | None = None, dependencies: list[Any] | None = None) -> None:
        self.prefix = prefix.rstrip("/")
        self.tags = tags or []
        self.dependencies = dependencies or []
        self.routes: list[dict[str, Any]] = []

    def add_api_route(self, path: str, endpoint: Callable[..., Any], methods: list[str]) -> None:
        self.routes.append({"path": f"{self.prefix}{path}", "endpoint": endpoint, "methods": [method.upper() for method in methods], "tags": self.tags})

    def get(self, path: str):
        return self._decorator(path, ["GET"])

    def post(self, path: str):
        return self._decorator(path, ["POST"])

    def patch(self, path: str):
        return self._decorator(path, ["PATCH"])

    def delete(self, path: str):
        return self._decorator(path, ["DELETE"])

    def _decorator(self, path: str, methods: list[str]):
        def register(func: Callable[..., Any]) -> Callable[..., Any]:
            self.add_api_route(path, func, methods)
            return func

        return register


class FastAPI:
    def __init__(self, *, title: str = "FastAPI", version: str = "0.1.0") -> None:
        self.title = title
        self.version = version
        self.routes: list[dict[str, Any]] = []

    def include_router(self, router: APIRouter) -> None:
        self.routes.extend(router.routes)

    def openapi(self) -> dict[str, Any]:
        paths: dict[str, dict[str, Any]] = {}
        for route in self.routes:
            path_item = paths.setdefault(route["path"], {})
            for method in route["methods"]:
                path_item[method.lower()] = {"tags": route["tags"], "responses": {"200": {"description": "Successful Response"}}}
        return {"openapi": "3.1.0", "info": {"title": self.title, "version": self.version}, "paths": paths}

    def handle(self, method: str, path: str, *, json_body: Any = None, files: Any = None) -> tuple[int, Any]:
        if path == "/openapi.json":
            return 200, self.openapi()
        for route in self.routes:
            match = _match(route["path"], path)
            if match is not None and method.upper() in route["methods"]:
                try:
                    kwargs = dict(match)
                    if json_body is not None:
                        kwargs["payload"] = json_body
                    if files is not None:
                        kwargs["file"] = _upload_from_files(files)
                        if isinstance(files, dict) and isinstance(files.get("__form"), dict):
                            kwargs.update(files["__form"])
                    result = route["endpoint"](**kwargs)
                    return 200, _jsonable(result)
                except HTTPException as exc:
                    return exc.status_code, _jsonable(exc.detail)
        return 404, {"detail": "Not Found"}


def _match(route_path: str, path: str) -> dict[str, str] | None:
    names = re.findall(r"{([^}]+)}", route_path)
    pattern = "^" + re.sub(r"{[^}]+}", r"([^/]+)", route_path) + "$"
    match = re.match(pattern, path)
    if not match:
        return None
    return dict(zip(names, match.groups()))


def _upload_from_files(files: Any) -> UploadFile:
    _, file_value = next((item for item in files.items() if item[0] != "__form"))
    filename, data, *_ = file_value
    import io

    return UploadFile(filename, io.BytesIO(data if isinstance(data, bytes) else data.encode("utf-8")))


def _jsonable(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return _jsonable(value.model_dump())
    if is_dataclass(value):
        return _jsonable(asdict(value))
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if hasattr(value, "value"):
        return value.value
    return value
