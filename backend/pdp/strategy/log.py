from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

_IST = ZoneInfo("Asia/Kolkata")
_LOGS_DIR = Path("logs")


def _now_ist() -> datetime:
    """Current time in IST; isolated so tests can monkeypatch it."""
    return datetime.now(tz=_IST)


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

    def close(self) -> None:
        self._do_close()

    def _do_close(self) -> None:
        if self._handle is not None:
            self._handle.close()
            self._handle = None
