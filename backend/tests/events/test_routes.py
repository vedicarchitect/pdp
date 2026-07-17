"""GET /api/v1/events — pagination regression.

Before the fix, any request hit `EventStore.list_events() got an unexpected keyword argument
'offset'` because `PaginationParams` always supplies `offset` (default 0) and the route always
forwarded it, but the store didn't accept it — a 500 on every single call, not just ?offset=N ones.
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from pdp.events.routes import router
from pdp.events.store import EventStore


def _make_app(store: EventStore | None) -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    app.state.event_store = store
    return app


def test_list_events_default_pagination_does_not_500() -> None:
    app = _make_app(EventStore(mongo_db=None))
    with TestClient(app) as client:
        resp = client.get("/api/v1/events")
    assert resp.status_code == 200
    assert resp.json() == {"items": [], "limit": 50, "offset": 0, "total": None}


def test_list_events_explicit_offset_does_not_500() -> None:
    app = _make_app(EventStore(mongo_db=None))
    with TestClient(app) as client:
        resp = client.get("/api/v1/events?offset=20&limit=10")
    assert resp.status_code == 200
    body = resp.json()
    assert body["offset"] == 20
    assert body["limit"] == 10


def test_list_events_no_store_configured_returns_empty_page() -> None:
    app = _make_app(None)
    with TestClient(app) as client:
        resp = client.get("/api/v1/events?offset=5")
    assert resp.status_code == 200
    assert resp.json()["items"] == []
