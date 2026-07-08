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


def test_open_short_contributes_zero_to_realized_pnl():
    """Regression: an open short (SELL with no BUY) MUST report realized_pnl == 0.

    Previously the code used `sell_value - buy_value - charges` which wrongly
    booked the full sell premium as realized (the -₹69,195 bug).
    """
    trades = [
        {"security_id": "OPT_PE", "side": "SELL", "qty": 130, "fill_price": "100", "charges": "30"},
    ]
    s = compute_daily_stats(trades)
    assert s["realized_pnl"] == 0.0, (
        f"Open short should contribute 0 to realized_pnl, got {s['realized_pnl']}"
    )


def test_completed_round_trip_realized_pnl():
    """A completed round-trip (SELL 100 → BUY 40) MUST report positive realized."""
    trades = [
        {"security_id": "OPT_PE", "side": "SELL", "qty": 130, "fill_price": "100", "charges": "30"},
        {"security_id": "OPT_PE", "side": "BUY", "qty": 130, "fill_price": "40", "charges": "20"},
    ]
    s = compute_daily_stats(trades)
    # (130*100 - 130*40 - 50) = 13000 - 5200 - 50 = 7750
    assert s["realized_pnl"] == 7750.0
    assert s["round_trips"] == 1


def test_mixed_open_and_closed_positions():
    """Day with one open short and one completed round-trip."""
    trades = [
        # Completed round-trip on OPT_PE
        {"security_id": "OPT_PE", "side": "SELL", "qty": 65, "fill_price": "100", "charges": "10"},
        {"security_id": "OPT_PE", "side": "BUY", "qty": 65, "fill_price": "40", "charges": "10"},
        # Open short on OPT_CE (no BUY)
        {"security_id": "OPT_CE", "side": "SELL", "qty": 65, "fill_price": "80", "charges": "15"},
    ]
    s = compute_daily_stats(trades)
    # Only the PE round-trip contributes: (65*100 - 65*40 - 20) = 6500 - 2600 - 20 = 3880
    assert s["realized_pnl"] == 3880.0
    assert s["round_trips"] == 1
    assert s["securities_traded"] == 2


def test_partial_close_contributes_matched_portion_only():
    """Regression: a partial close (e.g. a stop-half exit — sold 4 lots, bought back
    only 2) must book realized P&L on the MATCHED 2 lots, not zero (that would
    understate real P&L) and not the full 4 lots (that would overstate it — the
    remaining 2 lots are still open).
    """
    trades = [
        {"security_id": "OPT_PE", "side": "SELL", "qty": 260, "fill_price": "100", "charges": "40"},
        {"security_id": "OPT_PE", "side": "BUY", "qty": 130, "fill_price": "70", "charges": "20"},
    ]
    s = compute_daily_stats(trades)
    # matched_qty = 130; avg_sell=100, avg_buy=70; charges prorated by 130/260 = 0.5 -> 30
    # pnl = (100-70)*130 - 30 = 3900 - 30 = 3870
    assert s["realized_pnl"] == 3870.0
    assert s["round_trips"] == 1
    assert s["wins"] == 1


def test_partial_close_losing_matched_portion():
    """A partial close where the matched portion is a loss must still be counted
    (not silently dropped as 'still open')."""
    trades = [
        {"security_id": "OPT_CE", "side": "SELL", "qty": 260, "fill_price": "50", "charges": "0"},
        {"security_id": "OPT_CE", "side": "BUY", "qty": 65, "fill_price": "90", "charges": "0"},
    ]
    s = compute_daily_stats(trades)
    # matched_qty = 65; pnl = (50-90)*65 = -2600
    assert s["realized_pnl"] == -2600.0
    assert s["round_trips"] == 1
    assert s["losses"] == 1
