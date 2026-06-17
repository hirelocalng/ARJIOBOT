"""Dashboard authentication helpers."""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import time

from arjiobot.api.errors import api_error

AUTH_PASSWORD_ENV = "ARJIOBOT_DASHBOARD_PASSWORD"
AUTH_SECRET_ENV = "ARJIOBOT_DASHBOARD_SECRET"
AUTH_TTL_SECONDS = 60 * 60 * 12


def auth_required() -> bool:
    return bool(os.getenv(AUTH_PASSWORD_ENV))


def _secret() -> str:
    return os.getenv(AUTH_SECRET_ENV) or os.getenv(AUTH_PASSWORD_ENV) or "local-dev-dashboard-secret"


def _sign(payload: str) -> str:
    return hmac.new(_secret().encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()


def create_dashboard_token() -> str:
    issued_at = str(int(time.time()))
    nonce = secrets.token_urlsafe(18)
    payload = f"{issued_at}.{nonce}"
    return f"{payload}.{_sign(payload)}"


def verify_dashboard_token(token: str | None) -> bool:
    if not auth_required():
        return True
    if not token:
        return False
    parts = token.split(".")
    if len(parts) != 3:
        return False
    issued_at, nonce, signature = parts
    payload = f"{issued_at}.{nonce}"
    if not hmac.compare_digest(_sign(payload), signature):
        return False
    try:
        age = time.time() - int(issued_at)
    except ValueError:
        return False
    return 0 <= age <= AUTH_TTL_SECONDS


def validate_dashboard_password(password: str) -> bool:
    expected = os.getenv(AUTH_PASSWORD_ENV, "")
    return bool(expected) and hmac.compare_digest(password, expected)


def require_dashboard_auth(request) -> None:
    header = request.headers.get("Authorization", "")
    token = header.removeprefix("Bearer ").strip() if header.startswith("Bearer ") else ""
    if not verify_dashboard_token(token):
        raise api_error(401, "DASHBOARD_AUTH_REQUIRED", "Dashboard login is required.")
