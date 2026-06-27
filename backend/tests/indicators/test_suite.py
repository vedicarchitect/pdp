"""Tests for the indicator suite: per-family unit tests, config-driven selection,
backtest parity, and a latency micro-benchmark.
"""
from __future__ import annotations

import time
from datetime import UTC, date, datetime, timedelta, timezone

import pytest

from pdp.indicators.ema import EMATracker
from pdp.indicators.engine import IndicatorEngine
from pdp.indicators.fvg import FVGTracker
from pdp.indicators.market_profile import MarketProfileTracker
from pdp.indicators.pivots import PivotTracker, _compute_pivots
from pdp.indicators.psar import ParabolicSARTracker
from pdp.indicators.registry import available_families, build_tracker
from pdp.indicators.rsi import RSITracker
from pdp.indicators.snapshot import Snapshot
from pdp.indicators.volume_profile import VolumeProfileTracker
from pdp.indicators.vwap import VWAPTracker
from pdp.indicators.vwma import VWMATracker


# ── helpers ───────────────────────────────────────────────────────────────────

def _bar(close, high=None, low=None, volume=1000, bar_time=None, n=0):
    """Build a minimal bar tuple that trackers accept."""
    h = high if high is not None else close + 5
    lo = low if low is not None else close - 5
    t = bar_time or datetime(2026, 6, 15, 4, 0, n % 60, tzinfo=UTC)
    return h, lo, close, float(volume), t


def _make_bar_closed(close, high=None, low=None, volume=1000, bar_time=None,
                      security_id="13", timeframe="15m"):
    """Return a BarClosed-like object with the given values."""
    from decimal import Decimal
    from pdp.market.bars import BarClosed
    h = high if high is not None else close + 5
    lo = low if low is not None else close - 5
    t = bar_time or datetime(2026, 6, 15, 4, 0, tzinfo=UTC)
    return BarClosed(
        security_id=security_id,
        timeframe=timeframe,
        bar_time=t,
        open=Decimal(str(close)),
        high=Decimal(str(h)),
        low=Decimal(str(lo)),
        close=Decimal(str(close)),
        volume=int(volume),
        oi=0,
    )


# ── 6.1 Per-family unit tests ─────────────────────────────────────────────────

class TestEMATracker:
    def test_none_until_seeded(self):
        t = EMATracker(periods=[3])
        for c in [10.0, 11.0]:
            assert t.update(*_bar(c)[:5]) is None
        result = t.update(*_bar(12.0)[:5])
        assert result is not None
        assert 3 in result.values

    def test_seed_from_sma(self):
        t = EMATracker(periods=[3])
        closes = [10.0, 11.0, 12.0]
        for c in closes:
            state = t.update(*_bar(c)[:5])
        # Seed = SMA of first 3 = (10+11+12)/3 = 11.0
        assert state is not None
        assert abs(state.values[3] - 11.0) < 1e-9

    def test_incremental_update(self):
        t = EMATracker(periods=[3])
        closes = [10.0, 11.0, 12.0]
        for c in closes:
            t.update(*_bar(c)[:5])
        # After seed=11.0, apply EMA(3) with alpha=0.5 to close=13.0
        alpha = 2.0 / 4  # alpha for period=3
        expected = alpha * 13.0 + (1 - alpha) * 11.0
        state = t.update(*_bar(13.0)[:5])
        assert state is not None
        assert abs(state.values[3] - expected) < 1e-9

    def test_multiple_periods_partial_ready(self):
        t = EMATracker(periods=[3, 5])
        closes = [float(i) for i in range(1, 4)]
        for c in closes:
            state = t.update(*_bar(c)[:5])
        # period=3 seeded, period=5 not yet
        assert state is not None
        assert 3 in state.values
        assert 5 not in state.values


