"""Validation report routes."""

from __future__ import annotations

from fastapi import APIRouter

from arjiobot.api.dependencies import get_state
from arjiobot.api.errors import api_error
from arjiobot.api.schemas.common import ok

router = APIRouter(prefix="/api/reports", tags=["reports"])


@router.get("")
def list_reports():
    reports = []
    for name, path in get_state().report_paths().items():
        reports.append({"report_name": name, "path": str(path), "exists": path.exists()})
    return ok(reports)


@router.get("/{report_name}")
def get_report(report_name: str):
    path = get_state().report_paths().get(report_name)
    if path is None or not path.exists():
        raise api_error(404, "REPORT_NOT_FOUND", "report not found")
    return ok({"report_name": report_name, "content": path.read_text(encoding="utf-8")})
