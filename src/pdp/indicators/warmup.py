"""Indicator engine warmup: seed IndicatorEngine with historical bars on startup.

Priority:
  1. MongoDB market_bars collection (bars already stored from previous sessions).
  2. Dhan intraday_minute_data API (fetched when MongoDB has < MIN_BARS rows).
     Fetched bars are persisted to MongoDB so subsequent restarts use path 1.
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

import structlog

from pdp.market.bars import BarClosed

if TYPE_CHECKING:
    from motor.motor_asyncio import AsyncIOMotorDatabase

    from pdp.indicators.engine import IndicatorEngine
    from pdp.settings import Settings

log = structlog.get_logger()

# Warm up with this many bars minimum; fetch from API when MongoDB is short.
MIN_BARS = 10  # need period(3) + a few extra to stabilise bands
# How far back to look in MongoDB (one full trading day should be enough).
LOOKBACK_HOURS = 8

# Timeframe label → Dhan interval integer
_TF_TO_DHAN_INTERVAL: dict[str, int] = {
    "1m": 1,
    "5m": 5,
    "15m": 15,
    "25m": 25,
    "1H": 60,
}

# Segment string → Dhan instrument type string for the REST API
_SEGMENT_TO_INSTRUMENT: dict[str, str] = {
    "IDX_I": "INDEX",
    "NSE_EQ": "EQUITY",
    "NSE_FNO": "FUTIDX",  # used for options too
    "BSE_EQ": "EQUITY",
}


async def warm_up_indicator_engine(
    engine: IndicatorEngine,
    mongo_db: AsyncIOMotorDatabase,
    settings: Settings,
    watchlist: list[dict],  # [{security_id, exchange_segment, timeframes:[...]}]
) -> None:
    """Seed the IndicatorEngine from MongoDB or Dhan API for each watchlist entry."""
    for entry in watchlist:
        sid = str(entry["security_id"])
        segment = str(entry["exchange_segment"])
        for tf in entry.get("timeframes", []):
            try:
                await _warm_one(engine, mongo_db, settings, sid, segment, tf)
            except Exception as exc:
                log.warning(
                    "indicator_warmup_failed",
                    security_id=sid,
                    timeframe=tf,
                    exc=str(exc),
                )


async def _warm_one(
    engine: IndicatorEngine,
    mongo_db: AsyncIOMotorDatabase,
    settings: Settings,
    security_id: str,
    segment: str,
    timeframe: str,
) -> None:
    col = mongo_db["market_bars"]
    since = datetime.now(UTC) - timedelta(hours=LOOKBACK_HOURS)

    bars = await _fetch_from_mongo(col, security_id, timeframe, since)

    if len(bars) < MIN_BARS and settings.DHAN_CLIENT_ID and settings.DHAN_ACCESS_TOKEN:
        log.info(
            "indicator_warmup_fetching_from_api",
            security_id=security_id,
            timeframe=timeframe,
            mongo_count=len(bars),
        )
        api_bars = await asyncio.get_running_loop().run_in_executor(
            None, _fetch_from_dhan, settings, security_id, segment, timeframe
        )
        if api_bars:
            await _persist_bars(col, api_bars)
            # Merge: keep mongo bars as ground truth, prepend api bars not in mongo
            existing_times = {b.bar_time for b in bars}
            new_bars = [b for b in api_bars if b.bar_time not in existing_times]
            bars = sorted(new_bars + bars, key=lambda b: b.bar_time)

    if not bars:
        log.warning("indicator_warmup_no_bars", security_id=security_id, timeframe=timeframe)
        return

    fed = engine.seed_from_bars(bars)

    log.info(
        "indicator_warmup_done",
        security_id=security_id,
        timeframe=timeframe,
        bars_fed=fed,
        direction=engine.get(security_id, timeframe).direction if engine.get(security_id, timeframe) else None,
    )


async def _fetch_from_mongo(
    col,
    security_id: str,
    timeframe: str,
    since: datetime,
) -> list[BarClosed]:
    cursor = col.find(
        {
            "metadata.security_id": security_id,
            "metadata.timeframe": timeframe,
            "ts": {"$gte": since},
        },
        sort=[("ts", 1)],
    )
    bars: list[BarClosed] = []
    async for doc in cursor:
        try:
            bars.append(
                BarClosed(
                    security_id=security_id,
                    timeframe=timeframe,
                    bar_time=doc["ts"].replace(tzinfo=UTC) if doc["ts"].tzinfo is None else doc["ts"],
                    open=Decimal(str(doc["open"])),
                    high=Decimal(str(doc["high"])),
                    low=Decimal(str(doc["low"])),
                    close=Decimal(str(doc["close"])),
                    volume=int(doc.get("volume", 0)),
                    oi=int(doc.get("oi", 0)),
                )
            )
        except Exception:
            continue
    return bars


def _fetch_from_dhan(
    settings: Settings,
    security_id: str,
    segment: str,
    timeframe: str,
) -> list[BarClosed]:
    """Blocking — call via run_in_executor."""
    from dhanhq import dhanhq as DhanClient

    interval = _TF_TO_DHAN_INTERVAL.get(timeframe)
    if interval is None:
        log.warning("indicator_warmup_unsupported_tf", timeframe=timeframe)
        return []

    instrument = _SEGMENT_TO_INSTRUMENT.get(segment, "EQUITY")
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    yesterday = (datetime.now(UTC) - timedelta(days=1)).strftime("%Y-%m-%d")

    from dhanhq import DhanContext
    ctx = DhanContext(settings.DHAN_CLIENT_ID, settings.DHAN_ACCESS_TOKEN)
    client = DhanClient(ctx)
    resp = client.intraday_minute_data(
        security_id=security_id,
        exchange_segment=segment,
        instrument_type=instrument,
        from_date=yesterday,
        to_date=today,
        interval=interval,
    )

    if not isinstance(resp, dict) or resp.get("status") == "failure":
        log.warning("indicator_warmup_api_error", resp=str(resp)[:200])
        return []

    data = resp.get("data", resp)
    opens = data.get("open", [])
    highs = data.get("high", [])
    lows = data.get("low", [])
    closes = data.get("close", [])
    volumes = data.get("volume", [])
    timestamps = data.get("start_Time", data.get("timestamp", []))

    bars: list[BarClosed] = []
    for i in range(len(closes)):
        try:
            ts_raw = timestamps[i] if i < len(timestamps) else None
            if ts_raw is None:
                continue
            # Dhan returns epoch seconds (int) or ISO string
            if isinstance(ts_raw, (int, float)):
                bar_time = datetime.fromtimestamp(ts_raw, tz=UTC)
            else:
                bar_time = datetime.fromisoformat(str(ts_raw))
                if bar_time.tzinfo is None:
                    bar_time = bar_time.replace(tzinfo=UTC)
            bars.append(
                BarClosed(
                    security_id=security_id,
                    timeframe=timeframe,
                    bar_time=bar_time,
                    open=Decimal(str(opens[i])) if i < len(opens) else Decimal(str(closes[i])),
                    high=Decimal(str(highs[i])) if i < len(highs) else Decimal(str(closes[i])),
                    low=Decimal(str(lows[i])) if i < len(lows) else Decimal(str(closes[i])),
                    close=Decimal(str(closes[i])),
                    volume=int(volumes[i]) if i < len(volumes) else 0,
                    oi=0,
                )
            )
        except Exception:
            continue

    bars.sort(key=lambda b: b.bar_time)
    return bars


async def _persist_bars(col, bars: list[BarClosed]) -> None:
    if not bars:
        return
    docs = [
        {
            "ts": bar.bar_time,
            "metadata": {"security_id": bar.security_id, "timeframe": bar.timeframe},
            "open": float(bar.open),
            "high": float(bar.high),
            "low": float(bar.low),
            "close": float(bar.close),
            "volume": bar.volume,
            "oi": bar.oi,
        }
        for bar in bars
    ]
    try:
        from pymongo.errors import BulkWriteError
        await col.insert_many(docs, ordered=False)
        log.info("indicator_warmup_persisted", count=len(docs))
    except BulkWriteError as exc:
        n = exc.details.get("nInserted", 0)
        log.debug("indicator_warmup_persist_partial", inserted=n)
    except Exception as exc:
        log.warning("indicator_warmup_persist_error", exc=str(exc))
