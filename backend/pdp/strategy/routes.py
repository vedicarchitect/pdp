from __future__ import annotations

import dataclasses
import json
from datetime import UTC, date, datetime, timedelta
from typing import Any

import msgspec
import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ValidationError

from pdp.deps import parse_ist_date, require_auth
from pdp.strategy import unified_registry
from pdp.strategy.host import AlreadyRunning, NotRunning, StrategyHost
from pdp.strategy.schemas import (
    strategy_info_from_dict,
    StrategyListOut,
    StrategyRegisterOut,
    StrategyActionOut,
    StrangleStatusOut,
    StrangleLegsOut,
    StrangleActivityOut,
    StrangleStatsOut,
    StranglePnlOut,
    StrangleTradesOut,
    StrangleMonitorOut,
    LevelsResponseOut,
)

log = structlog.get_logger()

router = APIRouter(prefix="/api/v1/strategies", tags=["strategies"])
strangle_router = APIRouter(prefix="/api/v1/strangle", tags=["strangle"])
levels_router = APIRouter(prefix="/api/v1/levels", tags=["levels"])

# Spot security IDs for the three tracked indices
_INDEX_SIDS: dict[str, str] = {
    "NIFTY": "13",
    "BANKNIFTY": "25",
    "SENSEX": "51",
}

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


@router.get("", response_model=StrategyListOut)
async def list_strategies(request: Request) -> StrategyListOut:
    """List every registered strategy — live-host state merged with the unified registry.

    Each entry carries the canonical id, engine/kind, underlying, and editable param schema
    (name/type/default/bounds) from `pdp.strategy.unified_registry`, plus live-host status for
    strategies that also have a `strategies/*.yaml` config. Backtest-only strategies (no live
    counterpart) get `status: "BACKTEST_ONLY"`.
    """
    host = _host(request)
    live_by_id = {d["id"]: d for d in host.list_all()}
    strategies: list[dict[str, Any]] = []
    for entry in unified_registry.load_all(strategies_dir=host.strategies_dir):
        live = live_by_id.get(entry.id)
        strategies.append(
            {
                "id": entry.id,
                "kind": entry.kind,
                "underlying": entry.underlying,
                "source": entry.source,
                "status": str(live["status"]) if live else "BACKTEST_ONLY",
                "dropped_ticks": live["dropped_ticks"] if live else 0,
                "watchlist": live["watchlist"] if live else [],
                "params_schema": [dataclasses.asdict(p) for p in entry.params_schema],
                "defaults": entry.defaults,
            }
        )
    return StrategyListOut(strategies=strategies)


class RegisterStrategyRequest(BaseModel):
    strategy_id: str
    kind: str  # "strangle" | "supertrend"
    params: dict[str, Any]


@router.post("/register", response_model=StrategyRegisterOut, status_code=201, dependencies=[Depends(require_auth)])
async def register_strategy(body: RegisterStrategyRequest) -> StrategyRegisterOut:
    """Register a new strategy config, immediately visible in `GET /api/v1/strategies` and
    usable as a `POST /api/v1/strangle-backtests/runs` launch target — no code change needed.
    """
    try:
        entry = unified_registry.register_strategy(body.strategy_id, body.kind, body.params)
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return StrategyRegisterOut(
        id=entry.id,
        kind=entry.kind,
        underlying=entry.underlying,
        source=entry.source,
        params_schema=[dataclasses.asdict(p) for p in entry.params_schema],
        defaults=entry.defaults,
    )


@router.post("/{strategy_id}/start", response_model=StrategyActionOut, dependencies=[Depends(require_auth)])
async def start_strategy(strategy_id: str, request: Request) -> StrategyActionOut:
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
        return StrategyActionOut(**msgspec.to_builtins(info))
    return StrategyActionOut(id=strategy_id, status="RUNNING")


@router.post("/{strategy_id}/stop", response_model=StrategyActionOut, dependencies=[Depends(require_auth)])
async def stop_strategy(strategy_id: str, request: Request) -> StrategyActionOut:
    host = _host(request)
    try:
        await host.stop(strategy_id)
    except NotRunning as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return StrategyActionOut(id=strategy_id, status="STOPPED")


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
        if strategy_id
        else "DirectionalStrangle not running"
    )
    raise HTTPException(status_code=404, detail=detail)


