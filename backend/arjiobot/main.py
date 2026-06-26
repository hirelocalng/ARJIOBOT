"""ArjioBot FastAPI application."""

from __future__ import annotations

import logging

from fastapi import FastAPI

from arjiobot.api.auth import require_dashboard_auth
from arjiobot.api.dependencies import bootstrap_live_trading_from_env, get_state
from arjiobot.api.routes import ROUTERS
from arjiobot.api.routes.monitoring import resume_monitoring_if_enabled
from arjiobot.profile_freeze import PROFILE_FREEZE_RUNTIME_WARNING, assert_profile_freeze
from arjiobot.setup_tracker.setup_history_store import wipe_setup_history


logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    """Create Backend API Routes app."""
    # Wipe setup radar history on every startup so resolved_swing_keys,
    # resolved_setup_ids, completed_setups, and invalidated_setups all start
    # from a clean slate — stale keys from a previous long-running session
    # cannot accumulate in resolved_swing_keys and block detection.
    # IN PROGRESS (state.setups) is never touched by this.
    wipe_setup_history(get_state())
    assert_profile_freeze()
    logger.warning(PROFILE_FREEZE_RUNTIME_WARNING)
    app = FastAPI(title="ArjioBot Backend API", version="1.0.0")

    if hasattr(app, "middleware"):
        from starlette.responses import JSONResponse

        @app.middleware("http")
        async def dashboard_auth_middleware(request, call_next):
            path = request.url.path
            public_paths = {"/api/health", "/api/auth/status", "/api/auth/login"}
            if path.startswith("/api/") and path not in public_paths:
                try:
                    require_dashboard_auth(request)
                except Exception as exc:
                    status_code = getattr(exc, "status_code", 401)
                    detail = getattr(exc, "detail", {"success": False, "error": {"code": "DASHBOARD_AUTH_REQUIRED", "message": "Dashboard login is required."}})
                    return JSONResponse(status_code=status_code, content=detail)
            return await call_next(request)

    for router in ROUTERS:
        app.include_router(router)
    bootstrap_live_trading_from_env(get_state())
    resume_monitoring_if_enabled(get_state())
    return app
