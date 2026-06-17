"""Service facade for the Setup Tracker."""

from __future__ import annotations

from arjiobot.setup_tracker.setup_tracker import SetupTracker


class SetupService(SetupTracker):
    """Authoritative setup service API."""