@strangle_router.get("/status", response_model=StrangleStatusOut)
async def strangle_status(
    request: Request,
    strategy_id: str | None = Query(default=None),
) -> StrangleStatusOut:
    strategy = _get_strangle(request, strategy_id)
    data = await strategy.state()
    return StrangleStatusOut(**data)


@strangle_router.get("/legs", response_model=StrangleLegsOut)
async def strangle_legs(
    request: Request,
    strategy_id: str | None = Query(default=None),
) -> StrangleLegsOut:
    strategy = _get_strangle(request, strategy_id)
    data = await strategy.state()
    return StrangleLegsOut(legs=data["legs"])


@strangle_router.get("/activity", response_model=StrangleActivityOut)
async def strangle_activity(
    request: Request,
    n: int = Query(default=50, ge=1, le=200),
    strategy_id: str | None = Query(default=None),
) -> StrangleActivityOut:
    strategy = _get_strangle(request, strategy_id)
    events = list(strategy._activity)
    events.reverse()  # newest-first
    return StrangleActivityOut(events=events[:n], total=len(events))


@strangle_router.get("/stats", response_model=StrangleStatsOut)
async def strangle_stats(
    request: Request,
    strategy_id: str | None = Query(default=None),
) -> StrangleStatsOut:
    strategy = _get_strangle(request, strategy_id)
    data = await strategy.state()
    open_pe_lots = sum(
        lg["lots"]
        for lg in data["legs"]
        if not lg["is_hedge"] and not lg["is_momentum"] and lg["opt_type"] == "PE"
    )
    open_ce_lots = sum(
        lg["lots"]
        for lg in data["legs"]
        if not lg["is_hedge"] and not lg["is_momentum"] and lg["opt_type"] == "CE"
    )
    open_hedge_lots = sum(lg["lots"] for lg in data["legs"] if lg["is_hedge"])
    trade_count = sum(1 for e in strategy._activity if e.get("event_type") in ("leg_close", "take_profit"))
    return StrangleStatsOut(
        day_realized=data["day_realized"],
        day_unrealized=data["day_unrealized"],
        day_pnl=data["day_pnl"],
        trade_count=trade_count,
        open_pe_lots=open_pe_lots,
        open_ce_lots=open_ce_lots,
        open_hedge_lots=open_hedge_lots,
    )


@strangle_router.get("/pnl", response_model=StranglePnlOut)
async def strangle_pnl(request: Request) -> StranglePnlOut:
    """Per-index live P&L breakdown — the ONLY P&L source for dashboard + Execution tab.

    Returns one row per running strangle strategy (grouped by underlying) plus a
    totals object summing across indices.  `squared_off_at` is the IST time of
    the terminal square_off/day_loss_cap event for that index today.
    """
    from pdp.strategies.directional_strangle import DirectionalStrangle

    host: StrategyHost = request.app.state.strategy_host
    strategies = [
        state.instance for state in host._running.values() if isinstance(state.instance, DirectionalStrangle)
    ]
    if not strategies:
        raise HTTPException(status_code=404, detail="No DirectionalStrangle running")

    rows: list[dict[str, Any]] = []
    total_realized = 0.0
    total_unrealized = 0.0
    total_pnl = 0.0
    total_open = 0

    for strategy in strategies:
        data = await strategy.state()
        # Resolve squared_off_at from the activity ring buffer
        squared_off_at: str | None = None
        for evt in reversed(list(strategy._activity)):
            if evt.get("event_type") in ("square_off", "day_loss_cap"):
                squared_off_at = evt.get("ist_time")
                break

        row = {
            "underlying": data.get("underlying", strategy.underlying),
            "strategy_id": data["strategy_id"],
            "day_realized": data["day_realized"],
            "day_unrealized": data["day_unrealized"],
            "day_pnl": data["day_pnl"],
            "n_open_legs": data["n_open_legs"],
            "done_for_day": data["done_for_day"],
            "squared_off_at": squared_off_at,
        }
        rows.append(row)
        total_realized += data["day_realized"]
        total_unrealized += data["day_unrealized"]
        total_pnl += data["day_pnl"]
        total_open += data["n_open_legs"]

    return StranglePnlOut(
        by_index=rows,
        totals={
            "day_realized": round(total_realized, 2),
            "day_unrealized": round(total_unrealized, 2),
            "day_pnl": round(total_pnl, 2),
            "n_open_legs": total_open,
        },
    )


