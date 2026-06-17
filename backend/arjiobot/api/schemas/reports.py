"""Report API schemas."""

from __future__ import annotations

from pydantic import BaseModel


class ReportInfo(BaseModel):
    report_name: str
    path: str
