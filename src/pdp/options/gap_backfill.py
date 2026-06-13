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
"""
from __future__ import annotations

import json
import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

import structlog

from pdp.instruments.symbols import symbol_for
from pdp.options.warehouse import build_option_bar_doc, upsert_option_bars_sync

if TYPE_CHECKING:
    from pdp.instruments.expiry_calendar import NiftyExpiryCalendar

log = structlog.get_logger()

UNDERLYING = "NIFTY"
UNDERLYING_SID = 13
STEP = 50
IST = timedelta(hours=5, minutes=30)
API_PAUSE = 0.25  # stay under the 5 req/sec data-API limit
_IST_MS = int(IST.total_seconds() * 1000)


# ── Trade-day / band enumeration ─────────────────────────────────────────────────

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


# ── Dhan payload helpers ─────────────────────────────────────────────────────────

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


def spot_by_minute(dhan: Any, ds: str) -> dict[datetime, float]:
    """NIFTY index 1m close keyed by UTC minute, to derive ATM per bar."""
    r = dhan.intraday_minute_data(security_id=str(UNDERLYING_SID), exchange_segment="IDX_I",
                                  instrument_type="INDEX", from_date=ds, to_date=ds, interval=1)
    time.sleep(API_PAUSE)
    data = r.get("data", {}) if isinstance(r, dict) else {}
    if isinstance(data, dict) and "data" in data and "open" not in data:
        data = data["data"]
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


def bars_to_docs(data: dict, spot: dict[datetime, float], exp: date, ot: str,
                 label: str, offset: int) -> list[dict]:
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
            continue  # cannot derive strike without aligned spot
        strike = round(sp / STEP) * STEP + offset * STEP
        docs.append(build_option_bar_doc(
            underlying=UNDERLYING, expiry_date=exp, strike=float(strike), option_type=ot,
            timeframe="1m", ts=bt, open=o[i], high=h[i], low=lo[i], close=c[i],
            volume=vol[i] if i < len(vol) else 0, oi=oi[i] if i < len(oi) else 0,
            iv=iv[i] if i < len(iv) else 0.0,
            expiry_flag="WEEK", strike_label=label,
            trading_symbol=symbol_for(UNDERLYING, exp, float(strike), ot), source="dhan_api"))
    return docs


def fill_day(dhan: Any, col: Any, cal: NiftyExpiryCalendar, ds: str,
             codes: list[int], label_offsets: list[tuple[str, int]]) -> int:
    """Backfill one trade day's band from Dhan; returns the number of new bars inserted."""
    spot = spot_by_minute(dhan, ds)
    if not spot:
        log.warning("gap_fill_no_spot", day=ds)
        return 0
    inserted = 0
    for code in codes:
        exp = cal.resolve_expiry(date.fromisoformat(ds), "WEEK", code)
        if exp is None:
            log.warning("gap_fill_no_expiry", day=ds, code=code)
            continue
        for label, offset in label_offsets:
            for ot in ("CE", "PE"):
                drv = "CALL" if ot == "CE" else "PUT"
                try:
                    resp = dhan.expired_options_data(
                        security_id=UNDERLYING_SID, exchange_segment="NSE_FNO",
                        instrument_type="OPTIDX", expiry_flag="WEEK", expiry_code=code,
                        strike=label, drv_option_type=drv,
                        required_data=["open", "high", "low", "close", "volume", "oi", "iv"],
                        from_date=ds, to_date=ds, interval=1)
                    time.sleep(API_PAUSE)
                except Exception as exc:  # noqa: BLE001
                    log.warning("gap_fill_api_error", day=ds, code=code, label=label,
                                ot=ot, exc=str(exc))
                    continue
                data = unwrap_side(resp, ot)
                if not data:
                    continue
                docs = bars_to_docs(data, spot, exp, ot, label, offset)
                inserted += upsert_option_bars_sync(col, docs)
    return inserted


# ── Gap detection ────────────────────────────────────────────────────────────────

def expected_contracts(codes: list[int], band: int) -> int:
    """Distinct (expiry, strike, side) contracts a fully-covered day should hold."""
    return len(codes) * (2 * band + 1) * 2


def _ist_day_window(d: date) -> tuple[datetime, datetime]:
    """UTC [lo, hi) bounds covering the IST trade-day ``d``."""
    lo = (datetime(d.year, d.month, d.day) - IST).replace(tzinfo=UTC)
    return lo, lo + timedelta(days=1)


def days_missing(col: Any, days: list[date], codes: list[int], band: int,
                 *, min_fraction: float = 0.5) -> list[date]:
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
        {"$match": {"underlying": UNDERLYING, "timeframe": "1m",
                    "ts": {"$gte": win_lo, "$lt": win_hi}}},
        {"$group": {"_id": {"day": {"$dateTrunc": {"date": {"$add": ["$ts", _IST_MS]},
                                                   "unit": "day"}},
                            "contract": {"e": "$expiry_date", "s": "$strike",
                                         "o": "$option_type"}}}},
        {"$group": {"_id": "$_id.day", "contracts": {"$sum": 1}}},
    ]
    counts: dict[date, int] = {}
    for row in col.aggregate(pipeline):
        day_dt = row["_id"]  # midnight UTC of the IST day (we added IST then truncated)
        counts[day_dt.date()] = row["contracts"]
    return [d for d in days if counts.get(d, 0) < threshold]


# ── High-level entry points ──────────────────────────────────────────────────────

def backfill_gaps(*, dhan: Any, col: Any, cal: NiftyExpiryCalendar, days: list[date],
                  codes: list[int], band: int, min_fraction: float = 0.5,
                  only_missing: bool = True) -> dict[str, Any]:
    """Detect gaps over ``days`` and backfill them. Returns a summary dict.

    With ``only_missing`` (default) just the under-covered days are fetched; set it False to
    re-fetch every day in the window (still idempotent via first-write-wins).
    """
    targets = days_missing(col, days, codes, band, min_fraction=min_fraction) if only_missing else days
    label_offsets = labels(band)
    total, filled = 0, 0
    for d in targets:
        n = fill_day(dhan, col, cal, d.isoformat(), codes, label_offsets)
        total += n
        if n:
            filled += 1
        log.info("gap_fill_day_done", day=d.isoformat(), inserted=n)
    log.info("gap_fill_done", scanned=len(days), gaps=len(targets),
             days_filled=filled, total_inserted=total)
    return {"scanned": len(days), "gaps": len(targets), "days_filled": filled,
            "total_inserted": total, "gap_days": [d.isoformat() for d in targets]}


def run_gap_backfill(*, settings: Any, cal: NiftyExpiryCalendar, lookback_days: int,
                     codes: list[int] | None = None, band: int | None = None,
                     end: date | None = None) -> dict[str, Any]:
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
                                      "trading_days": len(days), "codes": codes, "band": band})
    return backfill_gaps(dhan=dhan, col=col, cal=cal, days=days, codes=codes, band=band)