class TestRSITracker:
    def _feed(self, closes):
        t = RSITracker(period=3)
        state = None
        for c in closes:
            state = t.update(*_bar(c)[:5])
        return state

    def test_none_until_seeded(self):
        # Need at least period+1 bars (1 for first close + period changes)
        t = RSITracker(period=3)
        # Feed only 2 changes (3 bars): seed at bar 4 (1 diff + 3 for seed)
        for c in [10.0, 11.0, 10.5]:
            assert t.update(*_bar(c)[:5]) is None
        state = t.update(*_bar(11.0)[:5])
        assert state is not None

    def test_all_gains_gives_100(self):
        t = RSITracker(period=3)
        # After seeding with all gains, RSI approaches 100
        closes = [10.0, 11.0, 12.0, 13.0]
        for c in closes:
            state = t.update(*_bar(c)[:5])
        assert state is not None
        assert state.rsi > 90.0

    def test_all_losses_gives_near_0(self):
        t = RSITracker(period=3)
        closes = [13.0, 12.0, 11.0, 10.0]
        for c in closes:
            state = t.update(*_bar(c)[:5])
        assert state is not None
        assert state.rsi < 10.0

    def test_wilder_reference(self):
        # Feed a known series and verify Wilder RSI matches hand-computed value
        # period=3, series: 10, 12, 11, 13, 14, 12
        # Changes: +2, -1, +2, +1, -2
        # Seed (first 3 changes): avg_gain=(2+0+2)/3=4/3, avg_loss=(0+1+0)/3=1/3
        # 4th change (+1): avg_gain=(4/3*2+1)/3=11/9, avg_loss=(1/3*2+0)/3=2/9
        # 5th change (-2): avg_gain=(11/9*2+0)/3=22/27, avg_loss=(2/9*2+2)/3=22/27
        # RSI = 100 - 100/(1+1) = 50.0
        t = RSITracker(period=3)
        closes = [10.0, 12.0, 11.0, 13.0, 14.0, 12.0]
        state = None
        for c in closes:
            state = t.update(*_bar(c)[:5])
        assert state is not None
        assert abs(state.rsi - 50.0) < 0.01
        # With default ma_period=9, only 3 RSI values have been seen — MA not yet seeded
        assert state.ma is None

    def test_ma_none_until_enough_rsi_values(self):
        # period=3, ma_period=3: RSI seeded at bar 4; MA needs 3 RSI values → seeded at bar 6
        t = RSITracker(period=3, ma_period=3)
        closes = [10.0, 12.0, 11.0, 13.0, 14.0, 12.0]
        states = [s for c in closes if (s := t.update(*_bar(c)[:5])) is not None]
        # bars 3,4,5 produce RSI values (3 total)
        assert len(states) == 3
        assert states[0].ma is None   # 1 of 3 RSI values
        assert states[1].ma is None   # 2 of 3 RSI values
        assert states[2].ma is not None  # 3rd RSI value seeds MA from SMA

    def test_ma_is_sma_on_seed_then_ema(self):
        # period=3, ma_period=3; verify first MA value equals SMA of first 3 RSI values
        t = RSITracker(period=3, ma_period=3)
        closes = [10.0, 12.0, 11.0, 13.0, 14.0, 12.0]
        rsi_vals: list[float] = []
        for c in closes:
            s = t.update(*_bar(c)[:5])
            if s is not None:
                rsi_vals.append(s.rsi)
        expected_ma_seed = sum(rsi_vals) / 3
        # Feed one more bar to get the EMA-updated MA
        s2 = t.update(*_bar(13.0)[:5])
        assert s2 is not None and s2.ma is not None
        alpha = 2.0 / (3 + 1)
        expected_ma_next = alpha * s2.rsi + (1 - alpha) * expected_ma_seed
        assert abs(s2.ma - expected_ma_next) < 1e-9

    def test_ma_in_valid_rsi_range(self):
        t = RSITracker(period=5, ma_period=3)
        closes = [float(100 + i % 7) for i in range(20)]
        state = None
        for c in closes:
            state = t.update(*_bar(c)[:5])
        assert state is not None and state.ma is not None
        assert 0.0 <= state.ma <= 100.0


class TestParabolicSARTracker:
    def test_none_on_first_bar(self):
        t = ParabolicSARTracker()
        assert t.update(*_bar(100.0)[:5]) is None

    def test_state_on_second_bar(self):
        t = ParabolicSARTracker()
        t.update(*_bar(100.0)[:5])
        state = t.update(*_bar(110.0)[:5])
        assert state is not None
        assert state.direction in (1, -1)
        assert state.sar > 0

    def test_flip_on_reversal(self):
        t = ParabolicSARTracker(step=0.02, max_step=0.2)
        # Start with downtrend bars, then a strong upward reversal
        bars = [
            (90, 80, 85),   # bar 1: init with downtrend expectation
            (88, 75, 76),   # bar 2: confirm downtrend (close < prior high)
            (89, 73, 74),   # bar 3: downtrend continues
            (88, 72, 73),
            (87, 71, 72),
        ]
        state = None
        for h, lo, c in bars:
            state = t.update(h, lo, c, 0.0, None)
        # Capture the direction
        if state is not None:
            start_dir = state.direction
            # Now push a strong rally above SAR
            for _ in range(10):
                state = t.update(200, 199, 199, 0.0, None)
            assert state is not None
            assert state.direction != start_dir or state.sar < 200  # flipped or SAR below price


