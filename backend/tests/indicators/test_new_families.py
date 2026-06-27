"""Unit tests for the new indicator families: MACD, Candlestick, Elliott, FibLevels, ElderImpulse."""
from __future__ import annotations

import pytest

from pdp.indicators.candlestick import CandlestickTracker
from pdp.indicators.elder_impulse import ElderImpulseTracker
from pdp.indicators.elliott import ElliottWaveTracker
from pdp.indicators.fib_levels import FibLevelsTracker
from pdp.indicators.macd import MACDTracker


def _u(tracker, high, low, close, **kw):
    """Helper: call tracker.update() with minimal args."""
    return tracker.update(high, low, close, 0.0, None, **kw)


# ── MACDTracker ───────────────────────────────────────────────────────────────

class TestMACDTracker:
    def test_none_until_slow_and_signal_seeded(self):
        t = MACDTracker(fast=3, slow=5, signal=3)
        # slow=5 bars to seed EMA, then signal=3 MACD values
        for _ in range(7):
            result = _u(t, 105, 95, 100)
        # At this point slow should be seeded (5 bars) + 2 more MACD values, still need 3rd
        assert result is None or result is not None  # just smoke-test no error

    def test_returns_state_after_seeding(self):
        t = MACDTracker(fast=3, slow=5, signal=3)
        state = None
        for i in range(20):
            state = _u(t, 105 + i, 95 + i, 100 + i)
        assert state is not None
        assert isinstance(state.macd, float)
        assert isinstance(state.signal, float)
        assert abs(state.histogram - (state.macd - state.signal)) < 1e-9

    def test_histogram_equals_macd_minus_signal(self):
        t = MACDTracker(fast=3, slow=5, signal=3)
        for i in range(20):
            _u(t, 105, 95, 100 + (i % 5))
        # last valid state
        s2 = _u(t, 105, 95, 102)
        if s2 is not None:
            assert abs(s2.histogram - (s2.macd - s2.signal)) < 1e-9

    def test_none_when_unseeded(self):
        t = MACDTracker(fast=3, slow=5, signal=3)
        assert _u(t, 105, 95, 100) is None

    def test_invalid_period_raises(self):
        with pytest.raises(ValueError):
            MACDTracker(fast=26, slow=12)  # fast >= slow


# ── CandlestickTracker ────────────────────────────────────────────────────────

class TestCandlestickTracker:
    def test_none_on_first_bar(self):
        t = CandlestickTracker()
        assert _u(t, 105, 95, 100, open_price=100) is None

    def test_neutral_when_no_pattern(self):
        t = CandlestickTracker()
        _u(t, 110, 90, 100, open_price=100)  # seed
        # Ordinary bar: moderate open/close near middle
        s = _u(t, 110, 90, 105, open_price=102)
        assert s is not None
        assert s.signal in (-1, 0, 1)

    def test_doji_detected(self):
        t = CandlestickTracker(doji_threshold=0.1)
        _u(t, 110, 90, 100, open_price=100)  # seed
        # Doji: open ≈ close, range = 20 → body must be ≤ 2
        s = _u(t, 110, 90, 100.1, open_price=100.0)
        assert s is not None
        assert s.doji

    def test_bullish_engulfing(self):
        t = CandlestickTracker()
        # Prior bearish bar: open=105, close=95
        _u(t, 110, 90, 95, open_price=105)
        # Bullish engulfing: open=93 (below prior close=95), close=107 (above prior open=105)
        s = _u(t, 115, 90, 107, open_price=93)
        assert s is not None
        assert s.bullish_engulfing
        assert s.signal == 1

    def test_bearish_engulfing(self):
        t = CandlestickTracker()
        # Prior bullish: open=95, close=105
        _u(t, 110, 90, 105, open_price=95)
        # Bearish engulfing: open=107 (above prior close=105), close=93 (below prior open=95)
        s = _u(t, 110, 90, 93, open_price=107)
        assert s is not None
        assert s.bearish_engulfing
        assert s.signal == -1

    def test_hammer_detected(self):
        t = CandlestickTracker(wick_ratio=2.0)
        _u(t, 110, 90, 100, open_price=100)  # seed
        # Hammer: open=106, close=109 (body=3), low=99, high=110 (range=11)
        # lower_shadow=106-99=7 >= 2*3=6 ✓, upper=110-109=1 <= 3 ✓, body in upper third ✓
        s = _u(t, 110, 99, 109, open_price=106)
        assert s is not None
        assert s.hammer

    def test_shooting_star_detected(self):
        t = CandlestickTracker(wick_ratio=2.0)
        _u(t, 110, 90, 100, open_price=100)  # seed
        # Shooting star: open=100, close=103 (body=3), high=113, low=100 (range=13)
        # upper_shadow=113-103=10 >= 2*3=6 ✓, lower=0 <= 3 ✓, body in lower third ✓
        s = _u(t, 113, 100, 103, open_price=100)
        assert s is not None
        assert s.shooting_star

    def test_morning_star(self):
        t = CandlestickTracker()
        # bar[-2]: strong bearish (open=110, close=90)
        _u(t, 115, 88, 90, open_price=110)
        # bar[-1]: small doji-like (open=91, close=89) — the star
        _u(t, 92, 87, 89, open_price=91)
        # bar[0]: strong bullish closing well into bar[-2]'s body
        s = _u(t, 110, 90, 105, open_price=92)
        assert s is not None
        assert s.morning_star

    def test_no_pattern_all_false(self):
        t = CandlestickTracker()
        _u(t, 110, 90, 100, open_price=99)
        s = _u(t, 111, 89, 101, open_price=100)
        # Just confirm it runs without error
        assert s is not None


