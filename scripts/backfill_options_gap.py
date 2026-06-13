"""Dhan gap-fill for `option_bars`: cover the range after the Abi cutoff up to the present.

The Abi DuckDB ends ~2026-05-22; this fills the tail from Dhan's `expired_options_data`
(/v2/charts/rollingoption) — the same source the Abi warehouse was built from — and upserts into
`option_bars` with `source=dhan_api`. The reusable core lives in `pdp.options.gap_backfill` (shared
with the warehouser's periodic self-healing loop): for each trade day, code, ATM-relative label and
side it fetches the rolling-option 1-minute bars, derives each bar's actual strike from the NIFTY
index 1m close at the same minute, resolves the real `expiry_date` via the expiry calendar, and
upserts the fixed-strike contract (idempotent via the unique index).

`--dry-run` reports the plan (trade days × codes × labels) without Dhan creds. Live runs require
`DHAN_CLIENT_ID` / `DHAN_ACCESS_TOKEN`.

Usage:
  python scripts/backfill_options_gap.py --dry-run
  python scripts/backfill_options_gap.py --from 2026-05-23 --to 2026-06-12
  python scripts/backfill_options_gap.py --only-missing   # skip already-covered days
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import date

import structlog
from dotenv import load_dotenv

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from pdp.instruments.expiry_calendar import NiftyExpiryCalendar  # noqa: E402
from pdp.options.gap_backfill import (  # noqa: E402
    backfill_gaps,
    holidays,
    labels,
    trading_days,
)
from pdp.options.warehouse import ensure_option_bars_indexes_sync  # noqa: E402
from pdp.settings import get_settings  # noqa: E402

load_dotenv()
log = structlog.get_logger()


def main() -> int:
    ap = argparse.ArgumentParser(description="Dhan gap-fill for option_bars (post-Abi tail).")
    ap.add_argument("--from", dest="date_from", default="2026-05-23")
    ap.add_argument("--to", dest="date_to", default=date.today().isoformat())
    ap.add_argument("--codes", default="1,2")
    ap.add_argument("--band", type=int, default=None)
    ap.add_argument("--only-missing", action="store_true",
                    help="Only backfill days whose coverage is below the expected band.")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    s = get_settings()
    band = a.band if a.band is not None else s.WAREHOUSE_STRIKE_BAND
    codes = [int(x) for x in a.codes.split(",") if x.strip()]
    days = trading_days(date.fromisoformat(a.date_from), date.fromisoformat(a.date_to),
                        holidays(s.NSE_HOLIDAYS_JSON))

    if a.dry_run:
        log.info("dry_run", trading_days=len(days), first=str(days[0]) if days else None,
                 last=str(days[-1]) if days else None, codes=codes, labels=len(labels(band)),
                 planned_fetches=len(days) * len(codes) * len(labels(band)) * 2)
        return 0

    from dhanhq import DhanContext, dhanhq
    from pymongo import MongoClient

    dhan = dhanhq(DhanContext(os.environ["DHAN_CLIENT_ID"], os.environ["DHAN_ACCESS_TOKEN"]))
    col = MongoClient(s.MONGO_URI)[s.MONGO_DB_NAME]["option_bars"]
    ensure_option_bars_indexes_sync(col)
    cal = NiftyExpiryCalendar.load(s.EXPIRY_CACHE_PATH)

    summary = backfill_gaps(dhan=dhan, col=col, cal=cal, days=days, codes=codes, band=band,
                            only_missing=a.only_missing)
    log.info("gap_fill_summary", **summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
