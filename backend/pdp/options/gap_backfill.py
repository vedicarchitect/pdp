"""Reusable Dhan gap-fill core for the ``option_bars`` warehouse.

Shared by two callers:

* ``scripts/backfill_options_gap.py`` — one-shot CLI gap-fill of the post-Abi tail.
* ``pdp.warehouse.service`` — the running warehouser's periodic self-healing loop, which scans a
  rolling look-back window for missing trade-days and backfills them automatically.

Everything here is **synchronous and blocking** (the Dhan REST data API + pymongo): the async
warehouser runs :func:`run_gap_backfill` inside ``asyncio.to_thread`` so the event loop never
blocks. First-write-wins upserts keep re-fills non-duplicate, so re-running a fully-covered day is
harmless (inserts 0).

The rolling-option API is ATM-relative, so each bar's actual strike is derived from the NIFTY index
1-minute close at the same minute (``strike = round(spot/STEP)*STEP + offset*STEP``); the real
``expiry_date`` comes from the expiry calendar.

Performance design
------------------
Each trade-day requires 1 spot call + (ladder * labels * 2 sides) option calls, where ``ladder`` is
the list of ``(expiry_flag, expiry_code)`` pairs fetched (see :data:`DEFAULT_LADDER`). The live
self-heal loop uses the lighter :data:`SELF_HEAL_LADDER` (2 entries, ~45 calls/day at band=5); the
one-shot CLI's full ladder (5 entries) is ~2.5x that. A global token-bucket rate limiter caps
throughput at ``_API_RATE`` req/sec (under Dhan's published 5/sec limit). Option calls for a day are
dispatched concurrently via ``ThreadPoolExecutor(max_workers=_MAX_WORKERS)``. All docs are collected
in memory and written in a single ``bulk_write`` per day to minimise MongoDB round trips.
"""

from __future__ import annotations

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, date, datetime, timedelta
from datetime import time as _dtime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import structlog

from pdp.instruments.symbols import symbol_for
from pdp.options.warehouse import build_option_bar_doc, upsert_option_bars_sync

if TYPE_CHECKING:
    from pdp.instruments.expiry_calendar import NiftyExpiryCalendar

log = structlog.get_logger()

IST = timedelta(hours=5, minutes=30)
_IST_MS = int(IST.total_seconds() * 1000)

_API_RATE = 3.0  # max requests per second (Dhan limit is 5; we stay under)
_MAX_WORKERS = 1  # concurrent option-fetch threads per day
_RETRY_ATTEMPTS = 1  # retries on DH-904 / transient errors
_RETRY_BASE_SLEEP = 2.0  # seconds; doubles each retry (2→4→8→16)

# ── Expiry ladder ────────────────────────────────────────────────────────────
#
# Dhan's ``expired_options_data`` is ATM-relative and addresses an expiry by
# ``(expiry_flag, expiry_code)`` — flag ∈ {WEEK, MONTH}, code documented as 0-3 only. There is no
# way to ask for "the 9th weekly", so full "weekly → next-month monthly" coverage is expressed as a
# *ladder* of (flag, code) pairs: the near weeklies plus the current/next monthly. Each pair is
# resolved to a real expiry date via the calendar (or an explicit override) before fetching; the
# response carries no expiry date, so this labelling is the caller's responsibility.
#
# ``DEFAULT_LADDER`` is what the one-shot CLI backfill uses (full ladder). The live warehouse
# self-heal loop keeps the lighter ``SELF_HEAL_LADDER`` (unchanged WEEK 1-2 behaviour) so the hot
# 4-hourly cycle is not made 2.5x heavier and so it never depends on a MONTH list the JSON cache may
# lack.
DEFAULT_LADDER: list[tuple[str, int]] = [
    ("WEEK", 1),
    ("WEEK", 2),
    ("WEEK", 3),
    ("MONTH", 1),
    ("MONTH", 2),
]
SELF_HEAL_LADDER: list[tuple[str, int]] = [("WEEK", 1), ("WEEK", 2)]


