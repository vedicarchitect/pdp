"""Unit tests for portfolio REST route functions."""
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from pdp.deps import PaginationParams
from pdp.portfolio.routes import get_positions, get_summary


def _make_pos(security_id="13", net_qty=1, unrealized="500", realized="200"):
    p = MagicMock()
    p.security_id = security_id
    p.exchange_segment = "NSE_FNO"
    p.product = "NRML"
    p.net_qty = net_qty
    p.avg_price = Decimal("22000")
    p.unrealized_pnl = Decimal(unrealized)
    p.realized_pnl = Decimal(realized)
    p.updated_at = datetime(2026, 6, 6, 9, 30, tzinfo=UTC)
    return p


def _mock_db(rows):
    session = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = rows
    session.execute = AsyncMock(return_value=result)
    return session


@pytest.mark.asyncio
async def test_positions_empty_returns_200():
    db = _mock_db([])
    page = await get_positions(db=db, pagination=PaginationParams(limit=50, offset=0))
    assert page.items == []
    assert page.total is None


@pytest.mark.asyncio
async def test_positions_returns_rows():
    pos = _make_pos(net_qty=2, unrealized="1000")
    db = _mock_db([pos])
    page = await get_positions(db=db, pagination=PaginationParams(limit=50, offset=0))
    assert len(page.items) == 1
    assert page.items[0].security_id == "13"
    assert page.items[0].net_qty == 2
    assert page.items[0].unrealized_pnl == "1000"


@pytest.mark.asyncio
async def test_summary_aggregates_pnl():
    pos1 = _make_pos(security_id="13", net_qty=1, unrealized="500", realized="200")
    pos2 = _make_pos(security_id="25", net_qty=2, unrealized="700", realized="300")
    db = _mock_db([pos1, pos2])
    summary = await get_summary(db=db)
    assert summary.total_unrealized_pnl == pytest.approx(1200.0)
    assert summary.total_realized_pnl == pytest.approx(500.0)
    assert summary.day_pnl == pytest.approx(1700.0)
    assert summary.open_positions == 2
    assert summary.mode in ("paper", "live")


@pytest.mark.asyncio
async def test_positions_no_mode_filter():
    """Mode filter was removed — positions table has no mode column."""
    db = _mock_db([])
    page = await get_positions(db=db, pagination=PaginationParams(limit=50, offset=0))
    assert page.items == []
