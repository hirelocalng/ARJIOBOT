"""Service facade for Risk Engine."""

from __future__ import annotations

from arjiobot.risk.risk_engine import RiskEngine


class RiskService(RiskEngine):
    """Authoritative risk service API."""

