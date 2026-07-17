"""Indicator engine warmup: seed IndicatorEngine with historical bars on startup.

Priority:
  1. MongoDB market_bars collection (bars already stored from previous sessions).
  2. Dhan intraday_minute_data API (fetched when MongoDB holds fewer bars than a
     full prior session). Fetched bars are persisted to MongoDB so subsequent
     restarts use path 1.
"""

from __future__ import annotations

import asyncio
import math
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

import structlog

from pdp.market.bars import BarClosed, bar_is_complete

if TYPE_CHECKING:
    from motor.motor_asyncio import AsyncIOMotorDatabase

    from pdp.indicators.engine import IndicatorEngine
    from pdp.settings import Settings

log = structlog.get_logger()

# NIFTY session start: 09:15 IST = 03:45 UTC
_SESSION_START_UTC_H = 3
_SESSION_START_UTC_M = 45

_IST = ZoneInfo("Asia/Kolkata")

# Bars expected from a full prior trading session (375-minute NIFTY session).
_TF_SESSION_BARS: dict[str, int] = {
    "1m": 375,
    "5m": 75,
    "15m": 25,
    "25m": 15,
    "30m": 13,
    "1H": 7,
    "1h": 7,
    "1D": 1,
    "1w": 1,  # one weekly bar per ISO week
}
_DEFAULT_SESSION_BARS = 75

# Period-like keys scanned across every configured indicator family to derive
# the warmup depth. Deliberately broad (covers ema/rsi/macd/vwma/elder_impulse)
# rather than family-specific, so a new family's period configuration is picked
# up without touching this module.
_PERIOD_KEYS: frozenset[str] = frozenset(
    {
        "periods",
        "period",
        "ma_period",
        "fast",
        "slow",
        "signal",
        "ema_period",
        "macd_fast",
        "macd_slow",
        "macd_signal",
    }
)


def required_bars(indicators: list[dict[str, Any]]) -> int:
    """Bars needed to fully converge the largest configured period.

    ``5 x max(period)`` across every period-like key in every configured
    indicator family (merged over registry defaults), floored at 200 bars so
    a config with only short periods still gets a comfortably-converged
    tracker. Replaces the hand-maintained ``_TF_WARMUP_CALENDAR_DAYS`` table —
    widening a config's largest period widens this automatically.
    """
    from pdp.indicators.registry import family_defaults

    max_period = 0
    for cfg in indicators:
        family = cfg.get("family") if isinstance(cfg, dict) else None
        if not family:
            continue
        merged = {**family_defaults(family), **{k: v for k, v in cfg.items() if k != "family"}}
        for key in _PERIOD_KEYS:
            val = merged.get(key)
            if isinstance(val, int):
                max_period = max(max_period, val)
            elif isinstance(val, list):
                max_period = max([max_period, *(v for v in val if isinstance(v, int))])
    return max(200, 5 * max_period)


def lookback_days(timeframe: str, bars_needed: int) -> int:
    """Calendar-day lookback so ``bars_needed`` bars are covered, with a
    weekend/holiday pad (``x 7 / 5``, rounded up).

    Raises ``ValueError`` on a timeframe absent from ``_TF_SESSION_BARS``
    rather than silently defaulting to a one-day lookback.
    """
    session_bars = _TF_SESSION_BARS.get(timeframe)
    if session_bars is None:
        raise ValueError(timeframe)
    return math.ceil(bars_needed / session_bars * 7 / 5)


# Timeframe label → Dhan interval integer
_TF_TO_DHAN_INTERVAL: dict[str, int] = {
    "1m": 1,
    "5m": 5,
    "15m": 15,
    "25m": 25,
    "30m": 30,
    "1H": 60,
    "1h": 60,
}

# Timeframes derivable from the 1m series already in `market_bars`. These are exactly the
# windows that trip Dhan's 90-day intraday cap (30m EMA200 ≈ 108 calendar days, 1H ≈ 200):
# warmup derives them from 1m via the shared session-anchored bucket function instead of a
# live intraday API call. 5m is intentionally excluded so it keeps its existing (small,
# never-over-90-day at the 200-floor) direct path. See `indicator-warmup-derive-from-1m`.
_DERIVABLE_TF_MINUTES: dict[str, int] = {"15m": 15, "30m": 30, "1H": 60, "1h": 60}

# Dhan serves at most 90 calendar days of intraday candles per request.
_DHAN_INTRADAY_MAX_DAYS = 90


