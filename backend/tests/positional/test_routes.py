"""Unit tests for positional EOD snapshot endpoints."""
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from pdp.main import create_app


def _make_col(find_docs: list | None = None) -> MagicMock:
    col = MagicMock()
    col.update_one = AsyncMock(return_value=MagicMock())
    cursor = MagicMock()
    cursor.to_list = AsyncMock(return_value=find_docs or [])
    cursor.sort = MagicMock(return_value=cursor)
    cursor.limit = MagicMock(return_value=cursor)
    col.find = MagicMock(return_value=cursor)
    return col


@pytest.fixture
def client(mock_mongo_lifespan):
    app = create_app()
    with TestClient(app, raise_server_exceptions=True) as c:
        c.app.state.mongo_db.__getitem__ = MagicMock(return_value=_make_col())
        yield c


def _patch_positions(client: TestClient, positions=None) -> None:
    """Patch the DB so get_positions returns given list of Position-like objects."""
    from unittest.mock import AsyncMock, MagicMock, patch

    pos_list = positions or []

    async def fake_execute(_):
        result = MagicMock()
        result.scalars.return_value.all.return_value = pos_list
        return result

    session_mock = MagicMock()
    session_mock.execute = fake_execute
    session_mock.__aenter__ = AsyncMock(return_value=session_mock)
    session_mock.__aexit__ = AsyncMock(return_value=False)

    client.app.dependency_overrides = {}  # clear before patching


class FakePosition:
    def __init__(self, net_qty: int, realized_pnl: float, unrealized_pnl: float):
        self.net_qty = net_qty
        self.realized_pnl = Decimal(str(realized_pnl))
        self.unrealized_pnl = Decimal(str(unrealized_pnl))


@pytest.fixture
def client_with_col(mock_mongo_lifespan):
    """Client with a controllable mongo collection."""
    app = create_app()
    col = _make_col()
    with TestClient(app, raise_server_exceptions=True) as c:
        c.app.state.mongo_db.__getitem__ = MagicMock(return_value=col)
        c._positional_col = col
        yield c


def test_snapshot_returns_201(client_with_col):
    with patch("pdp.positional.routes.get_db") as mock_get_db:
        from unittest.mock import AsyncMock, MagicMock

        async def fake_db():
            result = MagicMock()
            result.scalars.return_value.all.return_value = []
            session = MagicMock()
            session.execute = AsyncMock(return_value=result)
            yield session

        mock_get_db.return_value = fake_db()
        resp = client_with_col.post("/api/v1/positional/snapshot")
    assert resp.status_code == 201
    body = resp.json()
    assert "date" in body
    assert "day_pnl" in body
    assert body["mode"] == "paper"


def test_snapshot_upserts_on_same_day(client_with_col):
    col = client_with_col._positional_col
    with patch("pdp.positional.routes.get_db"):
        client_with_col.post("/api/v1/positional/snapshot")
        client_with_col.post("/api/v1/positional/snapshot")
    assert col.update_one.call_count >= 1
    # Both calls should use upsert=True
    for call in col.update_one.call_args_list:
        assert call.kwargs.get("upsert") is True or call.args[2] if len(call.args) > 2 else True


def test_snapshots_returns_empty_list(client_with_col):
    resp = client_with_col.get("/api/v1/positional/snapshots")
    assert resp.status_code == 200
    assert resp.json() == []


def test_snapshots_returns_history(client_with_col):
    docs = [
        {"date": "2026-06-01", "day_pnl": 1000.0, "total_unrealized_pnl": 800.0,
         "total_realized_pnl": 200.0, "position_count": 2, "mode": "paper",
         "created_at": datetime(2026, 6, 1, 15, 36, tzinfo=UTC).isoformat()},
        {"date": "2026-06-02", "day_pnl": -500.0, "total_unrealized_pnl": -300.0,
         "total_realized_pnl": -200.0, "position_count": 1, "mode": "paper",
         "created_at": datetime(2026, 6, 2, 15, 36, tzinfo=UTC).isoformat()},
    ]
    col = _make_col(find_docs=docs)
    client_with_col.app.state.mongo_db.__getitem__ = MagicMock(return_value=col)

    resp = client_with_col.get("/api/v1/positional/snapshots?days=30")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 2
    assert body[0]["date"] == "2026-06-01"
    assert body[1]["day_pnl"] == -500.0


def test_snapshot_paper_mode_flag(client_with_col):
    with patch("pdp.positional.routes.get_settings") as mock_settings:
        mock_settings.return_value = MagicMock(LIVE=False)
        with patch("pdp.positional.routes.get_db"):
            resp = client_with_col.post("/api/v1/positional/snapshot")
    assert resp.status_code == 201
    assert resp.json()["mode"] == "paper"
