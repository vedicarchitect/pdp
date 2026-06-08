"""Unit tests for journal daily-stats computation."""
from __future__ import annotations

from pdp.journal.stats import compute_daily_stats


def test_empty():
    s = compute_daily_stats([])
    assert s["total_trades"] == 0
    assert s["realized_pnl"] == 0.0
    assert s["round_trips"] == 0
    assert s["win_rate"] == 0.0


def test_winning_round_trip_net_of_charges():
    # Sold 130 @ 100 = 13000, bought back 130 @ 60 = 7800, charges 50 -> pnl 5150.
    trades = [
        {"security_id": "OPT_PE", "side": "SELL", "qty": 130, "fill_price": "100", "charges": "30"},
        {"security_id": "OPT_PE", "side": "BUY", "qty": 130, "fill_price": "60", "charges": "20"},
    ]
    s = compute_daily_stats(trades)
    assert s["gross_premium_sold"] == 13000.0
    assert s["gross_premium_bought"] == 7800.0
    assert s["net_premium"] == 5200.0
    assert s["total_charges"] == 50.0
    assert s["realized_pnl"] == 5150.0
    assert s["round_trips"] == 1
    assert s["wins"] == 1
    assert s["losses"] == 0
    assert s["win_rate"] == 1.0


def test_losing_round_trip_counts_as_loss():
    trades = [
        {"security_id": "OPT_CE", "side": "SELL", "qty": 65, "fill_price": "50", "charges": "10"},
        {"security_id": "OPT_CE", "side": "BUY", "qty": 65, "fill_price": "90", "charges": "10"},
    ]
    s = compute_daily_stats(trades)
    assert s["realized_pnl"] < 0
    assert s["round_trips"] == 1
    assert s["losses"] == 1
    assert s["win_rate"] == 0.0


def test_open_leg_not_counted_as_round_trip():
    trades = [
        {"security_id": "OPT_PE", "side": "SELL", "qty": 130, "fill_price": "100", "charges": "30"},
    ]
    s = compute_daily_stats(trades)
    assert s["round_trips"] == 0
    assert s["sells"] == 1
    assert s["buys"] == 0
