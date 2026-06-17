"""Service facade for the Expansion Candle Engine."""

from __future__ import annotations

from arjiobot.expansion.expansion import ExpansionDetectionEngine


class ExpansionService(ExpansionDetectionEngine):
    """Authoritative service API for Expansion Candle Engine consumers."""

