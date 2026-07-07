"""Per-underlying, per-family data-availability + gap-radar computation.

Backs `GET /api/v1/coverage`, the periodic OpenSearch coverage snapshot, and the
`/data:coverage` / `/data:gapfill` skills. Reuses the existing gap-detection helpers
(`gap_backfill.days_missing`/`expected_contracts`/`trading_days`) instead of a parallel
implementation, and reuses `pdp.backtest.completeness` for the per-family radar labels.

Coverage is computed live, not stored (except for OpenSearch snapshots emitted by the
self-heal cycle) — `option_bars`/`market_bars`/`index_levels` already are the source of
truth, so there is nothing else to keep in sync.
"""
from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING, Any

import structlog

from pdp.backtest.completeness import FamilyGaps, radar_window, weekly_camarilla_gap_days
from pdp.options.gap_backfill import (
    collapse_date_ranges,
    days_missing,
    holidays,
    trading_days,
)
from pdp.warehouse.service import SID_MAP, UNDERLYING_REGISTRY

if TYPE_CHECKING:
    from motor.motor_asyncio import AsyncIOMotorDatabase

log = structlog.get_logger()

IST = timedelta(hours=5, minutes=30)
_IST_MS = int(IST.total_seconds() * 1000)

_OPTION_CODES = [1, 2]


def _ist_date(ts: datetime) -> date:
    ts = ts if ts.tzinfo else ts.replace(tzinfo=UTC)
    return (ts + IST).date()


def _empty_family(total_days: int) -> dict[str, Any]:
    return {
        "min_date": None,
        "max_date": None,
        "covered_days": 0,
        "total_days": total_days,
        "coverage_pct": 0.0,
        "gap_ranges": [],
    }


def _family_summary(
    *, min_date: date | None, max_date: date | None, gap_days: set[date], days: list[date]
) -> dict[str, Any]:
    total = len(days)
    covered = total - len(gap_days & set(days))
    pct = round(100.0 * covered / total, 1) if total else 0.0
    return {
        "min_date": str(min_date) if min_date else None,
        "max_date": str(max_date) if max_date else None,
        "covered_days": covered,
        "total_days": total,
        "coverage_pct": pct,
        "gap_ranges": collapse_date_ranges(sorted(gap_days & set(days))),
    }


def _min_max(present: set[date]) -> tuple[date | None, date | None]:
    return (min(present), max(present)) if present else (None, None)


async def _spot_gaps(
    mongo_db: AsyncIOMotorDatabase, security_id: str, days: list[date]
) -> tuple[dict[str, Any], set[date]]:
    """Coverage summary + gap-day set for a `market_bars` spot-style series (spot or VIX).

    min/max are derived from the days present *within the requested window*, not a separate
    full-collection sorted scan — `option_bars`/`market_bars` can hold tens of millions of rows
    with no `(security_id, ts)`-only index, so an unbounded sort-by-ts query would be a full scan.
    """
    if not days:
        return _empty_family(0), set()

    col = mongo_db["market_bars"]
    win_lo, _ = _day_bounds(days[0])
    _, win_hi = _day_bounds(days[-1])
    pipeline = [
        {"$match": {
            "metadata.security_id": security_id,
            "metadata.timeframe": "1m",
            "ts": {"$gte": win_lo, "$lt": win_hi},
        }},
        {"$group": {
            "_id": {"$dateTrunc": {"date": {"$add": ["$ts", _IST_MS]}, "unit": "day"}},
            "n": {"$sum": 1},
        }},
    ]
    present: set[date] = set()
    async for row in col.aggregate(pipeline):
        present.add(row["_id"].date())

    min_date, max_date = _min_max(present)
    gap_days = {d for d in days if d not in present}
    summary = _family_summary(min_date=min_date, max_date=max_date, gap_days=gap_days, days=days)
    return summary, gap_days


