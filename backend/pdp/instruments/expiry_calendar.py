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
import itertools
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


# ── Expiry-cadence gap detection ─────────────────────────────────────────────

# (expected days between consecutive real expiries, holiday-shift tolerance in days).
#
# Empirically weekly, not the config-time assumption: BANKNIFTY's real-world forward listing
# went monthly-only (regime change, per `expiry-and-feed-truth`'s live scrip-master lookup), but
# `option_bars`' *historical* distinct-expiry set stays weekly-cadence right through 2026-07
# (confirmed via `real_expiries_from_option_bars` audit, `option-bars-expiry-gap-backfill`,
# 2026-07-13) — the backfill path (`pdp.options.gap_backfill.fill_day`) resolves every day
# against the "WEEK" flag unconditionally, so that's what's actually stored. Using a monthly
# threshold here against data that is still weekly would make the detector blind to BANKNIFTY's
# real gaps (false negatives); match the threshold to what is actually persisted.
_EXPECTED_CADENCE: dict[str, tuple[int, int]] = {
    "NIFTY": (7, 3),
    "SENSEX": (7, 3),
    "BANKNIFTY": (7, 3),
}
_DEFAULT_CADENCE = _EXPECTED_CADENCE["NIFTY"]


def expiry_cadence_threshold(underlying: str) -> int:
    """Max days between two consecutive real expiries before it's a coverage gap.

    ``expected_cadence + holiday_tolerance``, so a real holiday-shifted listing (a few days
    later than usual) is never mistaken for a missing expiry.
    """
    cadence, tolerance = _EXPECTED_CADENCE.get(underlying, _DEFAULT_CADENCE)
    return cadence + tolerance


def expiry_cadence_gaps(
    underlying: str,
    real_expiries: list[date],
    *,
    cadence_days: int | None = None,
    tolerance_days: int | None = None,
) -> list[tuple[str, date, date, int]]:
    """Cadence gaps in ``real_expiries`` (as from :func:`real_expiries_from_option_bars`).

    A gap is a stretch between two consecutive claimed expiries wider than the underlying's
    expected listing cadence (see :data:`_EXPECTED_CADENCE`) — i.e. an expiry that should have
    been listed and ingested is entirely absent, not merely incomplete. Distinguishes this from
    a legitimate lower-cadence stretch (e.g. a genuinely monthly-only underlying) using the
    underlying's own threshold rather than one global number.

    ``cadence_days``/``tolerance_days`` override the underlying's configured cadence (for
    underlyings not in :data:`_EXPECTED_CADENCE`, or to test a hypothetical cadence directly).

    Returns ``(underlying, gap_start, gap_end, gap_days)`` tuples, sorted by ``gap_start``.
    """
    if cadence_days is not None:
        threshold = cadence_days + (tolerance_days or 0)
    else:
        threshold = expiry_cadence_threshold(underlying)
    exps = sorted(set(real_expiries))
    gaps: list[tuple[str, date, date, int]] = []
    for prev, nxt in itertools.pairwise(exps):
        span = (nxt - prev).days
        if span > threshold:
            gaps.append((underlying, prev, nxt, span))
    return gaps


# ── DB-backed confirmed-expiry store ─────────────────────────────────────────
#
# Persistent alternative to the static `data/expiry/*.json` cache for callers (chiefly
# `pdp.options.gap_backfill`) that need to resolve a target expiry for a trade date. The JSON
# cache was built from the same incomplete ingestion history as `option_bars` itself, so it
# carries the identical coverage gaps — a tool resolving expiries from it can never target a
# genuinely-missing expiry (see `option-bars-expiry-gap-backfill`, 2026-07-13, where this was
# proven: `NiftyExpiryCalendar.load(json)` silently mislabelled real Dhan data under the wrong
# far-side expiry for a confirmed 2023-03-23 gap day). `expiry_calendar` (Mongo, regular
# collection) is the persistent, editable source of truth instead: one doc per
# `(underlying, flag, expiry_date)`, seeded via `scripts/seed_expiry_calendar.py`.