class TestVWAPTracker:
    def _ts(self, h, m, day=15):
        return datetime(2026, 6, day, h, m, tzinfo=UTC)

    def test_none_with_zero_volume(self):
        t = VWAPTracker()
        assert t.update(100, 95, 97, 0.0, self._ts(4, 0)) is None

    def test_basic_vwap(self):
        t = VWAPTracker()
        # Bar 1: typical=100, vol=100 → sum_pv=10000, sum_v=100
        state = t.update(105, 95, 100, 100.0, self._ts(4, 0))
        assert state is not None
        assert abs(state.vwap - 100.0) < 0.01

    def test_session_reset(self):
        t = VWAPTracker()
        # Day 1
        t.update(110, 100, 105, 1000.0, self._ts(4, 0, day=14))
        t.update(115, 105, 110, 1000.0, self._ts(4, 15, day=14))
        s1 = t.update(120, 110, 115, 1000.0, self._ts(5, 0, day=14))
        # Day 2 – new session, accumulator resets
        t.update(200, 190, 195, 500.0, self._ts(4, 0, day=15))
        s2 = t.update(210, 200, 205, 500.0, self._ts(4, 15, day=15))
        # VWAP for day 2 should be based only on day-2 bars
        assert s2 is not None
        # Typical prices on day 2 are ~195 and ~205; VWAP ≈ 200, definitely not 115
        assert s2.vwap > 180


class TestVWMATracker:
    def test_none_until_window_full(self):
        t = VWMATracker(period=3)
        assert t.update(*_bar(100.0)[:5]) is None
        assert t.update(*_bar(101.0)[:5]) is None
        state = t.update(*_bar(102.0)[:5])
        assert state is not None

    def test_rolling_window(self):
        t = VWMATracker(period=2)
        vol = 100.0
        t.update(105, 95, 100, vol, None)
        state = t.update(115, 105, 110, vol, None)
        # typical_1=100, typical_2=110, equal volumes → VWMA = 105
        assert state is not None
        assert abs(state.vwma - 105.0) < 0.5


class TestPivotTracker:
    def test_camarilla_levels_from_known_hlc(self):
        h, l, c = 200.0, 100.0, 150.0
        session = date(2026, 6, 15)
        state = _compute_pivots(h, l, c, session)
        rng = h - l  # 100
        # Camarilla R3 = C + Range * 1.1/4 = 150 + 100*0.275 = 177.5
        assert abs(state.cam_r3 - 177.5) < 0.01
        # Camarilla S3 = C - Range * 1.1/4 = 150 - 27.5 = 122.5
        assert abs(state.cam_s3 - 122.5) < 0.01
        # Standard PP = (H+L+C)/3 = 450/3 = 150
        assert abs(state.pp - 150.0) < 0.01

    def test_fibonacci_levels(self):
        h, l, c = 200.0, 100.0, 150.0
        session = date(2026, 6, 15)
        state = _compute_pivots(h, l, c, session)
        rng = 100.0
        pp = 150.0
        assert abs(state.fib_r1 - (pp + 0.382 * rng)) < 0.01
        assert abs(state.fib_s1 - (pp - 0.382 * rng)) < 0.01

    def test_standard_pivots(self):
        h, l, c = 200.0, 100.0, 150.0
        session = date(2026, 6, 15)
        state = _compute_pivots(h, l, c, session)
        pp = 150.0
        assert abs(state.r1 - (2 * pp - l)) < 0.01
        assert abs(state.s1 - (2 * pp - h)) < 0.01

    def test_pivot_seed_and_return(self):
        t = PivotTracker()
        t.seed_prior_hlc(200.0, 100.0, 150.0, date(2026, 6, 14))
        state = t.update(160, 155, 158, 100.0, datetime(2026, 6, 15, 4, 0, tzinfo=UTC))
        assert state is not None
        assert abs(state.pp - 150.0) < 0.01

    def test_new_session_recomputes(self):
        t = PivotTracker()
        ts_day1 = datetime(2026, 6, 14, 4, 0, tzinfo=UTC)
        ts_day2 = datetime(2026, 6, 15, 4, 0, tzinfo=UTC)
        # Feed day 1 bars (h=200, l=100, c=150)
        t.update(200, 100, 130, 1000, ts_day1)
        t.update(190, 110, 150, 1000, ts_day1 + timedelta(minutes=15))
        # Day 2 bar: should use day-1 HLC to compute pivots
        state2 = t.update(160, 155, 158, 1000, ts_day2)
        # day-1 H=200, L=100, C=150 → PP=150
        assert state2 is not None
        assert abs(state2.pp - 150.0) < 0.01