def build_ladder(week_codes: list[int], month_codes: list[int]) -> list[tuple[str, int]]:
    """Compose a ladder from separate WEEK / MONTH code lists (CLI convenience)."""
    return [("WEEK", c) for c in week_codes] + [("MONTH", c) for c in month_codes]


# ── Global token-bucket rate limiter ─────────────────────────────────────────


class _RateLimiter:
    """Thread-safe token bucket: at most ``rate`` acquire() calls per second."""

    def __init__(self, rate: float) -> None:
        self._rate = rate
        self._tokens: float = rate  # start full so first burst is immediate
        self._last: float = time.monotonic()
        self._lock = threading.Lock()

    def acquire(self) -> None:
        while True:
            with self._lock:
                now = time.monotonic()
                self._tokens = min(
                    self._rate,
                    self._tokens + (now - self._last) * self._rate,
                )
                self._last = now
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return
                wait = (1.0 - self._tokens) / self._rate
            time.sleep(wait)


_rate_limiter = _RateLimiter(_API_RATE)


# ── Trade-day / band enumeration ─────────────────────────────────────────────


def labels(band: int) -> list[tuple[str, int]]:
    """ATM-relative labels with their grid offsets: ATM, ATM±1 .. ATM±band."""
    out = [("ATM", 0)]
    for i in range(1, band + 1):
        out += [(f"ATM+{i}", i), (f"ATM-{i}", -i)]
    return out


def holidays(holidays_json: str | Path) -> set[date]:
    """Load NSE holiday dates from a ``{"dates": ["YYYY-MM-DD", ...]}`` JSON file."""
    try:
        with open(holidays_json) as fh:
            return {date.fromisoformat(d) for d in json.load(fh).get("dates", [])}
    except FileNotFoundError:
        log.warning("nse_holidays_json_missing", path=str(holidays_json))
        return set()


def trading_days(start: date, end: date, holiday_set: set[date]) -> list[date]:
    """Weekday dates in ``[start, end]`` excluding NSE holidays."""
    days, d = [], start
    while d <= end:
        if d.weekday() < 5 and d not in holiday_set:
            days.append(d)
        d += timedelta(days=1)
    return days


# ── Dhan payload helpers ──────────────────────────────────────────────────────


def unwrap_side(resp: dict, opt_type: str) -> dict | None:
    """Drill into the (possibly double-wrapped) rolling-option payload for one side."""
    if not (isinstance(resp, dict) and resp.get("status") == "success"):
        return None
    key = "ce" if opt_type == "CE" else "pe"
    data = resp.get("data", {})
    while (
        isinstance(data, dict)
        and "data" in data
        and "ce" not in data
        and "pe" not in data
        and "open" not in data
    ):
        data = data["data"]
    if isinstance(data, dict) and key in data:
        data = data[key]
    if isinstance(data, dict) and "data" in data and "open" not in data:
        data = data["data"]
    return data if isinstance(data, dict) and "open" in data else None


def spot_by_minute(dhan: Any, ds: str, *, underlying_sid: int = 13) -> dict[datetime, float]:
    """Index 1m close keyed by UTC minute, to derive ATM per bar."""
    for attempt in range(_RETRY_ATTEMPTS):
        _rate_limiter.acquire()
        r = dhan.intraday_minute_data(
            security_id=str(underlying_sid),
            exchange_segment="IDX_I",
            instrument_type="INDEX",
            from_date=ds,
            to_date=ds,
            interval=1,
        )
        if isinstance(r, dict) and r.get("error_code") == "DH-904":
            sleep_s = _RETRY_BASE_SLEEP * (2**attempt)
            log.warning("gap_fill_spot_rate_limited", day=ds, attempt=attempt, retry_in=sleep_s)
            time.sleep(sleep_s)
            continue
        data = r.get("data", {}) if isinstance(r, dict) else {}
        if isinstance(data, dict) and "data" in data and "open" not in data:
            data = data["data"]
        if not isinstance(data, dict):
            log.warning(
                "gap_fill_spot_unavailable",
                day=ds,
                status=r.get("status") if isinstance(r, dict) else None,
                remarks=r.get("remarks") if isinstance(r, dict) else None,
            )
            return {}
        closes, tss = data.get("close", []), data.get("timestamp", data.get("start_Time", []))
        out: dict[datetime, float] = {}
        for i, c in enumerate(closes):
            if c is None or i >= len(tss):
                continue
            t = tss[i]
            bt = (
                datetime.fromtimestamp(t, tz=UTC)
                if isinstance(t, (int, float))
                else datetime.fromisoformat(str(t)).astimezone(UTC)
            )
            out[bt.replace(second=0, microsecond=0)] = float(c)
        return out
    return {}


