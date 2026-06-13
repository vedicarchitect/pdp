"""Validate the `option_bars` warehouse — fails (non-zero exit) on any integrity breach.

Gates:
  1. OHLC sanity:  high >= low, high >= max(open,close), low <= min(open,close)
  2. Non-null / positive strike and close
  3. Zero duplicate (contract, ts)  — the unique index should already guarantee this
  4. expiry_date plausibility:  no bar's IST trade-day is after its expiry_date
  5. strike_label ↔ strike spacing consistency (sampled): within one (expiry_date, ts),
     ATM±N strikes sit N grid-steps from the ATM strike
  6. Timestamp coverage: abi series must span at least 3 distinct IST trade-days
  7. Live↔backfill overlap reconciliation: no abi bars after the Dhan gap-fill cutoff
  8. (optional) Abi↔Mongo count reconciliation for a range (`--duck --from --to`)

Usage:
  python scripts/validate_options_warehouse.py
  python scripts/validate_options_warehouse.py --duck --from 2026-04-01 --to 2026-04-08
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import UTC, date, datetime, timedelta

import structlog
from dotenv import load_dotenv

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from pdp.settings import get_settings  # noqa: E402

load_dotenv()
log = structlog.get_logger()

STEP = 50  # NIFTY strike grid
IST = timedelta(hours=5, minutes=30)


def _check(col, cutoff_date: date | None = None) -> list[str]:
    failures: list[str] = []
    total = col.count_documents({})
    log.info("counts", total=total)
    if total == 0:
        return ["warehouse is empty"]

    # 1. OHLC sanity
    bad_ohlc = col.count_documents({"$expr": {"$or": [
        {"$lt": ["$high", "$low"]},
        {"$lt": ["$high", {"$max": ["$open", "$close"]}]},
        {"$gt": ["$low", {"$min": ["$open", "$close"]}]},
    ]}})
    log.info("gate_ohlc_sanity", violations=bad_ohlc)
    if bad_ohlc:
        failures.append(f"OHLC sanity: {bad_ohlc} violations")

    # 2. null / non-positive strike or close
    bad_vals = col.count_documents({"$or": [
        {"strike": {"$in": [None]}}, {"strike": {"$lte": 0}},
        {"close": {"$in": [None]}}, {"close": {"$lte": 0}},
    ]})
    log.info("gate_values", violations=bad_vals)
    if bad_vals:
        failures.append(f"null/non-positive strike or close: {bad_vals}")

    # 3. duplicate (contract, ts)
    dup = list(col.aggregate([
        {"$group": {"_id": {"u": "$underlying", "e": "$expiry_date", "s": "$strike",
                            "o": "$option_type", "t": "$timeframe", "ts": "$ts"},
                    "n": {"$sum": 1}}},
        {"$match": {"n": {"$gt": 1}}}, {"$count": "dups"},
    ]))
    n_dup = dup[0]["dups"] if dup else 0
    log.info("gate_duplicates", duplicate_keys=n_dup)
    if n_dup:
        failures.append(f"duplicate (contract, ts): {n_dup}")

    # 4. expiry_date plausibility: IST trade-day <= expiry_date
    bad_exp = list(col.aggregate([
        {"$project": {"tsd": {"$dateTrunc": {"date": {"$add": ["$ts", int(IST.total_seconds() * 1000)]},
                                             "unit": "day"}},
                      "exp": "$expiry_date"}},
        {"$match": {"$expr": {"$gt": ["$tsd", "$exp"]}}}, {"$count": "n"},
    ]))
    n_bad_exp = bad_exp[0]["n"] if bad_exp else 0
    log.info("gate_expiry_plausibility", bars_after_expiry=n_bad_exp)
    if n_bad_exp:
        failures.append(f"bars dated after expiry_date: {n_bad_exp}")

    # 5. strike_label ↔ strike spacing (sample up to 50 (expiry_date, ts) groups)
    sample = list(col.aggregate([
        {"$match": {"strike_label": {"$ne": None}}},
        {"$group": {"_id": {"e": "$expiry_date", "ts": "$ts", "o": "$option_type"},
                    "rows": {"$push": {"label": "$strike_label", "strike": "$strike"}}}},
        {"$limit": 50},
    ]))
    label_bad = 0
    for grp in sample:
        rows = grp["rows"]
        atm = next((r["strike"] for r in rows if r["label"] == "ATM"), None)
        if atm is None:
            continue
        for r in rows:
            lbl = r["label"]
            off = 0 if lbl == "ATM" else int(lbl.replace("ATM", ""))  # ATM+4→4, ATM-3→-3
            if abs(r["strike"] - (atm + off * STEP)) > 1e-6:
                label_bad += 1
    log.info("gate_label_consistency", sampled_groups=len(sample), mismatches=label_bad)
    if label_bad:
        failures.append(f"strike_label↔strike mismatches in sample: {label_bad}")

    # 6. Timestamp coverage: every abi (expiry_date, option_type) series must span ≥3 IST trade-days.
    # A weekly series in the historical Abi export always covers multiple days; fewer than 3
    # indicates a partial migration or truncated scrape.
    thin_result = list(col.aggregate([
        {"$match": {"source": "abi"}},
        {"$group": {
            "_id": {
                "e": "$expiry_date", "o": "$option_type",
                "d": {"$dateTrunc": {
                    "date": {"$add": ["$ts", int(IST.total_seconds() * 1000)]},
                    "unit": "day",
                }},
            },
        }},
        {"$group": {"_id": {"e": "$_id.e", "o": "$_id.o"}, "days": {"$sum": 1}}},
        {"$match": {"days": {"$lt": 3}}},
        {"$count": "thin_series"},
    ]))
    n_thin = thin_result[0]["thin_series"] if thin_result else 0
    log.info("gate_timestamp_coverage", thin_abi_series=n_thin)
    if n_thin:
        failures.append(f"abi series with fewer than 3 distinct trade-days: {n_thin}")

    # 7. Live↔backfill overlap reconciliation: after the Abi cutoff only dhan_api bars expected.
    if cutoff_date is not None:
        cutoff_utc = (datetime(cutoff_date.year, cutoff_date.month, cutoff_date.day) - IST).replace(tzinfo=UTC)
        abi_post = col.count_documents({"source": "abi", "ts": {"$gte": cutoff_utc}})
        dhan_pre = col.count_documents({"source": "dhan_api", "ts": {"$lt": cutoff_utc}})
        log.info("gate_overlap_reconciliation",
                 abi_post_cutoff=abi_post, dhan_api_pre_cutoff=dhan_pre, cutoff=str(cutoff_date))
        if abi_post:
            failures.append(f"abi bars found after cutoff {cutoff_date}: {abi_post}")

    return failures


def _reconcile(col, duck_path: str, date_from: date, date_to: date, band: int) -> list[str]:
    import duckdb
    labels = ["ATM"] + [f"ATM{sign}{i}" for i in range(1, band + 1) for sign in ("+", "-")]
    con = duckdb.connect(duck_path, read_only=True)
    duck_n = con.execute(
        "SELECT COUNT(*) FROM expired_options_ohlcv WHERE underlying_scrip='NIFTY' "
        "AND expiry_flag='WEEK' AND expiry_code IN (1,2) AND close IS NOT NULL "
        f"AND strike_label IN ({','.join('?' * len(labels))}) "
        "AND timestamp >= ? AND timestamp < ?",
        [*labels, datetime(date_from.year, date_from.month, date_from.day),
         datetime(date_to.year, date_to.month, date_to.day)],
    ).fetchone()[0]
    con.close()
    lo = (datetime(date_from.year, date_from.month, date_from.day) - IST).replace(tzinfo=UTC)
    hi = (datetime(date_to.year, date_to.month, date_to.day) - IST).replace(tzinfo=UTC)
    mongo_n = col.count_documents({"source": "abi", "ts": {"$gte": lo, "$lt": hi}})
    log.info("gate_reconcile", duck_rows=duck_n, mongo_rows=mongo_n)
    return [] if duck_n == mongo_n else [f"Abi↔Mongo count mismatch: duck={duck_n} mongo={mongo_n}"]


def main() -> int:
    ap = argparse.ArgumentParser(description="Validate the option_bars warehouse.")
    ap.add_argument("--duck", action="store_true", help="Also reconcile counts against the abi DuckDB.")
    ap.add_argument("--from", dest="date_from", default=None)
    ap.add_argument("--to", dest="date_to", default=None)
    a = ap.parse_args()

    s = get_settings()
    from pymongo import MongoClient
    col = MongoClient(s.MONGO_URI)[s.MONGO_DB_NAME]["option_bars"]

    cutoff = date.fromisoformat(s.ABI_CUTOFF_DATE)
    failures = _check(col, cutoff_date=cutoff)
    if a.duck and a.date_from and a.date_to:
        failures += _reconcile(col, s.ABI_NIFTY_DUCKDB,
                               date.fromisoformat(a.date_from), date.fromisoformat(a.date_to),
                               s.WAREHOUSE_STRIKE_BAND)

    if failures:
        for f in failures:
            log.error("validation_failed", gate=f)
        return 1
    log.info("validation_passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
