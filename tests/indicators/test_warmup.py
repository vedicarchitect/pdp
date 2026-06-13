"""GAP 1 (task 1.4): IndicatorEngine warmup seeds the SuperTrend from stored bars so
``st_direction`` is non-None from the first live bar (rather than None for the first ~3 bars).

Driven offline with a fake Mongo collection and a real ``IndicatorEngine`` — no DB or Dhan
creds required. Settings carry empty Dhan credentials so the API path is skipped.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from pdp.indicators.engine import IndicatorEngine
from pdp.indicators.warmup import warm_up_indicator_engine


class _FakeCursor:
    def __init__(self, docs: list[dict]) -> None:
        self._docs = docs

    def __aiter__(self):
        self._it = iter(self._docs)
        return self

    async def __anext__(self):
        try:
            return next(self._it)
        except StopIteration:  # pragma: no cover - loop terminator
            raise StopAsyncIteration


class _FakeCol:
    def __init__(self, docs: list[dict]) -> None:
        self._docs = docs
        self.queries: list[dict] = []

    def find(self, query, sort=None):  # mirrors motor's signature used in warmup
        self.queries.append(query)
        return _FakeCursor(self._docs)


class _FakeDB:
    def __init__(self, docs: list[dict]) -> None:
        self.col = _FakeCol(docs)

    def __getitem__(self, name: str) -> _FakeCol:
        assert name == "market_bars"
        return self.col


def _bar_docs(closes: list[float]) -> list[dict]:
    """Ascending 5-minute bars within the warmup lookback window."""
    base = datetime.now(UTC) - timedelta(minutes=5 * len(closes))
    docs = []
    for i, c in enumerate(closes):
        docs.append(
            {
                "ts": base + timedelta(minutes=5 * i),
                "open": c,
                "high": c + 5,
                "low": c - 5,
                "close": c,
                "volume": 0,
                "oi": 0,
            }
        )
    return docs


_NO_CREDS = SimpleNamespace(DHAN_CLIENT_ID="", DHAN_ACCESS_TOKEN="")


@pytest.mark.asyncio
async def test_warmup_primes_supertrend_direction_from_mongo():
    """After warmup over a clean uptrend, the engine reports a non-None direction
    for (sid, tf) — so a strategy reading it on bar 1 is not blind."""
    engine = IndicatorEngine()
    db = _FakeDB(_bar_docs([22000 + 20 * i for i in range(15)]))  # steady uptrend
    watchlist = [{"security_id": "13", "exchange_segment": "IDX_I", "timeframes": ["5m"]}]

    await warm_up_indicator_engine(engine, db, _NO_CREDS, watchlist)

    state = engine.get("13", "5m")
    assert state is not None
    assert state.direction is not None  # primed: not None as it would be cold


@pytest.mark.asyncio
async def test_warmup_no_bars_leaves_engine_cold_without_raising():
    """An empty market_bars collection logs a warning and leaves the engine cold, but
    does not raise (warmup must never block startup)."""
    engine = IndicatorEngine()
    db = _FakeDB([])
    watchlist = [{"security_id": "13", "exchange_segment": "IDX_I", "timeframes": ["5m"]}]

    await warm_up_indicator_engine(engine, db, _NO_CREDS, watchlist)

    assert engine.get("13", "5m") is None