def bars_to_docs(
    data: dict,
    spot: dict[datetime, float],
    exp: date,
    ot: str,
    label: str,
    offset: int,
    *,
    underlying: str = "NIFTY",
    strike_step: int = 50,
    expiry_flag: str = "WEEK",
) -> list[dict]:
    """Convert one rolling-option side payload into fixed-strike option_bars docs."""
    o, h, lo, c = data["open"], data["high"], data["low"], data["close"]
    vol, oi, iv = data.get("volume", []), data.get("oi", []), data.get("iv", [])
    tss = data.get("timestamp", data.get("start_Time", []))
    docs = []
    for i in range(len(c)):
        if not c[i] or i >= len(tss):
            continue
        t = tss[i]
        bt = (
            datetime.fromtimestamp(t, tz=UTC)
            if isinstance(t, (int, float))
            else datetime.fromisoformat(str(t)).astimezone(UTC)
        ).replace(second=0, microsecond=0)
        sp = spot.get(bt)
        if sp is None:
            continue
        strike = round(sp / strike_step) * strike_step + offset * strike_step
        docs.append(
            build_option_bar_doc(
                underlying=underlying,
                expiry_date=exp,
                strike=float(strike),
                option_type=ot,
                timeframe="1m",
                ts=bt,
                open=o[i],
                high=h[i],
                low=lo[i],
                close=c[i],
                volume=vol[i] if i < len(vol) else 0,
                oi=oi[i] if i < len(oi) else 0,
                iv=iv[i] if i < len(iv) else 0.0,
                expiry_flag=expiry_flag,
                strike_label=label,
                trading_symbol=symbol_for(underlying, exp, float(strike), ot),
                source="dhan_api",
            )
        )
    return docs