def _day_bounds(d: date) -> tuple[datetime, datetime]:
    """UTC-naive [start, end) covering the IST trade-day ``d`` (matches `market_bars` writers)."""
    lo = datetime(d.year, d.month, d.day) - timedelta(hours=5, minutes=30)
    return lo, lo + timedelta(days=1)


def _options_gaps_sync(
    *, mongo_uri: str, mongo_db_name: str, underlying: str, band: int, days: list[date]
) -> set[date]:
    """Blocking pymongo helper — run via `asyncio.to_thread`.

    Reuses `gap_backfill.days_missing` directly rather than a parallel gap implementation. Its
    internal aggregation is already bounded to `[min(days), max(days)]`, so no separate min/max
    lookup is issued here — `option_bars` can hold tens of millions of rows with no
    `(underlying, ts)`-only index, so an unbounded sort-by-ts query would be a full scan.

    Opens its own short-lived `MongoClient` (closed on exit via the context manager) rather than
    a shared singleton — this runs on `GET /api/v1/coverage`, a request-frequency code path, so an
    unclosed client here would leak connections far faster than the once-per-cycle precedent in
    `gap_backfill.run_gap_backfill`.
    """
    from pymongo import MongoClient

    with MongoClient(mongo_uri) as client:
        col = client[mongo_db_name]["option_bars"]
        return set(days_missing(col, days, _OPTION_CODES, band, underlying=underlying))


async def _options_family(
    settings: Any, underlying: str, days: list[date]
) -> tuple[dict[str, Any], set[date]]:
    if not days:
        return _empty_family(0), set()
    band = settings.WAREHOUSE_STRIKE_BAND
    gap_days = await asyncio.to_thread(
        _options_gaps_sync,
        mongo_uri=settings.MONGO_URI,
        mongo_db_name=settings.MONGO_DB_NAME,
        underlying=underlying,
        band=band,
        days=days,
    )
    min_date, max_date = _min_max(set(days) - gap_days)
    summary = _family_summary(min_date=min_date, max_date=max_date, gap_days=gap_days, days=days)
    return summary, gap_days


async def _levels_family(
    mongo_db: AsyncIOMotorDatabase, underlying: str, period: str, days: list[date]
) -> tuple[dict[str, Any], set[date]]:
    if not days:
        return _empty_family(0), set()

    col = mongo_db["index_levels"]
    match = {
        "underlying": underlying,
        "period": period,
        "session_date": {"$gte": days[0].isoformat(), "$lte": days[-1].isoformat()},
    }
    present: set[date] = set()
    async for doc in col.find(match, {"session_date": 1}):
        present.add(date.fromisoformat(doc["session_date"]))

    min_date, max_date = _min_max(present)
    gap_days = {d for d in days if d not in present}
    summary = _family_summary(min_date=min_date, max_date=max_date, gap_days=gap_days, days=days)
    return summary, gap_days