def _ninety_day_chunks(
    from_d: date, to_d: date, max_days: int = _DHAN_INTRADAY_MAX_DAYS
) -> list[tuple[date, date]]:
    """Split ``[from_d, to_d]`` into ≤ ``max_days``-calendar-day inclusive windows.

    Mirrors ``scripts/backfill_spot.py``'s chunker so a warmup window wider than Dhan's
    90-day intraday cap is fetched in pieces instead of failing whole with DH-905.
    """
    out: list[tuple[date, date]] = []
    start = from_d
    while start <= to_d:
        end = min(start + timedelta(days=max_days - 1), to_d)
        out.append((start, end))
        start = end + timedelta(days=1)
    return out


def _derive_bars_from_1m(bars_1m: list[BarClosed], tf_minutes: int, timeframe: str) -> list[BarClosed]:
    """Roll up 1m ``BarClosed`` into ``timeframe`` buckets via the session-anchored
    ``_bar_boundary`` — the same bucket function the live ``BarAggregator`` uses, so a
    warmup-derived bar is bit-identical to one the live feed would have rolled."""
    from pdp.market.bars import _bar_boundary

    buckets: dict[datetime, list[BarClosed]] = {}
    for b in bars_1m:
        boundary = _bar_boundary(b.bar_time, tf_minutes)
        buckets.setdefault(boundary, []).append(b)

    out: list[BarClosed] = []
    for boundary in sorted(buckets):
        group = sorted(buckets[boundary], key=lambda b: b.bar_time)
        out.append(
            BarClosed(
                security_id=group[0].security_id,
                timeframe=timeframe,
                bar_time=boundary,
                open=group[0].open,
                high=max(b.high for b in group),
                low=min(b.low for b in group),
                close=group[-1].close,
                volume=sum(b.volume for b in group),
                oi=group[-1].oi,
            )
        )
    return out

# Segment string → Dhan instrument type string for the REST API
_SEGMENT_TO_INSTRUMENT: dict[str, str] = {
    "IDX_I": "INDEX",
    "NSE_EQ": "EQUITY",
    "NSE_FNO": "FUTIDX",
    "BSE_EQ": "EQUITY",
}


