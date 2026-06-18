"""Options analytics REST endpoints."""
from __future__ import annotations

from datetime import datetime
from typing import Any

import structlog
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, field_validator

from pdp.options.analytics import (
    classify_oi_buildup,
    compute_gex,
    compute_iv_rank_percentile,
    compute_straddle_history,
    multi_strike_oi_series,
)
from pdp.options.fii_dii import StubFIIDIISource
from pdp.options.payoff import READYMADE_STRATEGIES, PayoffLeg, build_payoff

log = structlog.get_logger()

router = APIRouter(prefix="/api/v1/options", tags=["options"])

_PAPER_CHAIN: dict[str, Any] = {"mode": "paper", "strikes": [], "max_pain": None, "pcr": None}
_LOT_SIZES: dict[str, int] = {"NIFTY": 75, "BANKNIFTY": 15, "SENSEX": 10}
_INTERVAL_MINUTES: dict[str, int] = {"5m": 5, "15m": 15, "1H": 60, "1D": 1440}


def _downsample_by_interval(docs: list[dict[str, Any]], interval_minutes: int) -> list[dict[str, Any]]:
    """Keep only snapshots at least `interval_minutes` apart (oldest-first input)."""
    if not docs or interval_minutes <= 1:
        return docs
    result: list[dict[str, Any]] = [docs[0]]
    last_ts = docs[0].get("snapshot_ts")
    for doc in docs[1:]:
        ts = doc.get("snapshot_ts")
        if ts is None or last_ts is None:
            result.append(doc)
            last_ts = ts
            continue
        delta_minutes = (ts - last_ts).total_seconds() / 60
        if delta_minutes >= interval_minutes:
            result.append(doc)
            last_ts = ts
    return result


def _poller_active(request: Request) -> bool:
    return getattr(request.app.state, "options_poller", None) is not None


def _collection(request: Request):  # type: ignore[no-untyped-def]
    return request.app.state.mongo_db["option_chains"]


def _serialise(doc: dict[str, Any]) -> dict[str, Any]:
    """Strip _id and convert datetime → ISO string for JSON response."""
    return {k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in doc.items() if k != "_id"}


async def _latest_snapshot(collection: Any, underlying: str, expiry: str | None) -> dict[str, Any] | None:
    query: dict[str, Any] = {"underlying": underlying.upper()}
    if expiry:
        query["expiry"] = expiry
    doc: dict[str, Any] | None = await collection.find_one(query, sort=[("snapshot_ts", -1)])
    return doc


def _ts(doc: dict[str, Any]) -> str | None:
    v = doc.get("snapshot_ts")
    return v.isoformat() if isinstance(v, datetime) else v  # type: ignore[no-any-return]


@router.get("/{underlying}/chain")
async def get_chain(request: Request, underlying: str, expiry: str | None = None) -> JSONResponse:
    if not _poller_active(request):
        return JSONResponse(_PAPER_CHAIN)
    doc = await _latest_snapshot(_collection(request), underlying, expiry)
    if doc is None:
        raise HTTPException(status_code=404, detail=f"No snapshot for {underlying}/{expiry or 'nearest'}")
    return JSONResponse(_serialise(doc))


@router.get("/{underlying}/max-pain")
async def get_max_pain(request: Request, underlying: str, expiry: str | None = None) -> JSONResponse:
    if not _poller_active(request):
        return JSONResponse({"mode": "paper", "max_pain": None})
    doc = await _latest_snapshot(_collection(request), underlying, expiry)
    if doc is None:
        raise HTTPException(status_code=404, detail=f"No snapshot for {underlying}/{expiry or 'nearest'}")
    return JSONResponse(
        {
            "underlying": doc["underlying"],
            "expiry": doc["expiry"],
            "max_pain": doc.get("max_pain"),
            "snapshot_ts": _ts(doc),
        }
    )


@router.get("/{underlying}/pcr")
async def get_pcr(request: Request, underlying: str, expiry: str | None = None) -> JSONResponse:
    if not _poller_active(request):
        return JSONResponse({"mode": "paper", "pcr": None})
    doc = await _latest_snapshot(_collection(request), underlying, expiry)
    if doc is None:
        raise HTTPException(status_code=404, detail=f"No snapshot for {underlying}/{expiry or 'nearest'}")
    return JSONResponse(
        {
            "underlying": doc["underlying"],
            "expiry": doc["expiry"],
            "pcr": doc.get("pcr"),
            "snapshot_ts": _ts(doc),
        }
    )


