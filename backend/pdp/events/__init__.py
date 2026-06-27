"""Live event publisher: position-aware realtime monitoring events.

Monitors manual Dhan positions + the underlying market via the universal
IndicatorEngine and option analytics, runs a detector library, de-duplicates,
persists to MongoDB, and fans out to WebSocket + Web Push. Alerts-only — never
places orders.
"""
from __future__ import annotations

from pdp.events.models import Event, EventType, MonitoredPosition, Severity

__all__ = ["Event", "EventType", "MonitoredPosition", "Severity"]
