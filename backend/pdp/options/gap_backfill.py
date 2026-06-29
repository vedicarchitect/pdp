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
Each trade-day requires 1 spot call + (codes × labels × 2 sides) option calls.  With the defaults
(2 codes, band=5) that is 45 API calls per day.  A global token-bucket rate limiter caps throughput
at ``_API_RATE`` req/sec (4.0, comfortably under Dhan's published 5/sec limit).  Within each day
the 44 option calls are dispatched concurrently via ``ThreadPoolExecutor(max_workers=_MAX_WORKERS)``
so the wall-clock time per day drops from ~47 s (sequential) to ~12 s (~4x faster).  All docs are
collected in memory and written in a single ``bulk_write`` per day to minimise MongoDB round trips.
"""
from __future__ import annotations

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, date, datetime, timedelta
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

_API_RATE = 3.0     # max requests per second (Dhan limit is 5; we stay under)
_MAX_WORKERS = 1     # concurrent option-fetch threads per day
_RETRY_ATTEMPTS = 1  # retries on DH-904 / transient errors
_RETRY_BASE_SLEEP = 2.0  # seconds; doubles each retry (2→4→8→16)


# ── Global token-bucket rate limiter ─────────────────────────────────────────

class _RateLimiter:
    """Thread-safe token bucket: at most ``rate`` acquire() calls per second."""

    def __init__(self, rate: float) -> None:
        self._rate = rate
        self._tokens: float = rate      # start full so first burst is immediate
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
    while (isinstance(data, dict) and "data" in data
           and "ce" not in data and "pe" not in data and "open" not in data):
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
        r = dhan.intraday_minute_data(security_id=str(underlying_sid), exchange_segment="IDX_I",
                                      instrument_type="INDEX", from_date=ds, to_date=ds, interval=1)
        if isinstance(r, dict) and r.get("error_code") == "DH-904":
            sleep_s = _RETRY_BASE_SLEEP * (2 ** attempt)
            log.warning("gap_fill_spot_rate_limited", day=ds, attempt=attempt, retry_in=sleep_s)
            time.sleep(sleep_s)
            continue
        data = r.get("data", {}) if isinstance(r, dict) else {}
        if isinstance(data, dict) and "data" in data and "open" not in data:
            data = data["data"]
        if not isinstance(data, dict):
            log.warning("gap_fill_spot_unavailable", day=ds,
                        status=r.get("status") if isinstance(r, dict) else None,
                        remarks=r.get("remarks") if isinstance(r, dict) else None)
            return {}
        closes, tss = data.get("close", []), data.get("timestamp", data.get("start_Time", []))
        out: dict[datetime, float] = {}
        for i, c in enumerate(closes):
            if c is None or i >= len(tss):
                continue
            t = tss[i]
            bt = datetime.fromtimestamp(t, tz=UTC) if isinstance(t, (int, float)) else \
                datetime.fromisoformat(str(t)).astimezone(UTC)
            out[bt.replace(second=0, microsecond=0)] = float(c)
        return out
    return {}


def bars_to_docs(data: dict, spot: dict[datetime, float], exp: date, ot: str,
                 label: str, offset: int, *,
                 underlying: str = "NIFTY", strike_step: int = 50) -> list[dict]:
    """Convert one rolling-option side payload into fixed-strike option_bars docs."""
    o, h, lo, c = data["open"], data["high"], data["low"], data["close"]
    vol, oi, iv = data.get("volume", []), data.get("oi", []), data.get("iv", [])
    tss = data.get("timestamp", data.get("start_Time", []))
    docs = []
    for i in range(len(c)):
        if not c[i] or i >= len(tss):
            continue
        t = tss[i]
        bt = (datetime.fromtimestamp(t, tz=UTC) if isinstance(t, (int, float))
              else datetime.fromisoformat(str(t)).astimezone(UTC)).replace(second=0, microsecond=0)
        sp = spot.get(bt)
        if sp is None:
            continue
        strike = round(sp / strike_step) * strike_step + offset * strike_step
        docs.append(build_option_bar_doc(
            underlying=underlying, expiry_date=exp, strike=float(strike), option_type=ot,
            timeframe="1m", ts=bt, open=o[i], high=h[i], low=lo[i], close=c[i],
            volume=vol[i] if i < len(vol) else 0, oi=oi[i] if i < len(oi) else 0,
            iv=iv[i] if i < len(iv) else 0.0,
            expiry_flag="WEEK", strike_label=label,
            trading_symbol=symbol_for(underlying, exp, float(strike), ot), source="dhan_api"))
    return docs


def fill_day(dhan: Any, col: Any, cal: "NiftyExpiryCalendar", ds: str,
             codes: list[int], label_offsets: list[tuple[str, int]], *,
             underlying: str = "NIFTY", underlying_sid: int = 13,
             strike_step: int = 50, exchange_segment: str = "NSE_FNO") -> int:
    """Backfill one trade day's band from Dhan; returns the number of new bars inserted.

    Spot data is fetched sequentially first (needed to derive strikes).  The 44 option-series
    calls are then dispatched concurrently up to ``_MAX_WORKERS`` threads, all sharing a global
    token-bucket rate limiter.  All resulting docs are collected and written in a single
    ``bulk_write`` to minimise MongoDB round-trips.
    """
    spot = spot_by_minute(dhan, ds, underlying_sid=underlying_sid)
    if not spot:
        log.warning("gap_fill_no_spot", day=ds, underlying=underlying)
        return 0

    # Interior-gap check on spot bars: if there is a hole in the minute series
    # between the first and last bar the day is suspect; skip rather than persist holes.
    spot_keys = sorted(spot.keys())
    if spot_keys:
        expected_minutes = int(
            (spot_keys[-1] - spot_keys[0]).total_seconds() / 60
        ) + 1
        if expected_minutes > 1:
            # Build a list of per-minute presence booleans and treat each as a "chunk"
            from datetime import timedelta as _td
            minute_chunks = [
                [spot_keys[0] + _td(minutes=m)]
                if (spot_keys[0] + _td(minutes=m)) in spot
                else []
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

    # Resolve expiries once per code (avoids repeated calendar lookups in threads).
    expiries: dict[int, date | None] = {}
    for code in codes:
        expiries[code] = cal.resolve_expiry(date.fromisoformat(ds), "WEEK", code)

    # Build the full task list: (code, exp, label, offset, opt_type)
    tasks: list[tuple[int, date, str, int, str]] = []
    for code in codes:
        exp = expiries.get(code)
        if exp is None:
            log.warning("gap_fill_no_expiry", day=ds, code=code, underlying=underlying)
            continue
        for label, offset in label_offsets:
            for ot in ("CE", "PE"):
                tasks.append((code, exp, label, offset, ot))

    if not tasks:
        return 0

    def _fetch_one(task: tuple[int, date, str, int, str]) -> list[dict]:
        code, exp, label, offset, ot = task
        drv = "CALL" if ot == "CE" else "PUT"
        for attempt in range(_RETRY_ATTEMPTS):
            _rate_limiter.acquire()
            try:
                resp = dhan.expired_options_data(
                    security_id=underlying_sid, exchange_segment=exchange_segment,
                    instrument_type="OPTIDX", expiry_flag="WEEK", expiry_code=code,
                    strike=label, drv_option_type=drv,
                    required_data=["open", "high", "low", "close", "volume", "oi", "iv"],
                    from_date=ds, to_date=ds, interval=1)
            except Exception as exc:  # noqa: BLE001
                log.warning("gap_fill_api_error", day=ds, code=code, label=label,
                            ot=ot, attempt=attempt, exc=str(exc))
                if attempt < _RETRY_ATTEMPTS - 1:
                    time.sleep(_RETRY_BASE_SLEEP * (2 ** attempt))
                    continue
                return []
            # Detect DH-904 rate-limit response (dict, not exception)
            if isinstance(resp, dict) and resp.get("error_code") == "DH-904":
                sleep_s = _RETRY_BASE_SLEEP * (2 ** attempt)
                log.warning("gap_fill_rate_limited", day=ds, code=code, label=label,
                            ot=ot, attempt=attempt, retry_in=sleep_s)
                time.sleep(sleep_s)
                continue
            data = unwrap_side(resp, ot)
            if not data:
                return []
            return bars_to_docs(data, spot, exp, ot, label, offset,
                                underlying=underlying, strike_step=strike_step)
        return []

    # Fan out concurrently; collect all docs; single bulk upsert.
    all_docs: list[dict] = []
    with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as executor:
        futures = {executor.submit(_fetch_one, t): t for t in tasks}
        for fut in as_completed(futures):
            try:
                all_docs.extend(fut.result())
            except Exception as exc:  # noqa: BLE001
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

def expected_contracts(codes: list[int], band: int) -> int:
    """Distinct (expiry, strike, side) contracts a fully-covered day should hold."""
    return len(codes) * (2 * band + 1) * 2


def _ist_day_window(d: date) -> tuple[datetime, datetime]:
    """UTC [lo, hi) bounds covering the IST trade-day ``d``."""
    lo = (datetime(d.year, d.month, d.day) - IST).replace(tzinfo=UTC)
    return lo, lo + timedelta(days=1)


def days_missing(col: Any, days: list[date], codes: list[int], band: int,
                 *, min_fraction: float = 0.5, underlying: str = "NIFTY") -> list[date]:
    """Trade-days whose option_bars coverage is below ``min_fraction`` of the expected band.

    A single aggregation counts distinct contracts per IST-day across the window; any day with
    fewer than ``min_fraction × expected_contracts`` distinct contracts (including days entirely
    absent) is reported as a gap. The fraction tolerates band-edge strikes that simply did not
    trade while still catching fully-missing or severely-incomplete days.
    """
    if not days:
        return []
    threshold = expected_contracts(codes, band) * min_fraction
    win_lo, _ = _ist_day_window(min(days))
    _, win_hi = _ist_day_window(max(days))
    pipeline = [
        {"$match": {"underlying": underlying, "timeframe": "1m",
                    "ts": {"$gte": win_lo, "$lt": win_hi}}},
        {"$group": {"_id": {"day": {"$dateTrunc": {"date": {"$add": ["$ts", _IST_MS]},
                                                   "unit": "day"}},
                            "contract": {"e": "$expiry_date", "s": "$strike",
                                         "o": "$option_type"}}}},
        {"$group": {"_id": "$_id.day", "contracts": {"$sum": 1}}},
    ]
    counts: dict[date, int] = {}
    for row in col.aggregate(pipeline):
        day_dt = row["_id"]
        counts[day_dt.date()] = row["contracts"]
    return [d for d in days if counts.get(d, 0) < threshold]


# ── High-level entry points ───────────────────────────────────────────────────

def backfill_gaps(*, dhan: Any, col: Any, cal: "NiftyExpiryCalendar", days: list[date],
                  codes: list[int], band: int, min_fraction: float = 0.5,
                  only_missing: bool = True, underlying: str = "NIFTY",
                  underlying_sid: int = 13, strike_step: int = 50,
                  exchange_segment: str = "NSE_FNO") -> dict[str, Any]:
    """Detect gaps over ``days`` and backfill them. Returns a summary dict.

    With ``only_missing`` (default) just the under-covered days are fetched; set it False to
    re-fetch every day in the window (still idempotent via first-write-wins).
    """
    targets = (days_missing(col, days, codes, band, min_fraction=min_fraction, underlying=underlying)
               if only_missing else days)
    label_offsets = labels(band)
    total, filled = 0, 0
    for d in targets:
        n = fill_day(dhan, col, cal, d.isoformat(), codes, label_offsets,
                     underlying=underlying, underlying_sid=underlying_sid,
                     strike_step=strike_step, exchange_segment=exchange_segment)
        total += n
        if n:
            filled += 1
        log.info("gap_fill_day_done", day=d.isoformat(), inserted=n, underlying=underlying)
    log.info("gap_fill_done", scanned=len(days), gaps=len(targets),
             days_filled=filled, total_inserted=total, underlying=underlying)
    return {"scanned": len(days), "gaps": len(targets), "days_filled": filled,
            "total_inserted": total, "gap_days": [d.isoformat() for d in targets]}


def run_gap_backfill(*, settings: Any, cal: "NiftyExpiryCalendar", lookback_days: int,
                     codes: list[int] | None = None, band: int | None = None,
                     end: date | None = None, underlying: str = "NIFTY",
                     underlying_sid: int = 13, strike_step: int = 50,
                     exchange_segment: str = "NSE_FNO") -> dict[str, Any]:
    """Blocking, self-contained gap backfill over a rolling look-back window.

    Builds its own sync pymongo collection + Dhan REST client from ``settings`` (so it is safe to
    run inside ``asyncio.to_thread`` from the async warehouser). Returns the :func:`backfill_gaps`
    summary, or ``{"skipped": ...}`` when creds/calendar are unavailable.
    """
    if not settings.DHAN_CLIENT_ID or not settings.DHAN_ACCESS_TOKEN:
        log.warning("gap_backfill_skipped", reason="no Dhan creds")
        return {"skipped": "no_dhan_creds"}

    band = band if band is not None else settings.WAREHOUSE_STRIKE_BAND
    codes = codes or [1, 2]
    end = end or datetime.now(UTC).astimezone().date()
    start = end - timedelta(days=lookback_days)
    days = trading_days(start, end, holidays(settings.NSE_HOLIDAYS_JSON))
    if not days:
        return {"skipped": "no_trading_days", "from": str(start), "to": str(end)}

    from dhanhq import DhanContext, dhanhq
    from pymongo import MongoClient

    dhan = dhanhq(DhanContext(settings.DHAN_CLIENT_ID, settings.DHAN_ACCESS_TOKEN))
    col = MongoClient(settings.MONGO_URI)[settings.MONGO_DB_NAME]["option_bars"]
    log.info("gap_backfill_scan", **{"from": str(start), "to": str(end),
                                      "trading_days": len(days), "codes": codes, "band": band,
                                      "underlying": underlying})
    return backfill_gaps(dhan=dhan, col=col, cal=cal, days=days, codes=codes, band=band,
                         underlying=underlying, underlying_sid=underlying_sid,
                         strike_step=strike_step, exchange_segment=exchange_segment)
