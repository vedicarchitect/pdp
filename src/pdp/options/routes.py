"""Options analytics REST endpoints."""
from __future__ import annotations

from datetime import datetime
from typing import Any

import structlog
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

log = structlog.get_logger()

router = APIRouter(prefix="/api/v1/options", tags=["options"])

_PAPER_CHAIN = {"mode": "paper", "strikes": [], "max_pain": None, "pcr": None}


def _poller_active(request: Request) -> bool:
    return getattr(request.app.state, "options_poller", None) is not None


def _collection(request: Request):  # type: ignore[no-untyped-def]
    return request.app.state.mongo_db["option_chains"]


def _serialise(doc: dict) -> dict[str, Any]:
    """Strip _id and convert datetime → ISO string for JSON response."""
    return {k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in doc.items() if k != "_id"}


async def _latest_snapshot(collection, underlying: str, expiry: str | None) -> dict | None:
    query: dict[str, Any] = {"underlying": underlying.upper()}
    if expiry:
        query["expiry"] = expiry
    doc = await collection.find_one(query, sort=[("snapshot_ts", -1)])
    return doc


def _ts(doc: dict) -> str | None:
    v = doc.get("snapshot_ts")
    return v.isoformat() if isinstance(v, datetime) else v


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