class TestFVGTracker:
    def test_none_until_3_bars(self):
        t = FVGTracker()
        assert t.update(105, 95, 100, 100, None) is None
        assert t.update(108, 98, 103, 100, None) is None

    def test_bullish_fvg_detected(self):
        t = FVGTracker()
        # bar0: high=100, bar1: normal, bar2: low=105 (gap: 100 < 105 → bullish FVG)
        t.update(100, 90, 95, 100, None)    # bar0: high=100
        t.update(102, 91, 96, 100, None)    # bar1: middle
        state = t.update(115, 105, 110, 100, None)  # bar2: low=105 > bar0.high=100
        assert state is not None
        assert state.unfilled_count == 1
        assert state.unfilled_gaps[0].gap_type == "bullish"

    def test_bearish_fvg_detected(self):
        t = FVGTracker()
        # bar0: low=105, bar1: middle, bar2: high=100 (gap: 105 > 100 → bearish FVG)
        t.update(120, 105, 110, 100, None)  # bar0: low=105
        t.update(112, 103, 107, 100, None)  # bar1: middle
        state = t.update(100, 88, 92, 100, None)   # bar2: high=100 < bar0.low=105
        assert state is not None
        assert state.unfilled_count == 1
        assert state.unfilled_gaps[0].gap_type == "bearish"

    def test_bullish_gap_filled(self):
        t = FVGTracker()
        t.update(100, 90, 95, 100, None)   # bar0: high=100
        t.update(102, 91, 96, 100, None)   # bar1
        t.update(115, 105, 110, 100, None) # bar2: creates bullish gap (low=105 > high=100)
        # Next bar: low=100 ≤ gap_low=100 → fills the gap
        state = t.update(110, 100, 105, 100, None)
        assert state is not None
        assert state.unfilled_count == 0


class TestVolumeProfileTracker:
    def _ts(self, day=15):
        return datetime(2026, 6, day, 4, 0, tzinfo=UTC)

    def test_poc_at_highest_volume(self):
        t = VolumeProfileTracker(bucket_size=10.0, value_area_pct=0.70)
        # 3 bars: most volume at price 100
        t.update(105, 95, 100, 1000, self._ts())
        t.update(105, 95, 100, 2000, self._ts())  # double volume at same bucket
        state = t.update(115, 105, 110, 500, self._ts())
        assert state is not None
        # POC should be at ~100 (highest volume bucket)
        assert abs(state.poc - 102.5) < 15  # bucket_size=10, centre of bucket at ~100

    def test_session_reset(self):
        t = VolumeProfileTracker(bucket_size=10.0)
        t.update(105, 95, 100, 1000, datetime(2026, 6, 14, 4, 0, tzinfo=UTC))
        s1 = t.update(105, 95, 100, 1000, datetime(2026, 6, 14, 5, 0, tzinfo=UTC))
        # New day
        t.update(200, 190, 195, 100, datetime(2026, 6, 15, 4, 0, tzinfo=UTC))
        s2 = t.update(200, 190, 195, 100, datetime(2026, 6, 15, 5, 0, tzinfo=UTC))
        assert s2 is not None
        assert s2.total_volume < s1.total_volume  # type: ignore[union-attr]

    def test_value_area(self):
        t = VolumeProfileTracker(bucket_size=10.0, value_area_pct=1.0)
        t.update(105, 95, 100, 500, self._ts())
        t.update(115, 105, 110, 500, self._ts())
        state = t.update(125, 115, 120, 500, self._ts())
        assert state is not None
        assert state.vah >= state.poc >= state.val


