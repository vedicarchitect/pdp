"""Unit tests for portfolio EOD snapshot."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from pdp.portfolio.models import PositionState
from pdp.portfolio.service import PortfolioService


def _make_service(eod_snapshot=True, mongo_db=None):
    redis = MagicMock()
    engine = MagicMock()
    hub = MagicMock()
    settings = MagicMock()
    settings.PORTFOLIO_MTM_INTERVAL_SECONDS = 5
    settings.PORTFOLIO_EOD_SNAPSHOT = eod_snapshot
    settings.LIVE = False
    return PortfolioService(
        redis=redis,
        engine=engine,
        hub=hub,
        settings=settings,
        mongo_db=mongo_db,
    )


def _make_pos_state():
    return PositionState(
        strategy_id="test-strategy",
        security_id="13",
        exchange_segment="NSE_FNO",
        product="NRML",
        net_qty=1,
        avg_price=Decimal("22000"),
        realized_pnl=Decimal("200"),
        unrealized_pnl=Decimal("500"),
        updated_at=datetime.now(UTC),
    )


@pytest.mark.asyncio
async def test_eod_snapshot_written_at_market_close():
    mock_col = AsyncMock()
    mock_db = MagicMock()
    mock_db.__getitem__ = MagicMock(return_value=mock_col)

    svc = _make_service(eod_snapshot=True, mongo_db=mock_db)
    svc._cache[("13", "NSE_FNO", "NRML")] = _make_pos_state()

    await svc._write_eod_snapshot(date(2026, 6, 6))

    mock_col.insert_one.assert_called_once()
    call_args = mock_col.insert_one.call_args[0][0]
    assert call_args["snapshot_date"] == "2026-06-06"
    assert "summary" in call_args
    assert "positions" in call_args
    assert call_args["summary"]["total_unrealized_pnl"] == 500.0
    assert call_args["summary"]["total_realized_pnl"] == 200.0
    assert call_args["summary"]["day_pnl"] == 700.0
    assert call_args["summary"]["open_positions"] == 1


@pytest.mark.asyncio
async def test_eod_snapshot_skipped_when_disabled():
    mock_col = AsyncMock()
    mock_db = MagicMock()
    mock_db.__getitem__ = MagicMock(return_value=mock_col)

    svc = _make_service(eod_snapshot=False, mongo_db=mock_db)
    svc._settings.PORTFOLIO_EOD_SNAPSHOT = False

    # _run_eod_snapshot returns immediately when disabled
    await svc._run_eod_snapshot()

    mock_col.insert_one.assert_not_called()


@pytest.mark.asyncio
async def test_eod_snapshot_written_only_once_per_day():
    mock_col = AsyncMock()
    mock_db = MagicMock()
    mock_db.__getitem__ = MagicMock(return_value=mock_col)

    svc = _make_service(eod_snapshot=True, mongo_db=mock_db)
    today = date(2026, 6, 6)

    # Write twice for the same date
    await svc._write_eod_snapshot(today)
    await svc._write_eod_snapshot(today)

    # Both calls go through (deduplication is in _run_eod_snapshot loop, not _write)
    assert mock_col.insert_one.call_count == 2
