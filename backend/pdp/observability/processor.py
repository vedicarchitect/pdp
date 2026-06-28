"""Universal Tier-A shipper: a structlog processor that enqueues every log record.

Inserted into the `configure_logging` chain just before `JSONRenderer`, so it sees the
structured event dict (not a rendered string). Returns the dict unchanged for normal
rendering. Records bound with ``_no_ship=True`` (the pipeline's own logs) are skipped to
avoid a feedback loop.
"""
from __future__ import annotations

from typing import Any

from pdp.observability.indexer import get_active_indexer

# structlog levels (lower-cased by add_log_level) → numeric, for the level floor.
_LEVELS = {
    "notset": 0,
    "debug": 10,
    "info": 20,
    "warning": 30,
    "warn": 30,
    "error": 40,
    "critical": 50,
    "exception": 40,
}

# Fields lifted to top-level columns; everything else goes under `context`.
_TOP = {
    "timestamp",
    "level",
    "event",
    "source",
    "logger",
    "service",
    "env",
    "request_id",
    "strategy_id",
    "screen",
    "build",
    "device",
    "exception",
    "_no_ship",
}

_floor = _LEVELS["info"]


def set_level_floor(level: str) -> None:
    global _floor
    _floor = _LEVELS.get(level.lower(), 20)


def opensearch_sink(
    logger: Any, method_name: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    # Never ship the pipeline's own logs (drop the marker so it doesn't render either).
    if event_dict.pop("_no_ship", False):
        return event_dict

    indexer = get_active_indexer()
    if indexer is None:
        return event_dict

    level = str(event_dict.get("level", method_name) or "info").lower()
    if _LEVELS.get(level, 20) < _floor:
        return event_dict

    indexer.enqueue("logs", _to_log_doc(event_dict))
    return event_dict


def _to_log_doc(ed: dict[str, Any]) -> dict[str, Any]:
    context = {k: v for k, v in ed.items() if k not in _TOP}
    return {
        "@timestamp": ed.get("timestamp"),
        "level": str(ed.get("level", "info")),
        "event": str(ed.get("event", "")),
        "source": ed.get("source") or "backend",
        "logger": ed.get("logger"),
        "service": ed.get("service"),
        "env": ed.get("env"),
        "request_id": ed.get("request_id"),
        "strategy_id": ed.get("strategy_id"),
        "screen": ed.get("screen"),
        "build": ed.get("build"),
        "device": ed.get("device"),
        "exc": ed.get("exception"),
        "context": context or None,
    }