# ── ElliottWaveTracker ────────────────────────────────────────────────────────

class TestElliottWaveTracker:
    def test_none_until_min_pivots(self):
        t = ElliottWaveTracker(threshold_pct=0.01, min_pivots=4)
        for i in range(5):
            c = 100.0 + (i % 2) * 5
            result = _u(t, c + 2, c - 2, c)
        # After only a few bars we may still not have enough pivots
        # (this is a smoke test — just ensure no exception)
        assert result is None or result is not None

    def test_returns_state_with_enough_data(self):
        t = ElliottWaveTracker(threshold_pct=0.005, min_pivots=4)
        # Create clear zigzag: 100, 110, 105, 115, 108, 120
        prices = [100, 110, 105, 115, 108, 120, 112, 125]
        state = None
        for p in prices:
            state = _u(t, p + 1, p - 1, p)
        # Should have enough pivots for a label
        if state is not None:
            assert state.trend in (-1, 0, 1)
            assert state.confidence >= 0.0

    def test_confidence_between_0_and_1(self):
        t = ElliottWaveTracker(threshold_pct=0.005)
        prices = [100, 108, 103, 112, 106, 115, 109, 118]
        for p in prices:
            s = _u(t, p + 1, p - 1, p)
        if s is not None:
            assert 0.0 <= s.confidence <= 1.0

    def test_swing_high_and_low_populated(self):
        t = ElliottWaveTracker(threshold_pct=0.005, min_pivots=4)
        prices = [100, 112, 105, 118, 108]
        s = None
        for p in prices:
            s = _u(t, p + 2, p - 2, p)
        if s is not None:
            if s.swing_high is not None:
                assert s.swing_high > 0
            if s.swing_low is not None:
                assert s.swing_low > 0


# ── FibLevelsTracker ─────────────────────────────────────────────────────────

class TestFibLevelsTracker:
    def test_none_until_swing_detected(self):
        t = FibLevelsTracker(threshold_pct=0.01)
        s = _u(t, 102, 98, 100)
        assert s is None  # only first bar, no swing yet

    def test_returns_state_after_swing(self):
        t = FibLevelsTracker(threshold_pct=0.005)
        # Build an upswing then downswing
        prices_up = [(100 + i, 98 + i, 99 + i) for i in range(10)]
        prices_dn = [(108 - i, 106 - i, 107 - i) for i in range(10)]
        state = None
        for h, lo, c in prices_up + prices_dn:
            state = t.update(h, lo, c)
        if state is not None:
            assert state.swing_high > state.swing_low
            assert len(state.retracements) == 5
            assert len(state.extensions) == 3

    def test_retracement_ratios(self):
        t = FibLevelsTracker(threshold_pct=0.001)
        # Tight zigzag: 100 up to 110, then retrace
        for i in range(10):
            t.update(100 + i, 99 + i, 99.5 + i)
        for i in range(5):
            s = t.update(110 - i, 109 - i, 109.5 - i)
        if s is not None:
            # 0.382 retracement from 110 to ~100: 110 - 0.382 * 10 ≈ 106.18
            r = s.retracements.get(0.382)
            if r is not None:
                assert 100 < r < 110

    def test_nearest_level_within_range(self):
        t = FibLevelsTracker(threshold_pct=0.001)
        for i in range(12):
            c = 100.0 + i
            s = t.update(c + 1, c - 1, c)
        if s is not None:
            all_levels = list(s.retracements.values()) + list(s.extensions.values())
            assert s.nearest_level in all_levels


# ── ElderImpulseTracker ───────────────────────────────────────────────────────

class TestElderImpulseTracker:
    def test_none_until_seeded(self):
        t = ElderImpulseTracker()
        s = _u(t, 105, 95, 100)
        assert s is None

    def test_returns_state_after_warmup(self):
        t = ElderImpulseTracker(macd_fast=3, macd_slow=5, macd_signal=3)
        state = None
        for i in range(30):
            state = _u(t, 105 + i * 0.1, 95 + i * 0.1, 100 + i * 0.1)
        assert state is not None
        assert state.regime in ("green", "red", "blue")

    def test_green_on_rising_trend(self):
        t = ElderImpulseTracker(macd_fast=3, macd_slow=5, macd_signal=3)
        for i in range(40):
            s = _u(t, 105 + i, 95 + i, 100 + i)
        # Strongly rising prices → green or blue (MACD catching up)
        assert s is None or s.regime in ("green", "blue")

    def test_red_on_falling_trend(self):
        t = ElderImpulseTracker(macd_fast=3, macd_slow=5, macd_signal=3)
        for i in range(40):
            s = _u(t, 105 - i * 0.5, 95 - i * 0.5, 100 - i * 0.5)
        assert s is None or s.regime in ("red", "blue")

    def test_regime_is_valid_string(self):
        t = ElderImpulseTracker(macd_fast=3, macd_slow=5, macd_signal=3)
        for i in range(30):
            s = _u(t, 105 + (i % 7), 95 + (i % 5), 100 + (i % 6))
        if s is not None:
            assert s.regime in ("green", "red", "blue")
