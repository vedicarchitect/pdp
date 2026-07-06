"""Persisted price-levels warehouse — Mongo `index_levels` collection.

Stores daily and weekly standard / Camarilla / Fibonacci pivot levels (computed
from prior-session/week HLC) for NIFTY, BANKNIFTY and SENSEX.  One document per
``(security_id, period, session_date)`` key.

Design decisions:
- Regular (non-time-series) collection so upserts work (TS collections reject them).
- Level math delegates entirely to :func:`pdp.indicators.pivots._compute_pivots`
  — no second pivot implementation.
- Schema version field + open ``levels`` map make adding new families migration-free.
- Idempotent upsert: re-running for the same key overwrites without duplicating.
"""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING, Any

import structlog

from pdp.indicators.pivots import _compute_pivots

if TYPE_CHECKING:
    from motor.motor_asyncio import AsyncIOMotorCollection, AsyncIOMotorDatabase

log = structlog.get_logger()

_SCHEMA_VERSION = 1

_UNDERLYING_MAP: dict[str, str] = {
    "13": "NIFTY",
    "25": "BANKNIFTY",
    "51": "SENSEX",
}


def _pivot_state_to_doc(
    security_id: str,
    period: str,
    session_date: date,
    source_h: float,
    source_l: float,
    source_c: float,
    window_start: date,
    window_end: date,
) -> dict[str, Any]:
    """Build a Mongo document from prior-session/week HLC using _compute_pivots."""
    ps = _compute_pivots(source_h, source_l, source_c, session_date)
    return {
        "schema_version": _SCHEMA_VERSION,
        "security_id": security_id,
        "underlying": _UNDERLYING_MAP.get(security_id, security_id),
        "period": period,
        "session_date": session_date.isoformat(),
        "source": {
            "h": source_h,
            "l": source_l,
            "c": source_c,
            "window_start": window_start.isoformat(),
            "window_end": window_end.isoformat(),
        },
        "standard": {
            "pp": ps.pp, "r1": ps.r1, "r2": ps.r2, "r3": ps.r3,
            "s1": ps.s1, "s2": ps.s2, "s3": ps.s3,
        },
        "camarilla": {
            "pp": ps.cam_pp, "r3": ps.cam_r3, "r4": ps.cam_r4,
            "s3": ps.cam_s3, "s4": ps.cam_s4,
        },
        "fibonacci": {
            "pp": ps.fib_pp, "r1": ps.fib_r1, "r2": ps.fib_r2, "r3": ps.fib_r3,
            "s1": ps.fib_s1, "s2": ps.fib_s2, "s3": ps.fib_s3,
        },
        "levels": {},   # open map for future families (cpr/vwap_bands/murrey/sd_zones)
        "computed_at": datetime.now(UTC).isoformat(),
    }