def classify_month_expiries(all_expiries: list[date]) -> tuple[list[date], list[date]]:
    """Split real expiries into ``(week_list, month_list)`` for calendar seeding.

    Cadence-agnostic and **weekday-free** (satisfies the module's no-hardcoded-weekday rule): the
    "monthly" expiry is simply the *last* real expiry within each ``(year, month)`` — the same rule
    openalgo's expiry categorisation uses. Dhan's ``expiry_flag="WEEK"`` code counts *every* weekly
    expiry (the monthly is also the last weekly of its month), so ``week_list`` is all of them; its
    ``"MONTH"`` code counts only the monthlies, so ``month_list`` is the last-of-month subset.
    """
    week_list = sorted(set(all_expiries))
    last_of_month: dict[tuple[int, int], date] = {}
    for d in week_list:
        last_of_month[(d.year, d.month)] = d  # sorted ascending → keeps the last
    month_list = sorted(last_of_month.values())
    return week_list, month_list


def load_expiry_calendar_from_db(mdb: Any, underlying: str) -> NiftyExpiryCalendar:
    """Build a :class:`NiftyExpiryCalendar` from the `expiry_calendar` Mongo collection.

    Drop-in replacement for ``NiftyExpiryCalendar.load(json_path)`` — same in-memory shape,
    persistent DB source instead of a static file.
    """
    by_flag: dict[str, list[date]] = {}
    for doc in mdb["expiry_calendar"].find({"underlying": underlying.upper()}):
        d = doc["expiry_date"]
        d = d.date() if isinstance(d, datetime) else d
        by_flag.setdefault(doc["flag"].upper(), []).append(d)
    return NiftyExpiryCalendar(by_flag)


def upsert_confirmed_expiries(
    mdb: Any, underlying: str, flag: str, dates: list[date], *, source: str,
    lot_by_date: dict[date, int] | None = None,
) -> int:
    """Upsert confirmed real expiry dates into the `expiry_calendar` collection.

    Idempotent on the unique key `(underlying, flag, expiry_date)`; re-adding an already-known
    date does not re-insert it, but the enrichment fields are always refreshed via `$set` so a
    later run (e.g. the NSE-archive seed) can upgrade an earlier bare `option_bars_observed` doc
    with the weekday / lot size it now knows. Returns the number of newly-*inserted* dates.

    Enrichment (for backtest ↔ `option_bars` mapping across strategies):

    - `expiry_weekday` / `expiry_weekday_num` — always stamped (pure function of the date); the
      weekday-regime signal (NIFTY Thu→Wed→Tue, SENSEX Thu, …) every DTE/expiry-day filter needs.
    - `lot_size` — stamped when `lot_by_date` supplies it (NSE bhavcopy `NewBrdLotQty`); left
      untouched otherwise so a known lot is never overwritten with a guess.
    """
    from pymongo import UpdateOne

    col = mdb["expiry_calendar"]
    lot_by_date = lot_by_date or {}
    u, f = underlying.upper(), flag.upper()
    ops = []
    for d in dates:
        set_fields: dict[str, Any] = {
            "expiry_weekday": d.strftime("%A"),
            "expiry_weekday_num": d.weekday(),  # Mon=0 … Sun=6
        }
        lot = lot_by_date.get(d)
        if lot is not None:
            set_fields["lot_size"] = int(lot)
        ops.append(UpdateOne(
            {"underlying": u, "flag": f, "expiry_date": _expiry_to_dt(d)},
            {
                "$setOnInsert": {
                    "underlying": u, "flag": f, "expiry_date": _expiry_to_dt(d),
                    "source": source, "confirmed_at": datetime.now(),
                },
                "$set": set_fields,
            },
            upsert=True,
        ))
    if not ops:
        return 0
    res = col.bulk_write(ops, ordered=False)
    return res.upserted_count


def _expiry_to_dt(d: date) -> datetime:
    return datetime(d.year, d.month, d.day)


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
