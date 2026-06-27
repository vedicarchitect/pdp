"""Verify NIFTY migration: DuckDB source vs MongoDB option_bars, single-pass aggregations.

DuckDB: one GROUP BY year-month query (fast).
MongoDB: one $group aggregation pipeline (fast — no per-month count_documents).
Then diff them side by side.
"""
from __future__ import annotations

import os
import sys
from datetime import UTC, timedelta

import structlog
from dotenv import load_dotenv

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
from pdp.settings import get_settings

load_dotenv()
log = structlog.get_logger()

IST_OFFSET_MS = int(timedelta(hours=5, minutes=30).total_seconds() * 1000)
UNDERLYING = "NIFTY"


def main():
    s = get_settings()

    import duckdb
    from pymongo import MongoClient

    con = duckdb.connect(s.ABI_NIFTY_DUCKDB, read_only=True)
    col = MongoClient(s.MONGO_URI)[s.MONGO_DB_NAME]["option_bars"]

    # ── DuckDB: date range + total ────────────────────────────────────────────
    print("Querying DuckDB...", flush=True)
    info = con.execute(
        "SELECT MIN(timestamp), MAX(timestamp), COUNT(*) "
        "FROM expired_options_ohlcv "
        "WHERE underlying_scrip = ? AND expiry_flag = 'WEEK' AND expiry_code IN (1,2) "
        "AND close IS NOT NULL",
        [UNDERLYING],
    ).fetchone()
    duck_min, duck_max, duck_total = info
    print(f"  DuckDB scoped: {duck_min} to {duck_max}, total={duck_total:,}")

    # ── DuckDB: per-month counts ──────────────────────────────────────────────
    duck_by_month = con.execute(
        "SELECT strftime(timestamp, '%Y-%m') AS ym, COUNT(*) AS n "
        "FROM expired_options_ohlcv "
        "WHERE underlying_scrip = ? AND expiry_flag = 'WEEK' AND expiry_code IN (1,2) "
        "AND close IS NOT NULL "
        "GROUP BY ym ORDER BY ym",
        [UNDERLYING],
    ).fetchall()
    con.close()

    duck_map = {ym: n for ym, n in duck_by_month}

    # ── MongoDB: single-pass $group by UTC year-month, then convert to IST ───
    print("Querying MongoDB (single aggregation pass)...", flush=True)
    pipeline = [
        {"$match": {"source": "abi"}},
        {"$group": {
            "_id": {
                "$dateToString": {
                    "format": "%Y-%m",
                    "date": {"$add": ["$ts", IST_OFFSET_MS]},
                    "timezone": "UTC",
                }
            },
            "n": {"$sum": 1},
        }},
        {"$sort": {"_id": 1}},
    ]
    mongo_map = {r["_id"]: r["n"] for r in col.aggregate(pipeline, allowDiskUse=True)}
    mongo_total = sum(mongo_map.values())
    print(f"  MongoDB source=abi total: {mongo_total:,}")

    # ── Side-by-side diff ─────────────────────────────────────────────────────
    all_months = sorted(set(duck_map) | set(mongo_map))
    print(f"\n{'Month':<10} {'DuckDB':>12} {'MongoDB':>12} {'Diff':>10}  Status")
    print("-" * 56)
    mismatches = []
    for ym in all_months:
        d = duck_map.get(ym, 0)
        m = mongo_map.get(ym, 0)
        diff = m - d
        ok = "OK" if d == m else f"MISMATCH ({diff:+,})"
        if d != m:
            mismatches.append((ym, d, m, diff))
        print(f"{ym:<10} {d:>12,} {m:>12,} {diff:>+10,}  {ok}")

    print("-" * 56)
    diff_total = mongo_total - duck_total
    status = "OK" if duck_total == mongo_total else f"MISMATCH ({diff_total:+,})"
    print(f"{'TOTAL':<10} {duck_total:>12,} {mongo_total:>12,} {diff_total:>+10,}  {status}")

    # ── Null/expiry skip analysis ─────────────────────────────────────────────
    con2 = duckdb.connect(s.ABI_NIFTY_DUCKDB, read_only=True)
    null_count = con2.execute(
        "SELECT COUNT(*) FROM expired_options_ohlcv "
        "WHERE underlying_scrip = ? AND expiry_flag = 'WEEK' AND expiry_code IN (1,2) "
        "AND close IS NULL",
        [UNDERLYING],
    ).fetchone()[0]
    # All rows including null-close
    total_all = con2.execute(
        "SELECT COUNT(*) FROM expired_options_ohlcv "
        "WHERE underlying_scrip = ? AND expiry_flag = 'WEEK' AND expiry_code IN (1,2)",
        [UNDERLYING],
    ).fetchone()[0]
    con2.close()

    # Expiry-resolve skips = rows that had close but expiry could not be resolved
    expiry_skips = duck_total - mongo_total if duck_total > mongo_total else 0

    print(f"\nSkip analysis:")
    print(f"  DuckDB total (codes 1&2 incl null-close): {total_all:,}")
    print(f"  Null-close rows (skipped pre-filter)    : {null_count:,}")
    print(f"  Scoped rows with close                  : {duck_total:,}")
    print(f"  Inserted into MongoDB                   : {mongo_total:,}")
    print(f"  Expiry-resolve skips (approx)           : {expiry_skips:,}")

    if not mismatches:
        print("\nResult: PASS - all months match.")
    else:
        print(f"\nResult: FAIL - {len(mismatches)} month(s) with mismatches:")
        for ym, d, m, diff in mismatches:
            print(f"  {ym}: duck={d:,} mongo={m:,} diff={diff:+,}")

    return 0 if not mismatches else 1


if __name__ == "__main__":
    sys.exit(main())