@strangle_router.get("/trades", response_model=StrangleTradesOut)
async def strangle_trades(
    request: Request,
    strategy_id: str | None = Query(default=None),
    date: str | None = Query(default=None, description="YYYY-MM-DD; defaults to today IST"),
) -> StrangleTradesOut:
    """Per-day entry→exit trade ledger grouped by index.

    Pairs each leg_open with its terminal close event from the durable Mongo
    events collection (DB-first), falling back to the JSONL log file when the
    durable source is empty (pre-migration days or Mongo unavailable).

    Returns round-trip rows with full economics; open legs have null exit fields.
    Unresolved symbols are lazily resolved before returning.
    """
    from datetime import date as date_type

    from pdp.instruments.symbols import symbol_for
    from pdp.mongo.collections import get_events_collection
    from pdp.strategies.directional_strangle import DirectionalStrangle
    from pdp.strategy.trade_ledger import (
        compute_totals,
        group_by_index,
        pair_trades,
        read_durable_day_events,
    )

    query_date = parse_ist_date(date)

    # Resolve Mongo collection from app state (graceful None if not available)
    mongo_col = None
    try:
        mongo_db = getattr(request.app.state, "mongo_db", None)
        if mongo_db is not None:
            mongo_col = get_events_collection(mongo_db)
    except Exception:
        pass

    host: StrategyHost = request.app.state.strategy_host
    strategies = [
        (sid, state.instance)
        for sid, state in host._running.items()
        if isinstance(state.instance, DirectionalStrangle) and (strategy_id is None or sid == strategy_id)
    ]

    all_rows: list[dict[str, Any]] = []
    for sid, strategy in strategies:
        events = await read_durable_day_events(sid, query_date, mongo_collection=mongo_col)
        rows = pair_trades(events)
        # Lazy symbol resolution for rows with symbol=null
        for row in rows:
            if row.get("symbol") is None and row.get("expiry") and row.get("strike"):
                raw_expiry = row["expiry"]
                exp = date_type.fromisoformat(raw_expiry) if isinstance(raw_expiry, str) else raw_expiry
                und = row.get("underlying") or strategy.underlying
                ot = row.get("opt_type", "PE")
                try:
                    row["symbol"] = symbol_for(und, exp, row["strike"], ot)
                except Exception as exc:
                    log.warning(
                        "strangle_trades_symbol_resolve_failed",
                        sid=row.get("security_id"),
                        exc=str(exc),
                    )
        all_rows.extend(rows)

    by_index = group_by_index(all_rows)
    totals = compute_totals(all_rows)

    res = _serialise(
        {
            "date": query_date.isoformat(),
            "by_index": by_index,
            "totals": totals,
        }
    )
    return StrangleTradesOut(**res)



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
        "delta": None,
        "vega": None,
        "gamma": None,
        "theta": None,
        "oi": None,
        "pcr": None,
        "oi_change_day": None,
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


