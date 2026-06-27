"""NIFTY expiry calendar — resolve (trade_date, expiry_flag, expiry_code) → real expiry_date.

The expiry list is derived **empirically** (no hardcoded weekday/holiday rules) so it survives
the NIFTY weekly-expiry weekday regime changes (Thursday → Wednesday → Tuesday) and holiday
shifts automatically. The calendar is built once by a script and cached to JSON
(``settings.EXPIRY_CACHE_PATH``). Runtime consumers only read the cache.

``resolve_expiry`` uses effective-window arithmetic: for a ``trade_date`` the ``code``-th expiry of
a flag is the ``code``-th entry of the sorted expiry list on or after ``trade_date`` (the expiry day
itself still counts as code 1).
"""
from __future__ import annotations

import bisect
import json
from datetime import date
from pathlib import Path

import structlog

log = structlog.get_logger()

_FLAGS = ("WEEK", "MONTH")


# ── Runtime calendar (reads cache) ───────────────────────────────────────────

class NiftyExpiryCalendar:
    """Sorted real expiry dates per flag, with ``resolve_expiry`` lookup.

    Despite the name this class is fully generic — it loads any ``{flag: [dates]}`` JSON cache
    and works for any underlying (NIFTY, BANKNIFTY, SENSEX, …). Use :func:`load_expiry_calendar`
    or the ``ExpiryCalendar`` alias for new code.
    """

    def __init__(self, expiries: dict[str, list[date]]) -> None:
        self._by_flag: dict[str, list[date]] = {
            flag: sorted(set(dates)) for flag, dates in expiries.items()
        }

    @classmethod
    def load(cls, cache_path: str | Path,
             extra: dict[str, list[date]] | None = None) -> NiftyExpiryCalendar:
        """Load the cached calendar, optionally merging ``extra`` forward expiries per flag."""
        data = json.loads(Path(cache_path).read_text())
        parsed: dict[str, list[date]] = {
            flag: [date.fromisoformat(s) for s in dates] for flag, dates in data.items()
        }
        if extra:
            for flag, dates in extra.items():
                parsed.setdefault(flag, []).extend(dates)
        return cls(parsed)

    def expiries(self, flag: str) -> list[date]:
        return self._by_flag.get(flag.upper(), [])

    def resolve_expiry(self, trade_date: date, flag: str, code: int) -> date | None:
        """The ``code``-th ``flag`` expiry on or after ``trade_date`` (expiry day counts as code 1).

        Returns ``None`` when the calendar does not extend far enough to resolve the request.
        """
        if code < 1:
            raise ValueError("expiry_code must be >= 1")
        dates = self._by_flag.get(flag.upper())
        if not dates:
            return None
        i = bisect.bisect_left(dates, trade_date)  # first expiry >= trade_date
        j = i + (code - 1)
        return dates[j] if 0 <= j < len(dates) else None


# Generic alias — NiftyExpiryCalendar is already symbol-agnostic; this alias signals intent.
ExpiryCalendar = NiftyExpiryCalendar


def load_expiry_calendar(symbol: str, path: str | Path,
                         extra: dict[str, list[date]] | None = None) -> NiftyExpiryCalendar:
    """Load the expiry calendar for ``symbol`` from its pre-built JSON cache at ``path``.

    The cache must follow the ``{flag: ["YYYY-MM-DD", ...]}`` format.
    """
    log.debug("expiry_calendar_load", symbol=symbol, path=str(path))
    return NiftyExpiryCalendar.load(path, extra)