@router.get("/{underlying}/gex")
async def get_gex(request: Request, underlying: str, expiry: str | None = None) -> JSONResponse:
    if not _poller_active(request):
        return JSONResponse({"mode": "paper", "per_strike": [], "net_gex": 0, "net_gex_cr": 0.0})
    doc = await _latest_snapshot(_collection(request), underlying, expiry)
    if doc is None:
        raise HTTPException(status_code=404, detail=f"No snapshot for {underlying}/{expiry or 'nearest'}")
    strikes = doc.get("strikes", [])
    lot_size = _LOT_SIZES.get(underlying.upper(), 75)
    spot = float(doc.get("spot_price") or 0)
    gex = compute_gex(strikes, lot_size, spot)
    return JSONResponse(
        {
            "underlying": doc["underlying"],
            "expiry": doc.get("expiry"),
            "spot_price": spot,
            "lot_size": lot_size,
            "per_strike": sorted(gex["per_strike"], key=lambda x: x["strike"]),
            "net_gex": gex["net_gex"],
            "net_gex_cr": round(gex["net_gex"] / 1e9, 2),
            "snapshot_ts": _ts(doc),
        }
    )


@router.get("/{underlying}/oi-history")
async def get_oi_history(
    request: Request,
    underlying: str,
    expiry: str | None = None,
    n: int = 40,
) -> JSONResponse:
    if not _poller_active(request):
        return JSONResponse({"mode": "paper", "snapshots": []})
    n = min(n, 200)
    col = _collection(request)
    query: dict[str, Any] = {"underlying": underlying.upper()}
    if expiry:
        query["expiry"] = expiry
    cursor = col.find(query, sort=[("snapshot_ts", -1)]).limit(n)
    docs: list[dict[str, Any]] = await cursor.to_list(length=n)
    if not docs:
        raise HTTPException(status_code=404, detail=f"No snapshots for {underlying}/{expiry or 'nearest'}")
    docs.reverse()  # oldest first
    snapshots: list[dict[str, Any]] = []
    for doc in docs:
        ts = doc.get("snapshot_ts")
        snapshots.append(
            {
                "ts": ts.isoformat() if isinstance(ts, datetime) else ts,
                "pcr": doc.get("pcr"),
                "strikes": [
                    {
                        "strike": int(s["strike"]),
                        "ce_oi": s.get("ce", {}).get("oi") or 0,
                        "pe_oi": s.get("pe", {}).get("oi") or 0,
                        "total_oi": (s.get("ce", {}).get("oi") or 0) + (s.get("pe", {}).get("oi") or 0),
                    }
                    for s in doc.get("strikes", [])
                ],
            }
        )
    return JSONResponse(
        {
            "underlying": underlying.upper(),
            "expiry": expiry or (docs[-1].get("expiry") if docs else None),
            "snapshots": snapshots,
        }
    )


@router.get("/{underlying}/oi-buildup")
async def get_oi_buildup(request: Request, underlying: str, expiry: str | None = None) -> JSONResponse:
    if not _poller_active(request):
        return JSONResponse({"mode": "paper", "buildup": []})
    col = _collection(request)
    query: dict[str, Any] = {"underlying": underlying.upper()}
    if expiry:
        query["expiry"] = expiry
    cursor = col.find(query, sort=[("snapshot_ts", -1)]).limit(2)
    docs = await cursor.to_list(length=2)
    if not docs or len(docs) < 2:
        return JSONResponse({"buildup": []})
        
    current = docs[0].get("strikes", [])
    previous = docs[1].get("strikes", [])
    buildup = classify_oi_buildup(current, previous)
    
    return JSONResponse({
        "underlying": underlying.upper(),
        "expiry": docs[0].get("expiry"),
        "snapshot_ts": _ts(docs[0]),
        "buildup": buildup
    })


@router.get("/{underlying}/oi-series")
async def get_oi_series(
    request: Request,
    underlying: str,
    expiry: str | None = None,
    interval: str = "15m",
    limit: int = 50,
) -> JSONResponse:
    if not _poller_active(request):
        return JSONResponse({"mode": "paper", "timestamps": [], "strikes": {}})
    col = _collection(request)
    query: dict[str, Any] = {"underlying": underlying.upper()}
    if expiry:
        query["expiry"] = expiry
    cursor = col.find(query, sort=[("snapshot_ts", -1)]).limit(limit)
    docs = await cursor.to_list(length=limit)
    if not docs:
        return JSONResponse({"timestamps": [], "strikes": {}})
    docs.reverse()
    interval_minutes = _INTERVAL_MINUTES.get(interval, 15)
    docs = _downsample_by_interval(docs, interval_minutes)
    res = multi_strike_oi_series(docs, top_n=10)
    return JSONResponse(res)