def _build_indicator_cell_inproc(engine: Any, sid: str, tf: str, fut_sid: str | None = None) -> dict[str, Any]:
    """Build one indicator cell for (sid, tf) from the in-process ``IndicatorEngine``.

    Price-based indicators (EMA/ST/PSAR/RSI) are read from the spot ``sid``; the
    volume-anchored VWAP/VWMA are read from ``fut_sid`` (the index futures contract)
    when provided, since spot indices carry no tradeable volume.
    """
    cell: dict[str, Any] = {}
    if engine is None:
        return cell

    # EMA (9/20/50/100/200)
    ema_state = engine.get_ema(sid, tf)
    if ema_state:
        cell["ema9"] = ema_state.values.get(9)
        cell["ema20"] = ema_state.values.get(20)
        cell["ema50"] = ema_state.values.get(50)
        cell["ema100"] = ema_state.values.get(100)
        cell["ema200"] = ema_state.values.get(200)

    # SuperTrend (engine-wide ST(10,2))
    st_state = engine.get(sid, tf)
    if st_state:
        cell["st_val"] = float(st_state.value) if st_state.value else None
        cell["st_dir"] = "up" if st_state.direction == 1 else "down"

    # PSAR
    psar_state = engine.get_psar(sid, tf)
    if psar_state:
        cell["psar"] = psar_state.sar

    # RSI + SMA signal
    rsi_state = engine.get_rsi(sid, tf)
    if rsi_state:
        cell["rsi"] = rsi_state.rsi
        cell["rsi_ma"] = rsi_state.ma

    # VWAP / VWMA — from the futures contract (volume-anchored)
    vwap_src = fut_sid or sid
    vwap_state = engine.get_vwap(vwap_src, tf)
    if vwap_state:
        cell["vwap"] = vwap_state.vwap
    vwma_state = engine.get_vwma(vwap_src, tf)
    if vwma_state:
        cell["vwma"] = vwma_state.vwma

    return cell


async def _build_indicator_cell_from_redis(redis: Any, sid: str, tf: str, fut_sid: str | None = None) -> dict[str, Any]:
    """Build one indicator cell for (sid, tf) from the ``ind:<sid>:<tf>`` / ``st:<sid>:<tf>``
    Redis snapshots published by the engine process (``market/router.py`` on bar close).

    Used when no in-process ``IndicatorEngine`` is attached (``pdp-api`` role, decoupled from
    ``pdp-engine``) — see ``api-worker-decoupling`` requirement "Engine-published state
    snapshots". Field layout mirrors ``_build_indicator_cell_inproc`` exactly.
    """
    cell: dict[str, Any] = {}
    if redis is None:
        return cell

    vwap_src = fut_sid or sid
    try:
        ind_raw = await redis.get(f"ind:{sid}:{tf}")
        st_raw = await redis.get(f"st:{sid}:{tf}")
        vwap_raw = ind_raw if vwap_src == sid else await redis.get(f"ind:{vwap_src}:{tf}")
    except Exception as exc:
        log.warning("indicator_redis_snapshot_read_failed", sid=sid, tf=tf, exc=str(exc))
        return cell

    if ind_raw:
        snap = json.loads(ind_raw)
        ema = snap.get("ema") or {}
        if ema:
            cell["ema9"] = ema.get("9")
            cell["ema20"] = ema.get("20")
            cell["ema50"] = ema.get("50")
            cell["ema100"] = ema.get("100")
            cell["ema200"] = ema.get("200")
        psar = snap.get("psar")
        if psar:
            cell["psar"] = psar.get("sar")
        if "rsi" in snap:
            cell["rsi"] = snap.get("rsi")
        if "rsi_ma" in snap:
            cell["rsi_ma"] = snap.get("rsi_ma")

    if st_raw:
        st = json.loads(st_raw)
        if st.get("value") is not None:
            cell["st_val"] = float(st["value"])
        cell["st_dir"] = "up" if st.get("direction") == 1 else "down"

    if vwap_raw:
        vwap_snap = json.loads(vwap_raw)
        if "vwap" in vwap_snap:
            cell["vwap"] = vwap_snap.get("vwap")
        if "vwma" in vwap_snap:
            cell["vwma"] = vwap_snap.get("vwma")

    return cell


async def _build_indicator_cell(
    engine: Any, redis: Any, sid: str, tf: str, fut_sid: str | None = None
) -> dict[str, Any]:
    """Build one indicator cell, preferring the in-process engine (zero-latency, ``all``/
    ``engine`` role) and falling back to the Redis snapshot when no engine is attached
    (``pdp-api`` role — see api-worker-decoupling's "Engine-published state snapshots").
    """
    if engine is not None:
        return _build_indicator_cell_inproc(engine, sid, tf, fut_sid)
    return await _build_indicator_cell_from_redis(redis, sid, tf, fut_sid)