class LevelsStore:
    """Async CRUD for the ``index_levels`` Mongo collection.

    All writes are idempotent upserts keyed on ``(security_id, period, session_date)``.
    """

    def __init__(self, collection: AsyncIOMotorCollection) -> None:  # type: ignore[type-arg]
        self._col = collection

    # ── Writes ──────────────────────────────────────────────────────────────────

    async def upsert(self, doc: dict[str, Any]) -> None:
        """Upsert a pre-built level document (idempotent)."""
        key = {
            "security_id": doc["security_id"],
            "period": doc["period"],
            "session_date": doc["session_date"],
        }
        await self._col.update_one(key, {"$set": doc}, upsert=True)

    async def compute_daily(
        self,
        security_id: str,
        session_date: date,
        prior_h: float,
        prior_l: float,
        prior_c: float,
        prior_date: date,
    ) -> None:
        """Compute and upsert daily levels for one index from prior-session HLC."""
        doc = _pivot_state_to_doc(
            security_id=security_id,
            period="daily",
            session_date=session_date,
            source_h=prior_h,
            source_l=prior_l,
            source_c=prior_c,
            window_start=prior_date,
            window_end=prior_date,
        )
        await self.upsert(doc)
        log.debug(
            "levels_store_daily_upserted",
            security_id=security_id,
            session_date=session_date.isoformat(),
        )

    async def compute_weekly(
        self,
        security_id: str,
        session_date: date,
        week_h: float,
        week_l: float,
        week_c: float,
        week_start: date,
        week_end: date,
    ) -> None:
        """Compute and upsert weekly levels for one index from prior-week HLC."""
        doc = _pivot_state_to_doc(
            security_id=security_id,
            period="weekly",
            session_date=session_date,
            source_h=week_h,
            source_l=week_l,
            source_c=week_c,
            window_start=week_start,
            window_end=week_end,
        )
        await self.upsert(doc)
        log.debug(
            "levels_store_weekly_upserted",
            security_id=security_id,
            session_date=session_date.isoformat(),
        )

    async def compute_monthly(
        self,
        security_id: str,
        session_date: date,
        month_h: float,
        month_l: float,
        month_c: float,
        month_start: date,
        month_end: date,
    ) -> None:
        """Compute and upsert monthly levels for one index from prior-month HLC."""
        doc = _pivot_state_to_doc(
            security_id=security_id,
            period="monthly",
            session_date=session_date,
            source_h=month_h,
            source_l=month_l,
            source_c=month_c,
            window_start=month_start,
            window_end=month_end,
        )
        await self.upsert(doc)
        log.debug(
            "levels_store_monthly_upserted",
            security_id=security_id,
            session_date=session_date.isoformat(),
        )

    # ── Reads ────────────────────────────────────────────────────────────────────

    async def get(
        self,
        security_id: str,
        period: str,
        session_date: date,
    ) -> dict[str, Any] | None:
        """Fetch one level document; returns None if not found."""
        doc = await self._col.find_one(
            {
                "security_id": security_id,
                "period": period,
                "session_date": session_date.isoformat(),
            },
            {"_id": 0},
        )
        return doc  # type: ignore[return-value]

    async def range(
        self,
        security_id: str,
        period: str,
        start: date,
        end: date,
    ) -> list[dict[str, Any]]:
        """Return all level docs for ``[start, end]`` ordered by session_date.

        Used by backtests and ML feature pipelines (``session_date`` join key).
        """
        cursor = self._col.find(
            {
                "security_id": security_id,
                "period": period,
                "session_date": {"$gte": start.isoformat(), "$lte": end.isoformat()},
            },
            {"_id": 0},
            sort=[("session_date", 1)],
        )
        return [doc async for doc in cursor]

    async def to_feature_rows(
        self,
        security_id: str,
        period: str,
        start: date,
        end: date,
    ) -> list[dict[str, Any]]:
        """Flatten nested level docs into ML-ready feature rows.

        Each row has ``session_date`` plus flat columns:
        ``std_pp, std_r1, …, cam_pp, cam_r3, …, fib_pp, …``
        PDH/PDL (daily) or PWH/PWL (weekly) come from ``source.h`` / ``source.l``.
        """
        docs = await self.range(security_id, period, start, end)
        rows: list[dict[str, Any]] = []
        for doc in docs:
            flat: dict[str, Any] = {"session_date": doc["session_date"]}
            for k, v in doc.get("standard", {}).items():
                flat[f"std_{k}"] = v
            for k, v in doc.get("camarilla", {}).items():
                flat[f"cam_{k}"] = v
            for k, v in doc.get("fibonacci", {}).items():
                flat[f"fib_{k}"] = v
            src = doc.get("source", {})
            if period == "daily":
                flat["pdh"] = src.get("h")
                flat["pdl"] = src.get("l")
                flat["pdc"] = src.get("c")
            elif period == "weekly":
                flat["pwh"] = src.get("h")
                flat["pwl"] = src.get("l")
            elif period == "monthly":
                flat["pmh"] = src.get("h")
                flat["pml"] = src.get("l")
            rows.append(flat)
        return rows


# ── Collection-level helper for Mongo lifespan job ──────────────────────────────

