"""Backfill persisted price levels (daily + weekly + monthly) for NIFTY, BANKNIFTY, SENSEX.

Reads 1m spot bars from `market_bars`, derives prior-session/week/month HLC using the same
session-anchored ([09:15,15:30) IST, 1m-only) window as the live `compute_session_levels` path,
computes standard + Camarilla + Fibonacci pivots, and upserts into `index_levels`.

Usage:
  python scripts/backfill_levels.py --dry-run
  python scripts/backfill_levels.py --symbol NIFTY --from 2021-06-30
  python scripts/backfill_levels.py --symbol BANKNIFTY --from 2021-06-30 --only-missing
  python scripts/backfill_levels.py --symbol SENSEX --from 2021-06-30 --to 2026-06-30

task backfill:levels -- --symbol NIFTY --from 2021-06-30 --dry-run
"""
from __future__ import annotations

import argparse
import sys
from datetime import UTC, date, datetime, timedelta
from typing import Any

import structlog
from dotenv import load_dotenv

from pdp.indicators.levels_store import _SESSION_LENGTH, _UNDERLYING_MAP
from pdp.indicators.pivots import _compute_pivots
from pdp.market.bars import _session_open_utc
from pdp.options.gap_backfill import holidays, trading_days
from pdp.settings import get_settings

load_dotenv()
log = structlog.get_logger()

SYMBOL_MAP: dict[str, str] = {
    "NIFTY": "13",
    "BANKNIFTY": "25",
    "SENSEX": "51",
}


def _iso_week_monday(d: date) -> date:
    """Return the Monday of the ISO week containing d."""
    return d - timedelta(days=d.weekday())


def _session_window_utc(day: date) -> tuple[datetime, datetime]:
    """Session-anchored [09:15, 15:30) IST window for a trade day, in UTC. Sync mirror of
    `pdp.indicators.levels_store._session_window_hlc`'s window (this script uses pymongo, not
    motor, so it re-derives HLC itself rather than awaiting the async helper)."""
    start = _session_open_utc(datetime(day.year, day.month, day.day, tzinfo=UTC))
    return start, start + _SESSION_LENGTH


def _fetch_day_hlc_sync(col: Any, security_id: str, day: date) -> tuple[float, float, float] | None:
    """Return session-anchored (H, L, C) from 1m bars for a given IST trade day. Sync (pymongo)."""
    lo, hi = _session_window_utc(day)
    pipeline = [
        {"$match": {
            "metadata.security_id": security_id,
            "metadata.timeframe": "1m",
            "ts": {"$gte": lo, "$lt": hi},
        }},
        {"$group": {
            "_id": None,
            "h": {"$max": "$high"},
            "l": {"$min": "$low"},
            "c": {"$last": "$close"},
            "count": {"$sum": 1},
        }},
    ]
    result = list(col.aggregate(pipeline))
    if not result or result[0].get("count", 0) < 10:
        return None
    r = result[0]
    return float(r["h"]), float(r["l"]), float(r["c"])


def _fetch_range_hlc_sync(
    col: Any, security_id: str, start: date, end: date
) -> tuple[float, float, float] | None:
    """Aggregate session-anchored HLC across every trading day in [start, end] (inclusive).

    Combines each day's independently-windowed HLC (max of highs, min of lows, last day's
    close) rather than running one aggregate over the whole padded range — the latter is what
    let an out-of-session print or an adjacent day leak into a week/month's H/L (the PMH bug).
    """
    h: float | None = None
    lo: float | None = None
    c: float | None = None
    c_day: date | None = None
    d = start
    while d <= end:
        day_hlc = _fetch_day_hlc_sync(col, security_id, d)
        if day_hlc is not None:
            dh, dl, dc = day_hlc
            h = dh if h is None else max(h, dh)
            lo = dl if lo is None else min(lo, dl)
            if c_day is None or d > c_day:
                c = dc
                c_day = d
        d += timedelta(days=1)
    if h is None:
        return None
    return h, lo, c  # type: ignore[return-value]


