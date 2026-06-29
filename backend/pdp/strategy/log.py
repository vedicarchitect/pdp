from __future__ import annotations

import json
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from zoneinfo import ZoneInfo


class StrangleEventType(StrEnum):
    LEG_OPEN = "leg_open"
    LEG_CLOSE = "leg_close"
    TAKE_PROFIT = "take_profit"
    STOP_HALF = "stop_half"
    STOP_ALL = "stop_all"
    DAY_LOSS_CAP = "day_loss_cap"
    ROLLED = "rolled"
    STOP_GATE_WAIT = "stop_gate_wait"
    BUCKET_CHANGE = "bucket_change"
    BIAS_EVALUATED = "bias_evaluated"
    LEG_STATUS = "leg_status"
    SQUARE_OFF = "square_off"

_IST = ZoneInfo("Asia/Kolkata")
_LOGS_DIR = Path("logs")


def _now_ist() -> datetime:
    """Current time in IST; isolated so tests can monkeypatch it."""
    return datetime.now(tz=_IST)


def _ship_event(record: dict) -> None:
    """Dual-sink the canonical event to OpenSearch (no-op when the indexer is inactive)."""
    if "event_type" not in record:
        return  # heartbeats and other non-canonical records go to pdp-logs-* via structlog only
    from pdp.observability.indexer import get_active_indexer

    indexer = get_active_indexer()
    if indexer is None:
        return
    from pdp.observability.sinks import STRANGLE_EVENTS, strangle_event_doc

    doc, doc_id = strangle_event_doc(record)
    indexer.enqueue(STRANGLE_EVENTS, doc, doc_id)


class StrategyDailyLog:
    """Append-mode daily log: logs/<strategy_id>/<YYYY-MM-DD>.log (IST date).

    One file per strategy per IST trading day; mid-day restart appends to the
    same file; IST date rollover automatically opens a new file.
    """

    def __init__(self, strategy_id: str, logs_dir: Path = _LOGS_DIR) -> None:
        self._strategy_id = strategy_id
        self._logs_dir = logs_dir
        self._handle = None
        self._current_date: str = ""

    def _ensure_open(self) -> None:
        today = _now_ist().date().isoformat()
        if today != self._current_date:
            self._do_close()
            path = self._logs_dir / self._strategy_id / f"{today}.log"
            path.parent.mkdir(parents=True, exist_ok=True)
            self._handle = path.open("a", buffering=1)
            self._current_date = today

    def write(self, record: dict) -> None:
        self._ensure_open()
        if self._handle is not None:
            self._handle.write(json.dumps(record, default=str) + "\n")
        _ship_event(record)

    def close(self) -> None:
        self._do_close()

    def _do_close(self) -> None:
        if self._handle is not None:
            self._handle.close()
            self._handle = None