async def compute_session_levels(
    db: AsyncIOMotorDatabase,  # type: ignore[type-arg]
    security_ids: list[str],
    holiday_json: str,
    *,
    session_date: date | None = None,
) -> None:
    """Compute and upsert daily + weekly levels for the given security IDs.

    Called at startup and at day-boundary events from ``pdp.jobs``.
    Reads prior-session 1D bar HLC from ``market_bars``.
    On Mondays, also recomputes weekly levels from the prior ISO-week bars.
    """
    from pdp.options.gap_backfill import holidays as _load_holidays
    from pdp.options.gap_backfill import trading_days

    store = LevelsStore(db["index_levels"])
    holiday_set = _load_holidays(holiday_json)
    today = session_date or (datetime.now(UTC) + timedelta(hours=5, minutes=30)).date()

    # ── Daily levels ──────────────────────────────────────────────────────────
    # Find the most recent prior trading day's 1D bar for each index.
    prior_td = _prior_trading_day(today, holiday_set)

    for sid in security_ids:
        try:
            h, lo, c = await _fetch_1d_hlc(db, sid, prior_td)
            if h is not None:
                await store.compute_daily(
                    security_id=sid,
                    session_date=today,
                    prior_h=h, prior_l=lo, prior_c=c,  # type: ignore[arg-type]
                    prior_date=prior_td,
                )
        except Exception as exc:
            log.warning("levels_daily_compute_error", security_id=sid, exc=str(exc))

    # ── Weekly levels (Monday, or when the current session's weekly doc is missing) ──
    if today.weekday() == 0 or not await _has_period_doc(store, security_ids, "weekly", today):
        # Prior ISO week: Monday of last week to Friday (or last trading day)
        prior_monday = today - timedelta(days=today.weekday() + 7)
        prior_week_days = [
            d for d in trading_days(prior_monday, prior_monday + timedelta(days=6), holiday_set)
        ]
        if prior_week_days:
            week_start = prior_week_days[0]
            week_end = prior_week_days[-1]
            for sid in security_ids:
                try:
                    h, lo, c = await _fetch_week_hlc(db, sid, week_start, week_end)
                    if h is not None:
                        await store.compute_weekly(
                            security_id=sid,
                            session_date=today,
                            week_h=h, week_l=lo, week_c=c,  # type: ignore[arg-type]
                            week_start=week_start,
                            week_end=week_end,
                        )
                except Exception as exc:
                    log.warning("levels_weekly_compute_error", security_id=sid, exc=str(exc))

    # ── Monthly levels (first trading day of month, or when the doc is missing) ──
    first_td_of_month = _first_trading_day_of_month(today, holiday_set)
    if today == first_td_of_month or not await _has_period_doc(store, security_ids, "monthly", today):
        # Prior calendar month: first→last day of the month before `today`.
        prior_month_end = today.replace(day=1) - timedelta(days=1)
        prior_month_start = prior_month_end.replace(day=1)
        for sid in security_ids:
            try:
                h, lo, c = await _fetch_month_hlc(db, sid, prior_month_start, prior_month_end)
                if h is not None:
                    await store.compute_monthly(
                        security_id=sid,
                        session_date=today,
                        month_h=h, month_l=lo, month_c=c,  # type: ignore[arg-type]
                        month_start=prior_month_start,
                        month_end=prior_month_end,
                    )
            except Exception as exc:
                log.warning("levels_monthly_compute_error", security_id=sid, exc=str(exc))


def _prior_trading_day(today: date, holiday_set: set[date]) -> date:
    d = today - timedelta(days=1)
    while d.weekday() >= 5 or d in holiday_set:
        d -= timedelta(days=1)
    return d


def _first_trading_day_of_month(day: date, holiday_set: set[date]) -> date:
    """Return the first trading day on/after the 1st of ``day``'s calendar month."""
    d = day.replace(day=1)
    while d.weekday() >= 5 or d in holiday_set:
        d += timedelta(days=1)
    return d