def _run_backfill(
    symbol: str,
    date_from: date,
    date_to: date,
    only_missing: bool,
    dry_run: bool,
) -> int:
    """Main backfill logic — synchronous (pymongo + motor not needed here)."""
    from pymongo import MongoClient

    s = get_settings()
    security_id = SYMBOL_MAP[symbol]
    underlying = _UNDERLYING_MAP.get(security_id, symbol)
    hol_set = holidays(s.NSE_HOLIDAYS_JSON)
    days = trading_days(date_from, date_to, hol_set)

    if not days:
        log.info("no_trading_days", symbol=symbol, from_=str(date_from), to=str(date_to))
        return 0

    if dry_run:
        log.info(
            "dry_run_levels",
            symbol=symbol,
            security_id=security_id,
            trading_days=len(days),
            first=str(days[0]),
            last=str(days[-1]),
        )
        return 0

    client = MongoClient(s.MONGO_URI)
    db = client[s.MONGO_DB_NAME]
    bars_col = db["market_bars"]
    levels_col = db["index_levels"]

    # ── Daily levels ──────────────────────────────────────────────────────────
    # For each trading day we need the prior day's HLC, then upsert for that day.
    total_daily = 0
    total_weekly = 0

    # Pre-cache all HLC per trade day in the range (plus one prior day for pivot)
    all_days = days  # trading days in [from, to]

    for i, session_date in enumerate(all_days):
        # Prior trading day
        prior_day = all_days[i - 1] if i > 0 else _prior_trading_day(session_date, hol_set)
        if prior_day is None:
            continue

        if only_missing:
            existing = levels_col.count_documents({
                "security_id": security_id,
                "period": "daily",
                "session_date": session_date.isoformat(),
            })
            if existing > 0:
                continue

        hlc = _fetch_day_hlc_sync(bars_col, security_id, prior_day)
        if hlc is None:
            log.debug("levels_backfill_no_bars", symbol=symbol, day=str(prior_day), period="daily")
            continue

        dy_h, dy_l, dy_c = hlc
        doc = _build_level_doc(
            security_id, underlying, "daily", session_date, dy_h, dy_l, dy_c, prior_day, prior_day
        )
        levels_col.update_one(
            {"security_id": security_id, "period": "daily", "session_date": session_date.isoformat()},
            {"$set": doc},
            upsert=True,
        )
        total_daily += 1

    log.info("levels_daily_done", symbol=symbol, upserted=total_daily)

    # ── Weekly levels ─────────────────────────────────────────────────────────
    # Find all Mondays in the range (each Monday = start of a new week → compute weekly pivots).
    mondays = [d for d in all_days if d.weekday() == 0]
    for monday in mondays:
        if only_missing:
            existing = levels_col.count_documents({
                "security_id": security_id,
                "period": "weekly",
                "session_date": monday.isoformat(),
            })
            if existing > 0:
                continue

        # Prior ISO week: previous Monday to previous Friday
        prior_monday = monday - timedelta(days=7)
        # Get all trading days in that prior week
        prior_week_days = trading_days(prior_monday, monday - timedelta(days=1), hol_set)
        if not prior_week_days:
            continue

        week_start = prior_week_days[0]
        week_end = prior_week_days[-1]

        hlc = _fetch_range_hlc_sync(bars_col, security_id, week_start, week_end)
        if hlc is None:
            log.debug("levels_backfill_no_bars", symbol=symbol, week=str(prior_monday), period="weekly")
            continue

        wk_h, wk_l, wk_c = hlc
        doc = _build_level_doc(
            security_id, underlying, "weekly", monday, wk_h, wk_l, wk_c, week_start, week_end
        )
        levels_col.update_one(
            {"security_id": security_id, "period": "weekly", "session_date": monday.isoformat()},
            {"$set": doc},
            upsert=True,
        )
        total_weekly += 1

    log.info("levels_weekly_done", symbol=symbol, upserted=total_weekly)

    # ── Monthly levels ────────────────────────────────────────────────────────
    # Find the first trading day of each calendar month in the range (that day gets the
    # prior calendar month's HLC).
    first_of_month_days = _first_trading_days_of_month(all_days)
    total_monthly = 0
    for session_date in first_of_month_days:
        if only_missing:
            existing = levels_col.count_documents({
                "security_id": security_id,
                "period": "monthly",
                "session_date": session_date.isoformat(),
            })
            if existing > 0:
                continue

        prior_month_end = session_date.replace(day=1) - timedelta(days=1)
        prior_month_start = prior_month_end.replace(day=1)

        hlc = _fetch_range_hlc_sync(bars_col, security_id, prior_month_start, prior_month_end)
        if hlc is None:
            log.debug(
                "levels_backfill_no_bars", symbol=symbol, month=str(prior_month_start), period="monthly"
            )
            continue

        mo_h, mo_l, mo_c = hlc
        doc = _build_level_doc(
            security_id, underlying, "monthly", session_date, mo_h, mo_l, mo_c,
            prior_month_start, prior_month_end,
        )
        levels_col.update_one(
            {"security_id": security_id, "period": "monthly", "session_date": session_date.isoformat()},
            {"$set": doc},
            upsert=True,
        )
        total_monthly += 1

    log.info("levels_monthly_done", symbol=symbol, upserted=total_monthly)
    log.info(
        "levels_backfill_summary",
        symbol=symbol,
        daily=total_daily,
        weekly=total_weekly,
        monthly=total_monthly,
    )
    client.close()
    return 0


