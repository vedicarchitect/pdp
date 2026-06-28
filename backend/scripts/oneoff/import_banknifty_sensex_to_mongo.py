"""Migrate BANKNIFTY and SENSEX from duckdb to Mongo (market_bars and option_bars).

Idempotent: spot uses cutoff by max existing ts; options uses cutoff by max existing ts
per underlying + upsert semantics (first-write-wins via $setOnInsert).
"""
import os
import sys
import argparse
from datetime import UTC, datetime, timedelta

import structlog
from dotenv import load_dotenv

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

from pdp.instruments.expiry_calendar import NiftyExpiryCalendar
from pdp.instruments.symbols import symbol_for
from pdp.options.warehouse import (
    build_option_bar_doc,
    ensure_option_bars_indexes_sync,
    upsert_option_bars_sync,
)
from pdp.settings import get_settings

load_dotenv()
log = structlog.get_logger()

IST = timedelta(hours=5, minutes=30)
BATCH = 5000

CONFIGS = {
    "BANKNIFTY": {
        "db": r"C:\Users\prasa\OneDrive\Desktop\komalavalli\Abi\data\historicaldata\banknifty.db",
        "sid": "25",
        "expiry_path": "BANKNIFTY_EXPIRY_CACHE_PATH"
    },
    "SENSEX": {
        "db": r"C:\Users\prasa\OneDrive\Desktop\komalavalli\Abi\data\historicaldata\sensex.db",
        "sid": "51",
        "expiry_path": "SENSEX_EXPIRY_CACHE_PATH"
    }
}


def _ist_to_utc(ts: datetime) -> datetime:
    return (ts - IST).replace(tzinfo=UTC)


def _utc_to_ist_naive(ts: datetime) -> datetime:
    """Convert UTC-aware datetime to naive IST (for DuckDB comparisons)."""
    return (ts.replace(tzinfo=None) + IST)


def migrate_spot(con, mdb, underlying: str, sid: str):
    from pymongo.errors import CollectionInvalid
    col = mdb["market_bars"]
    try:
        mdb.create_collection("market_bars", timeseries={
            "timeField": "ts", "metaField": "metadata", "granularity": "seconds"})
        log.info("collection_created", collection="market_bars")
    except CollectionInvalid:
        pass

    # Find max existing ts for this security to avoid a full set scan
    latest = col.find_one(
        {"metadata.security_id": sid, "metadata.timeframe": "1m"},
        sort=[("ts", -1)],
        projection={"ts": 1, "_id": 0},
    )
    if latest:
        cutoff_utc = latest["ts"] if latest["ts"].tzinfo else latest["ts"].replace(tzinfo=UTC)
        cutoff_ist = _utc_to_ist_naive(cutoff_utc)
        log.info("spot_cutoff", underlying=underlying, cutoff_utc=str(cutoff_utc), cutoff_ist=str(cutoff_ist))
        cur = con.execute(
            "SELECT timestamp, open, high, low, close, volume FROM spot_1m WHERE timestamp > ? ORDER BY timestamp",
            [cutoff_ist],
        )
    else:
        log.info("spot_full_import", underlying=underlying)
        cur = con.execute("SELECT timestamp, open, high, low, close, volume FROM spot_1m ORDER BY timestamp")

    inserted = skipped = 0
    buf = []
    while True:
        rows = cur.fetchmany(BATCH)
        if not rows:
            break
        for (ts, o, h, lo, c, vol) in rows:
            if c is None:
                skipped += 1
                continue
            buf.append({
                "ts": _ist_to_utc(ts),
                "metadata": {"security_id": sid, "timeframe": "1m"},
                "open": float(o), "high": float(h), "low": float(lo), "close": float(c),
                "volume": int(vol or 0), "oi": 0,
            })
        if len(buf) >= BATCH:
            col.insert_many(buf, ordered=False)
            inserted += len(buf)
            buf.clear()
            log.info("spot_progress", underlying=underlying, inserted=inserted, skipped=skipped)
    if buf:
        col.insert_many(buf, ordered=False)
        inserted += len(buf)

    log.info("spot_migrate_done", underlying=underlying, inserted=inserted, skipped=skipped)


