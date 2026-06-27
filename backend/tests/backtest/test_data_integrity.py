"""Tests for the backtest input-data completeness gate and the wait-for-first-flip rule.

The completeness gate (`pdp.backtest.completeness.spot_completeness`) decides whether a trade day
has a usable NIFTY 1m spot series. The first-flip rule suppresses entries until the first genuine
SuperTrend flip after session start; here we assert that contract against the real
`SuperTrendTracker.flipped` signal (the same flag `backtest_multiday.simulate_day` gates on).
"""
from datetime import datetime, timedelta, timezone

from pdp.backtest.completeness import (
    EXPECTED_SESSION_BARS,
    MAX_GAP_MIN,
    spot_completeness,
)
from pdp.indicators.supertrend import SuperTrendTracker

BASE = datetime(2026, 6, 12, 3, 45, tzinfo=timezone.utc)  # 09:15 IST


def _bars(n: int, *, start: datetime = BASE, step_min: int = 1) -> list[dict]:
    """n consecutive 1m bar dicts (only `ts` matters for the gate)."""
    return [
        {"ts": start + timedelta(minutes=i * step_min),
         "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0}
        for i in range(n)
    ]


# ── Completeness gate ────────────────────────────────────────────────────────

def test_complete_day_passes():
    res = spot_completeness(_bars(EXPECTED_SESSION_BARS))
    assert res["ok"] is True
    assert res["bars"] == EXPECTED_SESSION_BARS
    assert res["max_gap_min"] == 1.0
    assert res["reason"] == ""


def test_zero_bar_day_is_incomplete():
    res = spot_completeness([])
    assert res["ok"] is False
    assert res["bars"] == 0
    assert "no spot bars" in res["reason"]


def test_day_with_large_hole_is_incomplete():
    # Two contiguous blocks separated by an 88-minute hole (the real 2026-06-12 gap).
    first = _bars(60)                                   # 09:15–10:14
    hole_start = BASE + timedelta(minutes=60 + 88)
    second = _bars(EXPECTED_SESSION_BARS - 60, start=hole_start)
    res = spot_completeness(first + second)
    assert res["ok"] is False
    assert res["max_gap_min"] >= MAX_GAP_MIN
    assert "gap" in res["reason"]


def test_too_few_bars_is_incomplete():
    res = spot_completeness(_bars(100))  # well under 95% of 375
    assert res["ok"] is False
    assert "bars" in res["reason"]


def test_just_above_threshold_passes():
    # 95% of 375 == 356; a clean 360-bar series with no gap should pass.
    res = spot_completeness(_bars(360))
    assert res["ok"] is True


# ── Wait-for-first-flip contract ─────────────────────────────────────────────

def _flip_index(highs, lows, closes) -> int:
    """Index of the first bar whose SuperTrend(3,1) reports a genuine flip, else -1.

    Mirrors the gate in simulate_day: `first_flip_seen` is set on the first bar with
    `st.flipped` True, after which entries are allowed.
    """
    tr = SuperTrendTracker(period=3, multiplier=1)
    for i, (h, l, c) in enumerate(zip(highs, lows, closes)):
        st = tr.update(h, l, c, bar_time=BASE + timedelta(minutes=i))
        if st is not None and st.flipped:
            return i
    return -1


def test_first_bar_never_flips():
    # The very first emitted state seeds direction (cold start); `flipped` is False on it.
    tr = SuperTrendTracker(period=3, multiplier=1)
    st = tr.update(101.0, 99.0, 100.0, bar_time=BASE)
    assert st is None or st.flipped is False


def test_rising_series_flips_off_the_cold_start_seed():
    # SuperTrend seeds DOWN on the first bar (cold-start tie-break), so a sustained rise
    # produces a genuine flip to UP — this is exactly the "first flip of the day" the gate
    # waits for, rather than entering on the unestablished opening direction.
    closes = [100.0 + i for i in range(20)]
    highs = [c + 1 for c in closes]
    lows = [c - 1 for c in closes]
    idx = _flip_index(highs, lows, closes)
    assert idx > 0, "a sustained move must flip off the cold-start seed"


def test_no_entry_arms_before_the_first_flip():
    # Until the first flip index, the gate's `first_flip_seen` stays False (no entry);
    # it becomes True exactly at the flip bar and stays armed thereafter.
    up = [100.0 + i * 2 for i in range(10)]
    down = [up[-1] - i * 4 for i in range(1, 11)]
    closes = up + down
    highs = [c + 1 for c in closes]
    lows = [c - 1 for c in closes]
    idx = _flip_index(highs, lows, closes)
    assert idx > 0

    tr = SuperTrendTracker(period=3, multiplier=1)
    first_flip_seen = False
    armed_history = []
    for i, (h, l, c) in enumerate(zip(highs, lows, closes)):
        st = tr.update(h, l, c, bar_time=BASE + timedelta(minutes=i))
        if not first_flip_seen and st is not None and st.flipped:
            first_flip_seen = True
        armed_history.append(first_flip_seen)

    assert armed_history[idx - 1] is False, "entries must be suppressed before the first flip"
    assert armed_history[idx] is True, "entries arm exactly on the first-flip bar"
    assert all(armed_history[idx:]), "the gate stays armed for the rest of the day"


# ── Continuous cross-day warmup (prior-session seed) ─────────────────────────

def _warm_then_run(prior, day):
    """Warm a tracker on `prior` (h,l,c) bars, then return the per-bar (direction, flipped)
    for `day`. Mirrors simulate_day: warmup bars are fed but not emitted, so the day's first
    `flipped` reflects a carried-over-direction change, not a cold-start seed.
    """
    tr = SuperTrendTracker(period=3, multiplier=1)
    t = 0
    for h, l, c in prior:
        tr.update(h, l, c, bar_time=BASE + timedelta(minutes=t)); t += 1
    out = []
    for h, l, c in day:
        st = tr.update(h, l, c, bar_time=BASE + timedelta(minutes=t)); t += 1
        out.append((st.direction, st.flipped))
    return out


def test_warmup_carries_prior_direction_into_the_open():
    # A sustained rising prior session leaves the tracker UP; the next day opens UP (carried
    # over), not DOWN from a cold start — this is what makes the backtest match Kite's line.
    prior = [(100.0 + i + 1, 100.0 + i - 1, 100.0 + i) for i in range(15)]   # rising → UP
    flat = [(120.0 + 1, 120.0 - 1, 120.0) for _ in range(3)]                  # opens flat-ish
    out = _warm_then_run(prior, flat)
    assert out[0][0] > 0, "the day must open UP, inheriting the prior session's uptrend"
    assert out[0][1] is False, "the opening bar is a continuation, not a flip"


def test_warmup_then_fall_flips_down_at_the_open_window():
    # Prior up-session → opens UP (like 06-12's GREEN gap-up); a morning fall then flips the
    # carried-over UP to DOWN — the early flip the wait-for-first-flip gate enters on.
    prior = [(100.0 + i + 1, 100.0 + i - 1, 100.0 + i) for i in range(15)]   # rising → UP
    fall = [(118.0 - i * 2 + 1, 118.0 - i * 2 - 1, 118.0 - i * 2) for i in range(10)]
    out = _warm_then_run(prior, fall)
    assert out[0][0] > 0, "opens UP from the warmup"
    flip_idxs = [i for i, (_, flipped) in enumerate(out) if flipped]
    assert flip_idxs, "the morning fall must flip the carried-over UP direction"
    assert out[flip_idxs[0]][0] < 0, "the first flip is UP→DOWN, matching the 06-12 ~09:55 red flip"