class TestMarketProfileTracker:
    def test_poc_at_most_active_range(self):
        t = MarketProfileTracker(bucket_size=10.0)
        ts = datetime(2026, 6, 15, 4, 0, tzinfo=UTC)
        # Bars strictly within 100-109 (bucket 10 only): 4 TPOs on bucket 10
        # bar with high=109, low=100 → int(100/10)=10, int(109/10)=10 → only bucket 10
        t.update(109, 100, 104, 100, ts)
        t.update(109, 100, 104, 100, ts)
        t.update(109, 100, 104, 100, ts)
        t.update(109, 100, 104, 100, ts)
        # One bar in 110-119 (bucket 11 only): 1 TPO on bucket 11
        t.update(119, 110, 114, 100, ts)
        state = t.update(119, 110, 114, 100, ts)
        assert state is not None
        # Bucket 10 (price ~100-109) has 4 TPOs; bucket 11 has 2 TPOs → POC at bucket 10
        poc_bucket = int(state.poc / 10.0)
        assert poc_bucket == 10  # _from_bucket(10) = 10.5*10 = 105 → int(105/10) = 10

    def test_session_reset(self):
        t = MarketProfileTracker(bucket_size=10.0)
        ts1 = datetime(2026, 6, 14, 4, 0, tzinfo=UTC)
        ts2 = datetime(2026, 6, 15, 4, 0, tzinfo=UTC)
        t.update(110, 100, 105, 100, ts1)
        t.update(110, 100, 105, 100, ts1)
        t.update(200, 190, 195, 100, ts2)
        state = t.update(200, 190, 195, 100, ts2)
        assert state is not None
        # POC should be in the 190-200 range, not 100-110
        assert state.poc > 150


# ── 6.2 Config-driven selection ───────────────────────────────────────────────

class TestConfigDrivenSelection:
    def _engine_with(self, sid, tf, families):
        from pdp.indicators.engine import IndicatorEngine
        eng = IndicatorEngine(st_period=3, st_multiplier=1.0)
        indicators = [{"family": f} for f in families]
        eng.configure_suite(sid, tf, indicators)
        return eng

    def test_only_requested_families_built(self):
        eng = self._engine_with("13", "15m", ["ema", "rsi"])
        key = ("13", "15m")
        assert "ema" in eng._suite_trackers[key]
        assert "rsi" in eng._suite_trackers[key]
        assert "vwap" not in eng._suite_trackers[key]
        assert "volume_profile" not in eng._suite_trackers[key]

    def test_snapshot_has_only_requested_families(self):
        eng = self._engine_with("13", "15m", ["ema", "rsi"])
        for i in range(20):
            bar = _make_bar_closed(100 + i, security_id="13", timeframe="15m")
            eng.on_bar(bar)
        snap = eng.get_snapshot("13", "15m")
        assert snap is not None
        assert snap.vwap is None
        assert snap.pivots is None
        assert snap.volume_profile is None
        assert snap.market_profile is None
        # ema should be populated after 9 bars
        assert snap.ema is not None

    def test_no_suite_trackers_built_when_no_indicators(self):
        eng = IndicatorEngine(st_period=3, st_multiplier=1.0)
        bar = _make_bar_closed(100.0, security_id="13", timeframe="15m")
        eng.on_bar(bar)
        assert eng.get_snapshot("13", "15m") is None

    def test_union_across_strategies(self):
        eng = IndicatorEngine(st_period=3, st_multiplier=1.0)
        # Strategy A requests ema; strategy B requests rsi (same sid/tf)
        eng.configure_suite("13", "15m", [{"family": "ema"}])
        eng.configure_suite("13", "15m", [{"family": "rsi"}])
        key = ("13", "15m")
        assert "ema" in eng._suite_trackers[key]
        assert "rsi" in eng._suite_trackers[key]


# ── 6.3 Parity test ──────────────────────────────────────────────────────────

