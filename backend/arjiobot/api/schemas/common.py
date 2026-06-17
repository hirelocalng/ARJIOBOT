"""Common API schemas."""

from __future__ import annotations

from pydantic import BaseModel


class ErrorDetail(BaseModel):
    code: str
    message: str


class ApiResponse(BaseModel):
    success: bool
    data: object | None = None
    error: ErrorDetail | None = None


def ok(data: object) -> dict[str, object]:
    return {"success": True, "data": data}


def fail(code: str, message: str) -> dict[str, object]:
    return {"success": False, "error": {"code": code, "message": message}}
