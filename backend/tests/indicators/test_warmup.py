"""Indicator engine warmup tests.

Original suite (GAP 1 / task 1.4):
  Priming, cold-start, ordering, and signal-suppression tests for the existing
  warmup contract.

Session-warmup suite (live-supertrend-session-warmup tasks 2.1–2.3):
  _prior_trading_day unit tests, session-aware Mongo query verification, and
  thin-Mongo → Dhan-fallback trigger.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from pdp.indicators.engine import IndicatorEngine
from pdp.indicators.supertrend import UP
from pdp.indicators.warmup import (
    _prior_trading_day,
    warm_up_indicator_engine,
)
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


# NSE_HOLIDAYS_JSON points to a nonexistent path so holidays() returns set() without error.
_NO_CREDS = SimpleNamespace(
    DHAN_CLIENT_ID="", DHAN_ACCESS_TOKEN="", NSE_HOLIDAYS_JSON="/nonexistent/holidays.json"
)
_DHAN_CREDS = SimpleNamespace(
    DHAN_CLIENT_ID="test_id",
    DHAN_ACCESS_TOKEN="test_token",
    NSE_HOLIDAYS_JSON="/nonexistent/holidays.json",
)


# ── Original tests ────────────────────────────────────────────────────────────


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
    assert test_state.bar_time == ref_state.bar_time, (
        "last processed bar must be the chronologically-last bar"
    )


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


# ── Session-warmup tests (tasks 2.1 – 2.3) ───────────────────────────────────

# 2.1 — _prior_trading_day unit tests


def test_prior_trading_day_monday_returns_friday():
    """A Monday restart should seed from the prior Friday session."""
    monday = date(2026, 6, 15)  # 2026-06-15 is a Monday
    result = _prior_trading_day(set(), _today=monday)
    assert result == date(2026, 6, 12)  # 2026-06-12 is Friday


def test_prior_trading_day_tuesday_returns_monday():
    tuesday = date(2026, 6, 16)  # 2026-06-16 is a Tuesday
    result = _prior_trading_day(set(), _today=tuesday)
    assert result == date(2026, 6, 15)


def test_prior_trading_day_skips_holiday_cluster():
    """Monday + prior Friday both holidays → falls back to Thursday."""
    monday = date(2026, 6, 15)
    holiday_set = {date(2026, 6, 12)}  # Friday is a holiday
    result = _prior_trading_day(holiday_set, _today=monday)
    assert result == date(2026, 6, 11)  # Thursday


# 2.2 — Mongo query uses prior-session since


@pytest.mark.asyncio
async def test_warmup_mongo_query_uses_prior_session_start():
    """The $gte timestamp in the Mongo query is the prior day's session start (03:45 UTC),
    not a fixed wall-clock window from now."""
    engine = IndicatorEngine()
    db = _FakeDB(_bar_docs([22000 + 20 * i for i in range(15)]))
    watchlist = [{"security_id": "13", "exchange_segment": "IDX_I", "timeframes": ["5m"]}]

    fixed_prior_day = date(2026, 6, 12)  # Friday
    with patch("pdp.indicators.warmup._prior_trading_day", return_value=fixed_prior_day):
        await warm_up_indicator_engine(engine, db, _NO_CREDS, watchlist)

    # Warmup looks back _TF_WARMUP_CALENDAR_DAYS["5m"] calendar days from the prior day,
    # anchored at that day's session start (03:45 UTC), so EMA(100) can seed.
    from pdp.indicators.warmup import _TF_WARMUP_CALENDAR_DAYS

    query = db.col.queries[0]
    since_ts = query["ts"]["$gte"]
    warmup_from = fixed_prior_day - timedelta(days=_TF_WARMUP_CALENDAR_DAYS["5m"] - 1)
    expected = datetime(warmup_from.year, warmup_from.month, warmup_from.day, 3, 45, tzinfo=UTC)
    assert since_ts == expected


# 2.3 — Thin Mongo triggers Dhan fallback


@pytest.mark.asyncio
async def test_warmup_thin_mongo_triggers_dhan_fallback():
    """When Mongo holds fewer bars than a full prior session and Dhan creds are
    present, the API fetch is invoked."""
    engine = IndicatorEngine()
    # 3 bars — well below the 75-bar session target for 5m
    db = _FakeDB(_bar_docs([22000 + 20 * i for i in range(3)]))
    watchlist = [{"security_id": "13", "exchange_segment": "IDX_I", "timeframes": ["5m"]}]

    with patch("pdp.indicators.warmup._fetch_from_dhan", return_value=[]) as mock_fetch:
        await warm_up_indicator_engine(engine, db, _DHAN_CREDS, watchlist)

    mock_fetch.assert_called_once()
    args = mock_fetch.call_args.args
    assert args[1] == "13"  # security_id
    assert args[3] == "5m"  # timeframe


@pytest.mark.asyncio
async def test_warmup_full_mongo_skips_dhan_fallback():
    """When Mongo returns enough bars to seed EMA(100), the Dhan API is not called."""
    engine = IndicatorEngine()
    # Warmup demands enough bars to seed EMA(100) across the deepened 5m lookback
    # window; supply comfortably above that target so no top-up fires.
    from pdp.indicators.warmup import _TF_SESSION_BARS, _TF_WARMUP_CALENDAR_DAYS

    target = max(100, _TF_SESSION_BARS["5m"] * max(1, _TF_WARMUP_CALENDAR_DAYS["5m"] // 2))
    db = _FakeDB(_bar_docs([22000 + 20 * i for i in range(target + 10)]))
    watchlist = [{"security_id": "13", "exchange_segment": "IDX_I", "timeframes": ["5m"]}]

    with patch("pdp.indicators.warmup._fetch_from_dhan") as mock_fetch:
        await warm_up_indicator_engine(engine, db, _DHAN_CREDS, watchlist)

    mock_fetch.assert_not_called()


# 3.1 — Mid-day restart inherits prior-session direction (not cold-start)


@pytest.mark.asyncio
async def test_mid_day_restart_inherits_prior_session_direction():
    """3.1: Engine warmed from a prior up-session carries UP direction — not a cold-start None."""
    engine = IndicatorEngine()
    # 75 bars of strong uptrend — one full 5m session
    docs = _bar_docs([22000 + 50 * i for i in range(75)])
    db = _FakeDB(docs)
    watchlist = [{"security_id": "13", "exchange_segment": "IDX_I", "timeframes": ["5m"]}]

    await warm_up_indicator_engine(engine, db, _NO_CREDS, watchlist)

    state = engine.get("13", "5m")
    assert state is not None, "engine must be primed after a full prior session"
    assert state.direction == UP, "prior uptrend must carry over as UP, not cold-start None"


# ---------------------------------------------------------------------------
# Indicator engine is_warm
# ---------------------------------------------------------------------------


def test_engine_is_warm_tracks_bar_counts():
    engine = IndicatorEngine()
    sid = "13"
    tf = "5m"

    # initially cold
    assert not engine.is_warm(sid, tf, min_bars=200)

    # feed bars
    for i in range(199):
        bar = BarClosed(
            security_id=sid,
            timeframe=tf,
            bar_time=datetime.now(UTC),
            open=Decimal(100),
            high=Decimal(100),
            low=Decimal(100),
            close=Decimal(100),
            volume=0,
            oi=0,
        )
        engine.seed_from_bars(sid, tf, [bar])

    # still cold (199 bars)
    assert not engine.is_warm(sid, tf, min_bars=200)

    # feed 1 more
    bar = BarClosed(
        security_id=sid,
        timeframe=tf,
        bar_time=datetime.now(UTC),
        open=Decimal(100),
        high=Decimal(100),
        low=Decimal(100),
        close=Decimal(100),
        volume=0,
        oi=0,
    )
    engine.seed_from_bars(sid, tf, [bar])

    # now warm
    assert engine.is_warm(sid, tf, min_bars=200)


# 3.2 — Warmup path == direct seed path (parity)


@pytest.mark.asyncio
async def test_warmup_direction_matches_direct_seed_parity():
    """3.2: Warmup path and direct seed_from_bars produce identical SuperTrend direction —
    proving live direction matches the backtest's warmed series for the same bars."""
    closes = [22000 + 50 * i for i in range(75)]
    docs = _bar_docs(closes)

    # Direct-seed path (backtest equivalent)
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
        for doc in docs
    ]
    engine_ref.seed_from_bars(bars_ref)
    ref_direction = engine_ref.get("13", "5m").direction

    # Warmup path (live-process equivalent)
    engine_live = IndicatorEngine()
    db = _FakeDB(docs)
    watchlist = [{"security_id": "13", "exchange_segment": "IDX_I", "timeframes": ["5m"]}]
    await warm_up_indicator_engine(engine_live, db, _NO_CREDS, watchlist)
    live_direction = engine_live.get("13", "5m").direction

    assert live_direction == ref_direction, (
        f"warmup direction ({live_direction}) must match direct-seed ({ref_direction})"
    )