def fill_day(
    dhan: Any,
    col: Any,
    cal: NiftyExpiryCalendar | None,
    ds: str,
    ladder: list[tuple[str, int]],
    label_offsets: list[tuple[str, int]],
    *,
    underlying: str = "NIFTY",
    underlying_sid: int = 13,
    strike_step: int = 50,
    exchange_segment: str = "NSE_FNO",
    expiry_override: date | None = None,
) -> int:
    """Backfill one trade day's band from Dhan; returns the number of new bars inserted.

    ``ladder`` is a list of ``(expiry_flag, expiry_code)`` pairs (e.g. :data:`DEFAULT_LADDER`);
    each is resolved to a real expiry via ``cal.resolve_expiry(day, flag, code)`` and fetched with
    that flag, so a single day can span the near weeklies *and* the current/next monthly.

    Spot data is fetched sequentially first (needed to derive strikes).  The option-series calls
    are then dispatched concurrently up to ``_MAX_WORKERS`` threads, all sharing a global
    token-bucket rate limiter.  All resulting docs are collected and written in a single
    ``bulk_write`` to minimise MongoDB round-trips.

    ``expiry_override``, when given, labels *every* ladder entry with that one target expiry
    instead of ``cal.resolve_expiry()`` (``cal`` may then be ``None``). Because every fetched
    series is then labelled the same, callers must pass a **single-entry** ladder with the
    ``(flag, code)`` that actually resolves to that expiry on ``ds`` (see
    :func:`backfill_missing_expiry`) — a multi-entry ladder under an override would mislabel the
    other contracts. This exists to reach a genuinely-missing expiry the calendar cannot yet
    resolve; see `pdp.instruments.expiry_calendar`'s "DB-backed confirmed-expiry store" section.
    """
    spot = spot_by_minute(dhan, ds, underlying_sid=underlying_sid)
    if not spot:
        log.warning("gap_fill_no_spot", day=ds, underlying=underlying)
        return 0

    # Interior-gap check on spot bars: if there is a hole in the minute series
    # between the first and last bar the day is suspect; skip rather than persist holes.
    # Dhan's intraday endpoint can return a single stray tick well outside the
    # 09:15-15:30 IST session (observed: one bar at 18:33 IST on an otherwise
    # complete day) — used unfiltered, that stray bar becomes the "last" key and
    # makes a complete session look like it has one giant gap after close. Clip
    # to the session window (03:45-10:00 UTC = 09:15-15:30 IST, +5min buffer)
    # before computing the gap so a genuine complete day isn't skipped.
    _session_start = datetime.combine(date.fromisoformat(ds), _dtime(3, 45), tzinfo=UTC)
    _session_end = datetime.combine(date.fromisoformat(ds), _dtime(10, 5), tzinfo=UTC)
    spot_keys = sorted(k for k in spot if _session_start <= k <= _session_end)
    if spot_keys:
        expected_minutes = int((spot_keys[-1] - spot_keys[0]).total_seconds() / 60) + 1
        if expected_minutes > 1:
            # Build a list of per-minute presence booleans and treat each as a "chunk"
            from datetime import timedelta as _td

            minute_chunks = [
                [spot_keys[0] + _td(minutes=m)] if (spot_keys[0] + _td(minutes=m)) in spot else []
                for m in range(expected_minutes)
            ]
            if has_interior_gap(minute_chunks):
                log.warning(
                    "backfill_interior_gap",
                    day=ds,
                    underlying=underlying,
                    reason="spot minute series has interior empty chunks; skipping day",
                )
                return 0

    # Resolve expiries once per (flag, code) (avoids repeated calendar lookups in threads).
    expiries: dict[tuple[str, int], date | None] = {}
    for flag, code in ladder:
        if expiry_override is not None:
            expiries[(flag, code)] = expiry_override
        else:
            assert cal is not None, "cal is required when expiry_override is not given"
            expiries[(flag, code)] = cal.resolve_expiry(date.fromisoformat(ds), flag, code)

    # Build the full task list: (flag, code, exp, label, offset, opt_type)
    tasks: list[tuple[str, int, date, str, int, str]] = []
    for flag, code in ladder:
        exp = expiries.get((flag, code))
        if exp is None:
            log.warning("gap_fill_no_expiry", day=ds, flag=flag, code=code, underlying=underlying)
            continue
        for label, offset in label_offsets:
            for ot in ("CE", "PE"):
                tasks.append((flag, code, exp, label, offset, ot))

    if not tasks:
        return 0

    def _fetch_one(task: tuple[str, int, date, str, int, str]) -> list[dict]:
        flag, code, exp, label, offset, ot = task
        drv = "CALL" if ot == "CE" else "PUT"
        for attempt in range(_RETRY_ATTEMPTS):
            _rate_limiter.acquire()
            try:
                resp = dhan.expired_options_data(
                    security_id=underlying_sid,
                    exchange_segment=exchange_segment,
                    instrument_type="OPTIDX",
                    expiry_flag=flag,
                    expiry_code=code,
                    strike=label,
                    drv_option_type=drv,
                    required_data=["open", "high", "low", "close", "volume", "oi", "iv"],
                    from_date=ds,
                    to_date=ds,
                    interval=1,
                )
            except Exception as exc:
                log.warning(
                    "gap_fill_api_error", day=ds, flag=flag, code=code, label=label, ot=ot,
                    attempt=attempt, exc=str(exc),
                )
                if attempt < _RETRY_ATTEMPTS - 1:
                    time.sleep(_RETRY_BASE_SLEEP * (2**attempt))
                    continue
                return []
            # Detect DH-904 rate-limit response (dict, not exception)
            if isinstance(resp, dict) and resp.get("error_code") == "DH-904":
                sleep_s = _RETRY_BASE_SLEEP * (2**attempt)
                log.warning(
                    "gap_fill_rate_limited",
                    day=ds,
                    flag=flag,
                    code=code,
                    label=label,
                    ot=ot,
                    attempt=attempt,
                    retry_in=sleep_s,
                )
                time.sleep(sleep_s)
                continue
            data = unwrap_side(resp, ot)
            if not data:
                return []
            return bars_to_docs(
                data, spot, exp, ot, label, offset, underlying=underlying,
                strike_step=strike_step, expiry_flag=flag,
            )
        return []

    # Fan out concurrently; collect all docs; single bulk upsert.
    all_docs: list[dict] = []
    with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as executor:
        futures = {executor.submit(_fetch_one, t): t for t in tasks}
        for fut in as_completed(futures):
            try:
                all_docs.extend(fut.result())
            except Exception as exc:
                task = futures[fut]
                log.warning("gap_fill_worker_error", day=ds, task=str(task), exc=str(exc))

    return upsert_option_bars_sync(col, all_docs)


