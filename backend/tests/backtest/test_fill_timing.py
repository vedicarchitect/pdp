"""Tests: fill pricing is close-based and never looks ahead.

Covers three algorithmic contracts from backtest-fill-timing-no-lookahead:

  2.1  price_at with prefer='close' returns the bar's close, not its open.
  2.2  On a favorable-reversal flip bar (open high, close low), close-based
       pricing is strictly cheaper for a short seller than open-based pricing.
  2.3  price_at never selects a bar whose timestamp is later than the target.

price_at is a pure function defined in backtest_multiday.py. The script is not
directly importable (argparse runs at module level), so the contract is tested
by inlining the same algorithm here. If price_at is ever moved to a package
module, replace the inline below with a direct import.
"""
from __future__ import annotations

from datetime import datetime, timedelta


# ── Contract under test (mirrors backtest_multiday.price_at exactly) ─────────

def _price_at(bars, target, prefer="open"):
    best, bd = None, timedelta(hours=99)
    for (dt, o, h, l, c) in bars:
        if dt > target:
            continue  # never select a future bar (no look-ahead)
        d = abs(dt - target)
        if d < bd: bd, best = d, (dt, o, h, l, c)
    if best is None or bd > timedelta(minutes=15): return None
    return best[1] if prefer == "open" else best[4]


T = datetime(2026, 6, 12, 9, 55)  # arbitrary signal bar timestamp (UTC-naive)


# ── 2.1: close fill returns bar.close, not bar.open ──────────────────────────

def test_price_at_close_returns_close_not_open():
    bars = [(T, 120.0, 125.0, 118.0, 110.0)]  # open=120, close=110
    assert _price_at(bars, T, prefer="close") == 110.0
    assert _price_at(bars, T, prefer="open")  == 120.0


def test_price_at_close_on_nearest_prior_bar():
    # When the exact timestamp is missing, picks the nearest prior bar's close.
    prior = T - timedelta(minutes=2)
    bars = [(prior, 55.0, 60.0, 50.0, 48.0)]
    assert _price_at(bars, T, prefer="close") == 48.0


# ── 2.2: favorable-reversal bar no longer inflates exit price ─────────────────

def test_favorable_reversal_close_less_than_open():
    # Short seller BUYS BACK on a flip: a lower exit price = more profit.
    # Old path (prefer="open"): exit at 200 → less profit if avg_entry < 200
    # New path (prefer="close"): exit at 90 → more profit (correct close)
    bars = [(T, 200.0, 210.0, 80.0, 90.0)]  # spike open, close collapses
    close_fill = _price_at(bars, T, prefer="close")
    open_fill  = _price_at(bars, T, prefer="open")
    assert close_fill == 90.0
    assert close_fill < open_fill, "close must be cheaper than the inflated open on a reversal bar"


def test_reversal_pnl_not_inflated():
    # avg_entry = 150 (short), flip exit at close=90 (favourable) vs open=200 (look-ahead).
    avg_entry = 150.0
    qty = 130  # 2 lots × 65
    bars = [(T, 200.0, 210.0, 80.0, 90.0)]
    close_pnl = (avg_entry - _price_at(bars, T, prefer="close")) * qty   # +7,800
    open_pnl  = (avg_entry - _price_at(bars, T, prefer="open"))  * qty   # -6,500
    # Close-based PnL is positive (short entry 150, exit at 90 = profit).
    # Open-based PnL is negative (exit at 200 > entry 150 = artificial loss from look-ahead).
    assert close_pnl > 0
    assert open_pnl < 0, "look-ahead open would have booked a phantom loss here"


# ── 2.3: price_at never selects a bar later than the target ──────────────────

def test_price_at_never_selects_future_bar():
    earlier = T - timedelta(minutes=14)
    later   = T + timedelta(minutes=1)
    bars = [
        (later,   100.0, 105.0, 95.0, 102.0),  # future: must be excluded
        (earlier,  80.0,  85.0, 75.0,  82.0),  # prior: within 15-min tolerance
    ]
    assert _price_at(bars, T, prefer="close") == 82.0, "must select prior bar, not future bar"


def test_price_at_future_only_returns_none():
    later = T + timedelta(minutes=1)
    bars = [(later, 100.0, 105.0, 95.0, 102.0)]
    assert _price_at(bars, T, prefer="close") is None


def test_price_at_exact_target_not_filtered():
    # A bar at exactly the target timestamp is not future — it must be included.
    bars = [(T, 55.0, 60.0, 50.0, 53.0)]
    assert _price_at(bars, T, prefer="close") == 53.0


def test_price_at_beyond_15min_returns_none():
    old = T - timedelta(minutes=16)
    bars = [(old, 55.0, 60.0, 50.0, 53.0)]
    assert _price_at(bars, T, prefer="close") is None
