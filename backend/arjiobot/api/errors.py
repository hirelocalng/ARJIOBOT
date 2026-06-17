"""API error helpers."""

from __future__ import annotations

from fastapi import HTTPException

from arjiobot.api.schemas.common import fail


def api_error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail=fail(code, message))