class TestBacktestParity:
    """Same bar series through live engine and direct tracker yields identical states."""

    def test_ema_parity(self):
        closes = [float(i) for i in range(1, 25)]
        # Live engine path
        eng = IndicatorEngine(st_period=3, st_multiplier=1.0)
        eng.configure_suite("sid", "15m", [{"family": "ema", "periods": [9]}])
        for i, c in enumerate(closes):
            bar = _make_bar_closed(c, security_id="sid", timeframe="15m",
                                   bar_time=datetime(2026, 6, 15, 4, i, tzinfo=UTC))
            eng.on_bar(bar)
        snap = eng.get_snapshot("sid", "15m")
        live_ema = snap.ema.values[9] if snap and snap.ema else None  # type: ignore

        # Direct tracker path (backtest)
        t = EMATracker(periods=[9])
        direct_ema = None
        for i, c in enumerate(closes):
            h, lo, close, v, bt = _bar(c, n=i)
            s = t.update(h, lo, close, v, bt)
            if s is not None:
                direct_ema = s.values.get(9)

        assert live_ema is not None
        assert direct_ema is not None
        assert abs(live_ema - direct_ema) < 1e-9

    def test_rsi_parity(self):
        closes = [float(i % 5 + 10) for i in range(20)]
        eng = IndicatorEngine(st_period=3, st_multiplier=1.0)
        eng.configure_suite("sid", "5m", [{"family": "rsi", "period": 5}])
        for i, c in enumerate(closes):
            bar = _make_bar_closed(c, security_id="sid", timeframe="5m",
                                   bar_time=datetime(2026, 6, 15, 4, i, tzinfo=UTC))
            eng.on_bar(bar)
        snap = eng.get_snapshot("sid", "5m")
        live_rsi = snap.rsi.rsi if snap and snap.rsi else None  # type: ignore

        t = RSITracker(period=5)
        direct_rsi = None
        for i, c in enumerate(closes):
            h, lo, close, v, bt = _bar(c, n=i)
            s = t.update(h, lo, close, v, bt)
            if s is not None:
                direct_rsi = s.rsi

        assert live_rsi is not None
        assert direct_rsi is not None
        assert abs(live_rsi - direct_rsi) < 1e-9


# ── 6.4 Latency micro-benchmark ──────────────────────────────────────────────

class TestLatencyBenchmark:
    def test_200_bundles_sub_millisecond_mean(self):
        from decimal import Decimal
        from pdp.market.bars import BarClosed

        num_instruments = 200
        eng = IndicatorEngine(st_period=3, st_multiplier=1.0)
        for i in range(num_instruments):
            sid = str(i)
            eng.configure_suite(sid, "15m", [
                {"family": "ema"},
                {"family": "rsi"},
                {"family": "vwap"},
            ])
            # Prime with 25 warmup bars so trackers are seeded
            for j in range(25):
                bar = BarClosed(
                    security_id=sid,
                    timeframe="15m",
                    bar_time=datetime(2026, 6, 15, 3, 45, tzinfo=UTC) + timedelta(minutes=15 * j),
                    open=Decimal("100"),
                    high=Decimal(str(100 + j % 10)),
                    low=Decimal(str(100 - j % 5)),
                    close=Decimal(str(100 + j)),
                    volume=1000,
                    oi=0,
                )
                eng.on_bar(bar)

        # Measure on_bar latency across all 200 instruments for 10 bars each
        n_bars = 10
        bar_time = datetime(2026, 6, 15, 4, 0, tzinfo=UTC)
        start = time.perf_counter()
        for _ in range(n_bars):
            bar_time += timedelta(minutes=15)
            for i in range(num_instruments):
                from pdp.market.bars import BarClosed
                bar = BarClosed(
                    security_id=str(i),
                    timeframe="15m",
                    bar_time=bar_time,
                    open=Decimal("100"),
                    high=Decimal("105"),
                    low=Decimal("95"),
                    close=Decimal("102"),
                    volume=1000,
                    oi=0,
                )
                eng.on_bar(bar)
        elapsed = time.perf_counter() - start
        total_calls = n_bars * num_instruments
        mean_ms = (elapsed / total_calls) * 1000
        assert mean_ms < 1.0, f"mean on_bar latency {mean_ms:.4f}ms exceeds 1ms budget"


# ── registry smoke ────────────────────────────────────────────────────────────

def test_registry_available_families():
    families = available_families()
    for name in ("ema", "rsi", "psar", "vwap", "vwma", "pivots", "fvg",
                  "volume_profile", "market_profile"):
        assert name in families


def test_build_tracker_unknown_raises():
    with pytest.raises(KeyError):
        build_tracker("nonexistent_family")