# ── Interior-gap detection (market-feed-resilience) ──────────────────────────


def nonempty_idx(chunks: list[list]) -> list[int]:
    """Return indices of non-empty chunks (those with at least one bar)."""
    return [i for i, ch in enumerate(chunks) if ch]


def has_interior_gap(chunks: list[list]) -> bool:
    """Return True if any empty chunk sits strictly between two non-empty chunks.

    A leading or trailing empty window is acceptable (market not yet open / already
    closed).  An empty chunk with data on both sides indicates a Dhan fetch hole.
    """
    ne = nonempty_idx(chunks)
    if len(ne) < 2:
        return False
    first, last = ne[0], ne[-1]
    for i in range(first + 1, last):
        if not chunks[i]:
            return True
    return False


# ── Gap detection ─────────────────────────────────────────────────────────────


def collapse_date_ranges(days: list[date]) -> list[str]:
    """Collapse a sorted/unsorted date list into ``['YYYY-MM-DD..YYYY-MM-DD', 'YYYY-MM-DD', …]``
    ranges, tolerating weekend/holiday gaps of up to 3 calendar days between trade days.

    Shared by ``scripts/audit_options_coverage.py`` and ``pdp.warehouse.coverage`` so both report
    gaps identically.
    """
    days = sorted(days)
    if not days:
        return []
    out, start, prev = [], days[0], days[0]
    for d in days[1:]:
        if (d - prev).days <= 3:
            prev = d
            continue
        out.append(str(start) if start == prev else f"{start}..{prev}")
        start = prev = d
    out.append(str(start) if start == prev else f"{start}..{prev}")
    return out


def expected_contracts(ladder: list[tuple[str, int]], band: int) -> int:
    """Distinct (expiry, strike, side) contracts a fully-covered day should hold."""
    return len(ladder) * (2 * band + 1) * 2


def _ist_day_window(d: date) -> tuple[datetime, datetime]:
    """UTC [lo, hi) bounds covering the IST trade-day ``d``."""
    lo = (datetime(d.year, d.month, d.day) - IST).replace(tzinfo=UTC)
    return lo, lo + timedelta(days=1)


