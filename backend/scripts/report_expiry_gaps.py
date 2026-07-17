"""Report expiry-cadence gaps in ``option_bars`` and how the ``expiry_calendar`` covers them.

Read-only. Answers, per underlying, three questions the option backfill needs before it runs:

  1. Which expiries are *missing* from ``option_bars`` (cadence gaps: a weekly expiry that should
     sit between two present ones is entirely absent) — the holes the Dhan backfill must fill.
  2. Which of those missing expiries the DB ``expiry_calendar`` now *knows* (seeded from the NSE
     archive) and can therefore label — i.e. the fills that are ready to run.
  3. Which gaps the calendar still can't label (need more NSE-archive seeding first).

Usage:
  python scripts/report_expiry_gaps.py                     # all three indices
  python scripts/report_expiry_gaps.py --symbol NIFTY
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import date, datetime

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from pymongo import MongoClient
from pymongo.database import Database

from pdp.instruments.expiry_calendar import (
    expiry_cadence_gaps,
    real_expiries_from_option_bars,
)
from pdp.settings import get_settings


def _calendar_dates(mdb: Database, underlying: str, flag: str = "WEEK") -> set[date]:
    out: set[date] = set()
    for doc in mdb["expiry_calendar"].find({"underlying": underlying.upper(), "flag": flag}):
        d = doc["expiry_date"]
        out.add(d.date() if isinstance(d, datetime) else d)
    return out


def _report(mdb: Database, underlying: str) -> None:
    real = real_expiries_from_option_bars(mdb, underlying)
    cal = _calendar_dates(mdb, underlying)
    gaps = expiry_cadence_gaps(underlying, real)
    print(f"\n=== {underlying} ===")
    print(f"  option_bars: {len(real)} distinct expiries"
          + (f" ({real[0]}..{real[-1]})" if real else " (none)"))
    print(f"  expiry_calendar (WEEK): {len(cal)} dates")
    if not gaps:
        print("  no cadence gaps.")
        return
    print(f"  {len(gaps)} cadence gap(s):")
    labelled = notlabelled = 0
    for _, start, end, span in gaps:
        # calendar dates strictly inside the gap window can label a re-fetch of that expiry
        inside = sorted(d for d in cal if start < d < end)
        ready = [d for d in inside if d not in real]
        if ready:
            labelled += len(ready)
            print(f"    {start} -> {end} ({span}d): calendar can label {', '.join(map(str, ready))}")
        else:
            notlabelled += 1
            print(f"    {start} -> {end} ({span}d): NO calendar date inside -- needs NSE seeding")
    print(f"  summary: {labelled} missing expiry(ies) ready to backfill, "
          f"{notlabelled} gap(s) still unlabellable")


def main() -> int:
    ap = argparse.ArgumentParser(description="Report option_bars expiry-cadence gaps vs calendar.")
    ap.add_argument("--symbol", default=None, help="One of NIFTY/BANKNIFTY/SENSEX (default: all)")
    a = ap.parse_args()

    s = get_settings()
    mdb = MongoClient(s.MONGO_URI)[s.MONGO_DB_NAME]
    symbols = [a.symbol.upper()] if a.symbol else ["NIFTY", "BANKNIFTY", "SENSEX"]
    for sym in symbols:
        _report(mdb, sym)
    return 0


if __name__ == "__main__":
    sys.exit(main())