@router.get("/{underlying}/straddle-history")
async def get_straddle_history(request: Request, underlying: str, date: str | None = None) -> JSONResponse:
    if not _poller_active(request):
        return JSONResponse({"mode": "paper", "history": []})
    col = _collection(request)
    query: dict[str, Any] = {"underlying": underlying.upper()}
    if date:
        try:
            d = datetime.strptime(date, "%Y-%m-%d").date()
            start = datetime(d.year, d.month, d.day)
            end = datetime(d.year, d.month, d.day, 23, 59, 59)
            query["snapshot_ts"] = {"$gte": start, "$lte": end}
        except ValueError:
            pass
    cursor = col.find(query, sort=[("snapshot_ts", -1)]).limit(100)
    docs = await cursor.to_list(length=100)
    docs.reverse()
    
    history = compute_straddle_history(docs)
    return JSONResponse({"history": history})


@router.get("/{underlying}/iv-history")
async def get_iv_history(request: Request, underlying: str, lookback_days: int = 252) -> JSONResponse:
    if getattr(request.app.state, "mongo_db", None) is None:
        return JSONResponse({"mode": "paper"})
        
    db = request.app.state.mongo_db
    
    # Try fetching 1D bars first for historical IV
    cursor = db["option_bars"].find(
        {"underlying": underlying.upper(), "timeframe": "1D"}
    ).sort([("ts", -1)]).limit(lookback_days)
    docs = await cursor.to_list(length=lookback_days)
    
    # If not enough 1D bars, just use whatever is there (fallback)
    if len(docs) < 5:
        cursor = db["option_bars"].find(
            {"underlying": underlying.upper()}
        ).sort([("ts", -1)]).limit(lookback_days)
        docs = await cursor.to_list(length=lookback_days)
    
    # Current IV from latest chain
    current_chain = await _latest_snapshot(_collection(request), underlying, None)
    current_iv = 20.0
    if current_chain:
        spot = current_chain.get("spot_price", 0)
        strikes = current_chain.get("strikes", [])
        if strikes and spot > 0:
            atm = min(strikes, key=lambda s: abs(s["strike"] - spot))
            current_iv = atm.get("ce", {}).get("iv") or 20.0
            
    ivs = []
    for d in docs:
        if d.get("iv"):
            ivs.append(float(d["iv"]))
            
    res = compute_iv_rank_percentile(ivs, current_iv)
    return JSONResponse(res)

@router.get("/fii-dii")
async def get_fii_dii(request: Request, date_str: str | None = None) -> JSONResponse:
    source = getattr(request.app.state, "fii_dii_source", StubFIIDIISource())
    
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d").date() if date_str else datetime.now().date()
    except ValueError:
        d = datetime.now().date()
        
    data = await source.fetch(d)
    if not data:
        return JSONResponse({"available": False})
        
    from dataclasses import asdict
    return JSONResponse({
        "available": True,
        "data": {k: (v.isoformat() if hasattr(v, 'isoformat') else v) for k, v in asdict(data).items()}
    })

@router.post("/{underlying}/refresh", status_code=202)
async def refresh(request: Request, underlying: str) -> dict[str, str]:
    poller = getattr(request.app.state, "options_poller", None)
    if poller is None:
        raise HTTPException(
            status_code=503,
            detail="Options poller not running (paper mode or missing credentials)",
        )
    poller.request_refresh(underlying)
    return {"status": "accepted", "underlying": underlying.upper()}


class PayoffRequest(BaseModel):
    legs: list[PayoffLeg]
    spot: float
    lot_size: int
    risk_free_rate: float = 0.07
    days_to_expiry: int | None = None

    @field_validator("legs")
    @classmethod
    def legs_not_empty(cls, v: list[PayoffLeg]) -> list[PayoffLeg]:
        if not v:
            raise ValueError("At least one leg is required")
        return v


@router.post("/{underlying}/payoff")
async def calculate_payoff(underlying: str, payload: PayoffRequest) -> JSONResponse:
    from dataclasses import asdict
    result = build_payoff(
        legs=payload.legs,
        spot=payload.spot,
        lot_size=payload.lot_size,
        risk_free_rate=payload.risk_free_rate,
        days_to_expiry=payload.days_to_expiry,
    )
    return JSONResponse(asdict(result))


@router.get("/{underlying}/readymades")
async def get_readymades(underlying: str) -> JSONResponse:
    return JSONResponse({"strategies": READYMADE_STRATEGIES})