async def _get_matrix_futures_sids(engine: Any, redis: Any) -> dict[str, str]:
    """Index sid → front-month futures sid, from the in-process engine or its Redis mirror
    (``matrix:futures_sids``, published once at startup by ``FeedEngineGroup``)."""
    in_proc = getattr(engine, "matrix_futures_sids", None)
    if in_proc:
        return in_proc
    try:
        raw = await redis.get("matrix:futures_sids")
    except Exception:
        return {}
    return json.loads(raw) if raw else {}


async def _build_levels_cells(store: Any, sid: str, session_date: date) -> dict[str, Any]:
    """Build Camarilla + period levels for one security_id from the persisted warehouse.

    Reads daily / weekly / monthly docs from ``index_levels`` (LevelsStore) — the
    single correct source computed once per session/week/month — instead of the
    drifting live indicator-engine snapshot. TF→period mapping (5m/15m→daily,
    30m/1H→weekly, 1D→monthly) is applied client-side.
    """
    result: dict[str, Any] = {}
    if store is None:
        return result

    def _cam(doc: dict[str, Any] | None) -> dict[str, Any] | None:
        if not doc:
            return None
        c = doc.get("camarilla") or {}
        return {
            "pp": c.get("pp"),
            "r3": c.get("r3"),
            "r4": c.get("r4"),
            "s3": c.get("s3"),
            "s4": c.get("s4"),
        }

    daily = await store.get(sid, "daily", session_date)
    weekly = await store.get(sid, "weekly", session_date)
    monthly = await store.get(sid, "monthly", session_date)

    if (cam := _cam(daily)) is not None:
        result["camarilla_daily"] = cam
    if (cam := _cam(weekly)) is not None:
        result["camarilla_weekly"] = cam
    if (cam := _cam(monthly)) is not None:
        result["camarilla_monthly"] = cam

    d_src = (daily or {}).get("source") or {}
    w_src = (weekly or {}).get("source") or {}
    m_src = (monthly or {}).get("source") or {}
    result["period"] = {
        "pdh": d_src.get("h"),
        "pdl": d_src.get("l"),
        "pwh": w_src.get("h"),
        "pwl": w_src.get("l"),
        "pmh": m_src.get("h"),
        "pml": m_src.get("l"),
    }

    return result


