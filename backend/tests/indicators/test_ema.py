"""EMA convergence tests (indicator-history-depth task 1.1).

A period SHALL be omitted from ``EMAState.values`` until the tracker has
consumed at least that many bars — the console must render ``--`` for an
unconverged period rather than a stale/partial number.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from pdp.indicators.ema import EMATracker


def _feed(tracker: EMATracker, n: int, start_close: float = 100.0):
    state = None
    base = datetime(2026, 1, 1, tzinfo=UTC)
    for i in range(n):
        state = tracker.update(
            high=start_close + i + 1,
            low=start_close + i - 1,
            close=start_close + i,
            volume=0.0,
            bar_time=base + timedelta(minutes=i),
        )
    return state


class TestEMA200Convergence:
    def test_period_200_absent_at_150_bars(self):
        """Realistic live config: periods=[9, 20, 50, 100, 200] (task 2's addition)."""
        t = EMATracker(periods=[9, 20, 50, 100, 200])
        state = _feed(t, 150)
        assert state is not None
        assert 200 not in state.values
        # shorter periods are already converged and reported
        assert 9 in state.values
        assert 100 in state.values

    def test_period_200_present_at_200_bars(self):
        t = EMATracker(periods=[9, 20, 50, 100, 200])
        state = _feed(t, 200)
        assert state is not None
        assert 200 in state.values
