"""Indicator engine warmup: seed IndicatorEngine with historical bars on startup.

Priority:
  1. MongoDB market_bars collection (bars already stored from previous sessions).
  2. Dhan intraday_minute_data API (fetched when MongoDB holds fewer bars than a
     full prior session). Fetched bars are persisted to MongoDB so subsequent
     restarts use path 1.
"""
from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

import structlog

from pdp.market.bars import BarClosed

if TYPE_CHECKING:
    from motor.motor_asyncio import AsyncIOMotorDatabase

    from pdp.indicators.engine import IndicatorEngine
    from pdp.settings import Settings

log = structlog.get_logger()

# NIFTY session start: 09:15 IST = 03:45 UTC
_SESSION_START_UTC_H = 3
_SESSION_START_UTC_M = 45

# Bars expected from a full prior trading session (375-minute NIFTY session).
_TF_SESSION_BARS: dict[str, int] = {
    "1m": 375,
    "5m": 75,
    "15m": 25,
    "25m": 15,
    "1H": 7,
    "1h": 7,
}
_DEFAULT_SESSION_BARS = 75

# Timeframe label → Dhan interval integer
_TF_TO_DHAN_INTERVAL: dict[str, int] = {
    "1m": 1,
    "5m": 5,
    "15m": 15,
    "25m": 25,
    "1H": 60,
    "1h": 60,
}

# Segment string → Dhan instrument type string for the REST API
_SEGMENT_TO_INSTRUMENT: dict[str, str] = {
    "IDX_I": "INDEX",
    "NSE_EQ": "EQUITY",
    "NSE_FNO": "FUTIDX",
    "BSE_EQ": "EQUITY",
}


def _prior_trading_day(holiday_set: set[date], *, _today: date | None = None) -> date:
    """Return the most recent prior trading day (IST calendar), walking back over weekends/holidays."""
    today = _today or (datetime.now(UTC) + timedelta(hours=5, minutes=30)).date()
    d = today - timedelta(days=1)
    while d.weekday() >= 5 or d in holiday_set:
        d -= timedelta(days=1)
    return d


