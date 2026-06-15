"""GAP 1 (task 1.4): IndicatorEngine warmup seeds the SuperTrend from stored bars so
``st_direction`` is non-None from the first live bar (rather than None for the first ~3 bars).

Driven offline with a fake Mongo collection and a real ``IndicatorEngine`` — no DB or Dhan
creds required. Settings carry empty Dhan credentials so the API path is skipped.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from pdp.indicators.engine import IndicatorEngine
from pdp.indicators.warmup import warm_up_indicator_engine
from pdp.market.bars import BarClosed


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


@pytest.mark.asyncio
async def test_warmup_feeds_bars_in_chronological_order():
    """Bars returned in any order from MongoDB are fed chronologically.

    The fake cursor ignores the sort parameter, so this test proves that warmup
    sorts on the client side before calling seed_from_bars.  If the sort were
    missing, the reversed input would produce different indicator state (or no
    state at all for short inputs) compared to in-order seeding.
    """
    closes = [22000 + 20 * i for i in range(15)]
    docs_in_order = _bar_docs(closes)
    docs_reversed = list(reversed(docs_in_order))  # descending timestamps

    # Reference: direct in-order seeding
    engine_ref = IndicatorEngine()
    bars_ref = [
        BarClosed(
            security_id="13",
            timeframe="5m",
            bar_time=doc["ts"],
            open=Decimal(str(doc["open"])),
            high=Decimal(str(doc["high"])),
            low=Decimal(str(doc["low"])),
            close=Decimal(str(doc["close"])),
            volume=0,
            oi=0,
        )
        for doc in docs_in_order
    ]
    engine_ref.seed_from_bars(bars_ref)

    # Under test: warmup receives docs in reverse order from the fake DB
    engine_test = IndicatorEngine()
    db = _FakeDB(docs_reversed)
    watchlist = [{"security_id": "13", "exchange_segment": "IDX_I", "timeframes": ["5m"]}]
    await warm_up_indicator_engine(engine_test, db, _NO_CREDS, watchlist)

    ref_state = engine_ref.get("13", "5m")
    test_state = engine_test.get("13", "5m")
    assert test_state is not None, "engine must be primed even with reversed input"
    assert test_state.direction == ref_state.direction, "direction must match in-order reference"
    assert test_state.bar_time == ref_state.bar_time, "last processed bar must be the chronologically-last bar"


@pytest.mark.asyncio
async def test_warmup_only_primes_indicator_state_no_signals():
    """Warmup calls engine.on_bar once per bar (indicator primed) and produces no
    side effects: warm_up_indicator_engine returns None, and the engine state
    bar_time matches the last warmup bar's timestamp, not any live/current time.

    This ensures pre-session bars do not dispatch strategy signals — they only
    advance the indicator tracker so the first live on_bar call sees a warm state.
    """
    closes = [22000 + 20 * i for i in range(15)]
    docs = _bar_docs(closes)

    engine = IndicatorEngine()
    on_bar_calls: list[datetime] = []
    _real_on_bar = engine.on_bar

    def _spy(bar):
        on_bar_calls.append(bar.bar_time)
        return _real_on_bar(bar)

    engine.on_bar = _spy  # type: ignore[method-assign]

    db = _FakeDB(docs)
    watchlist = [{"security_id": "13", "exchange_segment": "IDX_I", "timeframes": ["5m"]}]

    result = await warm_up_indicator_engine(engine, db, _NO_CREDS, watchlist)

    # No return value → no signals propagated up the call stack
    assert result is None
    # engine.on_bar called exactly once per historical bar
    assert len(on_bar_calls) == len(docs)
    # Calls were in chronological order (sorted ascending)
    assert on_bar_calls == sorted(on_bar_calls)
    # Engine state bar_time is the last warmup bar — a past timestamp, not "now"
    state = engine.get("13", "5m")
    assert state is not None
    assert state.bar_time == docs[-1]["ts"]