async def _has_period_doc(
    store: LevelsStore,
    security_ids: list[str],
    period: str,
    session_date: date,
) -> bool:
    """True only if every security already has a ``period`` doc for ``session_date``."""
    for sid in security_ids:
        if await store.get(sid, period, session_date) is None:
            return False
    return True


async def _fetch_1d_hlc(
    db: Any,
    security_id: str,
    day: date,
) -> tuple[float | None, float | None, float | None]:
    """Fetch the 1D bar HLC for a security on a given day from market_bars."""
    # 1D bars are stored with bar_time = IST midnight in UTC (18:30 of prior UTC day)
    # Widen the window by ±1 day to be safe across timezone edges.

    day_start = datetime(day.year, day.month, day.day, 0, 0, 0, tzinfo=UTC) - timedelta(hours=6)
    day_end = day_start + timedelta(hours=30)
    col = db["market_bars"]
    doc = await col.find_one(
        {
            "metadata.security_id": security_id,
            "metadata.timeframe": "1D",
            "ts": {"$gte": day_start, "$lt": day_end},
        },
        sort=[("ts", -1)],
    )
    if doc is None:
        # Fallback: aggregate from 1m bars for that day
        doc = await col.find_one(
            {
                "metadata.security_id": security_id,
                "metadata.timeframe": "1m",
                "ts": {"$gte": day_start, "$lt": day_end},
            },
            sort=[("ts", 1)],
        )
        if doc:
            pipeline = [
                {"$match": {
                    "metadata.security_id": security_id,
                    "metadata.timeframe": "1m",
                    "ts": {"$gte": day_start, "$lt": day_end},
                }},
                {"$group": {
                    "_id": None,
                    "h": {"$max": "$high"},
                    "l": {"$min": "$low"},
                    "c": {"$last": "$close"},
                }},
            ]
            async for agg in col.aggregate(pipeline):
                return float(agg["h"]), float(agg["l"]), float(agg["c"])
        return None, None, None
    return float(doc["high"]), float(doc["low"]), float(doc["close"])


async def _fetch_week_hlc(
    db: Any,
    security_id: str,
    week_start: date,
    week_end: date,
) -> tuple[float | None, float | None, float | None]:
    """Fetch aggregated HLC for a security across a full ISO week from market_bars."""

    ws = datetime(week_start.year, week_start.month, week_start.day, tzinfo=UTC) - timedelta(hours=6)
    we = datetime(week_end.year, week_end.month, week_end.day, tzinfo=UTC) + timedelta(hours=24)
    col = db["market_bars"]
    pipeline = [
        {"$match": {
            "metadata.security_id": security_id,
            "metadata.timeframe": {"$in": ["1D", "1m"]},
            "ts": {"$gte": ws, "$lt": we},
        }},
        {"$group": {
            "_id": None,
            "h": {"$max": "$high"},
            "l": {"$min": "$low"},
            "c": {"$last": "$close"},
        }},
    ]
    async for agg in col.aggregate(pipeline):
        return float(agg["h"]), float(agg["l"]), float(agg["c"])
    return None, None, None


async def _fetch_month_hlc(
    db: Any,
    security_id: str,
    month_start: date,
    month_end: date,
) -> tuple[float | None, float | None, float | None]:
    """Fetch aggregated HLC for a security across a full calendar month from market_bars."""

    ms = datetime(month_start.year, month_start.month, month_start.day, tzinfo=UTC) - timedelta(hours=6)
    me = datetime(month_end.year, month_end.month, month_end.day, tzinfo=UTC) + timedelta(hours=24)
    col = db["market_bars"]
    pipeline = [
        {"$match": {
            "metadata.security_id": security_id,
            "metadata.timeframe": {"$in": ["1D", "1m"]},
            "ts": {"$gte": ms, "$lt": me},
        }},
        {"$group": {
            "_id": None,
            "h": {"$max": "$high"},
            "l": {"$min": "$low"},
            "c": {"$last": "$close"},
        }},
    ]
    async for agg in col.aggregate(pipeline):
        return float(agg["h"]), float(agg["l"]), float(agg["c"])
    return None, None, None
