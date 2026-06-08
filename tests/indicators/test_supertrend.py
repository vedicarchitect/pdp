"""Unit tests for the SuperTrend indicator."""
from __future__ import annotations

from decimal import Decimal

from pdp.indicators.supertrend import DOWN, UP, SuperTrendTracker, supertrend


def test_seeding_returns_none_until_period_bars():
    t = SuperTrendTracker(period=3, multiplier=1)
    assert t.update(10, 9, 9.5) is None  # bar 1
    assert t.update(11, 10, 10.5) is None  # bar 2
    assert t.update(12, 11, 11.5) is not None  # bar 3 — ATR seeded


def test_uptrend_direction_is_up():
    t = SuperTrendTracker(period=3, multiplier=1)
    state = None
    h = lo = c = 10.0
    for _ in range(12):
        h += 1
        lo += 1
        c += 1
        state = t.update(h, lo, c)
    assert state is not None
    assert state.direction == UP
    assert isinstance(state.value, Decimal)


def test_reversal_flips_direction():
    t = SuperTrendTracker(period=3, multiplier=1)
    # Build a clear uptrend.
    h = lo = c = 10.0
    for _ in range(10):
        h += 1
        lo += 1
        c += 1
        t.update(h, lo, c)
    assert t.direction == UP

    # Sharp drop well below the lower band — should flip to DOWN.
    flipped_seen = False
    last_dir = t.direction
    for low_close in (5.0, 4.0, 3.0):
        state = t.update(low_close + 0.5, low_close - 1, low_close)
        assert state is not None
        if state.flipped:
            flipped_seen = True
        last_dir = state.direction
    assert flipped_seen
    assert last_dir == DOWN


def test_batch_helper_matches_length_and_seeds():
    highs = [10, 11, 12, 13, 14]
    lows = [9, 10, 11, 12, 13]
    closes = [9.5, 10.5, 11.5, 12.5, 13.5]
    out = supertrend(highs, lows, closes, period=3, multiplier=1)
    assert len(out) == 5
    assert out[0] is None and out[1] is None  # seeding
    assert out[2] is not None
    assert out[-1].direction in (UP, DOWN)
