"""Migrate historical NIFTY index 1-minute bars from the abi DuckDB into `market_bars`.

Targets the existing `market_bars` time-series collection with
`metadata={security_id:"13", timeframe:"1m"}` (matching `BarWriter`), so backtests can read the
NIFTY index series locally instead of calling Dhan live each run. Sources the abi `nifty.db`
`nifty_spot_1m` + `spot_1m` tables (IST-naive → UTC) and deduplicates by `ts` in-app (time-series
collections cannot carry a unique index).

Usage:
  python scripts/migrate_spot_bars.py --dry-run
  python scripts/migrate_spot_bars.py
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import UTC, datetime, timedelta

import structlog
from dotenv import load_dotenv

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from pdp.settings import get_settings  # noqa: E402

load_dotenv()
log = structlog.get_logger()

SECURITY_ID = "13"  # NIFTY 50 index
TIMEFRAME = "1m"
IST = timedelta(hours=5, minutes=30)
SPOT_TABLES = ("nifty_spot_1m", "spot_1m")
BATCH = 5000


def _ensure_market_bars(db) -> None:
    from pymongo.errors import CollectionInvalid
    try:
        db.create_collection("market_bars", timeseries={
            "timeField": "ts", "metaField": "metadata", "granularity": "seconds"})
        log.info("collection_created", collection="market_bars")
    except CollectionInvalid:
        pass


def _existing_ts(col) -> set[datetime]:
    """Timestamps already stored for NIFTY index 1m (single-writer dedup for the time-series coll)."""
    cur = col.find({"metadata.security_id": SECURITY_ID, "metadata.timeframe": TIMEFRAME},
                   {"ts": 1, "_id": 0})
    return {(d["ts"] if d["ts"].tzinfo else d["ts"].replace(tzinfo=UTC)) for d in cur}


def migrate(dry_run: bool) -> int:
    import duckdb
    from pymongo import MongoClient

    s = get_settings()
    con = duckdb.connect(s.ABI_NIFTY_DUCKDB, read_only=True)
    have_tables = {t[0] for t in con.execute("SHOW TABLES").fetchall()}
    tables = [t for t in SPOT_TABLES if t in have_tables]

    if dry_run:
        for t in tables:
            n = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            rng = con.execute(f"SELECT MIN(timestamp), MAX(timestamp) FROM {t}").fetchone()
            log.info("dry_run_table", table=t, rows=n, first=str(rng[0]), last=str(rng[1]))
        con.close()
        return 0

    mdb = MongoClient(s.MONGO_URI)[s.MONGO_DB_NAME]
    _ensure_market_bars(mdb)
    col = mdb["market_bars"]
    existing = _existing_ts(col)
    seen_run: set[datetime] = set()
    inserted = skipped = 0

    for table in tables:
        cur = con.execute(f"SELECT timestamp, open, high, low, close, volume FROM {table} ORDER BY timestamp")
        buf: list[dict] = []
        while True:
            rows = cur.fetchmany(BATCH)
            if not rows:
                break
            for (ts, o, h, lo, c, vol) in rows:
                if c is None:
                    skipped += 1
                    continue
                ts_utc = (ts - IST).replace(tzinfo=UTC)
                if ts_utc in existing or ts_utc in seen_run:
                    skipped += 1
                    continue
                seen_run.add(ts_utc)
                buf.append({
                    "ts": ts_utc,
                    "metadata": {"security_id": SECURITY_ID, "timeframe": TIMEFRAME},
                    "open": float(o), "high": float(h), "low": float(lo), "close": float(c),
                    "volume": int(vol or 0), "oi": 0,
                })
            if len(buf) >= BATCH:
                col.insert_many(buf, ordered=False)
                inserted += len(buf)
                buf.clear()
                log.info("progress", table=table, inserted=inserted, skipped=skipped)
        if buf:
            col.insert_many(buf, ordered=False)
            inserted += len(buf)

    con.close()
    log.info("spot_migrate_done", inserted=inserted, skipped=skipped, tables=tables)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Migrate abi NIFTY spot 1m → market_bars (sid 13).")
    ap.add_argument("--dry-run", action="store_true", help="Report table coverage; write nothing.")
    a = ap.parse_args()
    return migrate(a.dry_run)


if __name__ == "__main__":
    sys.exit(main())