def days_missing(
    col: Any,
    days: list[date],
    ladder: list[tuple[str, int]],
    band: int,
    *,
    min_fraction: float = 0.5,
    underlying: str = "NIFTY",
) -> list[date]:
    """Trade-days whose option_bars coverage is below ``min_fraction`` of the expected band.

    A single aggregation counts distinct contracts per IST-day across the window; any day with
    fewer than ``min_fraction * expected_contracts`` distinct contracts (including days entirely
    absent) is reported as a gap. The fraction tolerates band-edge strikes that simply did not
    trade while still catching fully-missing or severely-incomplete days.
    """
    if not days:
        return []
    threshold = expected_contracts(ladder, band) * min_fraction
    win_lo, _ = _ist_day_window(min(days))
    _, win_hi = _ist_day_window(max(days))
    pipeline = [
        {"$match": {"underlying": underlying, "timeframe": "1m", "ts": {"$gte": win_lo, "$lt": win_hi}}},
        {
            "$group": {
                "_id": {
                    "day": {"$dateTrunc": {"date": {"$add": ["$ts", _IST_MS]}, "unit": "day"}},
                    "contract": {"e": "$expiry_date", "s": "$strike", "o": "$option_type"},
                }
            }
        },
        {"$group": {"_id": "$_id.day", "contracts": {"$sum": 1}}},
    ]
    counts: dict[date, int] = {}
    for row in col.aggregate(pipeline):
        day_dt = row["_id"]
        counts[day_dt.date()] = row["contracts"]
    return [d for d in days if counts.get(d, 0) < threshold]


# ── High-level entry points ───────────────────────────────────────────────────


def backfill_gaps(
    *,
    dhan: Any,
    col: Any,
    cal: NiftyExpiryCalendar,
    days: list[date],
    ladder: list[tuple[str, int]],
    band: int,
    min_fraction: float = 0.5,
    only_missing: bool = True,
    underlying: str = "NIFTY",
    underlying_sid: int = 13,
    strike_step: int = 50,
    exchange_segment: str = "NSE_FNO",
) -> dict[str, Any]:
    """Detect gaps over ``days`` and backfill them. Returns a summary dict.

    ``ladder`` is the list of ``(expiry_flag, expiry_code)`` pairs to fetch per day (see
    :data:`DEFAULT_LADDER`). With ``only_missing`` (default) just the under-covered days are
    fetched; set it False to re-fetch every day in the window (still idempotent via
    first-write-wins) — required after seeding a previously-missing expiry into the calendar,
    since those days already look "full" against the wrong expiry.
    """
    targets = (
        days_missing(col, days, ladder, band, min_fraction=min_fraction, underlying=underlying)
        if only_missing
        else days
    )
    label_offsets = labels(band)
    total, filled = 0, 0
    for d in targets:
        n = fill_day(
            dhan,
            col,
            cal,
            d.isoformat(),
            ladder,
            label_offsets,
            underlying=underlying,
            underlying_sid=underlying_sid,
            strike_step=strike_step,
            exchange_segment=exchange_segment,
        )
        total += n
        if n:
            filled += 1
        log.info("gap_fill_day_done", day=d.isoformat(), inserted=n, underlying=underlying)
    log.info(
        "gap_fill_done",
        scanned=len(days),
        gaps=len(targets),
        days_filled=filled,
        total_inserted=total,
        underlying=underlying,
    )
    return {
        "scanned": len(days),
        "gaps": len(targets),
        "days_filled": filled,
        "total_inserted": total,
        "gap_days": [d.isoformat() for d in targets],
    }


