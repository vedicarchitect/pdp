"""Composed `GET /api/v1/dashboard` — one call seeds the Flutter home screen.

Reads only caches/DB — no synchronous third-party calls in the request path. Live deltas ride the
existing `/ws/market` + `/ws/portfolio` sockets, not this endpoint.
"""

from __future__ import annotations

import datetime
from dataclasses import asdict
from decimal import Decimal

from fastapi import APIRouter, Request
from sqlalchemy import select

from pdp.broker_sync.models import BrokerFund
from pdp.db.session import get_session_maker
from pdp.intel.sections import (
    compute_commodities,
    compute_global_indices,
    compute_news,
    compute_next_expiry,
    compute_sentiment,
)
from pdp.intel.schemas import DashboardOut
from pdp.options.fii_dii import StubFIIDIISource
from pdp.orders.models import Position
from pdp.settings import get_settings
from pdp.strategy import unified_registry

router = APIRouter(prefix="/api/v1", tags=["dashboard"])

_INDEX_SIDS: dict[str, str] = {"NIFTY": "13", "BANKNIFTY": "25", "SENSEX": "51"}


async def _prev_close(mongo_db, security_id: str, today: datetime.date) -> float | None:
    """Latest 1D bar close strictly before `today` from `market_bars`."""
    col = mongo_db["market_bars"]
    day_start = datetime.datetime(
        today.year,
        today.month,
        today.day,
        0,
        0,
        0,
        tzinfo=datetime.UTC,
    ) - datetime.timedelta(hours=6)
    doc = await col.find_one(
        {
            "metadata.security_id": security_id,
            "metadata.timeframe": "1D",
            "ts": {"$lt": day_start},
        },
        sort=[("ts", -1)],
    )
    return float(doc["close"]) if doc else None


async def _index_section(request: Request) -> dict:
    redis = request.app.state.redis
    mongo_db = request.app.state.mongo_db
    today = datetime.date.today()
    indices = {}
    for symbol, sid in _INDEX_SIDS.items():
        raw_ltp = await redis.get(f"ltp:{sid}")
        if raw_ltp is None:
            indices[symbol] = {"available": False}
            continue
        ltp = float(raw_ltp)
        prev_close = await _prev_close(mongo_db, sid, today)
        change = (ltp - prev_close) if prev_close else None
        change_pct = (change / prev_close * 100) if prev_close else None
        indices[symbol] = {
            "available": True,
            "security_id": sid,
            "ltp": ltp,
            "prev_close": prev_close,
            "change": change,
            "change_pct": change_pct,
        }
    return indices


async def _fii_dii_section(request: Request) -> dict:
    from pdp.intel.poller import CACHE_KEY_FII_DII

    poller = getattr(request.app.state, "intel_poller", None)
    source = getattr(request.app.state, "fii_dii_source", StubFIIDIISource())
    if poller is not None:
        cached = await poller.read_cache(CACHE_KEY_FII_DII)
        if cached and cached.get("data"):
            return {"available": True, "as_of": cached["as_of"], "days": cached["data"]}
    # Poller hasn't populated the cache yet (or Redis unavailable) — fall back to a direct
    # (thread-offloaded) fetch so the section isn't blank on a cold start.
    fetch_range = getattr(source, "fetch_range", None)
    if fetch_range is None:
        return {"available": False, "days": []}
    rows = await fetch_range(7)
    if not rows:
        return {"available": False, "days": []}
    return {
        "available": True,
        "days": [
            {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in asdict(r).items()} for r in rows
        ],
    }


async def _portfolio_section() -> dict:
    settings = get_settings()
    session_maker = get_session_maker()
    async with session_maker() as session:
        result = await session.execute(select(Position))
        positions = result.scalars().all()
    total_unrealized = sum((p.unrealized_pnl or Decimal("0")) for p in positions)
    total_realized = sum((p.realized_pnl or Decimal("0")) for p in positions)
    open_count = sum(1 for p in positions if p.net_qty != 0)
    return {
        "available": True,
        "mode": "live" if settings.LIVE else "paper",
        "total_unrealized_pnl": float(total_unrealized),
        "total_realized_pnl": float(total_realized),
        "day_pnl": float(total_unrealized + total_realized),
        "open_positions": open_count,
        "position_count": len(positions),
    }


async def _today_pnl_section(request: Request) -> dict:
    journal_service = getattr(request.app.state, "journal_service", None)
    if journal_service is None:
        return {"available": False}
    stats = journal_service.get_stats(None)
    return {"available": True, **stats}


async def _margin_section() -> dict:
    session_maker = get_session_maker()
    async with session_maker() as session:
        rows = (await session.scalars(select(BrokerFund))).all()
    if not rows:
        return {"available": False}
    fund = rows[0]
    return {
        "available": True,
        "available_balance": str(fund.available_balance),
        "utilized_amount": str(fund.utilized_amount),
    }


async def _strategy_chips_section(request: Request) -> dict:
    host = getattr(request.app.state, "strategy_host", None)
    if host is None:
        return {"available": False, "strategies": []}
    live_by_id = {d["id"]: d for d in host.list_all()}
    chips = []
    for entry in unified_registry.load_all(strategies_dir=host.strategies_dir):
        live = live_by_id.get(entry.id)
        chips.append(
            {
                "id": entry.id,
                "underlying": entry.underlying,
                "status": str(live["status"]) if live else "BACKTEST_ONLY",
            }
        )
    return {"available": True, "strategies": chips}


@router.get("/dashboard", response_model=DashboardOut)
async def get_dashboard(request: Request) -> DashboardOut:
    return DashboardOut(
        {
            "as_of": datetime.datetime.now(datetime.UTC).isoformat(),
            "indices": await _index_section(request),
            "global_indices": await compute_global_indices(request),
            "commodities": await compute_commodities(request),
            "vix": await compute_vix(request),
            "next_expiry": await compute_next_expiry(),
            "fii_dii": await _fii_dii_section(request),
            "news": await compute_news(request),
            "sentiment": await compute_sentiment(request),
            "portfolio": await _portfolio_section(),
            "today_pnl": await _today_pnl_section(request),
            "margin": await _margin_section(),
            "strategies": await _strategy_chips_section(request),
        }
    )
