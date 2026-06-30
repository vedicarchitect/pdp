"""Unit tests for LevelsStore daily and weekly rollup."""
from __future__ import annotations

import datetime
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from motor.motor_asyncio import AsyncIOMotorCollection

from pdp.indicators.levels_store import LevelsStore


@pytest.fixture
def mock_collection() -> AsyncMock:
    m = AsyncMock()
    m.update_one = AsyncMock()
    return m


@pytest.fixture
def store(mock_collection: AsyncMock) -> LevelsStore:
    return LevelsStore(mock_collection)


@pytest.mark.asyncio
async def test_compute_daily(store: LevelsStore, mock_collection: AsyncMock) -> None:
    session_date = datetime.date(2026, 6, 30)
    prior_date = datetime.date(2026, 6, 29)

    await store.compute_daily(
        security_id="13",
        session_date=session_date,
        prior_h=100.0,
        prior_l=90.0,
        prior_c=95.0,
        prior_date=prior_date,
    )

    mock_collection.update_one.assert_called_once()
    args, kwargs = mock_collection.update_one.call_args
    assert args[0] == {
        "security_id": "13",
        "period": "daily",
        "session_date": "2026-06-30",
    }
    doc = args[1]["$set"]
    assert doc["period"] == "daily"
    assert doc["source"]["h"] == 100.0
    assert doc["source"]["l"] == 90.0
    assert doc["source"]["c"] == 95.0
    assert doc["source"]["window_start"] == "2026-06-29"
    assert doc["source"]["window_end"] == "2026-06-29"
    assert "standard" in doc
    assert "camarilla" in doc
    assert "fibonacci" in doc


@pytest.mark.asyncio
async def test_compute_weekly(store: LevelsStore, mock_collection: AsyncMock) -> None:
    session_date = datetime.date(2026, 6, 29)  # Monday
    week_start = datetime.date(2026, 6, 22)
    week_end = datetime.date(2026, 6, 26)

    await store.compute_weekly(
        security_id="25",
        session_date=session_date,
        week_h=200.0,
        week_l=180.0,
        week_c=190.0,
        week_start=week_start,
        week_end=week_end,
    )

    mock_collection.update_one.assert_called_once()
    args, kwargs = mock_collection.update_one.call_args
    assert args[0] == {
        "security_id": "25",
        "period": "weekly",
        "session_date": "2026-06-29",
    }
    doc = args[1]["$set"]
    assert doc["period"] == "weekly"
    assert doc["source"]["h"] == 200.0
    assert doc["source"]["window_start"] == "2026-06-22"
    assert doc["source"]["window_end"] == "2026-06-26"
