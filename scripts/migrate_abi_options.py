"""Migrate NIFTY expired-option bars from the abi-project DuckDB into the `option_bars` warehouse.

Source (read-only, never mutated): `expired_options_ohlcv` in the abi `nifty.db`
(`settings.ABI_NIFTY_DUCKDB`). Each 1-minute bar carries the real `strike_price`, so we key it by
the true fixed contract `(underlying, expiry_date, strike, option_type, timeframe, ts)` — resolving
`expiry_date` from the OI-reset expiry calendar and `trading_symbol` from the symbol resolver — and
upsert it into `option_bars` with `source=abi`. The unique index makes re-runs idempotent.

Scope (matches the data pipeline decisions): NIFTY, WEEK, expiry codes 1 & 2 (current + next week),
strike band ATM±10, CE+PE, 1-minute. `--include-monthly` adds the MONTH flag.

Usage:
  python scripts/migrate_abi_options.py --dry-run               # report planned counts, write nothing
  python scripts/migrate_abi_options.py --from 2026-04-01 --to 2026-05-01   # one month
  python scripts/migrate_abi_options.py                         # full scoped history
  python scripts/migrate_abi_options.py --codes 1 --band 5 --include-monthly
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import UTC, date, datetime, timedelta

import structlog
from dotenv import load_dotenv

# Defensive: allow running as a plain script from any cwd.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from pdp.instruments.expiry_calendar import NiftyExpiryCalendar  # noqa: E402
from pdp.instruments.symbols import symbol_for  # noqa: E402
from pdp.options.warehouse import (  # noqa: E402
    build_option_bar_doc,
    ensure_option_bars_indexes_sync,
    upsert_option_bars_sync,
)
from pdp.settings import get_settings  # noqa: E402

load_dotenv()
log = structlog.get_logger()

UNDERLYING = "NIFTY"
TIMEFRAME = "1m"
IST = timedelta(hours=5, minutes=30)  # abi DuckDB timestamps are IST-naive
BATCH = 5000


def _strike_labels(band: int) -> list[str]:
    """ATM, ATM±1 .. ATM±band — the warehoused strike ladder."""
    labels = ["ATM"]
    for i in range(1, band + 1):
        labels.append(f"ATM+{i}")
        labels.append(f"ATM-{i}")
    return labels


def _ist_to_utc(ts: datetime) -> datetime:
    """abi timestamps are IST wall-clock without tzinfo → convert to aware UTC."""
    return (ts - IST).replace(tzinfo=UTC)


def _connect():
    import duckdb
    from pymongo import MongoClient

    s = get_settings()
    con = duckdb.connect(s.ABI_NIFTY_DUCKDB, read_only=True)
    mdb = MongoClient(s.MONGO_URI)[s.MONGO_DB_NAME]
    return con, mdb, s


def _scoped_sql(flags: list[str], codes: list[int], labels: list[str],
                date_from: date | None, date_to: date | None) -> tuple[str, list]:
    params: list = [UNDERLYING]
    sql = [
        "SELECT timestamp, expiry_flag, expiry_code, strike_label, strike_price, option_type,",
        "       open, high, low, close, volume, oi, iv",
        "FROM expired_options_ohlcv",
        "WHERE underlying_scrip = ?",
    ]
    sql.append(f"AND expiry_flag IN ({','.join('?' * len(flags))})"); params += flags
    sql.append(f"AND expiry_code IN ({','.join('?' * len(codes))})"); params += codes
    sql.append(f"AND strike_label IN ({','.join('?' * len(labels))})"); params += labels
    if date_from:
        sql.append("AND timestamp >= ?"); params.append(datetime(date_from.year, date_from.month, date_from.day))
    if date_to:
        sql.append("AND timestamp < ?"); params.append(datetime(date_to.year, date_to.month, date_to.day))
    sql.append("ORDER BY timestamp")
    return "\n".join(sql), params


def migrate(*, flags: list[str], codes: list[int], band: int,
            date_from: date | None, date_to: date | None, dry_run: bool) -> int:
    con, mdb, s = _connect()
    labels = _strike_labels(band)
    sql, params = _scoped_sql(flags, codes, labels, date_from, date_to)

    if dry_run:
        count_sql = "SELECT COUNT(*) FROM (" + sql.replace(
            "SELECT timestamp, expiry_flag, expiry_code, strike_label, strike_price, option_type,\n"
            "       open, high, low, close, volume, oi, iv", "SELECT 1", 1) + ")"
        total = con.execute(count_sql, params).fetchone()[0]
        log.info("dry_run", scoped_rows=total, flags=flags, codes=codes, band=band,
                 date_from=str(date_from), date_to=str(date_to))
        con.close()
        return 0

    cal = NiftyExpiryCalendar.load(s.EXPIRY_CACHE_PATH)
    col = mdb["option_bars"]
    ensure_option_bars_indexes_sync(col)

    cur = con.execute(sql, params)
    inserted = seen = skipped = 0
    buf: list[dict] = []
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
                underlying=UNDERLYING, expiry_date=exp, strike=float(strike), option_type=ot,
                timeframe=TIMEFRAME, ts=_ist_to_utc(ts),
                open=o, high=h, low=lo, close=c, volume=vol, oi=oi, iv=iv,
                expiry_flag=flag, strike_label=label,
                trading_symbol=symbol_for(UNDERLYING, exp, float(strike), ot),
                source="abi",
            ))
        if len(buf) >= BATCH:
            inserted += upsert_option_bars_sync(col, buf)
            buf.clear()
            log.info("progress", seen=seen, inserted=inserted, skipped=skipped)
    if buf:
        inserted += upsert_option_bars_sync(col, buf)

    con.close()
    log.info("migrate_done", seen=seen, inserted=inserted, skipped=skipped)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Migrate abi DuckDB NIFTY options → option_bars.")
    ap.add_argument("--codes", default="1,2", help="Comma list of expiry_code values (default 1,2).")
    ap.add_argument("--band", type=int, default=None, help="Strike band ATM±N (default: settings).")
    ap.add_argument("--include-monthly", action="store_true", help="Also migrate MONTH expiries.")
    ap.add_argument("--from", dest="date_from", default=None, help="Start date YYYY-MM-DD (inclusive).")
    ap.add_argument("--to", dest="date_to", default=None, help="End date YYYY-MM-DD (exclusive).")
    ap.add_argument("--dry-run", action="store_true", help="Report planned counts; write nothing.")
    a = ap.parse_args()

    band = a.band if a.band is not None else get_settings().WAREHOUSE_STRIKE_BAND
    flags = ["WEEK"] + (["MONTH"] if a.include_monthly else [])
    codes = [int(x) for x in a.codes.split(",") if x.strip()]
    df = date.fromisoformat(a.date_from) if a.date_from else None
    dt = date.fromisoformat(a.date_to) if a.date_to else None
    return migrate(flags=flags, codes=codes, band=band, date_from=df, date_to=dt, dry_run=a.dry_run)


if __name__ == "__main__":
    sys.exit(main())
