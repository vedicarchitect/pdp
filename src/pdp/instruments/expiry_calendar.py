"""NIFTY expiry calendar — resolve (trade_date, expiry_flag, expiry_code) → real expiry_date.

The expiry list is derived **empirically** (no hardcoded weekday/holiday rules) so it survives
the NIFTY weekly-expiry weekday regime changes (Thursday → Wednesday → Tuesday) and holiday
shifts automatically:

* **History** — OI-reset detection on the abi-project DuckDB `expired_options_ohlcv`. On expiry
  rollover the first bar of D+1 belongs to a fresh contract with near-zero OI, so the ratio
  ``first_bar_oi[D+1] / first_bar_oi[D]`` drops below ~0.55 only on a true expiry day D.
  (Approach ported from ``Abi/src/data/bootstrap_expiry_history.py``.)
* **Forward** — additional expiry dates (beyond the DuckDB cutoff, or future weeks) supplied by
  callers from the live instruments table / masters snapshot, which hold the ground truth.

Detection requires ``duckdb`` and the source DB; it is run once by a builder/script and cached to
JSON (``settings.EXPIRY_CACHE_PATH``). Runtime consumers only read the cache — no DuckDB dependency
on the hot path.

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

# OI-reset ratio threshold: first-bar total OI on D+1 vs D. < 0.55 ⇒ rollover (fresh contract).
OI_RESET_THRESHOLD = 0.55

_FLAGS = ("WEEK", "MONTH")


# ── Detection (builder side; requires duckdb + source DB) ────────────────────────

def detect_expiries(duck_path: str | Path, flag: str, *, threshold: float = OI_RESET_THRESHOLD,
                    code: int = 1) -> list[date]:
    """Detect real expiry dates for ``flag`` via first-bar OI-reset on the DuckDB source."""
    import duckdb  # lazy: only the builder needs it

    con = duckdb.connect(str(duck_path), read_only=True)
    try:
        rows = con.execute(
            """
            WITH first_bar AS (
                SELECT CAST(timestamp AS DATE) AS dt, SUM(oi) AS day_oi
                FROM (
                    SELECT timestamp, oi, ROW_NUMBER() OVER (
                        PARTITION BY CAST(timestamp AS DATE), strike_price, option_type
                        ORDER BY timestamp ASC) AS rn
                    FROM expired_options_ohlcv
                    WHERE expiry_flag = ? AND expiry_code = ? AND oi IS NOT NULL AND oi > 0
                ) sub
                WHERE rn = 1
                GROUP BY CAST(timestamp AS DATE)
            )
            SELECT dt, day_oi FROM first_bar ORDER BY dt
            """,
            [flag, code],
        ).fetchall()
    finally:
        con.close()

    expiries: list[date] = []
    for i in range(len(rows) - 1):
        _, oi_curr = rows[i]
        _, oi_next = rows[i + 1]
        if oi_curr and oi_curr > 0 and (oi_next / oi_curr) < threshold:
            expiries.append(rows[i][0])
    return expiries


def build_cache(duck_path: str | Path, out_path: str | Path,
                *, threshold: float = OI_RESET_THRESHOLD) -> dict[str, list[date]]:
    """Detect WEEK + MONTH expiries from the source and persist them to ``out_path`` (JSON)."""
    result: dict[str, list[date]] = {}
    for flag in _FLAGS:
        dates = detect_expiries(duck_path, flag, threshold=threshold)
        result[flag] = dates
        log.info("expiry_detected", flag=flag, count=len(dates),
                 first=str(dates[0]) if dates else None, last=str(dates[-1]) if dates else None)
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({f: [d.isoformat() for d in ds] for f, ds in result.items()}, indent=2))
    log.info("expiry_cache_written", path=str(out))
    return result


# ── Runtime calendar (reads cache; no duckdb) ────────────────────────────────────

class NiftyExpiryCalendar:
    """Sorted real expiry dates per flag, with ``resolve_expiry`` lookup."""

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
