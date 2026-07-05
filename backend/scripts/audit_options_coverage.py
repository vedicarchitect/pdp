"""Read-only coverage audit for the `option_bars` warehouse — reports gaps, fetches nothing.

Answers "what do we actually have, and where are the holes?" before any gap-fill decision:

  1. Overall: total docs, IST date range, `source` split (abi vs dhan_api vs …).
  2. Per IST month: document count + distinct trade-days present.
  3. Gap days: trading days (weekday, non-holiday) in the audited range whose coverage is below
     `--min-fraction` of the expected contract band — reusing the same `days_missing` detector the
     gap-fill uses, so the audit and the fill agree on what "missing" means. Consecutive gap days
     are collapsed into ranges for readability.

Usage:
  python scripts/audit_options_coverage.py
  python scripts/audit_options_coverage.py --from 2023-01-01 --to 2026-06-12
  python scripts/audit_options_coverage.py --out coverage.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, date, datetime, timedelta

import structlog
from dotenv import load_dotenv

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from pdp.options.gap_backfill import collapse_date_ranges, days_missing, holidays, trading_days
from pdp.settings import get_settings

load_dotenv()
log = structlog.get_logger()

IST = timedelta(hours=5, minutes=30)
IST_MS = int(IST.total_seconds() * 1000)


def _ist_date(ts: datetime) -> date:
    ts = ts if ts.tzinfo else ts.replace(tzinfo=UTC)
    return (ts + IST).date()


def main() -> int:
    ap = argparse.ArgumentParser(description="Audit option_bars coverage (read-only).")
    ap.add_argument("--symbol", default="NIFTY", choices=["NIFTY", "BANKNIFTY", "SENSEX"],
                    help="Underlying to audit (default: NIFTY).")
    ap.add_argument("--from", dest="date_from", default=None, help="IST start (default: earliest data).")
    ap.add_argument("--to", dest="date_to", default=None, help="IST end (default: today).")
    ap.add_argument("--codes", default="1,2")
    ap.add_argument("--band", type=int, default=None)
    ap.add_argument("--min-fraction", type=float, default=0.5)
    ap.add_argument("--out", default=None, help="Write the JSON summary to this path.")
    a = ap.parse_args()

    s = get_settings()
    band = a.band if a.band is not None else s.WAREHOUSE_STRIKE_BAND
    codes = [int(x) for x in a.codes.split(",") if x.strip()]
    underlying_match = {"underlying": a.symbol}

    from pymongo import MongoClient
    col = MongoClient(s.MONGO_URI)[s.MONGO_DB_NAME]["option_bars"]

    total = col.count_documents(underlying_match)
    if total == 0:
        print(f"option_bars has no docs for {a.symbol}.")
        return 0

    # ── Overall range + source split ──────────────────────────────────────────
    first = col.find_one(underlying_match, {"ts": 1}, sort=[("ts", 1)])["ts"]
    last = col.find_one(underlying_match, {"ts": 1}, sort=[("ts", -1)])["ts"]
    data_lo, data_hi = _ist_date(first), _ist_date(last)
    src = {r["_id"]: r["n"] for r in col.aggregate([
        {"$match": underlying_match},
        {"$group": {"_id": "$source", "n": {"$sum": 1}}},
    ])}
    src_str = ", ".join(f"{k}={v:,}" for k, v in sorted(src.items(), key=lambda x: str(x[0])))

    print(f"\n  option_bars coverage audit — {a.symbol}")
    print(f"  total docs : {total:,}")
    print(f"  IST range  : {data_lo} .. {data_hi}")
    print(f"  source     : {src_str}")

    # ── Per-month: docs + distinct trade-days ─────────────────────────────────
    by_month = {r["_id"]: r["n"] for r in col.aggregate([
        {"$match": underlying_match},
        {"$group": {"_id": {"$dateToString": {"format": "%Y-%m",
                                              "date": {"$add": ["$ts", IST_MS]}, "timezone": "UTC"}},
                    "n": {"$sum": 1}}},
        {"$sort": {"_id": 1}},
    ], allowDiskUse=True)}
    days_per_month = {r["_id"]: r["days"] for r in col.aggregate([
        {"$match": underlying_match},
        {"$group": {"_id": {"$dateTrunc": {"date": {"$add": ["$ts", IST_MS]}, "unit": "day"}}}},
        {"$group": {"_id": {"$dateToString": {"format": "%Y-%m", "date": "$_id", "timezone": "UTC"}},
                    "days": {"$sum": 1}}},
    ], allowDiskUse=True)}

    print(f"\n  {'Month':<8} {'Docs':>12} {'TradeDays':>10}")
    print(f"  {'-'*8} {'-'*12} {'-'*10}")
    for ym in sorted(by_month):
        print(f"  {ym:<8} {by_month[ym]:>12,} {days_per_month.get(ym, 0):>10}")

    # ── Gap days in the audited range (same detector as gap-fill) ─────────────
    dfrom = date.fromisoformat(a.date_from) if a.date_from else data_lo
    dto = date.fromisoformat(a.date_to) if a.date_to else date.today()
    hol = holidays(s.NSE_HOLIDAYS_JSON)
    tdays = trading_days(dfrom, dto, hol)
    gaps = days_missing(col, tdays, codes, band, min_fraction=a.min_fraction, underlying=a.symbol)
    gap_ranges = collapse_date_ranges(gaps)

    print(f"\n  Gap scan {dfrom}..{dto}  (codes={codes}, band={band}, min_fraction={a.min_fraction})")
    print(f"  trading days : {len(tdays)}")
    print(f"  gap days     : {len(gaps)}")
    if gap_ranges:
        for rng in gap_ranges:
            print(f"    - {rng}")
        print("\n  Suggested fill (where Dhan serves the range):")
        print(
            f"    python scripts/backfill_options_gap.py --symbol {a.symbol} "
            f"--from {dfrom} --to {dto} --only-missing"
        )

    summary = {
        "symbol": a.symbol, "total_docs": total, "ist_range": [str(data_lo), str(data_hi)], "source": src,
        "docs_by_month": by_month, "trade_days_by_month": days_per_month,
        "gap_scan": {"from": str(dfrom), "to": str(dto), "codes": codes, "band": band,
                     "min_fraction": a.min_fraction, "trading_days": len(tdays),
                     "gap_days": len(gaps), "gap_ranges": gap_ranges},
    }
    if a.out:
        with open(a.out, "w") as fh:
            json.dump(summary, fh, indent=2)
        print(f"\n  wrote {a.out}")
    log.info("coverage_audit_done", symbol=a.symbol, total=total, months=len(by_month), gap_days=len(gaps))
    return 0


if __name__ == "__main__":
    sys.exit(main())
