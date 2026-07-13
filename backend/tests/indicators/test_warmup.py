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
from zoneinfo import ZoneInfo

import pytest

from pdp.indicators.engine import IndicatorEngine
from pdp.indicators.supertrend import UP
from pdp.indicators.warmup import (
    _fetch_from_dhan,
    _prior_trading_day,
    lookback_days,
    required_bars,
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

    # Warmup looks back lookback_days("5m", required_bars(entry indicators)) calendar
    # days from the prior day, anchored at that day's session start (03:45 UTC).
    query = db.col.queries[0]
    since_ts = query["ts"]["$gte"]
    days_back = lookback_days("5m", required_bars(watchlist[0].get("indicators", [])))
    warmup_from = fixed_prior_day - timedelta(days=days_back - 1)
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
    # Warmup demands required_bars() across the entry's configured indicators
    # (200 floor with no "indicators" configured on this watchlist entry);
    # supply comfortably above that target so no top-up fires.
    target = required_bars([])
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
        engine.seed_from_bars([bar])

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
    engine.seed_from_bars([bar])

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


# ── dhan-same-day-data: IST boundary via ZoneInfo (task 3.2) ────────────────


def test_prior_trading_day_boundary_1829_utc_is_still_2026_07_09():
    """18:29 UTC on 2026-07-09 is 23:59 IST the same day -> prior trading day is 07-08."""
    from unittest.mock import patch as _patch

    ist_instant = datetime(2026, 7, 9, 18, 29, tzinfo=UTC).astimezone(ZoneInfo("Asia/Kolkata"))
    with _patch("pdp.indicators.warmup.datetime") as mock_dt:
        mock_dt.now.return_value = ist_instant
        result = _prior_trading_day(set())
    assert result == date(2026, 7, 8)  # 2026-07-09 is a Thursday -> prior trading day is Wed 07-08


def test_prior_trading_day_boundary_1831_utc_rolls_to_2026_07_10():
    """18:31 UTC on 2026-07-09 is 00:01 IST on 2026-07-10 -> prior trading day is 07-09."""
    from unittest.mock import patch as _patch

    ist_instant = datetime(2026, 7, 9, 18, 31, tzinfo=UTC).astimezone(ZoneInfo("Asia/Kolkata"))
    with _patch("pdp.indicators.warmup.datetime") as mock_dt:
        mock_dt.now.return_value = ist_instant
        result = _prior_trading_day(set())
    assert result == date(2026, 7, 9)  # 2026-07-10 is a Friday -> prior trading day is Thu 07-09


def test_fetch_from_dhan_today_ist_boundary_1829_utc():
    """3.2: today_ist derived at 18:29 UTC on 2026-07-09 is still 2026-07-09."""
    now = datetime(2026, 7, 9, 18, 29, tzinfo=UTC)
    fake_client = _FakeDhanResponseClient(_dhan_resp([]))
    with (
        patch("dhanhq.dhanhq", return_value=fake_client),
        patch("dhanhq.DhanContext", return_value=object()),
    ):
        _fetch_from_dhan(_DHAN_CREDS, "13", "IDX_I", "5m", prior_day=date(2026, 7, 8), now=now)
    assert fake_client.last_call["to_date"] == "2026-07-09"


def test_fetch_from_dhan_today_ist_boundary_1831_utc_rolls_over():
    """3.2: today_ist derived at 18:31 UTC on 2026-07-09 rolls to 2026-07-10."""
    now = datetime(2026, 7, 9, 18, 31, tzinfo=UTC)
    fake_client = _FakeDhanResponseClient(_dhan_resp([]))
    with (
        patch("dhanhq.dhanhq", return_value=fake_client),
        patch("dhanhq.DhanContext", return_value=object()),
    ):
        _fetch_from_dhan(_DHAN_CREDS, "13", "IDX_I", "5m", prior_day=date(2026, 7, 9), now=now)
    assert fake_client.last_call["to_date"] == "2026-07-10"


def test_prior_trading_day_late_evening_1930_utc_maps_to_next_ist_day():
    """spec.md: 19:30 UTC on 2026-07-09 is 01:00 IST on 2026-07-10 -> prior trading day is 07-09."""
    from unittest.mock import patch as _patch

    ist_instant = datetime(2026, 7, 9, 19, 30, tzinfo=UTC).astimezone(ZoneInfo("Asia/Kolkata"))
    with _patch("pdp.indicators.warmup.datetime") as mock_dt:
        mock_dt.now.return_value = ist_instant
        result = _prior_trading_day(set())
    assert result == date(2026, 7, 9)  # 2026-07-10 is a Friday -> prior trading day is Thu 07-09


def test_fetch_from_dhan_late_evening_1930_utc_maps_to_next_ist_day():
    """spec.md: today_ist derived at 19:30 UTC on 2026-07-09 rolls to 2026-07-10."""
    now = datetime(2026, 7, 9, 19, 30, tzinfo=UTC)
    fake_client = _FakeDhanResponseClient(_dhan_resp([]))
    with (
        patch("dhanhq.dhanhq", return_value=fake_client),
        patch("dhanhq.DhanContext", return_value=object()),
    ):
        _fetch_from_dhan(_DHAN_CREDS, "13", "IDX_I", "5m", prior_day=date(2026, 7, 9), now=now)
    assert fake_client.last_call["to_date"] == "2026-07-10"


# ── dhan-same-day-data: incomplete-candle guard (tasks 2.1-2.2) ─────────────


class _FakeDhanResponseClient:
    """Stands in for `dhanhq.dhanhq` — returns a canned intraday response and
    records the last call's kwargs (e.g. to assert the computed `to_date`)."""

    def __init__(self, resp: dict) -> None:
        self._resp = resp
        self.last_call: dict = {}

    def intraday_minute_data(self, **kwargs):
        self.last_call = kwargs
        return self._resp

    def historical_daily_data(self, **kwargs):
        self.last_call = kwargs
        return self._resp


def _dhan_resp(timestamps: list[int]) -> dict:
    n = len(timestamps)
    return {
        "status": "success",
        "data": {
            "open": [100.0] * n,
            "high": [101.0] * n,
            "low": [99.0] * n,
            "close": [100.5] * n,
            "volume": [10] * n,
            "start_Time": timestamps,
        },
    }


def test_fetch_from_dhan_drops_still_forming_final_candle():
    """2.1: a fetch at 11:07 IST returning a 5m candle stamped 11:05 IST is discarded."""
    now = datetime(2026, 6, 15, 5, 37, tzinfo=UTC)  # 11:07 IST
    stamped_1105_ist = datetime(2026, 6, 15, 5, 35, tzinfo=UTC)  # 11:05 IST -> +5m = 11:10 > now
    ts = int(stamped_1105_ist.timestamp())

    fake_client = _FakeDhanResponseClient(_dhan_resp([ts]))
    with (
        patch("dhanhq.dhanhq", return_value=fake_client),
        patch("dhanhq.DhanContext", return_value=object()),
    ):
        bars = _fetch_from_dhan(
            _DHAN_CREDS, "13", "IDX_I", "5m", prior_day=date(2026, 6, 12), now=now
        )

    assert bars == []


def test_fetch_from_dhan_retains_completed_candles_after_close():
    """2.2: a fetch at 16:00 IST retains the 15:25 candle (15:25 + 5m = 15:30 <= 16:00)."""
    now = datetime(2026, 6, 15, 10, 30, tzinfo=UTC)  # 16:00 IST
    stamped_1525_ist = datetime(2026, 6, 15, 9, 55, tzinfo=UTC)  # 15:25 IST
    ts = int(stamped_1525_ist.timestamp())

    fake_client = _FakeDhanResponseClient(_dhan_resp([ts]))
    with (
        patch("dhanhq.dhanhq", return_value=fake_client),
        patch("dhanhq.DhanContext", return_value=object()),
    ):
        bars = _fetch_from_dhan(
            _DHAN_CREDS, "13", "IDX_I", "5m", prior_day=date(2026, 6, 12), now=now
        )

    assert len(bars) == 1
    assert bars[0].bar_time == stamped_1525_ist


def test_fetch_from_dhan_mixed_batch_keeps_only_complete_bars():
    """A batch with both a settled and a still-forming candle keeps only the settled one."""
    now = datetime(2026, 6, 15, 5, 37, tzinfo=UTC)  # 11:07 IST
    settled = datetime(2026, 6, 15, 5, 30, tzinfo=UTC)  # 11:00 IST -> +5m = 11:05 <= now
    forming = datetime(2026, 6, 15, 5, 35, tzinfo=UTC)  # 11:05 IST -> +5m = 11:10 > now
    timestamps = [int(settled.timestamp()), int(forming.timestamp())]

    fake_client = _FakeDhanResponseClient(_dhan_resp(timestamps))
    with (
        patch("dhanhq.dhanhq", return_value=fake_client),
        patch("dhanhq.DhanContext", return_value=object()),
    ):
        bars = _fetch_from_dhan(
            _DHAN_CREDS, "13", "IDX_I", "5m", prior_day=date(2026, 6, 12), now=now
        )

    assert len(bars) == 1
    assert bars[0].bar_time == settled


# ── indicator-history-depth: required_bars / lookback_days (tasks 1.2–1.4) ──


class TestRequiredBars:
    def test_ema_200_needs_1000_bars(self):
        indicators = [{"family": "ema", "periods": [9, 20, 50, 100, 200]}]
        assert required_bars(indicators) == 1000  # 5 x 200

    def test_floor_applies_to_short_periods(self):
        """Largest configured period is 14 (rsi) -> floor of 200, not 5*14=70."""
        indicators = [{"family": "rsi", "period": 14, "ma_period": 9}]
        assert required_bars(indicators) == 200

    def test_no_indicators_configured_floors_to_200(self):
        assert required_bars([]) == 200

    def test_max_across_multiple_families(self):
        indicators = [
            {"family": "rsi", "period": 14},
            {"family": "ema", "periods": [9, 20, 50, 100, 200]},
            {"family": "macd", "fast": 12, "slow": 26, "signal": 9},
        ]
        assert required_bars(indicators) == 1000  # ema's 200 dominates


class TestLookbackDays:
    def test_unknown_timeframe_raises_naming_it(self):
        with pytest.raises(ValueError, match="7m"):
            lookback_days("7m", 1000)

    def test_longer_period_widens_window_automatically(self):
        """A config's largest EMA period going from 100 to 200 must double the
        derived lookback with no change to this module."""
        short = lookback_days("30m", required_bars([{"family": "ema", "periods": [9, 20, 50, 100]}]))
        long = lookback_days("30m", required_bars([{"family": "ema", "periods": [9, 20, 50, 100, 200]}]))
        assert long == short * 2


# ── indicator-history-depth: indicator_warmup_short (task 1.4) ──────────────


def _events(mock_log, name: str) -> list[dict]:
    """Extract (event_name, kwargs) calls made on a mocked structlog logger.

    Not structlog.testing.capture_logs(): pdp.logging configures
    cache_logger_on_first_use=True, so a module-level `log` already exercised
    elsewhere in a full-suite run has its bound logger permanently cached with
    the real processor chain -- capture_logs()'s reconfiguration never reaches
    it. Patching the module's `log` object directly is order-independent.
    """
    calls = mock_log.warning.call_args_list + mock_log.info.call_args_list
    return [c.kwargs for c in calls if c.args and c.args[0] == name]


@pytest.mark.asyncio
async def test_warmup_short_emits_exactly_one_warning_with_counts():
    """150 of 1000 required 30m bars for a single-family (ema, period 200) entry
    emits exactly one indicator_warmup_short carrying bars_found/bars_needed."""
    from unittest.mock import MagicMock

    import pdp.indicators.warmup as warmup_module

    engine = IndicatorEngine()
    db = _FakeDB(_bar_docs([22000 + i for i in range(150)]))
    watchlist = [
        {
            "security_id": "13",
            "exchange_segment": "IDX_I",
            "timeframes": ["30m"],
            "indicators": [{"family": "ema", "periods": [9, 20, 50, 100, 200]}],
        }
    ]

    mock_log = MagicMock()
    with patch.object(warmup_module, "log", mock_log):
        await warm_up_indicator_engine(engine, db, _NO_CREDS, watchlist)

    short_events = _events(mock_log, "indicator_warmup_short")
    assert len(short_events) == 1
    assert short_events[0]["security_id"] == "13"
    assert short_events[0]["timeframe"] == "30m"
    assert short_events[0]["family"] == "ema"
    assert short_events[0]["bars_found"] == 150
    assert short_events[0]["bars_needed"] == 1000


@pytest.mark.asyncio
async def test_warmup_no_short_warning_when_depth_met():
    from unittest.mock import MagicMock

    import pdp.indicators.warmup as warmup_module

    engine = IndicatorEngine()
    db = _FakeDB(_bar_docs([22000 + i for i in range(250)]))
    watchlist = [
        {
            "security_id": "13",
            "exchange_segment": "IDX_I",
            "timeframes": ["5m"],
            "indicators": [{"family": "rsi", "period": 14}],
        }
    ]

    mock_log = MagicMock()
    with patch.object(warmup_module, "log", mock_log):
        await warm_up_indicator_engine(engine, db, _NO_CREDS, watchlist)

    assert _events(mock_log, "indicator_warmup_short") == []


# ── indicator-history-depth: engine.seeding_summary (task 6.3) ──────────────


# ── bias-input-completeness: weekly pivot seeding correctness ──────────────


def _week_bar_docs(weeks: list[tuple[float, float, float]]) -> list[dict]:
    """Ascending synthetic 1w bar docs, one per ISO week, Monday-anchored.

    Mirrors the shape ``_synthesize_weekly_from_daily``/a real BarAggregator 1w
    doc would produce: ``ts`` = the ISO week's Monday, ``high``/``low``/``close``
    = that single week's own range.
    """
    from pdp.market.bars import _bar_boundary_1w

    base_monday = _bar_boundary_1w(datetime.now(UTC)) - timedelta(weeks=len(weeks))
    docs = []
    for i, (h, lo, c) in enumerate(weeks):
        ts = base_monday + timedelta(weeks=i)
        docs.append({"ts": ts, "open": (h + lo) / 2, "high": h, "low": lo, "close": c, "volume": 0, "oi": 0})
    return docs


@pytest.mark.asyncio
async def test_weekly_pivot_seeds_from_single_prior_week_not_aggregate():
    """Weekly Camarilla must reflect exactly the most recently completed ISO
    week's HLC, not an aggregate high/low across several prior weeks.

    _warm_one's generic "prior session" filter (bar_time >= yesterday) is built
    for daily-or-finer bars; a Monday-anchored 1w bar's timestamp is never >=
    yesterday, so it always fell through to the bars[-10:] fallback and
    aggregated up to 10 weeks' high/low together (keeping only the most recent
    week's close) instead of using that single most-recent week's own HLC.
    """
    engine = IndicatorEngine()
    engine.configure_suite("13", "1w", [{"family": "pivots"}])
    weeks = [
        (100.0, 90.0, 95.0),
        (110.0, 95.0, 105.0),
        (90.0, 80.0, 85.0),
        (120.0, 100.0, 115.0),
        (105.0, 98.0, 102.0),  # most recently completed week
    ]
    docs = _week_bar_docs(weeks)
    db = _FakeDB(docs)
    watchlist = [
        {
            "security_id": "13",
            "exchange_segment": "IDX_I",
            "timeframes": ["1w"],
            "indicators": [{"family": "pivots"}],
        }
    ]

    await warm_up_indicator_engine(engine, db, _NO_CREDS, watchlist)

    state = engine.get_pivots("13", "1w")
    assert state is not None
    assert state.prior_h == 105.0
    assert state.prior_l == 98.0
    assert state.prior_c == 102.0


class TestSeedingSummary:
    def test_partial_seeding_reports_exactly_unseeded_combinations(self):
        engine = IndicatorEngine()
        sid, tf = "13", "1H"
        engine.configure_suite(sid, tf, [{"family": "ema", "periods": [9, 20, 200]}, {"family": "vwap"}])

        base = datetime(2026, 1, 1, tzinfo=UTC)
        for i in range(20):
            bar = BarClosed(
                security_id=sid, timeframe=tf, bar_time=base + timedelta(hours=i),
                open=Decimal(100 + i), high=Decimal(101 + i), low=Decimal(99 + i),
                close=Decimal(100 + i), volume=10, oi=0,
            )
            engine.on_bar(bar)

        summary = engine.seeding_summary(sid, tf)
        assert summary[("ema", 9)] is True
        assert summary[("ema", 20)] is True
        assert summary[("ema", 200)] is False  # only 20 bars fed, needs 200
        assert summary[("vwap", None)] is True  # vwap has no convergence period

    def test_fully_seeded_reports_no_unseeded_combinations(self):
        engine = IndicatorEngine()
        sid, tf = "13", "5m"
        engine.configure_suite(sid, tf, [{"family": "ema", "periods": [3]}])

        base = datetime(2026, 1, 1, tzinfo=UTC)
        for i in range(5):
            bar = BarClosed(
                security_id=sid, timeframe=tf, bar_time=base + timedelta(minutes=5 * i),
                open=Decimal(100), high=Decimal(101), low=Decimal(99), close=Decimal(100),
                volume=10, oi=0,
            )
            engine.on_bar(bar)

        summary = engine.seeding_summary(sid, tf)
        assert all(summary.values())