async def warm_up_indicator_engine(
    engine: IndicatorEngine,
    mongo_db: AsyncIOMotorDatabase,
    settings: Settings,
    watchlist: list[dict],
) -> None:
    """Seed the IndicatorEngine from MongoDB or Dhan API for each watchlist entry."""
    from pdp.options.gap_backfill import holidays as _load_holidays

    holiday_set = _load_holidays(settings.NSE_HOLIDAYS_JSON)
    prior_day = _prior_trading_day(holiday_set)
    since = datetime(
        prior_day.year, prior_day.month, prior_day.day,
        _SESSION_START_UTC_H, _SESSION_START_UTC_M,
        tzinfo=UTC,
    )
    log.info("indicator_warmup_start", prior_day=str(prior_day), since=since.isoformat())

    for entry in watchlist:
        sid = str(entry["security_id"])
        segment = str(entry["exchange_segment"])
        for tf in entry.get("timeframes", []):
            try:
                await _warm_one(engine, mongo_db, settings, sid, segment, tf, since, prior_day)
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
    since: datetime,
    prior_day: date,
) -> None:
    col = mongo_db["market_bars"]
    bars = await _fetch_from_mongo(col, security_id, timeframe, since)

    session_bars = _TF_SESSION_BARS.get(timeframe, _DEFAULT_SESSION_BARS)
    if len(bars) < session_bars and settings.DHAN_CLIENT_ID and settings.DHAN_ACCESS_TOKEN:
        log.info(
            "indicator_warmup_fetching_from_api",
            security_id=security_id,
            timeframe=timeframe,
            mongo_count=len(bars),
            session_target=session_bars,
        )
        api_bars = await asyncio.get_running_loop().run_in_executor(
            None, _fetch_from_dhan, settings, security_id, segment, timeframe, prior_day
        )
        if api_bars:
            await _persist_bars(col, api_bars)
            existing_times = {b.bar_time for b in bars}
            new_bars = [b for b in api_bars if b.bar_time not in existing_times]
            bars = sorted(new_bars + bars, key=lambda b: b.bar_time)

    if not bars:
        log.warning("indicator_warmup_no_bars", security_id=security_id, timeframe=timeframe)
        return

    if not engine._suite_trackers.get((security_id, timeframe)):
        log.debug("indicator_warmup_suite_not_configured", security_id=security_id, timeframe=timeframe)

    # Seed period_levels (PWH/PWL/PMH/PML) from the trailing ~40 days that predate
    # the prior-session bars below, so week/month boundaries are correct on day one.
    history = await _fetch_history_before(col, security_id, timeframe, since, days=40)
    if history:
        engine.seed_period_levels_history(security_id, timeframe, history)

    fed = engine.seed_from_bars(bars)

    # Derive prior-session HLC for PivotTrackers in the suite bundle.
    if bars:
        prior_h = max(float(b.high) for b in bars)
        prior_l = min(float(b.low) for b in bars)
        prior_c = float(bars[-1].close)
        engine.seed_prior_session_pivots(security_id, timeframe, prior_h, prior_l, prior_c, prior_day)

    log.info(
        "indicator_warmup_done",
        security_id=security_id,
        timeframe=timeframe,
        bars_fed=fed,
        direction=((_st := engine.get(security_id, timeframe)) and _st.direction) or None,
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
        except Exception:  # noqa: S112
            continue
    bars.sort(key=lambda b: b.bar_time)
    return bars


async def _fetch_history_before(
    col,
    security_id: str,
    timeframe: str,
    before: datetime,
    days: int,
) -> list[BarClosed]:
    """Fetch bars in ``[before - days, before)`` for period-level seeding (Mongo only)."""
    lower = before - timedelta(days=days)
    cursor = col.find(
        {
            "metadata.security_id": security_id,
            "metadata.timeframe": timeframe,
            "ts": {"$gte": lower, "$lt": before},
        },
        sort=[("ts", 1)],
    )
    bars: list[BarClosed] = []
    async for doc in cursor:
        try:
            ts = doc["ts"].replace(tzinfo=UTC) if doc["ts"].tzinfo is None else doc["ts"]
            bars.append(
                BarClosed(
                    security_id=security_id,
                    timeframe=timeframe,
                    bar_time=ts,
                    open=Decimal(str(doc["open"])),
                    high=Decimal(str(doc["high"])),
                    low=Decimal(str(doc["low"])),
                    close=Decimal(str(doc["close"])),
                    volume=int(doc.get("volume", 0)),
                    oi=int(doc.get("oi", 0)),
                )
            )
        except Exception:  # noqa: S112
            continue
    bars.sort(key=lambda b: b.bar_time)
    return bars


def _fetch_from_dhan(
    settings: Settings,
    security_id: str,
    segment: str,
    timeframe: str,
    prior_day: date | None = None,
) -> list[BarClosed]:
    """Blocking — call via run_in_executor."""
    from dhanhq import dhanhq as DhanClient  # noqa: N812

    interval = _TF_TO_DHAN_INTERVAL.get(timeframe)
    if interval is None:
        log.warning("indicator_warmup_unsupported_tf", timeframe=timeframe)
        return []

    instrument = _SEGMENT_TO_INSTRUMENT.get(segment, "EQUITY")
    today_ist = (datetime.now(UTC) + timedelta(hours=5, minutes=30)).date()
    from_d = prior_day if prior_day is not None else today_ist - timedelta(days=1)
    from_date = from_d.strftime("%Y-%m-%d")
    to_date = today_ist.strftime("%Y-%m-%d")

    from dhanhq import DhanContext
    ctx = DhanContext(settings.DHAN_CLIENT_ID, settings.DHAN_ACCESS_TOKEN)
    client = DhanClient(ctx)
    resp = client.intraday_minute_data(
        security_id=security_id,
        exchange_segment=segment,
        instrument_type=instrument,
        from_date=from_date,
        to_date=to_date,
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
        except Exception:  # noqa: S112
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
