from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

import msgspec
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from pdp.strategy.host import AlreadyRunning, NotRunning, StrategyHost
from pdp.strategy.schemas import strategy_info_from_dict

router = APIRouter(prefix="/api/v1/strategies", tags=["strategies"])
strangle_router = APIRouter(prefix="/api/v1/strangle", tags=["strangle"])
levels_router = APIRouter(prefix="/api/v1/levels", tags=["levels"])

# Spot security IDs for the three tracked indices
_INDEX_SIDS: dict[str, str] = {
    "NIFTY": "13",
    "BANKNIFTY": "25",
    "SENSEX": "51",
}
# Reverse map
_SID_TO_INDEX: dict[str, str] = {v: k for k, v in _INDEX_SIDS.items()}

# Indicator timeframes for the matrix
_MATRIX_TFS: list[str] = ["5m", "15m", "30m", "1H", "1D"]


def _host(request: Request) -> StrategyHost:
    return request.app.state.strategy_host


def _serialise(obj: Any) -> Any:
    """Recursively convert non-JSON types (Decimal, datetime, date) to JSON-safe values."""
    if isinstance(obj, dict):
        return {k: _serialise(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_serialise(v) for v in obj]
    try:
        from decimal import Decimal
        if isinstance(obj, Decimal):
            return float(obj)
    except ImportError:
        pass
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    return obj


@router.get("")
async def list_strategies(request: Request) -> JSONResponse:
    host = _host(request)
    items = [strategy_info_from_dict(d) for d in host.list_all()]
    return JSONResponse(content={"strategies": msgspec.to_builtins(items)})


@router.post("/{strategy_id}/start")
async def start_strategy(strategy_id: str, request: Request) -> JSONResponse:
    host = _host(request)
    try:
        await host.start(strategy_id)
    except AlreadyRunning as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (ImportError, FileNotFoundError, ValueError, ValidationError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    items = [d for d in host.list_all() if d["id"] == strategy_id]
    if items:
        info = strategy_info_from_dict(items[0])
        return JSONResponse(content=msgspec.to_builtins(info))
    return JSONResponse(content={"id": strategy_id, "status": "RUNNING"})


@router.post("/{strategy_id}/stop")
async def stop_strategy(strategy_id: str, request: Request) -> JSONResponse:
    host = _host(request)
    try:
        await host.stop(strategy_id)
    except NotRunning as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return JSONResponse(content={"id": strategy_id, "status": "STOPPED"})


# ------------------------------------------------------------------ #
# Strangle execution console — read-only API                          #
# ------------------------------------------------------------------ #

def _get_strangle(request: Request, strategy_id: str | None = None):
    from pdp.strategies.directional_strangle import DirectionalStrangle
    host: StrategyHost = request.app.state.strategy_host
    for sid, state in host._running.items():
        if isinstance(state.instance, DirectionalStrangle):
            if strategy_id is None or sid == strategy_id:
                return state.instance
    detail = (
        f"DirectionalStrangle '{strategy_id}' not running"
        if strategy_id else "DirectionalStrangle not running"
    )
    raise HTTPException(status_code=404, detail=detail)


@strangle_router.get("/status")
async def strangle_status(
    request: Request,
    strategy_id: str | None = Query(default=None),
) -> JSONResponse:
    strategy = _get_strangle(request, strategy_id)
    data = await strategy.state()
    return JSONResponse(content=data)


@strangle_router.get("/legs")
async def strangle_legs(
    request: Request,
    strategy_id: str | None = Query(default=None),
) -> JSONResponse:
    strategy = _get_strangle(request, strategy_id)
    data = await strategy.state()
    return JSONResponse(content={"legs": data["legs"]})


@strangle_router.get("/activity")
async def strangle_activity(
    request: Request,
    n: int = Query(default=50, ge=1, le=200),
    strategy_id: str | None = Query(default=None),
) -> JSONResponse:
    strategy = _get_strangle(request, strategy_id)
    events = list(strategy._activity)
    events.reverse()       # newest-first
    return JSONResponse(content={"events": events[:n], "total": len(events)})


@strangle_router.get("/stats")
async def strangle_stats(
    request: Request,
    strategy_id: str | None = Query(default=None),
) -> JSONResponse:
    strategy = _get_strangle(request, strategy_id)
    data = await strategy.state()
    open_pe_lots = sum(lg["lots"] for lg in data["legs"]
                       if not lg["is_hedge"] and not lg["is_momentum"] and lg["opt_type"] == "PE")
    open_ce_lots = sum(lg["lots"] for lg in data["legs"]
                       if not lg["is_hedge"] and not lg["is_momentum"] and lg["opt_type"] == "CE")
    open_hedge_lots = sum(lg["lots"] for lg in data["legs"] if lg["is_hedge"])
    trade_count = sum(1 for e in strategy._activity if e.get("event_type") in ("leg_close", "take_profit"))
    return JSONResponse(content={
        "day_realized": data["day_realized"],
        "day_unrealized": data["day_unrealized"],
        "day_pnl": data["day_pnl"],
        "trade_count": trade_count,
        "open_pe_lots": open_pe_lots,
        "open_ce_lots": open_ce_lots,
        "open_hedge_lots": open_hedge_lots,
    })


# ------------------------------------------------------------------ #
# Strangle realtime monitor — GET /api/v1/strangle/monitor            #
# ------------------------------------------------------------------ #

async def _get_ltp_redis(redis: Any, security_id: str) -> float | None:
    """Read LTP from Redis ltp:{sid} hash. Returns None if not found."""
    try:
        val = await redis.get(f"ltp:{security_id}")
        return float(val) if val is not None else None
    except Exception:
        return None


async def _get_greeks_for_strike(
    chains_col: Any,
    underlying: str,
    strike: float,
    opt_type: str,
    day_start_ts: datetime | None = None,
) -> dict[str, Any]:
    """Read delta/vega/gamma/theta/OI/PCR from the latest option_chains snapshot."""
    result: dict[str, Any] = {
        "delta": None, "vega": None, "gamma": None, "theta": None,
        "oi": None, "pcr": None, "oi_change_day": None,
    }
    if chains_col is None:
        return result

    try:
        # Latest snapshot for this underlying
        doc = await chains_col.find_one(
            {"underlying": underlying.upper()},
            sort=[("snapshot_ts", -1)],
        )
        if doc is None:
            return result

        strikes_data = doc.get("strikes", [])
        # Find matching strike row
        strike_row = next(
            (s for s in strikes_data if abs(float(s.get("strike", 0)) - strike) < 0.01),
            None,
        )
        if strike_row is None:
            return result

        side = strike_row.get(opt_type.lower(), {})
        result["delta"] = side.get("delta")
        result["vega"] = side.get("vega")
        result["gamma"] = side.get("gamma")
        result["theta"] = side.get("theta")
        result["oi"] = side.get("oi")

        # PCR for this strike
        from pdp.options.analytics import compute_pcr
        result["pcr"] = compute_pcr([strike_row])

        # OI change since day start
        if day_start_ts and result["oi"] is not None:
            earliest = await chains_col.find_one(
                {
                    "underlying": underlying.upper(),
                    "snapshot_ts": {"$gte": day_start_ts},
                },
                sort=[("snapshot_ts", 1)],
            )
            if earliest:
                e_strikes = earliest.get("strikes", [])
                e_row = next(
                    (s for s in e_strikes if abs(float(s.get("strike", 0)) - strike) < 0.01),
                    None,
                )
                if e_row:
                    e_oi = e_row.get(opt_type.lower(), {}).get("oi")
                    if e_oi is not None:
                        result["oi_change_day"] = result["oi"] - e_oi

    except Exception:  # noqa: S110
        pass

    return result


def _build_indicator_cell(engine: Any, sid: str, tf: str) -> dict[str, Any]:
    """Build one indicator cell for (sid, tf)."""
    cell: dict[str, Any] = {}
    if engine is None:
        return cell

    # EMA
    ema_state = engine.get_ema(sid, tf)
    if ema_state:
        cell["ema9"] = ema_state.values.get(9)
        cell["ema20"] = ema_state.values.get(20)
        cell["ema50"] = ema_state.values.get(50)
        cell["ema100"] = ema_state.values.get(100)

    # SuperTrend
    st_state = engine.get(sid, tf)
    if st_state:
        cell["st_val"] = float(st_state.value) if st_state.value else None
        cell["st_dir"] = "up" if st_state.direction == 1 else "down"

    # PSAR
    psar_state = engine.get_psar(sid, tf)
    if psar_state:
        cell["psar"] = psar_state.sar

    return cell


def _build_pivot_cells(engine: Any, sid: str) -> dict[str, Any]:
    """Build per-session Camarilla + period level constants for one security_id."""
    result: dict[str, Any] = {}
    if engine is None:
        return result

    # Daily Camarilla (from 5m pivot snapshot — pivots computed once per session)
    daily_pivot = engine.get_pivots(sid, "5m")
    if daily_pivot:
        result["camarilla_daily"] = {
            "pp": daily_pivot.cam_pp, "r3": daily_pivot.cam_r3, "r4": daily_pivot.cam_r4,
            "s3": daily_pivot.cam_s3, "s4": daily_pivot.cam_s4,
        }

    # Weekly Camarilla (from 1w pivot snapshot)
    weekly_pivot = engine.get_pivots(sid, "1w")
    if weekly_pivot:
        result["camarilla_weekly"] = {
            "pp": weekly_pivot.cam_pp, "r3": weekly_pivot.cam_r3, "r4": weekly_pivot.cam_r4,
            "s3": weekly_pivot.cam_s3, "s4": weekly_pivot.cam_s4,
        }

    # Period levels (PDH/PDL/PWH/PWL)
    pl = engine.get_period_levels(sid, "5m")
    if pl:
        result["period"] = {
            "pdh": pl.pdh, "pdl": pl.pdl,
            "pwh": pl.pwh, "pwl": pl.pwl,
        }

    return result


@strangle_router.get("/monitor")
async def strangle_monitor(
    request: Request,
    strategy_id: str | None = Query(default=None),
    n_events: int = Query(default=20, ge=1, le=100),
) -> JSONResponse:
    """Realtime directional-strangle monitor snapshot.

    Returns a single JSON doc with:
    - indices: spot+future LTP for NIFTY/BANKNIFTY/SENSEX
    - groups: legs grouped by underlying with entry metadata + Greeks
    - totals: per-index and overall P&L
    - status: bucket/score/done_for_day/session metadata
    - recent_events: last N from _activity (closed legs + exit reasons)
    - indicators: EMA/ST/PSAR matrix x timeframes + Camarilla + period levels
    """
    from pdp.strategies.directional_strangle import DirectionalStrangle
    host = request.app.state.strategy_host
    strategies = []
    for sid, state_obj in host._running.items():
        if isinstance(state_obj.instance, DirectionalStrangle):
            if strategy_id is None or sid == strategy_id:
                strategies.append(state_obj.instance)

    if not strategies:
        raise HTTPException(status_code=404, detail="No DirectionalStrangle running")

    redis = request.app.state.redis
    engine = getattr(request.app.state, "indicator_engine", None)
    chains_col = (
        request.app.state.mongo_db["option_chains"]
        if hasattr(request.app.state, "mongo_db")
        else None
    )

    states = [await s.state() for s in strategies]

    # ── Indices spot + future LTPs ──────────────────────────────────────────
    indices: dict[str, dict[str, Any]] = {}
    for idx_name, idx_sid in _INDEX_SIDS.items():
        spot_ltp = await _get_ltp_redis(redis, idx_sid)
        # Try to resolve futures SID from strategy (only works for the strategy's underlying)
        future_ltp = None
        for s in strategies:
            futures_sid = getattr(s, "_futures_sid", None)
            if futures_sid and _SID_TO_INDEX.get(idx_sid) == s.underlying:
                future_ltp = await _get_ltp_redis(redis, futures_sid)
                break
        indices[idx_name] = {"spot": spot_ltp or 0.0, "future": future_ltp}

    # ── Legs grouped by underlying ──────────────────────────────────────────
    today_ist_start = datetime.now(UTC).replace(
        hour=3, minute=45, second=0, microsecond=0,
    )

    legs_by_underlying: dict[str, list[dict[str, Any]]] = {}
    unrealized_by_underlying: dict[str, float] = {}
    active_strike_sids = set()

    for strategy, state in zip(strategies, states):
        und = strategy.underlying  # all legs under same underlying for now
        for leg in state["legs"]:
            leg_enriched = dict(leg)
    
            # Greeks/OI/PCR only for active non-hedge strikes
            if not leg["is_hedge"] and not leg["is_momentum"]:
                active_strike_sids.add(leg["security_id"])
                greeks = await _get_greeks_for_strike(
                    chains_col,
                    underlying=und,
                    strike=leg["strike"],
                    opt_type=leg["opt_type"],
                    day_start_ts=today_ist_start,
                )
                leg_enriched.update(greeks)
    
            legs_by_underlying.setdefault(und, []).append(leg_enriched)
            unrealized_by_underlying[und] = (
                unrealized_by_underlying.get(und, 0.0) + (leg["mtm"] or 0.0)
            )

    groups = [
        {
            "underlying": und,
            "legs": legs,
            "totals": {
                "day_realized": 0.0,  # per-index realized not tracked separately
                "day_unrealized": unrealized_by_underlying.get(und, 0.0),
                "day_pnl": unrealized_by_underlying.get(und, 0.0),
            },
            "status": underlying_status.get(und, {}),
        }
        for und, legs in legs_by_underlying.items()
    ]

    # ── Overall totals ──────────────────────────────────────────────────────
    totals = {
        "day_realized": sum(s.get("day_realized", 0.0) for s in states),
        "day_unrealized": sum(s.get("day_unrealized", 0.0) for s in states),
        "day_pnl": sum(s.get("day_pnl", 0.0) for s in states),
    }

    # ── Status — per-underlying + overall ──────────────────────────────────
    primary_state = next(
        (s for s_idx, s in enumerate(states) if strategies[s_idx].underlying == "NIFTY"),
        states[0]
    )
    # Per-underlying status so Flutter can show individual buckets/scores
    underlying_status = {
        strategies[i].underlying: {
            "bucket": s.get("bucket"),   # None → JSON null (Flutter shows '--')
            "score": s.get("score"),
            "done_for_day": s.get("done_for_day", False),
            "n_open_shorts": s.get("n_open_shorts", 0),
            "n_open_hedges": s.get("n_open_hedges", 0),
        }
        for i, s in enumerate(states)
    }
    status = {
        "bucket": primary_state.get("bucket"),   # None → JSON null, not "None" string
        "score": primary_state.get("score"),
        "done_for_day": all(s.get("done_for_day", False) for s in states),
        "started_at": primary_state.get("started_at"),
        "n_open_shorts": sum(s.get("n_open_shorts", 0) for s in states),
        "n_open_hedges": sum(s.get("n_open_hedges", 0) for s in states),
        "n_open_momentum": sum(s.get("n_open_momentum", 0) for s in states),
        "by_underlying": underlying_status,
    }

    # ── Recent events (newest-first, closed legs + exit reasons) ───────────
    all_events = []
    for s in strategies:
        all_events.extend(list(s._activity))
    
    # Sort events by ts (descending)
    all_events.sort(key=lambda x: x.get("ts", "") or x.get("timestamp", ""), reverse=True)
    recent_events = all_events[:n_events]

    # ── Indicator matrix ────────────────────────────────────────────────────
    # Covers 3 index sids + active non-hedge strike sids
    matrix_sids = list(_INDEX_SIDS.values()) + [
        s for s in active_strike_sids if s not in _INDEX_SIDS.values()
    ]

    indicators: dict[str, Any] = {}
    for sid in matrix_sids:
        sid_data: dict[str, Any] = {}
        tf_data: dict[str, Any] = {}
        for tf in _MATRIX_TFS:
            tf_data[tf] = _build_indicator_cell(engine, sid, tf)
        sid_data["tf"] = tf_data
        sid_data.update(_build_pivot_cells(engine, sid))
        indicators[sid] = sid_data

    payload = {
        "indices": indices,
        "groups": groups,
        "totals": totals,
        "status": status,
        "recent_events": recent_events,
        "indicators": indicators,
    }
    return JSONResponse(content=_serialise(payload))


# ------------------------------------------------------------------ #
# Levels warehouse — GET /api/v1/levels/{underlying}                  #
# ------------------------------------------------------------------ #

@levels_router.get("/{underlying}")
async def get_levels(
    request: Request,
    underlying: str,
    period: str = Query(default="daily", regex="^(daily|weekly)$"),
    date: str | None = Query(default=None, description="YYYY-MM-DD (single doc)"),
    start: str | None = Query(default=None, description="YYYY-MM-DD range start"),
    end: str | None = Query(default=None, description="YYYY-MM-DD range end"),
) -> JSONResponse:
    """Fetch persisted price levels from index_levels.

    Single-doc mode:  ?period=daily&date=2026-06-30
    Range mode:       ?period=weekly&start=2026-01-01&end=2026-06-30
    """
    from pdp.indicators.levels_store import LevelsStore

    # Resolve underlying → security_id
    uid = underlying.upper()
    security_id = _INDEX_SIDS.get(uid)
    if security_id is None:
        raise HTTPException(status_code=422, detail=f"Unknown underlying: {underlying}")

    col = request.app.state.mongo_db["index_levels"]
    store = LevelsStore(col)

    if date:
        from datetime import date as date_type
        session_date = date_type.fromisoformat(date)
        doc = await store.get(security_id, period, session_date)
        if doc is None:
            raise HTTPException(
                status_code=404,
                detail=f"No {period} levels for {uid} on {date}",
            )
        return JSONResponse(content=_serialise(doc))

    # Range mode
    from datetime import date as date_type
    start_d = date_type.fromisoformat(start) if start else date_type.today().replace(day=1)
    end_d = date_type.fromisoformat(end) if end else date_type.today()
    docs = await store.range(security_id, period, start_d, end_d)
    return JSONResponse(content={"docs": [_serialise(d) for d in docs], "count": len(docs)})

