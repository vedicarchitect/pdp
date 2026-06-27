"""Dhan backfill for index 1-minute spot into `market_bars` (NIFTY, BANKNIFTY, SENSEX).

Dhan holds the full history. This script fetches index 1m bars
(`intraday_minute_data(security_id, IDX_I, INDEX, interval=1)`) over a configurable
range, converts epoch seconds → **UTC-naive** `datetime` (matching the existing schema, where
09:15 IST is stored as `ts=03:45 UTC`), and **upserts** keyed on
`(ts, metadata.security_id, metadata.timeframe)` so already-complete days are never duplicated.

Run this BEFORE `scripts/backfill_options_gap.py` — option strike derivation reads the index
1m close at the same minute, so spot must be complete first.

Usage:
  python scripts/backfill_spot.py --dry-run
  python scripts/backfill_spot.py --from 2026-06-04 --to 2026-06-12
  python scripts/backfill_spot.py --from 2026-06-04 --only-missing
  python scripts/backfill_spot.py --symbol BANKNIFTY --from 2021-06-01 --only-missing
  python scripts/backfill_spot.py --symbol SENSEX    --from 2021-06-01 --only-missing
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import UTC, date, datetime, timedelta
from typing import Any, cast

import structlog
from dotenv import load_dotenv

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from pdp.options.gap_backfill import holidays, trading_days  # noqa: E402
from pdp.settings import get_settings  # noqa: E402

load_dotenv()
log = structlog.get_logger()

SYMBOL_MAP: dict[str, str] = {
    "NIFTY":     "13",
    "BANKNIFTY": "25",
    "SENSEX":    "51",
}
EXCHANGE_SEGMENT = "IDX_I"
INSTRUMENT_TYPE = "INDEX"
TIMEFRAME = "1m"
INTERVAL = 1

CHUNK_DAYS = 90             # ≤ 90 calendar days per Dhan call
EXPECTED_BARS = 375        # full 09:15–15:30 session
MISSING_FRAC = 0.95        # --only-missing: skip days already at ≥ 95% of expected
DATA_API_QPS = 5           # Data API rate limit: 5 req/sec
_MIN_GAP_S = 1.0 / DATA_API_QPS
RATE_LIMIT_BACKOFF_S = 2.0  # backoff on DH-904
MAX_RETRIES = 4


def _chunks(days: list[date], size: int) -> list[tuple[date, date]]:
    """Group sorted trade days into ≤ `size`-calendar-day [from, to] windows."""
    out: list[tuple[date, date]] = []
    i = 0
    while i < len(days):
        start = days[i]
        j = i
        while j + 1 < len(days) and (days[j + 1] - start).days < size:
            j += 1
        out.append((start, days[j]))
        i = j + 1
    return out


def _fetch_chunk(dhan: Any, from_d: date, to_d: date, security_id: str) -> list[dict[str, Any]]:
    """Fetch index 1m bars for [from_d, to_d]; return docs ready to upsert.

    Throttles to the Data-API limit and retries with backoff on DH-904 rate-limit.
    Dhan's `to_date` is exclusive on the day boundary, so pass to_d + 1.
    """
    last_call = 0.0
    for attempt in range(1, MAX_RETRIES + 1):
        elapsed = time.monotonic() - last_call
        if elapsed < _MIN_GAP_S:
            time.sleep(_MIN_GAP_S - elapsed)
        last_call = time.monotonic()

        raw: object = dhan.intraday_minute_data(
            security_id=security_id,
            exchange_segment=EXCHANGE_SEGMENT,
            instrument_type=INSTRUMENT_TYPE,
            from_date=from_d.isoformat(),
            to_date=(to_d + timedelta(days=1)).isoformat(),
            interval=INTERVAL,
        )

        if not isinstance(raw, dict):
            log.warning("fetch_bad_response", resp=str(raw)[:200])
            return []
        resp = cast("dict[str, Any]", raw)

        if resp.get("status") == "failure":
            blob = str(resp).upper()
            if "DH-904" in blob or "RATE" in blob:
                wait = RATE_LIMIT_BACKOFF_S * attempt
                log.warning("rate_limited", attempt=attempt, wait_s=wait,
                            window=f"{from_d}..{to_d}")
                time.sleep(wait)
                continue
            log.warning("fetch_failure", resp=str(resp)[:200], window=f"{from_d}..{to_d}")
            return []

        data: dict[str, Any] = resp.get("data", resp)
        opens: list[Any] = data.get("open", [])
        highs: list[Any] = data.get("high", [])
        lows: list[Any] = data.get("low", [])
        closes: list[Any] = data.get("close", [])
        volumes: list[Any] = data.get("volume", [])
        timestamps: list[Any] = data.get("timestamp", data.get("start_Time", []))

        docs: list[dict[str, Any]] = []
        for i in range(len(closes)):
            ts_raw = timestamps[i] if i < len(timestamps) else None
            if ts_raw is None:
                continue
            # Epoch seconds → UTC-naive to match the market_bars schema.
            ts = datetime.fromtimestamp(float(ts_raw), tz=UTC).replace(tzinfo=None)
            docs.append({
                "ts": ts,
                "metadata": {"security_id": security_id, "timeframe": TIMEFRAME},
                "open": float(opens[i]) if i < len(opens) else float(closes[i]),
                "high": float(highs[i]) if i < len(highs) else float(closes[i]),
                "low": float(lows[i]) if i < len(lows) else float(closes[i]),
                "close": float(closes[i]),
                "volume": int(volumes[i]) if i < len(volumes) else 0,
                "oi": 0,
            })
        docs.sort(key=lambda d: d["ts"])
        return docs

    log.error("fetch_giving_up", window=f"{from_d}..{to_d}")
    return []


def _existing_count(col: Any, day: date, security_id: str) -> int:
    """Count 1m bars already stored for a trade day (UTC-naive window)."""
    # IST session 09:15–15:30 == UTC 03:45–10:00.
    lo = datetime(day.year, day.month, day.day, 3, 45)
    hi = datetime(day.year, day.month, day.day, 10, 1)
    return col.count_documents({
        "metadata.security_id": security_id,
        "metadata.timeframe": TIMEFRAME,
        "ts": {"$gte": lo, "$lte": hi},
    })


def _day_bounds(day: date) -> tuple[datetime, datetime]:
    """UTC-naive [start, end) covering a full IST trade day (00:00–23:59 IST)."""
    lo = datetime(day.year, day.month, day.day) - timedelta(hours=5, minutes=30)
    return lo, lo + timedelta(days=1)


def _write_day(col: Any, day: date, docs: list[dict[str, Any]], security_id: str) -> int:
    """Idempotent write for one trade day into the time-series `market_bars`.

    MongoDB time-series collections do not support upsert/non-multi update
    (error code 72), so idempotency is delete-the-day-then-insert: remove any
    existing bars in the day's window, then insert the fresh fetch.
    """
    if not docs:
        return 0
    lo, hi = _day_bounds(day)
    col.delete_many({
        "metadata.security_id": security_id,
        "metadata.timeframe": TIMEFRAME,
        "ts": {"$gte": lo, "$lt": hi},
    })
    col.insert_many(docs, ordered=False)
    return len(docs)


def main() -> int:
    ap = argparse.ArgumentParser(description="Dhan backfill for index 1m spot (NIFTY/BANKNIFTY/SENSEX).")
    ap.add_argument("--symbol", default="NIFTY", choices=list(SYMBOL_MAP),
                    help="Index to backfill (default: NIFTY).")
    ap.add_argument("--from", dest="date_from", required=True)
    ap.add_argument("--to", dest="date_to", default=date.today().isoformat())
    ap.add_argument("--only-missing", action="store_true",
                    help="Skip trade days already at ≥ 95%% of expected bar count.")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print the planned trade-day range; no Dhan calls or writes.")
    a = ap.parse_args()

    security_id = SYMBOL_MAP[a.symbol]
    s = get_settings()
    days = trading_days(
        date.fromisoformat(a.date_from),
        date.fromisoformat(a.date_to),
        holidays(s.NSE_HOLIDAYS_JSON),
    )

    if a.dry_run:
        log.info("dry_run", symbol=a.symbol, security_id=security_id,
                 trading_days=len(days),
                 first=str(days[0]) if days else None,
                 last=str(days[-1]) if days else None,
                 chunks=len(_chunks(days, CHUNK_DAYS)))
        return 0

    from dhanhq import DhanContext, dhanhq
    from pymongo import MongoClient

    dhan = dhanhq(DhanContext(s.DHAN_CLIENT_ID, s.DHAN_ACCESS_TOKEN))
    col = MongoClient(s.MONGO_URI)[s.MONGO_DB_NAME]["market_bars"]

    target_days = days
    if a.only_missing:
        threshold = int(EXPECTED_BARS * MISSING_FRAC)
        target_days = [d for d in days if _existing_count(col, d, security_id) < threshold]
        log.info("only_missing_filter", symbol=a.symbol, total=len(days),
                 to_fill=len(target_days), threshold=threshold)

    if not target_days:
        log.info("nothing_to_backfill", symbol=a.symbol)
        return 0

    log.info("backfill_start", symbol=a.symbol, security_id=security_id,
             days=len(target_days))
    target_set = set(target_days)
    total_written = 0
    for from_d, to_d in _chunks(target_days, CHUNK_DAYS):
        docs = _fetch_chunk(dhan, from_d, to_d, security_id)
        # Group fetched bars by IST trade day; write each day idempotently.
        by_day: dict[date, list[dict[str, Any]]] = {}
        for d in docs:
            ist = d["ts"] + timedelta(hours=5, minutes=30)
            day = ist.date()
            if day in target_set:
                by_day.setdefault(day, []).append(d)
        for day, day_docs in sorted(by_day.items()):
            written = _write_day(col, day, day_docs, security_id)
            total_written += written
            log.info("day_done", symbol=a.symbol, day=str(day), bars=written)

    log.info("backfill_summary", symbol=a.symbol, days=len(target_days),
             rows_written=total_written)
    return 0


if __name__ == "__main__":
    sys.exit(main())
