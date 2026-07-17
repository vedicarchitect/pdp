"""Seed the DB-backed `expiry_calendar` collection (confirmed real expiry dates).

Persistent replacement for the static `data/expiry/*.json` cache as the source
`pdp.options.gap_backfill` resolves target expiries from — the JSON cache carries the same
coverage gaps as `option_bars` itself (see `option-bars-expiry-gap-backfill`). Modes,
usable together in one invocation:

  --from-option-bars              seed the entire covered history from `option_bars`' real expiries
                                  (authoritative + free): WEEK = all distinct expiries, MONTH =
                                  last-of-calendar-month subset (`classify_month_expiries`)
  --from-json <path>              migrate an existing {"WEEK": [...], "MONTH": [...]} JSON cache
  --add DATE [DATE ...] --flag F  add specific confirmed dates (e.g. NSE-verified gap fills)

Idempotent — re-running with the same dates is a no-op (unique key is
`(underlying, flag, expiry_date)`).

Usage:
  python scripts/seed_expiry_calendar.py --symbol NIFTY --from-option-bars
  python scripts/seed_expiry_calendar.py --symbol NIFTY --from-json data/expiry/nifty_expiries.json
  python scripts/seed_expiry_calendar.py --symbol NIFTY --add 2023-02-16 2023-03-23 2023-04-19 \\
      2024-04-18 --flag WEEK --source nse_verified
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from pymongo import MongoClient

from pdp.instruments.expiry_calendar import (
    classify_month_expiries,
    real_expiries_from_option_bars,
    upsert_confirmed_expiries,
)
from pdp.settings import get_settings


def main() -> int:
    ap = argparse.ArgumentParser(description="Seed the DB-backed expiry_calendar collection.")
    ap.add_argument("--symbol", required=True, help="Underlying, e.g. NIFTY / BANKNIFTY / SENSEX")
    ap.add_argument("--from-option-bars", action="store_true",
                    help="Seed all real expiries observed in option_bars (WEEK=all, MONTH=last-of-month)")
    ap.add_argument("--from-json", default=None, help="Migrate an existing {WEEK,MONTH} JSON cache")
    ap.add_argument("--add", nargs="+", default=None, help="Explicit confirmed dates (YYYY-MM-DD)")
    ap.add_argument("--flag", default="WEEK", choices=["WEEK", "MONTH"], help="Flag for --add dates")
    ap.add_argument("--source", default="manual_confirmed", help="Provenance tag for --add dates")
    a = ap.parse_args()

    if not a.from_option_bars and not a.from_json and not a.add:
        print("ERROR: pass --from-option-bars, --from-json and/or --add", file=sys.stderr)
        return 1

    s = get_settings()
    mdb = MongoClient(s.MONGO_URI)[s.MONGO_DB_NAME]
    # Ensure the unique index even when run standalone (outside app startup, where
    # pdp.mongo.collections._ensure_expiry_calendar would create it). Idempotent.
    mdb["expiry_calendar"].create_index(
        [("underlying", 1), ("flag", 1), ("expiry_date", 1)],
        unique=True, name="uq_underlying_flag_expiry",
    )

    total = 0
    if a.from_option_bars:
        real = real_expiries_from_option_bars(mdb, a.symbol.upper())
        week_list, month_list = classify_month_expiries(real)
        n_week = upsert_confirmed_expiries(mdb, a.symbol, "WEEK", week_list,
                                           source="option_bars_observed")
        n_month = upsert_confirmed_expiries(mdb, a.symbol, "MONTH", month_list,
                                            source="option_bars_observed")
        print(f"{a.symbol} from option_bars: {len(real)} real expiries -> "
              f"WEEK +{n_week}/{len(week_list)}, MONTH +{n_month}/{len(month_list)}")
        total += n_week + n_month

    if a.from_json:
        data = json.loads(Path(a.from_json).read_text())
        for flag, dates in data.items():
            parsed = [date.fromisoformat(x) for x in dates]
            n = upsert_confirmed_expiries(mdb, a.symbol, flag, parsed, source="json_migration")
            print(f"{a.symbol} {flag}: migrated {n} new / {len(parsed)} total from {a.from_json}")
            total += n

    if a.add:
        parsed = [date.fromisoformat(x) for x in a.add]
        n = upsert_confirmed_expiries(mdb, a.symbol, a.flag, parsed, source=a.source)
        print(f"{a.symbol} {a.flag}: added {n} new / {len(parsed)} from --add")
        total += n

    print(f"total newly inserted: {total}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