def backfill_missing_expiry(
    *,
    dhan: Any,
    col: Any,
    target_expiry: date,
    days: list[date],
    band: int,
    flag: str = "WEEK",
    code: int = 1,
    underlying: str = "NIFTY",
    underlying_sid: int = 13,
    strike_step: int = 50,
    exchange_segment: str = "NSE_FNO",
) -> dict[str, Any]:
    """Backfill ``days`` against a single known-but-uningested ``target_expiry``.

    Escape hatch for when the calendar cannot resolve an expiry at all. It bypasses calendar
    resolution and labels **every** fetched series as ``target_expiry`` — so it fetches exactly
    one ``(flag, code)`` per day (default WEEK code 1) and the caller must only pass ``days`` on
    which ``target_expiry`` genuinely is that ``(flag, code)`` (i.e. the expiry's own final week
    for WEEK/1). For a wider window prefer seeding ``target_expiry`` into the calendar and
    re-running :func:`backfill_gaps` with ``only_missing=False``, which labels each day correctly.

    Every day in ``days`` is unconditionally fetched (no ``only_missing`` gate — a day "fully
    covered" against the wrong expiry must still be re-fetched against the right one).
    """
    label_offsets = labels(band)
    ladder = [(flag, code)]
    total, filled = 0, 0
    for d in days:
        n = fill_day(
            dhan,
            col,
            None,
            d.isoformat(),
            ladder,
            label_offsets,
            underlying=underlying,
            underlying_sid=underlying_sid,
            strike_step=strike_step,
            exchange_segment=exchange_segment,
            expiry_override=target_expiry,
        )
        total += n
        if n:
            filled += 1
        log.info(
            "gap_fill_known_expiry_day_done",
            day=d.isoformat(),
            target_expiry=str(target_expiry),
            inserted=n,
            underlying=underlying,
        )
    log.info(
        "gap_fill_known_expiry_done",
        target_expiry=str(target_expiry),
        scanned=len(days),
        days_filled=filled,
        total_inserted=total,
        underlying=underlying,
    )
    return {
        "target_expiry": str(target_expiry),
        "scanned": len(days),
        "days_filled": filled,
        "total_inserted": total,
    }


def run_gap_backfill(
    *,
    settings: Any,
    cal: NiftyExpiryCalendar,
    lookback_days: int,
    ladder: list[tuple[str, int]] | None = None,
    band: int | None = None,
    end: date | None = None,
    underlying: str = "NIFTY",
    underlying_sid: int = 13,
    strike_step: int = 50,
    exchange_segment: str = "NSE_FNO",
) -> dict[str, Any]:
    """Blocking, self-contained gap backfill over a rolling look-back window.

    Builds its own sync pymongo collection + Dhan REST client from ``settings`` (so it is safe to
    run inside ``asyncio.to_thread`` from the async warehouser). Returns the :func:`backfill_gaps`
    summary, or ``{"skipped": ...}`` when creds/calendar are unavailable.
    """
    if not settings.DHAN_CLIENT_ID or not settings.DHAN_ACCESS_TOKEN:
        log.warning("gap_backfill_skipped", reason="no Dhan creds")
        return {"skipped": "no_dhan_creds"}

    band = band if band is not None else settings.WAREHOUSE_STRIKE_BAND
    ladder = ladder or SELF_HEAL_LADDER
    end = end or datetime.now(UTC).astimezone().date()
    start = end - timedelta(days=lookback_days)
    days = trading_days(start, end, holidays(settings.NSE_HOLIDAYS_JSON))
    if not days:
        return {"skipped": "no_trading_days", "from": str(start), "to": str(end)}

    from dhanhq import DhanContext, dhanhq
    from pymongo import MongoClient

    dhan = dhanhq(DhanContext(settings.DHAN_CLIENT_ID, settings.DHAN_ACCESS_TOKEN))
    col = MongoClient(
        settings.MONGO_URI,
        socketTimeoutMS=settings.MONGO_SOCKET_TIMEOUT_MS,
        connectTimeoutMS=settings.MONGO_CONNECT_TIMEOUT_MS,
        serverSelectionTimeoutMS=settings.MONGO_CONNECT_TIMEOUT_MS,
        maxPoolSize=1,  # one-shot background job; a single connection is sufficient
    )[settings.MONGO_DB_NAME]["option_bars"]
    log.info(
        "gap_backfill_scan",
        **{
            "from": str(start),
            "to": str(end),
            "trading_days": len(days),
            "ladder": ladder,
            "band": band,
            "underlying": underlying,
        },
    )
    return backfill_gaps(
        dhan=dhan,
        col=col,
        cal=cal,
        days=days,
        ladder=ladder,
        band=band,
        underlying=underlying,
        underlying_sid=underlying_sid,
        strike_step=strike_step,
        exchange_segment=exchange_segment,
    )
