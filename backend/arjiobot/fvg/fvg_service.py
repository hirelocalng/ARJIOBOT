"""Service facade for the FVG Engine."""

from __future__ import annotations

from arjiobot.fvg.fvg import FVGDetectionEngine


class FVGService(FVGDetectionEngine):
    """Authoritative FVG service API."""

