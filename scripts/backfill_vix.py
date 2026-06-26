"""Dhan backfill for India VIX 1-minute bars into `market_bars`.

The directional-strangle strategy gates entries on India VIX (no >5% intraday spike, not at the
day high, not rising over the last 3 5m candles). VIX is not stored locally, so this script
fetches India VIX 1m bars from Dhan (`intraday_minute_data(security_id=<vix>, IDX_I, INDEX)`) over
a configurable range and upserts them into `market_bars` under a dedicated `security_id` (default
"21", the India VIX index id on Dhan; override with --vix-sid or resolve from the scrip master).

It mirrors `backfill_spot.py`: epoch seconds -> UTC-naive `ts` (09:15 IST == 03:45 UTC),
Data-API throttling with DH-904 backoff, and idempotent delete-then-insert per trade day.

Usage:
  python scripts/backfill_vix.py --from 2021-06-01 --to 2026-05-31 --only-missing
  python scripts/backfill_vix.py --from 2026-06-01 --resolve          # resolve VIX id from master
  python scripts/backfill_vix.py --from 2026-06-01 --dry-run
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

from pdp.options.gap_backfill import holidays, trading_days
from pdp.settings import get_settings

load_dotenv()
log = structlog.get_logger()

DEFAULT_VIX_SID = os.getenv("VIX_SECURITY_ID", "21")  # India VIX on Dhan IDX_I
EXCHANGE_SEGMENT = "IDX_I"
INSTRUMENT_TYPE = "INDEX"
TIMEFRAME = "1m"
INTERVAL = 1

CHUNK_DAYS = 90
EXPECTED_BARS = 375
MISSING_FRAC = 0.95
DATA_API_QPS = 5
_MIN_GAP_S = 1.0 / DATA_API_QPS
RATE_LIMIT_BACKOFF_S = 2.0
MAX_RETRIES = 4


def _resolve_vix_sid(dhan: Any) -> str | None:
    """Find the India VIX security id from the Dhan scrip master (IDX_I)."""
    try:
        master = dhan.fetch_security_list("compact")
    except Exception as exc:
        log.warning("vix_master_fetch_failed", err=str(exc))
        return None
    rows = master.itertuples() if hasattr(master, "itertuples") else master
    for r in rows:
        sym = str(getattr(r, "SEM_TRADING_SYMBOL", getattr(r, "symbol", ""))).upper()
        if "VIX" in sym:
            sid = getattr(r, "SEM_SMST_SECURITY_ID", getattr(r, "security_id", None))
            if sid is not None:
                log.info("vix_resolved", symbol=sym, security_id=str(sid))
                return str(int(sid))
    return None


def _chunks(days: list[date], size: int) -> list[tuple[date, date]]:
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


def _fetch_chunk(dhan: Any, sid: str, from_d: date, to_d: date) -> list[dict[str, Any]]:
    """Fetch India VIX 1m bars for [from_d, to_d]; return docs ready to upsert."""
    last_call = 0.0
    for attempt in range(1, MAX_RETRIES + 1):
        elapsed = time.monotonic() - last_call
        if elapsed < _MIN_GAP_S:
            time.sleep(_MIN_GAP_S - elapsed)
        last_call = time.monotonic()

        raw: object = dhan.intraday_minute_data(
            security_id=sid,
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
                log.warning("rate_limited", attempt=attempt, wait_s=wait, window=f"{from_d}..{to_d}")
                time.sleep(wait)
                continue
            log.warning("fetch_failure", resp=str(resp)[:200], window=f"{from_d}..{to_d}")
            return []

        data: dict[str, Any] = resp.get("data", resp)
        opens: list[Any] = data.get("open", [])
        highs: list[Any] = data.get("high", [])
        lows: list[Any] = data.get("low", [])
        closes: list[Any] = data.get("close", [])
        timestamps: list[Any] = data.get("timestamp", data.get("start_Time", []))

        docs: list[dict[str, Any]] = []
        for i in range(len(closes)):
            ts_raw = timestamps[i] if i < len(timestamps) else None
            if ts_raw is None:
                continue
            ts = datetime.fromtimestamp(float(ts_raw), tz=UTC).replace(tzinfo=None)
            docs.append({
                "ts": ts,
                "metadata": {"security_id": sid, "timeframe": TIMEFRAME},
                "open": float(opens[i]) if i < len(opens) else float(closes[i]),
                "high": float(highs[i]) if i < len(highs) else float(closes[i]),
                "low": float(lows[i]) if i < len(lows) else float(closes[i]),
                "close": float(closes[i]),
                "volume": 0,
                "oi": 0,
            })
        docs.sort(key=lambda d: d["ts"])
        return docs

    log.error("fetch_giving_up", window=f"{from_d}..{to_d}")
    return []


def _existing_count(col: Any, sid: str, day: date) -> int:
    lo = datetime(day.year, day.month, day.day, 3, 45)
    hi = datetime(day.year, day.month, day.day, 10, 1)
    return col.count_documents({
        "metadata.security_id": sid, "metadata.timeframe": TIMEFRAME,
        "ts": {"$gte": lo, "$lte": hi},
    })


def _day_bounds(day: date) -> tuple[datetime, datetime]:
    lo = datetime(day.year, day.month, day.day) - timedelta(hours=5, minutes=30)
    return lo, lo + timedelta(days=1)


def _write_day(col: Any, sid: str, day: date, docs: list[dict[str, Any]]) -> int:
    if not docs:
        return 0
    lo, hi = _day_bounds(day)
    col.delete_many({
        "metadata.security_id": sid, "metadata.timeframe": TIMEFRAME,
        "ts": {"$gte": lo, "$lt": hi},
    })
    col.insert_many(docs, ordered=False)
    return len(docs)


def main() -> int:
    ap = argparse.ArgumentParser(description="Dhan backfill for India VIX 1m bars.")
    ap.add_argument("--from", dest="date_from", required=True)
    ap.add_argument("--to", dest="date_to", default=date.today().isoformat())
    ap.add_argument("--vix-sid", default=DEFAULT_VIX_SID, help="India VIX security id (default 21)")
    ap.add_argument("--resolve", action="store_true", help="Resolve VIX id from the Dhan scrip master")
    ap.add_argument("--only-missing", action="store_true",
                    help="Skip trade days already at >= 95%% of expected bar count.")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print the planned trade-day range; no Dhan calls or writes.")
    a = ap.parse_args()

    s = get_settings()
    days = trading_days(
        date.fromisoformat(a.date_from),
        date.fromisoformat(a.date_to),
        holidays(s.NSE_HOLIDAYS_JSON),
    )

    if a.dry_run:
        log.info("dry_run", trading_days=len(days), vix_sid=a.vix_sid,
                 first=str(days[0]) if days else None, last=str(days[-1]) if days else None,
                 chunks=len(_chunks(days, CHUNK_DAYS)))
        return 0

    from dhanhq import DhanContext, dhanhq
    from pymongo import MongoClient

    dhan = dhanhq(DhanContext(s.DHAN_CLIENT_ID, s.DHAN_ACCESS_TOKEN))
    sid = a.vix_sid
    if a.resolve:
        resolved = _resolve_vix_sid(dhan)
        if resolved:
            sid = resolved
        else:
            log.warning("vix_resolve_failed_using_default", sid=sid)
    col = MongoClient(s.MONGO_URI)[s.MONGO_DB_NAME]["market_bars"]

    target_days = days
    if a.only_missing:
        threshold = int(EXPECTED_BARS * MISSING_FRAC)
        target_days = [d for d in days if _existing_count(col, sid, d) < threshold]
        log.info("only_missing_filter", total=len(days), to_fill=len(target_days), threshold=threshold)

    if not target_days:
        log.info("nothing_to_backfill")
        return 0

    target_set = set(target_days)
    total_written = 0
    for from_d, to_d in _chunks(target_days, CHUNK_DAYS):
        docs = _fetch_chunk(dhan, sid, from_d, to_d)
        by_day: dict[date, list[dict[str, Any]]] = {}
        for d in docs:
            day = (d["ts"] + timedelta(hours=5, minutes=30)).date()
            if day in target_set:
                by_day.setdefault(day, []).append(d)
        for day, day_docs in sorted(by_day.items()):
            written = _write_day(col, sid, day, day_docs)
            total_written += written
            log.info("day_done", day=str(day), bars=written)

    log.info("vix_backfill_summary", vix_sid=sid, days=len(target_days), rows_written=total_written)
    return 0


if __name__ == "__main__":
    sys.exit(main())
