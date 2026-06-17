"""Dashboard login routes."""

from __future__ import annotations

from fastapi import APIRouter

from arjiobot.api.auth import auth_required, create_dashboard_token, validate_dashboard_password
from arjiobot.api.errors import api_error
from arjiobot.api.schemas.common import ok

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.get("/status")
def auth_status():
    return ok({"auth_required": auth_required(), "method": "password" if auth_required() else "disabled"})


@router.post("/login")
def login(payload: dict[str, object]):
    if not auth_required():
        return ok({"token": "", "auth_required": False})
    password = str(payload.get("password") or "")
    if not validate_dashboard_password(password):
        raise api_error(401, "DASHBOARD_LOGIN_FAILED", "Invalid dashboard password.")
    return ok({"token": create_dashboard_token(), "auth_required": True})
