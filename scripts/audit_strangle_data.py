"""Per-year data-coverage audit for the directional-strangle backtest (Mongo only).

Reports, per calendar year, how many trading days have adequate NIFTY spot (`market_bars`),
option-chain (`option_bars`), and India VIX coverage, and prints the earliest date that meets the
spot threshold. The backtest window for optimization should be derived from this report — we do
not assume 5 full years exist; we measure what Dhan actually backfilled into Mongo.

Usage:
  python scripts/audit_strangle_data.py --from 2021-01-01 --to 2026-06-30
  python scripts/audit_strangle_data.py --from 2021-01-01 --vix-sid 21
"""
from __future__ import annotations

import argparse
import os
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any

from dotenv import load_dotenv

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from pdp.options.gap_backfill import holidays, trading_days
from pdp.settings import get_settings

load_dotenv()

NIFTY_SID = "13"
SPOT_THRESHOLD = 350   # >= this many 1m spot bars => "adequate" day (full session ~375)
VIX_THRESHOLD = 300


def _day_window(day: date) -> tuple[datetime, datetime]:
    lo = datetime(day.year, day.month, day.day) - timedelta(hours=5, minutes=30)
    return lo, lo + timedelta(days=1)


def _spot_count(col: Any, sid: str, day: date) -> int:
    lo, hi = _day_window(day)
    return col.count_documents({
        "metadata.security_id": sid, "metadata.timeframe": "1m",
        "ts": {"$gte": lo, "$lt": hi},
    })


def _option_strikes(col: Any, day: date) -> int:
    """Distinct strikes present for NIFTY options on this trade day (any expiry)."""
    lo, hi = _day_window(day)
    strikes = col.distinct("strike", {
        "underlying": "NIFTY", "timeframe": "1m", "ts": {"$gte": lo, "$lt": hi},
    })
    return len(strikes)


def main() -> int:
    ap = argparse.ArgumentParser(description="Per-year strangle data-coverage audit.")
    ap.add_argument("--from", dest="date_from", required=True)
    ap.add_argument("--to", dest="date_to", default=date.today().isoformat())
    ap.add_argument("--vix-sid", default=os.getenv("VIX_SECURITY_ID", "21"))
    a = ap.parse_args()

    from pymongo import MongoClient
    s = get_settings()
    mdb = MongoClient(s.MONGO_URI)[s.MONGO_DB_NAME]
    mkt, opt = mdb["market_bars"], mdb["option_bars"]

    days = trading_days(
        date.fromisoformat(a.date_from), date.fromisoformat(a.date_to),
        holidays(s.NSE_HOLIDAYS_JSON),
    )

    by_year: dict[int, dict[str, int]] = defaultdict(lambda: {"days": 0, "spot": 0, "opt": 0, "vix": 0})
    earliest_spot: date | None = None
    for d in days:
        y = by_year[d.year]
        y["days"] += 1
        if _spot_count(mkt, NIFTY_SID, d) >= SPOT_THRESHOLD:
            y["spot"] += 1
            if earliest_spot is None:
                earliest_spot = d
        if _option_strikes(opt, d) >= 5:
            y["opt"] += 1
        if _spot_count(mkt, a.vix_sid, d) >= VIX_THRESHOLD:
            y["vix"] += 1

    print(f"\n{'='*72}")
    print(f"  STRANGLE DATA COVERAGE  ({days[0]} .. {days[-1]})")
    print(f"{'='*72}")
    print(f"  {'Year':<6}  {'TrDays':>7}  {'Spot':>10}  {'Options':>10}  {'VIX':>10}")
    print(f"  {'-'*6}  {'-'*7}  {'-'*10}  {'-'*10}  {'-'*10}")
    for year in sorted(by_year):
        c = by_year[year]
        n = c["days"] or 1
        print(f"  {year:<6}  {c['days']:>7}  {c['spot']:>4} ({c['spot']*100//n:>3}%)  "
              f"{c['opt']:>4} ({c['opt']*100//n:>3}%)  {c['vix']:>4} ({c['vix']*100//n:>3}%)")
    print(f"  {'-'*72}")
    print(f"  Earliest adequately-covered spot day: {earliest_spot or 'NONE — backfill spot first'}")
    print("  -> Use this as the backtest window start. Years with low Options/VIX %% are gaps.")
    print(f"{'='*72}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
