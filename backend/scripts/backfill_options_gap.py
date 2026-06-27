"""Dhan gap-fill for `option_bars`: cover a date range up to the present.

Supports three underlyings via ``--symbol``:

  NIFTY    (default) — sid 13, step 50, NSE_FNO, requires data/expiry/nifty_expiries.json
  BANKNIFTY          — sid 25, step 100, NSE_FNO, requires data/expiry/banknifty_expiries.json
  SENSEX             — sid 51, step 100, BSE_FNO, requires data/expiry/sensex_expiries.json

For each trade day, code, ATM-relative label and side the script fetches rolling-option 1-minute
bars from Dhan's ``expired_options_data`` endpoint, derives each bar's actual strike from the index
1m close at the same minute, resolves the real ``expiry_date`` via the per-symbol expiry calendar,
and upserts the fixed-strike contract into ``option_bars`` (idempotent via the unique index).

``--dry-run`` reports the plan without Dhan creds. Live runs require DHAN_CLIENT_ID /
DHAN_ACCESS_TOKEN. The expiry cache for the selected symbol must exist on disk before running.

Usage:
  python scripts/backfill_options_gap.py --dry-run
  python scripts/backfill_options_gap.py --symbol BANKNIFTY --from 2021-06-01 --only-missing
  python scripts/backfill_options_gap.py --symbol SENSEX --from 2021-06-01 --dry-run
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import date
from pathlib import Path

import structlog
from dotenv import load_dotenv

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from pdp.instruments.expiry_calendar import NiftyExpiryCalendar
from pdp.options.gap_backfill import (
    backfill_gaps,
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
    ap.add_argument("--codes", default="1,2")
    ap.add_argument("--band", type=int, default=None)
    ap.add_argument("--only-missing", action="store_true",
                    help="Only backfill days whose coverage is below the expected band.")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    s = get_settings()
    cfg = _SYMBOL_CONFIG[a.symbol]

    # Resolve expiry cache path from settings
    expiry_path_map = {
        "NIFTY":     s.EXPIRY_CACHE_PATH,
        "BANKNIFTY": s.BANKNIFTY_EXPIRY_CACHE_PATH,
        "SENSEX":    s.SENSEX_EXPIRY_CACHE_PATH,
    }
    expiry_path = expiry_path_map[a.symbol]

    # Guard: expiry cache must exist before we open a Dhan connection
    if not Path(expiry_path).exists():
        print(
            f"ERROR: expiry cache not found for {a.symbol}: {expiry_path}\n"
            "Build it first with: python scripts/build_expiry_cache.py",
            file=sys.stderr,
        )
        return 1

    band = a.band if a.band is not None else s.WAREHOUSE_STRIKE_BAND
    date_from = a.date_from if a.date_from is not None else "2021-01-01"
    codes = [int(x) for x in a.codes.split(",") if x.strip()]
    days = trading_days(date.fromisoformat(date_from), date.fromisoformat(a.date_to),
                        holidays(s.NSE_HOLIDAYS_JSON))

    if a.dry_run:
        log.info("dry_run", symbol=a.symbol, underlying_sid=cfg["sid"], step=cfg["step"],
                 trading_days=len(days), first=str(days[0]) if days else None,
                 last=str(days[-1]) if days else None, codes=codes, labels=len(labels(band)),
                 planned_fetches=len(days) * len(codes) * len(labels(band)) * 2,
                 date_from=date_from)
        return 0

    from dhanhq import DhanContext, dhanhq
    from pymongo import MongoClient

    dhan = dhanhq(DhanContext(os.environ["DHAN_CLIENT_ID"], os.environ["DHAN_ACCESS_TOKEN"]))
    col = MongoClient(s.MONGO_URI)[s.MONGO_DB_NAME]["option_bars"]
    ensure_option_bars_indexes_sync(col)
    cal = NiftyExpiryCalendar.load(expiry_path)

    summary = backfill_gaps(
        dhan=dhan, col=col, cal=cal, days=days, codes=codes, band=band,
        only_missing=a.only_missing, underlying=a.symbol,
        underlying_sid=cfg["sid"], strike_step=cfg["step"],
        exchange_segment=cfg["exchange_segment"],
    )
    log.info("gap_fill_summary", symbol=a.symbol, **summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
