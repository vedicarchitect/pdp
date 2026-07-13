"""One-off probe: what does Dhan actually return for the current, in-progress trading session?

Context (`dhan-same-day-data` task 1.1-1.4): `warmup.py::_fetch_from_dhan` sets `to_date = today`,
so warmup's Dhan fallback *asks* for today's candles whenever it needs to top up `market_bars` on
an intraday restart. What Dhan actually serves for an in-progress session - completed candles only,
nothing at all, or a still-forming final candle - is undocumented and unverified anywhere in this
repo. This script calls `intraday_minute_data` (5m) and `historical_daily_data` (1D) for NIFTY
(security_id "13", segment IDX_I) with `to_date = today` and records exactly what comes back:
every candle timestamp, and whether the final one looks complete (`bar_time + period <= now`).

Run it twice on the same trading day per the task:
  1. During market hours (~11:00 IST)
  2. After the close (~16:00 IST)
and diff the two JSON outputs (task 1.2) to determine which of the three answers holds (task 1.3):
  (a) today's completed candles are returned
  (b) nothing for today is returned
  (c) today's candles are returned *including* a still-forming final candle

Writes nothing to market_bars — this is read-only reconnaissance.

Usage:
    uv run python scripts/oneoff/probe_dhan_same_day.py
    uv run python scripts/oneoff/probe_dhan_same_day.py --out probe_1100.json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from pdp.market.bars import bar_is_complete
from pdp.settings import get_settings

_IST = ZoneInfo("Asia/Kolkata")
_NIFTY_SID = "13"
_SEGMENT = "IDX_I"
_INSTRUMENT = "INDEX"


def _extract_candles(resp: object) -> list[dict[str, Any]]:
    """Flatten a Dhan chart response into one dict per candle, timestamp-sorted."""
    if not isinstance(resp, dict) or resp.get("status") == "failure":
        return []
    data = resp.get("data", resp)
    opens = data.get("open", [])
    highs = data.get("high", [])
    lows = data.get("low", [])
    closes = data.get("close", [])
    volumes = data.get("volume", [])
    timestamps = data.get("start_Time", data.get("timestamp", []))

    candles: list[dict[str, Any]] = []
    for i in range(len(closes)):
        ts_raw = timestamps[i] if i < len(timestamps) else None
        if ts_raw is None:
            continue
        bar_time = (
            datetime.fromtimestamp(ts_raw, tz=UTC)
            if isinstance(ts_raw, (int, float))
            else datetime.fromisoformat(str(ts_raw)).replace(tzinfo=UTC)
        )
        candles.append(
            {
                "bar_time_utc": bar_time.isoformat(),
                "bar_time_ist": bar_time.astimezone(_IST).isoformat(),
                "open": opens[i] if i < len(opens) else None,
                "high": highs[i] if i < len(highs) else None,
                "low": lows[i] if i < len(lows) else None,
                "close": closes[i] if i < len(closes) else None,
                "volume": volumes[i] if i < len(volumes) else None,
            }
        )
    candles.sort(key=lambda c: c["bar_time_utc"])
    return candles


def probe(*, timeframe: str, interval: int | None, now: datetime) -> dict[str, Any]:
    from dhanhq import DhanContext, dhanhq

    settings = get_settings()
    if not settings.DHAN_CLIENT_ID or not settings.DHAN_ACCESS_TOKEN:
        return {"timeframe": timeframe, "error": "DHAN_CLIENT_ID/DHAN_ACCESS_TOKEN not configured"}

    today_ist = now.astimezone(_IST).date()
    from_date = (today_ist - timedelta(days=3)).strftime("%Y-%m-%d")
    to_date = today_ist.strftime("%Y-%m-%d")

    ctx = DhanContext(settings.DHAN_CLIENT_ID, settings.DHAN_ACCESS_TOKEN)
    client = dhanhq(ctx)

    if interval is None:
        resp = client.historical_daily_data(
            security_id=_NIFTY_SID,
            exchange_segment=_SEGMENT,
            instrument_type=_INSTRUMENT,
            from_date=from_date,
            to_date=to_date,
        )
    else:
        resp = client.intraday_minute_data(
            security_id=_NIFTY_SID,
            exchange_segment=_SEGMENT,
            instrument_type=_INSTRUMENT,
            from_date=from_date,
            to_date=to_date,
            interval=interval,
        )

    candles = _extract_candles(resp)
    todays_candles = [c for c in candles if c["bar_time_ist"][:10] == today_ist.isoformat()]

    final_complete = None
    if todays_candles:
        last = todays_candles[-1]
        last_bar_time = datetime.fromisoformat(last["bar_time_utc"])
        final_complete = bar_is_complete(last_bar_time, timeframe, now)

    return {
        "timeframe": timeframe,
        "requested_from": from_date,
        "requested_to": to_date,
        "probed_at_utc": now.isoformat(),
        "probed_at_ist": now.astimezone(_IST).isoformat(),
        "raw_status": resp.get("status") if isinstance(resp, dict) else "non-dict-response",
        "raw_remarks": resp.get("remarks") if isinstance(resp, dict) else None,
        "total_candles": len(candles),
        "todays_candle_count": len(todays_candles),
        "todays_candles": todays_candles,
        "final_candle_complete": final_complete,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=None, help="Write JSON result to this path in addition to stdout.")
    args = ap.parse_args()

    now = datetime.now(UTC)
    result = {
        "probed_at_utc": now.isoformat(),
        "probed_at_ist": now.astimezone(_IST).isoformat(),
        "intraday_5m": probe(timeframe="5m", interval=5, now=now),
        "daily_1D": probe(timeframe="1D", interval=None, now=now),
    }

    text = json.dumps(result, indent=2, default=str)
    print(text)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"\nWritten to {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