def _prior_trading_day(holiday_set: set[date], *, _today: date | None = None) -> date:
    """Return the most recent prior trading day (IST calendar), walking back over weekends/holidays."""
    today = _today or datetime.now(_IST).date()
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
    log.info("indicator_warmup_start", prior_day=str(prior_day))

    for entry in watchlist:
        sid = str(entry["security_id"])
        segment = str(entry["exchange_segment"])
        indicators = entry.get("indicators", [])
        req = required_bars(indicators)
        for tf in entry.get("timeframes", []):
            try:
                days_back = lookback_days(tf, req)
            except ValueError as exc:
                log.warning(
                    "indicator_warmup_failed",
                    security_id=sid,
                    timeframe=tf,
                    exc=str(exc),
                )
                continue
            warmup_from = prior_day - timedelta(days=days_back - 1)
            since = datetime(
                warmup_from.year,
                warmup_from.month,
                warmup_from.day,
                _SESSION_START_UTC_H,
                _SESSION_START_UTC_M,
                tzinfo=UTC,
            )
            try:
                await _warm_one(
                    engine, mongo_db, settings, sid, segment, tf, since, warmup_from, prior_day, indicators, req
                )
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
    warmup_from: date,
    prior_day: date,
    indicators: list[dict[str, Any]],
    target_bars: int,
) -> None:
    col = mongo_db["market_bars"]
    bars = await _fetch_from_mongo(col, security_id, timeframe, since)

    # target_bars is the depth required by the configured indicator families
    # (derive_bars x max period, floor 200) — see required_bars().
    #
    # Preferred top-up: derive a derivable higher timeframe (15m/30m/1H) from the 1m
    # series already in Mongo — no live API, and it never trips Dhan's 90-day intraday
    # cap. Only when 1m coverage is itself insufficient do we fall back to a chunked
    # Dhan intraday fetch. See `indicator-warmup-derive-from-1m`.
    if len(bars) < target_bars and timeframe in _DERIVABLE_TF_MINUTES:
        bars_1m = await _fetch_from_mongo(col, security_id, "1m", since)
        if bars_1m:
            now = datetime.now(UTC)
            derived = [
                b
                for b in _derive_bars_from_1m(bars_1m, _DERIVABLE_TF_MINUTES[timeframe], timeframe)
                if bar_is_complete(b.bar_time, timeframe, now)
            ]
            if len(derived) > len(bars):
                await _replace_derived_bars(col, security_id, timeframe, since, derived)
                log.info(
                    "indicator_warmup_derived_from_1m",
                    security_id=security_id,
                    timeframe=timeframe,
                    derived=len(derived),
                    from_1m=len(bars_1m),
                )
                bars = derived

    if len(bars) < target_bars and settings.DHAN_CLIENT_ID and settings.DHAN_ACCESS_TOKEN:
        log.info(
            "indicator_warmup_fetching_from_api",
            security_id=security_id,
            timeframe=timeframe,
            mongo_count=len(bars),
            target=target_bars,
        )
        api_bars = await asyncio.get_running_loop().run_in_executor(
            None, _fetch_from_dhan, settings, security_id, segment, timeframe, warmup_from
        )
        if api_bars:
            await _persist_bars(col, api_bars)
            existing_times = {b.bar_time for b in bars}
            new_bars = [b for b in api_bars if b.bar_time not in existing_times]
            bars = sorted(new_bars + bars, key=lambda b: b.bar_time)

    if not bars:
        if timeframe == "1w":
            # No 1w bars in Mongo (BarAggregator hasn't run for a full week yet).
            # Synthesize weekly bars from 1D bars so weekly pivot/Camarilla is seeded.
            bars = await _synthesize_weekly_from_daily(col, security_id, since)
            if bars:
                log.info("indicator_warmup_1w_synthesized_from_1d", security_id=security_id, n=len(bars))
        if not bars:
            log.warning("indicator_warmup_no_bars", security_id=security_id, timeframe=timeframe)
            return

    if not engine._suite_trackers.get((security_id, timeframe)):
        log.debug("indicator_warmup_suite_not_configured", security_id=security_id, timeframe=timeframe)

    # One indicator_warmup_short per (sid, tf, family) that didn't reach its own
    # required depth — a family with a smaller max period may already be fully
    # converged even when the entry's overall target_bars (driven by the largest
    # period across all families) was not met.
    for cfg in indicators:
        family = cfg.get("family") if isinstance(cfg, dict) else None
        if not family:
            continue
        family_needed = required_bars([cfg])
        if len(bars) < family_needed:
            log.warning(
                "indicator_warmup_short",
                security_id=security_id,
                timeframe=timeframe,
                family=family,
                bars_found=len(bars),
                bars_needed=family_needed,
            )

    # Seed period_levels (PWH/PWL/PMH/PML) from the trailing ~40 days that predate
    # the prior-session bars below, so week/month boundaries are correct on day one.
    history = await _fetch_history_before(col, security_id, timeframe, since, days=40)
    if history:
        engine.seed_period_levels_history(security_id, timeframe, history)

    fed = engine.seed_from_bars(bars)

    # Derive prior-period HLC for PivotTrackers in the suite bundle.
    if bars:
        if _TF_SESSION_BARS.get(timeframe) == 1:
            # One bar IS one whole period (1D: one bar/day, 1w: one bar/ISO week) --
            # the prior period is simply the most recently completed bar itself.
            # The day-boundary filter below only makes sense for sub-daily bars: a
            # Monday-anchored 1w bar's timestamp is never >= "yesterday", so it fell
            # through to the bars[-10:] fallback and wrongly aggregated up to 10
            # prior weeks' high/low together instead of using the single most
            # recent completed week's own HLC.
            pivot_bars = [bars[-1]]
        else:
            prior_day_start = datetime(
                prior_day.year,
                prior_day.month,
                prior_day.day,
                _SESSION_START_UTC_H,
                _SESSION_START_UTC_M,
                tzinfo=UTC,
            )
            # Use only bars from the most recent prior trading day to get its HLC, not
            # the entire extended lookback window (which would give a multi-day range).
            prior_session_bars = [b for b in bars if b.bar_time >= prior_day_start]
            pivot_bars = prior_session_bars if prior_session_bars else bars[-10:]
        prior_h = max(float(b.high) for b in pivot_bars)
        prior_l = min(float(b.low) for b in pivot_bars)
        prior_c = float(pivot_bars[-1].close)
        engine.seed_prior_session_pivots(security_id, timeframe, prior_h, prior_l, prior_c, prior_day)

    log.info(
        "indicator_warmup_done",
        security_id=security_id,
        timeframe=timeframe,
        bars_fed=fed,
        direction=((_st := engine.get(security_id, timeframe)) and _st.direction) or None,
    )


