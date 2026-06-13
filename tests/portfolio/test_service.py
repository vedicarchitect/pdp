"""Unit tests for PortfolioService MTM computation."""
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pdp.portfolio.hub import PortfolioHub
from pdp.portfolio.models import PositionState
from pdp.portfolio.service import PortfolioService


def _make_settings(**overrides):
    s = MagicMock()
    s.PORTFOLIO_MTM_INTERVAL_SECONDS = 5
    s.PORTFOLIO_EOD_SNAPSHOT = False
    s.LIVE = False
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


def _make_service(hub=None):
    redis = MagicMock()
    engine = MagicMock()
    if hub is None:
        hub = PortfolioHub()
    settings = _make_settings()
    svc = PortfolioService(redis=redis, engine=engine, hub=hub, settings=settings)
    return svc


def _make_pos(net_qty=1, avg_price="22000.0000") -> PositionState:
    return PositionState(
        security_id="13",
        exchange_segment="NSE_FNO",
        product="NRML",
        net_qty=net_qty,
        avg_price=Decimal(avg_price),
        realized_pnl=Decimal("0"),
        unrealized_pnl=Decimal("0"),
        updated_at=datetime.now(UTC),
    )


def test_mtm_recomputed_on_tick():
    svc = _make_service()
    key = ("13", "NSE_FNO", "NRML")
    svc._cache[key] = _make_pos(net_qty=1, avg_price="22000.0000")

    tick_data = {"security_id": "13", "ltp": "22500.0000"}
    svc._handle_tick(tick_data)

    pos = svc._cache[key]
    assert pos.unrealized_pnl == Decimal("500.0000")
    assert pos.ltp_stale is False
    assert key in svc._dirty


def test_mtm_short_position():
    svc = _make_service()
    key = ("13", "NSE_FNO", "NRML")
    svc._cache[key] = _make_pos(net_qty=-1, avg_price="22000.0000")

    svc._handle_tick({"security_id": "13", "ltp": "21500.0000"})

    pos = svc._cache[key]
    assert pos.unrealized_pnl == Decimal("500.0000")


def test_tick_for_unrelated_security_ignored():
    svc = _make_service()
    key = ("13", "NSE_FNO", "NRML")
    svc._cache[key] = _make_pos(net_qty=1, avg_price="22000.0000")

    svc._handle_tick({"security_id": "999", "ltp": "100.0"})

    assert svc._cache[key].unrealized_pnl == Decimal("0")
    assert not svc._dirty


def test_ltp_stale_cleared_on_tick():
    svc = _make_service()
    key = ("13", "NSE_FNO", "NRML")
    svc._cache[key] = _make_pos()
    svc._cache[key].ltp_stale = True  # pre-marked stale

    svc._handle_tick({"security_id": "13", "ltp": "22300.0"})
    assert svc._cache[key].ltp_stale is False


@pytest.mark.asyncio
async def test_ltp_stale_set_when_redis_key_missing():
    """_check_ltp_stale sets ltp_stale=True when Redis GET returns None."""
    svc = _make_service()
    svc._redis.get = AsyncMock(return_value=None)  # key expired
    key = ("13", "NSE_FNO", "NRML")
    svc._cache[key] = _make_pos(net_qty=1)

    await svc._check_ltp_stale()

    assert svc._cache[key].ltp_stale is True


@pytest.mark.asyncio
async def test_ltp_stale_not_set_when_redis_key_present():
    svc = _make_service()
    svc._redis.get = AsyncMock(return_value="22500.0")  # key alive
    key = ("13", "NSE_FNO", "NRML")
    ps = _make_pos(net_qty=1)
    ps.ltp_stale = False
    svc._cache[key] = ps

    await svc._check_ltp_stale()

    assert svc._cache[key].ltp_stale is False


def _make_pos_for_sid(sid: str, net_qty: int = 1) -> PositionState:
    ps = _make_pos(net_qty=net_qty)
    ps.security_id = sid
    return ps


def test_get_snapshot_returns_all_positions():
    svc = _make_service()
    svc._cache[("13", "NSE_FNO", "NRML")] = _make_pos_for_sid("13", net_qty=1)
    svc._cache[("25", "NSE_FNO", "NRML")] = _make_pos_for_sid("25", net_qty=-2)

    snapshot = svc.get_snapshot()
    assert len(snapshot) == 2
    sids = {p["security_id"] for p in snapshot}
    assert sids == {"13", "25"}


def test_tick_flags_broadcast_needed():
    hub = MagicMock()
    svc = _make_service(hub=hub)
    key = ("13", "NSE_FNO", "NRML")
    svc._cache[key] = _make_pos(net_qty=1)
    svc._needs_broadcast = False

    svc._handle_tick({"security_id": "13", "ltp": "22500.0"})

    assert svc._needs_broadcast is True


@pytest.mark.asyncio
async def test_flush_dirty_writes_to_pg():
    svc = _make_service()
    key = ("13", "NSE_FNO", "NRML")
    svc._cache[key] = _make_pos(net_qty=1, avg_price="22000.0000")
    svc._cache[key].unrealized_pnl = Decimal("500.0000")
    svc._dirty.add(key)

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock()
    mock_session.commit = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch("pdp.portfolio.service.AsyncSession", return_value=mock_session):
        await svc._flush_dirty()

    mock_session.execute.assert_called_once()
    mock_session.commit.assert_called_once()
    assert not svc._dirty