@strangle_router.get("/monitor", response_model=StrangleMonitorOut)
async def strangle_monitor(
    request: Request,
    strategy_id: str | None = Query(default=None),
    n_events: int = Query(default=20, ge=1, le=100),
) -> StrangleMonitorOut:
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
        request.app.state.mongo_db["option_chains"] if hasattr(request.app.state, "mongo_db") else None
    )

    states = [await s.state() for s in strategies]

    # ── Indices spot + future LTPs ──────────────────────────────────────────
    # Futures SID comes from the matrix's startup-resolved map (configure_matrix_suites),
    # not the strategy (bias-scoring dropped its own futures-SID path in backtest-paper-parity).
    matrix_fut_sids: dict[str, str] = await _get_matrix_futures_sids(engine, redis)
    indices: dict[str, dict[str, Any]] = {}
    for idx_name, idx_sid in _INDEX_SIDS.items():
        spot_ltp = await _get_ltp_redis(redis, idx_sid)
        futures_sid = matrix_fut_sids.get(idx_sid)
        future_ltp = await _get_ltp_redis(redis, futures_sid) if futures_sid else None
        indices[idx_name] = {"spot": spot_ltp or 0.0, "future": future_ltp}

    # ── Legs grouped by underlying ──────────────────────────────────────────
    today_ist_start = datetime.now(UTC).replace(
        hour=3,
        minute=45,
        second=0,
        microsecond=0,
    )

    legs_by_underlying: dict[str, list[dict[str, Any]]] = {}
    unrealized_by_underlying: dict[str, float] = {}

    for strategy, state in zip(strategies, states, strict=False):
        und = strategy.underlying  # all legs under same underlying for now
        for leg in state["legs"]:
            leg_enriched = dict(leg)

            # Greeks/OI/PCR only for active non-hedge strikes
            if not leg["is_hedge"] and not leg["is_momentum"]:
                greeks = await _get_greeks_for_strike(
                    chains_col,
                    underlying=und,
                    strike=leg["strike"],
                    opt_type=leg["opt_type"],
                    day_start_ts=today_ist_start,
                )
                leg_enriched.update(greeks)

            legs_by_underlying.setdefault(und, []).append(leg_enriched)
            unrealized_by_underlying[und] = unrealized_by_underlying.get(und, 0.0) + (leg["mtm"] or 0.0)

    # ── Status — per-underlying + overall ──────────────────────────────────
    primary_state = next(
        (s for s_idx, s in enumerate(states) if strategies[s_idx].underlying == "NIFTY"), states[0]
    )
    # Per-underlying status so Flutter can show individual buckets/scores (must come before groups)
    underlying_status = {
        strategies[i].underlying: {
            "bucket": s.get("bucket"),  # None → JSON null (Flutter shows '--')
            "score": s.get("score"),
            "done_for_day": s.get("done_for_day", False),
            "n_open_shorts": s.get("n_open_shorts", 0),
            "n_open_hedges": s.get("n_open_hedges", 0),
        }
        for i, s in enumerate(states)
    }

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
    status = {
        "bucket": primary_state.get("bucket"),  # None → JSON null, not "None" string
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
    # Index sids only — EMA/PSAR/RSI/SuperTrend suites are configured for the 3
    # spot indices (+ their futures for VWAP/VWMA), never for option strikes, so
    # a strike sid here would only ever render `--` rows.
    matrix_sids = list(_INDEX_SIDS.values())

    from pdp.indicators.levels_store import LevelsStore

    levels_store = (
        LevelsStore(request.app.state.mongo_db["index_levels"])
        if hasattr(request.app.state, "mongo_db")
        else None
    )
    session_date_ist = (datetime.now(UTC) + timedelta(hours=5, minutes=30)).date()

    fut_sids: dict[str, str] = await _get_matrix_futures_sids(engine, redis)

    indicators: dict[str, Any] = {}
    for sid in matrix_sids:
        sid_data: dict[str, Any] = {}
        tf_data: dict[str, Any] = {}
        fut_sid = fut_sids.get(sid)
        for tf in _MATRIX_TFS:
            tf_data[tf] = await _build_indicator_cell(engine, redis, sid, tf, fut_sid)
        sid_data["tf"] = tf_data
        if levels_store is not None:
            sid_data.update(await _build_levels_cells(levels_store, sid, session_date_ist))
        indicators[sid] = sid_data

    payload = {
        "indices": indices,
        "groups": groups,
        "totals": totals,
        "status": status,
        "recent_events": recent_events,
        "indicators": indicators,
    }
    return StrangleMonitorOut(**_serialise(payload))


# ------------------------------------------------------------------ #
# Levels warehouse — GET /api/v1/levels/{underlying}                  #
# ------------------------------------------------------------------ #


@levels_router.get("/{underlying}", response_model=LevelsResponseOut)
async def get_levels(
    request: Request,
    underlying: str,
    period: str = Query(default="daily", pattern="^(daily|weekly|monthly)$"),
    date: str | None = Query(default=None, description="YYYY-MM-DD (single doc)"),
    start: str | None = Query(default=None, description="YYYY-MM-DD range start"),
    end: str | None = Query(default=None, description="YYYY-MM-DD range end"),
) -> LevelsResponseOut:
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
        return LevelsResponseOut(**_serialise(doc))

    # Range mode
    from datetime import date as date_type

    start_d = date_type.fromisoformat(start) if start else date_type.today().replace(day=1)
    end_d = date_type.fromisoformat(end) if end else date_type.today()
    docs = await store.range(security_id, period, start_d, end_d)
    return LevelsResponseOut(docs=[_serialise(d) for d in docs], count=len(docs))
