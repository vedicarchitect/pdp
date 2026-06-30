"""Backfill persisted price levels (daily + weekly) for NIFTY, BANKNIFTY, SENSEX.

Reads 1m spot bars from `market_bars`, derives prior-session/week HLC,
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

from pdp.indicators.levels_store import LevelsStore, _UNDERLYING_MAP
from pdp.indicators.pivots import _compute_pivots
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


def _day_window_utc(day: date) -> tuple[datetime, datetime]:
    """UTC-naive [start, end) for a full IST trade day."""
    # IST 00:00 = UTC -5:30 of that calendar day
    lo = datetime(day.year, day.month, day.day) - timedelta(hours=5, minutes=30)
    return lo, lo + timedelta(days=1)


def _fetch_day_hlc_sync(col: Any, security_id: str, day: date) -> tuple[float, float, float] | None:
    """Return (H, L, C) from 1m bars for a given IST trade day. Sync (pymongo)."""
    lo, hi = _day_window_utc(day)
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

        h, l, c = hlc
        ps = _compute_pivots(h, l, c, session_date)
        doc: dict[str, Any] = {
            "schema_version": 1,
            "security_id": security_id,
            "underlying": underlying,
            "period": "daily",
            "session_date": session_date.isoformat(),
            "source": {
                "h": h, "l": l, "c": c,
                "window_start": prior_day.isoformat(),
                "window_end": prior_day.isoformat(),
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
        prior_friday = monday - timedelta(days=3)  # approximate; use last available trading day
        # Get all trading days in that prior week
        prior_week_days = trading_days(prior_monday, monday - timedelta(days=1), hol_set)
        if not prior_week_days:
            continue

        week_start = prior_week_days[0]
        week_end = prior_week_days[-1]

        # Aggregate HLC across all days in prior week
        wlo, _ = _day_window_utc(week_start)
        _, whi = _day_window_utc(week_end)
        pipeline = [
            {"$match": {
                "metadata.security_id": security_id,
                "metadata.timeframe": "1m",
                "ts": {"$gte": wlo, "$lt": whi},
            }},
            {"$group": {
                "_id": None,
                "h": {"$max": "$high"},
                "l": {"$min": "$low"},
                "c": {"$last": "$close"},
                "count": {"$sum": 1},
            }},
        ]
        result = list(bars_col.aggregate(pipeline))
        if not result or result[0].get("count", 0) < 10:
            log.debug("levels_backfill_no_bars", symbol=symbol, week=str(prior_monday), period="weekly")
            continue

        r = result[0]
        h, l, c = float(r["h"]), float(r["l"]), float(r["c"])
        ps = _compute_pivots(h, l, c, monday)
        doc = {
            "schema_version": 1,
            "security_id": security_id,
            "underlying": underlying,
            "period": "weekly",
            "session_date": monday.isoformat(),
            "source": {
                "h": h, "l": l, "c": c,
                "window_start": week_start.isoformat(),
                "window_end": week_end.isoformat(),
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
        levels_col.update_one(
            {"security_id": security_id, "period": "weekly", "session_date": monday.isoformat()},
            {"$set": doc},
            upsert=True,
        )
        total_weekly += 1

    log.info("levels_weekly_done", symbol=symbol, upserted=total_weekly)
    log.info(
        "levels_backfill_summary",
        symbol=symbol,
        daily=total_daily,
        weekly=total_weekly,
    )
    client.close()
    return 0


def _prior_trading_day(d: date, hol_set: set[date]) -> date | None:
    candidate = d - timedelta(days=1)
    for _ in range(10):
        if candidate.weekday() < 5 and candidate not in hol_set:
            return candidate
        candidate -= timedelta(days=1)
    return None


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Backfill daily + weekly price levels for NIFTY/BANKNIFTY/SENSEX into index_levels."
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
