"""Shared section builders for the intel feeds — used by both the standalone
`/api/v1/intel/*` routes (`pdp/intel/routes.py`) and the composed `GET /api/v1/dashboard`
endpoint (`pdp/intel/dashboard_routes.py`) so the two never drift out of sync.
"""
from __future__ import annotations

import structlog
from fastapi import Request

from pdp.settings import get_settings

log = structlog.get_logger()

_MCX_COMMODITIES: list[tuple[str, str, str]] = [
    # (symbol, display name, settings attr for security id)
    ("GOLD", "Gold", "MCX_GOLD_SECURITY_ID"),
    ("SILVER", "Silver", "MCX_SILVER_SECURITY_ID"),
    ("CRUDE", "Crude Oil", "MCX_CRUDE_SECURITY_ID"),
    ("NATGAS", "Natural Gas", "MCX_NATGAS_SECURITY_ID"),
]

# Indices whose next expiry the dashboard resolves — from the instruments table (real Dhan
# scrip master), NOT a projected weekday calendar.
_EXPIRY_UNDERLYINGS: tuple[str, ...] = ("NIFTY", "BANKNIFTY", "SENSEX")


async def read_poller_cache(request: Request, key: str) -> dict | None:
    poller = getattr(request.app.state, "intel_poller", None)
    if poller is None:
        return None
    return await poller.read_cache(key)


async def compute_global_indices(request: Request) -> dict:
    from pdp.intel.poller import CACHE_KEY_GLOBAL_INDICES

    cached = await read_poller_cache(request, CACHE_KEY_GLOBAL_INDICES)
    if not cached or not cached.get("data"):
        return {"available": False, "indices": []}
    return {"available": True, "as_of": cached["as_of"], "indices": cached["data"]}


async def compute_news(request: Request) -> dict:
    from pdp.intel.poller import CACHE_KEY_NEWS

    cached = await read_poller_cache(request, CACHE_KEY_NEWS)
    if not cached or not cached.get("data"):
        return {"available": False, "articles": []}
    return {"available": True, "as_of": cached["as_of"], "articles": cached["data"]}


async def compute_sentiment(request: Request) -> dict:
    from pdp.intel.poller import CACHE_KEY_SENTIMENT

    cached = await read_poller_cache(request, CACHE_KEY_SENTIMENT)
    if not cached or not cached.get("data"):
        return {"available": False}
    return {"available": True, "as_of": cached["as_of"], **cached["data"]}


async def compute_commodities(request: Request) -> list[dict]:
    """MCX commodity LTP in INR — from the live Dhan feed's Redis ltp cache, not a
    third-party library."""
    settings = get_settings()
    redis = request.app.state.redis
    out: list[dict] = []
    for symbol, name, settings_attr in _MCX_COMMODITIES:
        sid = getattr(settings, settings_attr, "")
        if not sid:
            out.append({"symbol": symbol, "name": name, "available": False})
            continue
        raw_ltp = await redis.get(f"ltp:{sid}")
        if raw_ltp is None:
            out.append({"symbol": symbol, "name": name, "available": False, "security_id": sid})
            continue
        out.append({
            "symbol": symbol, "name": name, "available": True,
            "security_id": sid, "ltp": float(raw_ltp),
        })
    return out


async def compute_vix(request: Request) -> dict:
    settings = get_settings()
    redis = request.app.state.redis
    raw_ltp = await redis.get(f"ltp:{settings.VIX_SECURITY_ID}")
    if raw_ltp is None:
        return {"available": False, "security_id": settings.VIX_SECURITY_ID}
    return {"available": True, "security_id": settings.VIX_SECURITY_ID, "value": float(raw_ltp)}


async def compute_next_expiry() -> dict:
    """Next tradeable expiry per index, resolved from the instruments table (real Dhan scrip
    master) — never a projected weekday calendar. Each index degrades to ``None`` (→
    ``available: false``) when the table has no upcoming expiry, rather than fabricating a date.
    """
    from pdp.db.session import get_session_maker
    from pdp.strategy.strikes import nearest_expiry

    result: dict[str, str | None] = {}
    session_maker = get_session_maker()
    async with session_maker() as session:
        for underlying in _EXPIRY_UNDERLYINGS:
            try:
                expiry = await nearest_expiry(session, underlying)
                result[underlying] = expiry.isoformat() if expiry else None
            except Exception as exc:
                log.warning("next_expiry_resolve_failed", underlying=underlying, exc=str(exc))
                result[underlying] = None
    return {"available": any(v is not None for v in result.values()), "expiries": result}
