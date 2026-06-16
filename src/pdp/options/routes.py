"""Options analytics REST endpoints."""
from __future__ import annotations

from datetime import datetime
from typing import Any

import structlog
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from pdp.options.analytics import compute_gex

log = structlog.get_logger()

router = APIRouter(prefix="/api/v1/options", tags=["options"])

_PAPER_CHAIN: dict[str, Any] = {"mode": "paper", "strikes": [], "max_pain": None, "pcr": None}
_LOT_SIZES: dict[str, int] = {"NIFTY": 75, "BANKNIFTY": 15, "SENSEX": 10}


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
