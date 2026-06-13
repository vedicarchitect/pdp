"""
DEPRECATED — writes to the ``expired_option_bars`` ATM-label collection which is
no longer read by the backtest.  Use ``scripts/backfill_options_gap.py`` instead,
which backfills fixed-strike bars into the ``option_bars`` warehouse.

This script is retained for historical reference only.  Do NOT run it to populate
new data; the ``expired_option_bars`` collection receives no new writes as part of
the backtest pipeline.

----

Backfill expired-option OHLCV bars into MongoDB (`expired_option_bars`).

Dhan drops expired weekly contracts from the security master, so their
security_ids vanish. This warehouses the ATM-relative rolling series from
Dhan's `expired_options_data` (/v2/charts/rollingoption) so the backtest can
read bars from Mongo instead of hitting the rate-limited data API live.

Stored docs (one per 5-min bar) match the time-series collection created by
`pdp.mongo.collections._ensure_expired_option_bars`:

    {ts, metadata:{underlying, expiry_flag, expiry_code, strike_label,
                   option_type, timeframe}, open, high, low, close, volume, oi, iv}

Usage:
  python scripts/backfill_expired_options.py                 # last 12 months
  python scripts/backfill_expired_options.py --months 1      # smoke test
  python scripts/backfill_expired_options.py --strikes ATM-1,ATM,ATM+1 --codes 1
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import UTC, date, datetime, timedelta

import structlog
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()

log = structlog.get_logger()

UNDERLYING_SID = 13  # NIFTY 50
TIMEFRAME = "5m"
CHUNK_DAYS = 30  # Dhan rolling-option API: max 30 days per call
API_PAUSE = 0.25  # stay under the 5 req/sec data-API limit


def _client_and_db() -> tuple:
    from dhanhq import DhanContext, dhanhq

    mdb = MongoClient(os.environ.get("MONGO_URI", "mongodb://localhost:27017"))[
        os.environ.get("MONGO_DB_NAME", "pdp")
    ]
    dhan = dhanhq(DhanContext(os.environ["DHAN_CLIENT_ID"], os.environ["DHAN_ACCESS_TOKEN"]))
    return dhan, mdb


def _ensure_collection(db) -> None:
    """Create the time-series collection if missing (matches pdp.mongo.collections)."""
    if "expired_option_bars" in db.list_collection_names():
        return
    db.create_collection(
        "expired_option_bars",
        timeseries={"timeField": "ts", "metaField": "metadata", "granularity": "seconds"},
    )
    log.info("collection_created", collection="expired_option_bars")


def _date_chunks(start: date, end: date, span: int):
    cur = start
    while cur <= end:
        chunk_end = min(cur + timedelta(days=span - 1), end)
        yield cur, chunk_end
        cur = chunk_end + timedelta(days=1)


def _extract_side(resp: dict, opt_type: str) -> dict | None:
    """Drill into the (possibly double-wrapped) rolling-option payload."""
    if not (isinstance(resp, dict) and resp.get("status") == "success"):
        return None
    data_key = "ce" if opt_type == "CE" else "pe"
    data = resp.get("data", {})
    # Unwrap nested {"data": {...}} wrapper(s) until we reach the ce/pe level.
    while (isinstance(data, dict) and "data" in data
           and "ce" not in data and "pe" not in data and "open" not in data):
        data = data["data"]
    if isinstance(data, dict) and data_key in data:
        data = data[data_key]
    if isinstance(data, dict) and "data" in data and "open" not in data:
        data = data["data"]
    if not (isinstance(data, dict) and "open" in data):
        return None
    return data


def _parse_bars(data: dict) -> list[dict]:
    """Rolling-option arrays -> list of partial docs (UTC ts, OHLCV, oi, iv)."""
    opens = data["open"]
    highs = data["high"]
    lows = data["low"]
    closes = data["close"]
    vols = data.get("volume", [])
    ois = data.get("oi", [])
    ivs = data.get("iv", [])
    tss = data.get("timestamp", data.get("start_Time", []))
    out: list[dict] = []
    for i in range(len(closes)):
        if not closes[i]:
            continue
        ts = tss[i] if i < len(tss) else None
        if ts is None:
            continue
        if isinstance(ts, (int, float)):
            bar_ts = datetime.fromtimestamp(ts, tz=UTC)
        else:
            try:
                bar_ts = datetime.fromisoformat(str(ts))
                if bar_ts.tzinfo is None:
                    bar_ts = bar_ts.replace(tzinfo=UTC)
                else:
                    bar_ts = bar_ts.astimezone(UTC)
            except ValueError:
                continue
        out.append(
            {
                "ts": bar_ts,
                "open": float(opens[i]),
                "high": float(highs[i]),
                "low": float(lows[i]),
                "close": float(closes[i]),
                "volume": int(vols[i]) if i < len(vols) and vols[i] is not None else 0,
                "oi": int(ois[i]) if i < len(ois) and ois[i] is not None else 0,
                "iv": float(ivs[i]) if i < len(ivs) and ivs[i] is not None else 0.0,
            }
        )
    out.sort(key=lambda d: d["ts"])
    return out


def _existing_ts(col, meta: dict, lo: datetime, hi: datetime) -> set:
    """Timestamps already stored for this rolling series (idempotent backfill)."""
    q = {f"metadata.{k}": v for k, v in meta.items()}
    q["ts"] = {"$gte": lo, "$lte": hi}
    # pymongo returns naive UTC datetimes; normalise to aware UTC so the set
    # membership check matches the aware ts on freshly parsed bars.
    return {
        (d["ts"] if d["ts"].tzinfo else d["ts"].replace(tzinfo=UTC))
        for d in col.find(q, {"ts": 1, "_id": 0})
    }


def backfill(
    dhan,
    col,
    flag: str,
    code: int,
    strike_label: str,
    opt_type: str,
    start: date,
    end: date,
    interval: int,
) -> int:
    drv = "CALL" if opt_type == "CE" else "PUT"
    meta = {
        "underlying": "NIFTY",
        "expiry_flag": flag,
        "expiry_code": code,
        "strike_label": strike_label,
        "option_type": opt_type,
        "timeframe": TIMEFRAME,
    }
    inserted = 0
    for chunk_start, chunk_end in _date_chunks(start, end, CHUNK_DAYS):
        try:
            resp = dhan.expired_options_data(
                security_id=UNDERLYING_SID,
                exchange_segment="NSE_FNO",
                instrument_type="OPTIDX",
                expiry_flag=flag,
                expiry_code=code,
                strike=strike_label,
                drv_option_type=drv,
                required_data=["open", "high", "low", "close", "volume", "oi", "iv"],
                from_date=chunk_start.isoformat(),
                to_date=chunk_end.isoformat(),
                interval=interval,
            )
            time.sleep(API_PAUSE)
        except Exception as exc:  # noqa: BLE001 - network/SDK errors, keep going
            log.warning("backfill_api_error", strike=strike_label, opt=opt_type,
                        chunk=f"{chunk_start}..{chunk_end}", exc=str(exc))
            continue

        data = _extract_side(resp, opt_type)
        if data is None:
            log.debug("backfill_empty", strike=strike_label, opt=opt_type,
                      chunk=f"{chunk_start}..{chunk_end}")
            continue

        bars = _parse_bars(data)
        if not bars:
            continue

        lo, hi = bars[0]["ts"], bars[-1]["ts"]
        have = _existing_ts(col, meta, lo, hi)
        docs = [{**b, "metadata": dict(meta)} for b in bars if b["ts"] not in have]
        if docs:
            col.insert_many(docs, ordered=False)
            inserted += len(docs)
        log.info("backfill_chunk", strike=strike_label, opt=opt_type,
                 chunk=f"{chunk_start}..{chunk_end}", fetched=len(bars), inserted=len(docs))
    return inserted


def main() -> int:
    ap = argparse.ArgumentParser(description="Backfill expired-option bars into MongoDB.")
    ap.add_argument("--months", type=int, default=12, help="Lookback window in months (approx).")
    ap.add_argument("--end", type=str, default=None, help="End date YYYY-MM-DD (default: today).")
    ap.add_argument("--flag", type=str, default="WEEK", help="Expiry flag: WEEK or MONTH.")
    ap.add_argument("--codes", type=str, default="1", help="Comma list of expiry_code values.")
    ap.add_argument("--strikes", type=str, default="ATM-1,ATM,ATM+1",
                    help="Comma list of ATM-relative strike labels.")
    ap.add_argument("--types", type=str, default="CE,PE", help="Comma list: CE,PE.")
    ap.add_argument("--interval", type=int, default=5, help="Bar interval minutes.")
    a = ap.parse_args()

    end = date.fromisoformat(a.end) if a.end else datetime.now(UTC).date()
    start = end - timedelta(days=int(a.months * 30.5))
    codes = [int(c) for c in a.codes.split(",") if c.strip()]
    strikes = [s.strip() for s in a.strikes.split(",") if s.strip()]
    types = [t.strip().upper() for t in a.types.split(",") if t.strip()]

    dhan, mdb = _client_and_db()
    _ensure_collection(mdb)
    col = mdb["expired_option_bars"]

    log.info("backfill_start", flag=a.flag, codes=codes, strikes=strikes, types=types,
             start=start.isoformat(), end=end.isoformat(), interval=a.interval)

    total = 0
    for code in codes:
        for strike_label in strikes:
            for opt_type in types:
                total += backfill(dhan, col, a.flag, code, strike_label, opt_type,
                                  start, end, a.interval)

    log.info("backfill_done", total_inserted=total)
    return 0


if __name__ == "__main__":
    sys.exit(main())
