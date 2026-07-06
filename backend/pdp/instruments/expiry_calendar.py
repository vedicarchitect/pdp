"""Expiry resolution — the one place every module resolves an option expiry or DTE.

The expiry list is derived **empirically** (no hardcoded weekday/holiday rules) so it survives
weekly-expiry weekday regime changes (e.g. NIFTY's Thursday → Wednesday → Tuesday history,
BANKNIFTY going monthly-only, SENSEX being Thursday not Tuesday) and holiday shifts
automatically. Never hardcode a weekday anywhere else — add a caller here instead.

Two lookup families, both generic/cadence-agnostic:

- **Live/dashboard/warehouse** (forward-looking): ``pdp.strategy.strikes.nearest_expiry`` reads
  the Dhan scrip master (``instruments`` table) — the authoritative source for "what expiries
  exist right now and in the future".
- **Backtest** (historical): ``real_expiries_from_option_bars`` / ``nearest_real_expiry`` (below)
  read the expiries actually stored in ``option_bars`` for a trade date — the authoritative
  source for "what expiry actually traded on this historical date".

``dte`` is the one shared calendar-days-to-expiry calculation used by every DTE filter.

The legacy ``NiftyExpiryCalendar`` (JSON-cache, weekday-projected) remains for any pre-existing
synthetic cache reads, but new code should prefer the two functions above.
"""
from __future__ import annotations

import bisect
import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

import structlog

log = structlog.get_logger()

_FLAGS = ("WEEK", "MONTH")


def dte(trade_date: date, expiry: date) -> int:
    """Calendar days from ``trade_date`` to ``expiry`` (0 = expiry day itself)."""
    return (expiry - trade_date).days


def within_dte(trade_date: date, expiry: date | None, dte_max: int | None) -> bool:
    """Whether ``trade_date`` is within ``dte_max`` calendar days of ``expiry``.

    ``dte_max=None`` means no filter (always True). An unresolved ``expiry`` (``None``) also
    passes through — a missing expiry is a data gap the caller's own gating handles elsewhere,
    not a DTE-filter decision.
    """
    if dte_max is None or expiry is None:
        return True
    return dte(trade_date, expiry) <= dte_max


def real_expiries_from_option_bars(mdb: Any, underlying: str) -> list[date]:
    """Distinct real expiries actually stored in ``option_bars`` for ``underlying``, sorted.

    This is the historically-correct expiry source for a backtest: the chain that truly
    existed per date, cadence-agnostic (weekly / monthly-only / weekday-shifted / regime
    change). Empty when the collection has no chain for the underlying.
    """
    vals = mdb["option_bars"].distinct("expiry_date", {"underlying": underlying})
    out: list[date] = []
    for v in vals:
        if isinstance(v, datetime):
            out.append(v.date())
        elif isinstance(v, date):
            out.append(v)
        elif isinstance(v, str):
            try:
                out.append(date.fromisoformat(v[:10]))
            except ValueError:
                continue
    return sorted(set(out))


def nearest_real_expiry(real_expiries: list[date], d: date) -> date | None:
    """The first real expiry on or after ``d`` (expiry day itself counts), else ``None``."""
    for e in real_expiries:
        if e >= d:
            return e
    return None


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
