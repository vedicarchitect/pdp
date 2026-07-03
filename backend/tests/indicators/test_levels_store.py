"""Unit tests for LevelsStore daily and weekly rollup."""
from __future__ import annotations

import datetime
from unittest.mock import AsyncMock

import pytest

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
    args, _kwargs = mock_collection.update_one.call_args
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
    args, _kwargs = mock_collection.update_one.call_args
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


@pytest.mark.asyncio
async def test_weekly_keys_match_spec(store: LevelsStore, mock_collection: AsyncMock) -> None:
    """Weekly doc shape: standard/camarilla/fibonacci keys exactly per design spec."""
    await store.compute_weekly(
        security_id="13", session_date=datetime.date(2026, 6, 29),
        week_h=24600.0, week_l=23800.0, week_c=24300.0,
        week_start=datetime.date(2026, 6, 22), week_end=datetime.date(2026, 6, 26),
    )
    doc = mock_collection.update_one.call_args[0][1]["$set"]
    assert set(doc["standard"].keys()) == {"pp", "r1", "r2", "r3", "s1", "s2", "s3"}
    assert set(doc["camarilla"].keys()) == {"pp", "r3", "r4", "s3", "s4"}
    assert set(doc["fibonacci"].keys()) == {"pp", "r1", "r2", "r3", "s1", "s2", "s3"}
    assert "levels" in doc  # open map for future ML families


@pytest.mark.asyncio
async def test_to_feature_rows_flattens_prefixes(mock_collection: AsyncMock) -> None:
    """to_feature_rows() produces flat ML-ready dicts with std_/cam_/fib_ prefixes."""
    from pdp.indicators.levels_store import _pivot_state_to_doc

    doc = _pivot_state_to_doc(
        security_id="13", period="daily",
        session_date=datetime.date(2026, 7, 3),
        source_h=24500.0, source_l=24100.0, source_c=24300.0,
        window_start=datetime.date(2026, 7, 2), window_end=datetime.date(2026, 7, 2),
    )

    # Make col.find return an async iterable with this doc
    class _AsyncList:
        def __init__(self, items): self._items = items
        def __aiter__(self): return _AsyncIter(self._items)

    class _AsyncIter:
        def __init__(self, items): self._it = iter(items)
        async def __anext__(self):
            try:
                return next(self._it)
            except StopIteration:
                raise StopAsyncIteration from None

    mock_collection.find = lambda *a, **kw: _AsyncList([doc])
    store = LevelsStore(mock_collection)

    rows = await store.to_feature_rows(
        "13", "daily",
        datetime.date(2026, 7, 3), datetime.date(2026, 7, 3),
    )
    assert len(rows) == 1
    row = rows[0]
    assert "std_pp" in row
    assert "cam_r3" in row
    assert "fib_s1" in row
    # PDH/PDL come from source for daily
    assert row["pdh"] == 24500.0
    assert row["pdl"] == 24100.0
    assert "pwh" not in row  # only for weekly