async def _synthesize_weekly_from_daily(
    col,
    security_id: str,
    since: datetime,
) -> list[BarClosed]:
    """Build synthetic 1w BarClosed objects by aggregating 1D bars from MongoDB.

    Reads the last ~3 weeks of 1D bars and groups them by ISO week (Monday boundary).
    Returns one BarClosed per complete prior week so that PivotTracker("1w") can
    compute weekly Camarilla levels on startup even before any live 1w bar rolls.
    """
    # Fetch 1D bars for the last 21 days (covers ~3 ISO weeks including partials)
    daily_since = since - timedelta(days=21)
    daily_bars = await _fetch_from_mongo(col, security_id, "1D", daily_since)
    if not daily_bars:
        return []

    # Group by ISO-week Monday (UTC Monday 00:00)
    from pdp.market.bars import _bar_boundary_1w

    weekly: dict[datetime, list[BarClosed]] = {}
    for bar in daily_bars:
        wk = _bar_boundary_1w(bar.bar_time)
        weekly.setdefault(wk, []).append(bar)

    # Build one synthetic 1w BarClosed per complete week (exclude the current partial week)
    now_week = _bar_boundary_1w(datetime.now(UTC))
    result: list[BarClosed] = []
    for wk_start in sorted(weekly):
        if wk_start >= now_week:
            continue  # skip current partial week
        week_bars = sorted(weekly[wk_start], key=lambda b: b.bar_time)
        result.append(
            BarClosed(
                security_id=security_id,
                timeframe="1w",
                bar_time=wk_start,
                open=week_bars[0].open,
                high=max(b.high for b in week_bars),
                low=min(b.low for b in week_bars),
                close=week_bars[-1].close,
                volume=sum(b.volume for b in week_bars),
                oi=week_bars[-1].oi,
            )
        )
    return result


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
    *,
    now: datetime | None = None,
) -> list[BarClosed]:
    """Blocking — call via run_in_executor.

    `now` is injectable for tests; production calls always fall through to the
    real wall clock. Any bar whose period has not fully elapsed as of `now` is
    dropped before it can be persisted or seed an indicator — see
    `dhan-same-day-data`.
    """
    from dhanhq import dhanhq as DhanClient  # noqa: N812

    is_daily = timeframe in ("1D", "1w", "1M")
    interval = _TF_TO_DHAN_INTERVAL.get(timeframe)
    if interval is None and not is_daily:
        log.warning("indicator_warmup_unsupported_tf", timeframe=timeframe)
        return []

    instrument = _SEGMENT_TO_INSTRUMENT.get(segment, "EQUITY")
    effective_now = now if now is not None else datetime.now(UTC)
    today_ist = effective_now.astimezone(_IST).date()
    from_d = prior_day if prior_day is not None else today_ist - timedelta(days=1)
    from_date = from_d.strftime("%Y-%m-%d")
    to_date = today_ist.strftime("%Y-%m-%d")

    from dhanhq import DhanContext

    ctx = DhanContext(settings.DHAN_CLIENT_ID, settings.DHAN_ACCESS_TOKEN)
    client = DhanClient(ctx)

    def _parse(resp: object) -> list[BarClosed]:
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
        out: list[BarClosed] = []
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
                out.append(
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
        return out

    bars: list[BarClosed] = []
    if is_daily:
        # Intraday endpoint does not serve daily candles — use the daily-candles API
        # (not subject to the 90-day intraday cap, so no chunking needed).
        bars.extend(
            _parse(
                client.historical_daily_data(
                    security_id=security_id,
                    exchange_segment=segment,
                    instrument_type=instrument,
                    from_date=from_date,
                    to_date=to_date,
                )
            )
        )
    else:
        # Chunk the intraday window into ≤ 90-calendar-day pieces so a warmup lookback
        # wider than Dhan's cap (30m EMA200 ≈ 108 days, 1H ≈ 200) no longer fails whole
        # with DH-905. A single failed chunk is logged and skipped, not fatal.
        for c_from, c_to in _ninety_day_chunks(from_d, today_ist):
            bars.extend(
                _parse(
                    client.intraday_minute_data(
                        security_id=security_id,
                        exchange_segment=segment,
                        instrument_type=instrument,
                        from_date=c_from.strftime("%Y-%m-%d"),
                        to_date=c_to.strftime("%Y-%m-%d"),
                        interval=interval,
                    )
                )
            )

    bars.sort(key=lambda b: b.bar_time)

    complete_bars = [b for b in bars if bar_is_complete(b.bar_time, timeframe, effective_now)]
    dropped = len(bars) - len(complete_bars)
    if dropped:
        log.info(
            "indicator_warmup_incomplete_bar_dropped",
            security_id=security_id,
            timeframe=timeframe,
            count=dropped,
        )
    return complete_bars


# ── Monitor indicator-matrix bootstrap ─────────────────────────────────────────

# Spot index SIDs shown in the Execution-tab matrix.
_MATRIX_INDEX_SIDS: dict[str, str] = {"NIFTY": "13", "BANKNIFTY": "25", "SENSEX": "51"}
_MATRIX_TFS: list[str] = ["5m", "15m", "30m", "1H", "1D"]

# Price-based families on the spot index (EMA200 + RSI(14) with SMA(14) signal to
# match Kite "RSI 14 SMA 14"; PSAR already registry-default 0.02/0.2).
_MATRIX_SPOT_INDICATORS: list[dict] = [
    {"family": "ema", "periods": [9, 20, 50, 100, 200]},
    {"family": "psar"},
    {"family": "rsi", "period": 14, "ma_period": 14, "ma_kind": "sma"},
]
# Volume-anchored families computed on the index FUTURES contract (spot has no volume).
_MATRIX_FUT_INDICATORS: list[dict] = [
    {"family": "vwap"},
    {"family": "vwma", "period": 20},
]


async def _resolve_front_month_futures_sid(underlying: str, session_maker: object) -> str | None:
    """Query the instruments table for the nearest-expiry FUTIDX for this underlying.

    Sole consumer is the matrix's futures VWAP/VWMA display (spot has no volume) —
    bias-scoring dropped its own futures-SID path in ``backtest-paper-parity``.
    """
    from sqlalchemy import select

    from pdp.instruments.models import Instrument

    try:
        async with session_maker() as session:  # type: ignore[operator]
            result = await session.execute(
                select(Instrument.security_id)
                .where(
                    Instrument.instrument_type == "FUTIDX",
                    Instrument.underlying == underlying,
                    Instrument.expiry >= date.today(),
                )
                .order_by(Instrument.expiry)
                .limit(1)
            )
            row = result.scalar_one_or_none()
            return str(row) if row else None
    except Exception:
        return None


async def configure_matrix_suites(
    engine: IndicatorEngine,
    session_maker: object,
) -> list[dict]:
    """Configure the Execution-tab indicator matrix suites and return warmup entries.

    Ensures the three spot index SIDs carry EMA(9..200)/PSAR/RSI on every matrix
    timeframe, and each index's current-month futures contract carries VWAP/VWMA
    (volume-anchored — meaningless on spot). Returns the additional warmup watchlist
    entries (spot + futures) so ``warm_up_indicator_engine`` seeds them.
    """
    entries: list[dict] = []

    # Spot index price indicators.
    for sid in _MATRIX_INDEX_SIDS.values():
        for tf in _MATRIX_TFS:
            engine.configure_suite(sid, tf, _MATRIX_SPOT_INDICATORS)
        entries.append(
            {
                "security_id": sid,
                "exchange_segment": "IDX_I",
                "timeframes": list(_MATRIX_TFS),
                "indicators": _MATRIX_SPOT_INDICATORS,
            }
        )

    # Futures volume indicators — resolve the front-month FUTIDX per index.
    fut_map: dict[str, str] = {}
    for name, sid in _MATRIX_INDEX_SIDS.items():
        try:
            fut_sid = await _resolve_front_month_futures_sid(name, session_maker)
        except Exception:
            fut_sid = None
        if not fut_sid:
            log.warning("matrix_futures_unresolved", underlying=name)
            continue
        fut_map[sid] = fut_sid
        for tf in _MATRIX_TFS:
            engine.configure_suite(fut_sid, tf, _MATRIX_FUT_INDICATORS)
        entries.append(
            {
                "security_id": fut_sid,
                "exchange_segment": "NSE_FNO",
                "timeframes": list(_MATRIX_TFS),
                "indicators": _MATRIX_FUT_INDICATORS,
            }
        )

    engine.matrix_futures_sids = fut_map  # type: ignore[attr-defined]
    log.info("matrix_suites_configured", spot=list(_MATRIX_INDEX_SIDS.values()), futures=fut_map)
    return entries


async def _replace_derived_bars(
    col, security_id: str, timeframe: str, since: datetime, bars: list[BarClosed]
) -> None:
    """Delete-then-insert the ``[since, ∞)`` window for ``(security_id, timeframe)`` and
    write the 1m-derived bars. MongoDB time-series collections reject upsert/non-multi
    update (error 72), so idempotency is delete-the-window-then-insert — matching
    ``scripts/backfill_spot.py``'s ``_write_day``."""
    if not bars:
        return
    try:
        await col.delete_many(
            {
                "metadata.security_id": security_id,
                "metadata.timeframe": timeframe,
                "ts": {"$gte": since},
            }
        )
        await _persist_bars(col, bars)
    except Exception as exc:
        log.warning("indicator_warmup_derive_persist_error", security_id=security_id, exc=str(exc))


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