def _build_level_doc(
    security_id: str,
    underlying: str,
    period: str,
    session_date: date,
    h: float,
    lo: float,
    c: float,
    window_start: date,
    window_end: date,
) -> dict[str, Any]:
    """Build an `index_levels` document from source HLC — shared by daily/weekly/monthly."""
    ps = _compute_pivots(h, lo, c, session_date)
    return {
        "schema_version": 1,
        "security_id": security_id,
        "underlying": underlying,
        "period": period,
        "session_date": session_date.isoformat(),
        "source": {
            "h": h, "l": lo, "c": c,
            "window_start": window_start.isoformat(),
            "window_end": window_end.isoformat(),
        },
        "standard": {
            "pp": ps.pp, "r1": ps.r1, "r2": ps.r2, "r3": ps.r3,
            "s1": ps.s1, "s2": ps.s2, "s3": ps.s3,
        },
        "camarilla": {
            "pp": ps.cam_pp, "r3": ps.cam_r3, "r4": ps.cam_r4,
            "s3": ps.cam_s3, "s4": ps.cam_s4,
        },
        "fibonacci": {
            "pp": ps.fib_pp, "r1": ps.fib_r1, "r2": ps.fib_r2, "r3": ps.fib_r3,
            "s1": ps.fib_s1, "s2": ps.fib_s2, "s3": ps.fib_s3,
        },
        "levels": {},
        "computed_at": datetime.now(UTC).isoformat(),
    }


def _first_trading_days_of_month(all_days: list[date]) -> list[date]:
    """Return the first trading day of each calendar month present in `all_days`."""
    seen_months: set[tuple[int, int]] = set()
    result: list[date] = []
    for d in all_days:
        key = (d.year, d.month)
        if key not in seen_months:
            seen_months.add(key)
            result.append(d)
    return result


def _prior_trading_day(d: date, hol_set: set[date]) -> date | None:
    candidate = d - timedelta(days=1)
    for _ in range(10):
        if candidate.weekday() < 5 and candidate not in hol_set:
            return candidate
        candidate -= timedelta(days=1)
    return None


def main() -> int:
    ap = argparse.ArgumentParser(
        description=(
            "Backfill daily + weekly + monthly price levels for NIFTY/BANKNIFTY/SENSEX into "
            "index_levels."
        )
    )
    ap.add_argument("--symbol", default="NIFTY", choices=list(SYMBOL_MAP),
                    help="Index to backfill (default: NIFTY).")
    ap.add_argument("--from", dest="date_from",
                    default=(date.today() - timedelta(days=365 * 5)).isoformat(),
                    help="Start date YYYY-MM-DD (default: 5 years ago).")
    ap.add_argument("--to", dest="date_to", default=date.today().isoformat(),
                    help="End date YYYY-MM-DD (default: today).")
    ap.add_argument("--only-missing", action="store_true",
                    help="Skip session_dates already present in index_levels.")
    ap.add_argument("--dry-run", action="store_true",
                    help="Log plan without writing to MongoDB.")
    a = ap.parse_args()

    return _run_backfill(
        symbol=a.symbol,
        date_from=date.fromisoformat(a.date_from),
        date_to=date.fromisoformat(a.date_to),
        only_missing=a.only_missing,
        dry_run=a.dry_run,
    )


if __name__ == "__main__":
    sys.exit(main())
