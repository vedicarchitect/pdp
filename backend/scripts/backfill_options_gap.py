"""Dhan gap-fill for `option_bars`: cover a date range up to the present.

Supports three underlyings via ``--symbol``:

  NIFTY    (default) — sid 13, step 50, NSE_FNO
  BANKNIFTY          — sid 25, step 100, NSE_FNO
  SENSEX             — sid 51, step 100, BSE_FNO

For each trade day, code, ATM-relative label and side the script fetches rolling-option 1-minute
bars from Dhan's ``expired_options_data`` endpoint, derives each bar's actual strike from the index
1m close at the same minute, resolves the real ``expiry_date`` via the per-symbol expiry calendar,
and upserts the fixed-strike contract into ``option_bars`` (idempotent via the unique index).

The expiry calendar is read from the DB-backed `expiry_calendar` Mongo collection (see
`pdp.instruments.expiry_calendar.load_expiry_calendar_from_db`), not a static JSON file — seed it
first with `scripts/seed_expiry_calendar.py`. A calendar with a gap (an expiry that was never
listed there) can never resolve a trade day to that missing expiry; use ``--target-expiry`` for
those days instead (see below), not the default resolution path.

``--target-expiry YYYY-MM-DD`` bypasses calendar resolution entirely: every day in ``--from..--to``
is fetched directly against that one known expiry (for a confirmed expiry-cadence gap — see
`pdp.instruments.expiry_calendar.expiry_cadence_gaps`). Use this, not the default path, once you
know the exact missing expiry date; the default path can only ever resolve to expiries the
calendar already has.

``--dry-run`` reports the plan without Dhan creds. Live runs require DHAN_CLIENT_ID /
DHAN_ACCESS_TOKEN.

Usage:
  python scripts/backfill_options_gap.py --dry-run
  python scripts/backfill_options_gap.py --symbol BANKNIFTY --from 2021-06-01 --only-missing
  python scripts/backfill_options_gap.py --symbol SENSEX --from 2021-06-01 --dry-run
  python scripts/backfill_options_gap.py --symbol NIFTY --from 2023-03-17 --to 2023-03-23 \\
      --target-expiry 2023-03-23
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import date

import structlog
from dotenv import load_dotenv

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from pdp.instruments.expiry_calendar import load_expiry_calendar_from_db
from pdp.options.gap_backfill import (
    DEFAULT_LADDER,
    backfill_gaps,
    backfill_missing_expiry,
    build_ladder,
    holidays,
    labels,
    trading_days,
)
from pdp.options.warehouse import ensure_option_bars_indexes_sync
from pdp.settings import get_settings

load_dotenv()
log = structlog.get_logger()

# Per-symbol static config; expiry_path is resolved after settings are loaded.
_SYMBOL_CONFIG: dict[str, dict] = {
    "NIFTY":     {"sid": 13, "step": 50,  "exchange_segment": "NSE_FNO"},
    "BANKNIFTY": {"sid": 25, "step": 100, "exchange_segment": "NSE_FNO"},
    "SENSEX":    {"sid": 51, "step": 100, "exchange_segment": "BSE_FNO"},
}


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Dhan gap-fill for option_bars (NIFTY / BANKNIFTY / SENSEX).")
    ap.add_argument("--symbol", choices=list(_SYMBOL_CONFIG), default="NIFTY",
                    help="Underlying index to backfill (default: NIFTY)")
    ap.add_argument("--from", dest="date_from", default=None)
    ap.add_argument("--to", dest="date_to", default=date.today().isoformat())
    ap.add_argument("--week-codes", default=None,
                    help="Comma list of WEEK expiry codes to fetch (Dhan supports 1-3). "
                         "Default: the full ladder (WEEK 1,2,3 + MONTH 1,2).")
    ap.add_argument("--month-codes", default=None,
                    help="Comma list of MONTH expiry codes to fetch (current/next monthly; "
                         "Dhan supports 1-2). Default: the full ladder.")
    ap.add_argument("--codes", default=None,
                    help="Deprecated alias for --week-codes (kept for backfill:daily back-compat).")
    ap.add_argument("--band", type=int, default=None)
    ap.add_argument("--only-missing", action="store_true",
                    help="Only backfill days whose coverage is below the expected band.")
    ap.add_argument("--target-expiry", default=None,
                    help="Bypass calendar resolution; fetch every day in range against this "
                         "one known-but-uningested expiry (YYYY-MM-DD), labelling every fetched "
                         "series as it. Escape hatch for the expiry's own final week only — for a "
                         "wider window, seed the expiry into expiry_calendar and re-run with "
                         "--only-missing off instead.")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    s = get_settings()
    cfg = _SYMBOL_CONFIG[a.symbol]

    band = a.band if a.band is not None else s.WAREHOUSE_STRIKE_BAND
    date_from = a.date_from if a.date_from is not None else "2021-01-01"

    # Compose the (flag, code) ladder. --codes is a back-compat alias for --week-codes; if neither
    # week nor month codes are given, use the full DEFAULT_LADDER (WEEK 1,2,3 + MONTH 1,2).
    week_arg = a.week_codes if a.week_codes is not None else a.codes
    if week_arg is None and a.month_codes is None:
        ladder = list(DEFAULT_LADDER)
    else:
        week_codes = [int(x) for x in (week_arg or "").split(",") if x.strip()]
        month_codes = [int(x) for x in (a.month_codes or "").split(",") if x.strip()]
        ladder = build_ladder(week_codes, month_codes)

    days = trading_days(date.fromisoformat(date_from), date.fromisoformat(a.date_to),
                        holidays(s.NSE_HOLIDAYS_JSON))

    if a.dry_run:
        log.info("dry_run", symbol=a.symbol, underlying_sid=cfg["sid"], step=cfg["step"],
                 trading_days=len(days), first=str(days[0]) if days else None,
                 last=str(days[-1]) if days else None, ladder=ladder, labels=len(labels(band)),
                 planned_fetches=len(days) * len(ladder) * len(labels(band)) * 2,
                 date_from=date_from, target_expiry=a.target_expiry)
        return 0

    from dhanhq import DhanContext, dhanhq
    from pymongo import MongoClient

    dhan = dhanhq(DhanContext(os.environ["DHAN_CLIENT_ID"], os.environ["DHAN_ACCESS_TOKEN"]))
    mdb = MongoClient(s.MONGO_URI)[s.MONGO_DB_NAME]
    col = mdb["option_bars"]
    ensure_option_bars_indexes_sync(col)

    if a.target_expiry:
        summary = backfill_missing_expiry(
            dhan=dhan, col=col, target_expiry=date.fromisoformat(a.target_expiry),
            days=days, band=band, underlying=a.symbol,
            underlying_sid=cfg["sid"], strike_step=cfg["step"],
            exchange_segment=cfg["exchange_segment"],
        )
    else:
        cal = load_expiry_calendar_from_db(mdb, a.symbol)
        summary = backfill_gaps(
            dhan=dhan, col=col, cal=cal, days=days, ladder=ladder, band=band,
            only_missing=a.only_missing, underlying=a.symbol,
            underlying_sid=cfg["sid"], strike_step=cfg["step"],
            exchange_segment=cfg["exchange_segment"],
        )
    log.info("gap_fill_summary", symbol=a.symbol, **summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