async def per_expiry_coverage(
    mongo_db: AsyncIOMotorDatabase,
    underlying: str,
    *,
    window_from: date,
    window_to: date,
    min_strikes_complete: int = 1,
) -> list[dict[str, Any]]:
    """Per-``(underlying, expiry_date)`` option-chain coverage within the window.

    Groups ``option_bars`` by ``expiry_date`` and reports, for each expiry that has any stored
    chain, the distinct-strike count, CE/PE contract counts, the trade-day span covered, and a
    ``status`` of ``complete`` vs ``partial``. An expiry claimed upstream but with **no** stored
    chain never appears here — so a caller comparing this list against the claimed/upcoming
    expiries can flag a phantom expiry (claimed, absent) or a partial chain (present, thin).
    """
    lo, _ = _day_bounds(window_from)
    _, hi = _day_bounds(window_to)
    col = mongo_db["option_bars"]
    pipeline: list[dict[str, Any]] = [
        {"$match": {"underlying": underlying, "timeframe": "1m", "ts": {"$gte": lo, "$lt": hi}}},
        {"$group": {
            "_id": "$expiry_date",
            "strikes": {"$addToSet": "$strike"},
            "ce": {"$addToSet": {"$cond": [{"$eq": ["$option_type", "CE"]}, "$strike", "$$REMOVE"]}},
            "pe": {"$addToSet": {"$cond": [{"$eq": ["$option_type", "PE"]}, "$strike", "$$REMOVE"]}},
            "first_ts": {"$min": "$ts"},
            "last_ts": {"$max": "$ts"},
        }},
        {"$sort": {"_id": 1}},
    ]
    out: list[dict[str, Any]] = []
    async for doc in col.aggregate(pipeline):
        expiry = doc["_id"]
        n_strikes = len(doc.get("strikes") or [])
        n_ce = len(doc.get("ce") or [])
        n_pe = len(doc.get("pe") or [])
        # "complete" = both sides present with enough strikes; else partial. A stricter
        # expected-strike-band check can layer on top, but presence of both legs across the
        # band is the primary "is there a usable chain" signal.
        complete = n_ce >= min_strikes_complete and n_pe >= min_strikes_complete and n_ce == n_pe
        out.append({
            "expiry_date": str(expiry),
            "strikes": n_strikes,
            "ce_contracts": n_ce,
            "pe_contracts": n_pe,
            "first_ts": doc["first_ts"].isoformat() if doc.get("first_ts") else None,
            "last_ts": doc["last_ts"].isoformat() if doc.get("last_ts") else None,
            "status": "complete" if complete else "partial",
        })
    return out


async def underlying_coverage(
    mongo_db: AsyncIOMotorDatabase,
    settings: Any,
    underlying: str,
    *,
    window_from: date,
    window_to: date,
) -> dict[str, Any]:
    """Per-family coverage + gap-radar for one underlying within [window_from, window_to]."""
    if underlying not in UNDERLYING_REGISTRY:
        raise ValueError(f"Unsupported underlying: {underlying!r}")

    sid = SID_MAP[underlying]
    hol = holidays(settings.NSE_HOLIDAYS_JSON)
    days = trading_days(window_from, window_to, hol)

    spot_summary, spot_gaps = await _spot_gaps(mongo_db, sid, days)
    options_summary, options_gaps = await _options_family(settings, underlying, days)
    vix_summary, vix_gaps = await _spot_gaps(mongo_db, SID_MAP["VIX"], days)
    levels_daily_summary, _ = await _levels_family(mongo_db, underlying, "daily", days)
    levels_weekly_summary, levels_weekly_gaps = await _levels_family(mongo_db, underlying, "weekly", days)

    camarilla_gaps = weekly_camarilla_gap_days(spot_gaps, levels_weekly_gaps, days)
    gaps = FamilyGaps(
        spot=spot_gaps, options=options_gaps, vix=vix_gaps,
        levels_weekly=camarilla_gaps,
    )

    by_expiry = await per_expiry_coverage(
        mongo_db, underlying, window_from=window_from, window_to=window_to
    )

    return {
        "underlying": underlying,
        "window": {"from": str(window_from), "to": str(window_to)},
        "families": {
            "spot": spot_summary,
            "options": options_summary,
            "vix": vix_summary,
            "levels_daily": levels_daily_summary,
            "levels_weekly": levels_weekly_summary,
        },
        "by_expiry": by_expiry,
        "radar": radar_window(gaps, days),
    }


async def all_coverage(
    mongo_db: AsyncIOMotorDatabase,
    settings: Any,
    *,
    window_from: date,
    window_to: date,
    underlyings: list[str] | None = None,
) -> dict[str, Any]:
    """Coverage + radar for every configured underlying (NIFTY/BANKNIFTY/SENSEX by default)."""
    names = underlyings or list(UNDERLYING_REGISTRY)
    results = {}
    for name in names:
        results[name] = await underlying_coverage(
            mongo_db, settings, name, window_from=window_from, window_to=window_to
        )
    return {"window": {"from": str(window_from), "to": str(window_to)}, "underlyings": results}