def migrate_options(con, mdb, s, underlying: str, expiry_path_attr: str):
    cache_path = getattr(s, expiry_path_attr)
    cal = NiftyExpiryCalendar.load(cache_path)
    col = mdb["option_bars"]
    ensure_option_bars_indexes_sync(col)

    # Find max existing ts for this underlying — only migrate rows newer than this
    latest = col.find_one({"underlying": underlying}, sort=[("ts", -1)], projection={"ts": 1, "_id": 0})
    if latest:
        cutoff_utc = latest["ts"] if latest["ts"].tzinfo else latest["ts"].replace(tzinfo=UTC)
        cutoff_ist = _utc_to_ist_naive(cutoff_utc)
        log.info("options_cutoff", underlying=underlying, cutoff_utc=str(cutoff_utc), cutoff_ist=str(cutoff_ist))
        sql = """
            SELECT timestamp, expiry_flag, expiry_code, strike_label, strike_price, option_type,
                   open, high, low, close, volume, oi, iv
            FROM expired_options_ohlcv
            WHERE underlying_scrip = ? AND timestamp > ?
            ORDER BY timestamp
        """
        cur = con.execute(sql, [underlying, cutoff_ist])
    else:
        log.info("options_full_import", underlying=underlying)
        sql = """
            SELECT timestamp, expiry_flag, expiry_code, strike_label, strike_price, option_type,
                   open, high, low, close, volume, oi, iv
            FROM expired_options_ohlcv
            WHERE underlying_scrip = ?
            ORDER BY timestamp
        """
        cur = con.execute(sql, [underlying])

    inserted = seen = skipped = 0
    buf = []
    while True:
        rows = cur.fetchmany(BATCH)
        if not rows:
            break
        for (ts, flag, code, label, strike, ot, o, h, lo, c, vol, oi, iv) in rows:
            seen += 1
            if c is None or strike is None:
                skipped += 1
                continue
            exp = cal.resolve_expiry(ts.date(), flag, int(code))
            if exp is None:
                skipped += 1
                continue
            buf.append(build_option_bar_doc(
                underlying=underlying, expiry_date=exp, strike=float(strike), option_type=ot,
                timeframe="1m", ts=_ist_to_utc(ts),
                open=o, high=h, low=lo, close=c, volume=vol, oi=oi, iv=iv,
                expiry_flag=flag, strike_label=label,
                trading_symbol=symbol_for(underlying, exp, float(strike), ot),
                source="abi",
            ))
        if len(buf) >= BATCH:
            inserted += upsert_option_bars_sync(col, buf)
            buf.clear()
            log.info("options_progress", underlying=underlying, seen=seen, inserted=inserted, skipped=skipped)
    if buf:
        inserted += upsert_option_bars_sync(col, buf)

    log.info("options_migrate_done", underlying=underlying, seen=seen, inserted=inserted, skipped=skipped)


def migrate_all(dry_run: bool):
    import duckdb
    from pymongo import MongoClient

    s = get_settings()
    mdb = MongoClient(s.MONGO_URI)[s.MONGO_DB_NAME]

    for underlying, cfg in CONFIGS.items():
        db_path = cfg["db"]
        if not os.path.exists(db_path):
            log.error("db_not_found", path=db_path)
            continue

        log.info("migrating", underlying=underlying)

        if dry_run:
            con = duckdb.connect(db_path, read_only=True)
            n_spot = con.execute("SELECT COUNT(*) FROM spot_1m").fetchone()[0]
            n_options = con.execute(
                "SELECT COUNT(*) FROM expired_options_ohlcv WHERE underlying_scrip = ?", [underlying]
            ).fetchone()[0]
            # Check what's already in Mongo
            mongo_client = MongoClient(s.MONGO_URI)
            db = mongo_client[s.MONGO_DB_NAME]
            m_spot = db["market_bars"].count_documents({"metadata.security_id": cfg["sid"], "metadata.timeframe": "1m"})
            m_opts = db["option_bars"].count_documents({"underlying": underlying})
            latest_opt = db["option_bars"].find_one({"underlying": underlying}, sort=[("ts", -1)], projection={"ts": 1, "_id": 0})
            log.info("dry_run", underlying=underlying,
                     duckdb_spot=n_spot, mongo_spot=m_spot,
                     duckdb_options=n_options, mongo_options=m_opts,
                     mongo_options_latest=str(latest_opt["ts"]) if latest_opt else None)
            con.close()
            continue

        con = duckdb.connect(db_path, read_only=True)
        migrate_spot(con, mdb, underlying, cfg["sid"])
        migrate_options(con, mdb, s, underlying, cfg["expiry_path"])
        con.close()


def main():
    ap = argparse.ArgumentParser(description="Migrate BANKNIFTY/SENSEX duckdb -> mongo (idempotent).")
    ap.add_argument("--dry-run", action="store_true", help="Report row counts and cutoffs; write nothing.")
    a = ap.parse_args()
    migrate_all(a.dry_run)

if __name__ == "__main__":
    main()
