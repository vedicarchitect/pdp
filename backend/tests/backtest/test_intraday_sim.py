"""Engine tests for the intraday-directional backtest.

Days are synthesised in-process — no Mongo, no chain loader — so each test pins one
engine behaviour (entry, ladder, rollup, each exit, commissions, no look-ahead) against
a hand-written option chain.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from pdp.backtest.intraday_config import IntradayDirectionalConfig
from pdp.backtest.intraday_loader import (
    IntradayDayData,
    IntradayDecisionBar,
    OptionTrendReader,
)
from pdp.backtest.intraday_sim import simulate_intraday_day
from pdp.signals.bias import CamLevels
from pdp.signals.intraday_directional import IntradayInputs

TD = date(2026, 7, 20)
EXPIRY = date(2026, 7, 21)
STEP = 50
SPOT = 24_500.0
LOT = 75


def t(hh: int, mm: int) -> datetime:
    return datetime(TD.year, TD.month, TD.day, hh, mm)


def bar_times(start=(9, 30), end=(15, 15), step_min=5) -> list[datetime]:
    out, cur, stop = [], t(*start), t(*end)
    while cur <= stop:
        out.append(cur)
        cur += timedelta(minutes=step_min)
    return out


def make_chain(
    times: list[datetime],
    pe: dict[float, list[float] | float] | None = None,
    ce: dict[float, list[float] | float] | None = None,
) -> dict[str, dict[float, list]]:
    """Build a day_chain of ``(dt, o, h, lo, c)`` rows from per-strike price series."""
    chain: dict[str, dict[float, list]] = {"PE": {}, "CE": {}}
    for opt, spec in (("PE", pe or {}), ("CE", ce or {})):
        for strike, prices in spec.items():
            series = prices if isinstance(prices, list) else [prices] * len(times)
            chain[opt][float(strike)] = [
                (ts, p, p, p, p) for ts, p in zip(times, series, strict=False)
            ]
    return chain


def make_day(
    times: list[datetime],
    chain: dict[str, dict[float, list]],
    *,
    spots: list[float] | None = None,
    bullish: bool = True,
    st_dir: list[int] | int = 1,
    cfg: IntradayDirectionalConfig | None = None,
) -> IntradayDayData:
    cfg = cfg or IntradayDirectionalConfig(lot_size=LOT)
    if not times:
        return IntradayDayData(
            trade_date=TD, expiry_date=EXPIRY, decision_bars=[], day_chain=chain,
            option_trend=OptionTrendReader(chain, cfg.st_period, cfg.st_mult),
            spot_open=0.0, spot_close=0.0, orb_high=None, orb_low=None,
        )
    spots = spots or [SPOT] * len(times)
    st_dirs = st_dir if isinstance(st_dir, list) else [st_dir] * len(times)
    bars: list[IntradayDecisionBar] = []
    for i, ts in enumerate(times):
        spot = spots[i]
        if bullish:
            ema9, ema20, ema9_prev = spot - 10, spot - 30, spot - 12
        else:
            ema9, ema20, ema9_prev = spot + 10, spot + 30, spot + 12
        inputs = IntradayInputs(
            ist_dt=ts,
            spot=spot,
            bar_high=spot + 5,
            bar_low=spot - 5,
            ema9_5m=ema9,
            ema20_5m=ema20,
            ema9_prev_5m=ema9_prev,
            ema20_prev_5m=ema20,
            ema9_15m=ema9,
            ema20_15m=ema20,
            st_5m_dir=st_dirs[i],
            st_15m_dir=st_dirs[i],
            session_vwap=spot - 50 if bullish else spot + 50,
            orb_high=SPOT + 200,
            orb_low=SPOT - 200,
            cam=CamLevels(r3=SPOT + 900, r4=SPOT + 1200, s3=SPOT - 900, s4=SPOT - 1200),
        )
        bars.append(IntradayDecisionBar(
            ist_dt=ts, open=spot, high=spot + 5, low=spot - 5, close=spot, inputs=inputs
        ))
    return IntradayDayData(
        trade_date=TD,
        expiry_date=EXPIRY,
        decision_bars=bars,
        day_chain=chain,
        option_trend=OptionTrendReader(chain, cfg.st_period, cfg.st_mult),
        spot_open=spots[0],
        spot_close=spots[-1],
        orb_high=SPOT + 200,
        orb_low=SPOT - 200,
    )


def cfg(**over) -> IntradayDirectionalConfig:
    base: dict = {"lot_size": LOT, "strike_step": STEP}
    base.update(over)
    return IntradayDirectionalConfig(**base)


def sells(res) -> list:
    return [tr for tr in res.trades if tr.side == "SELL"]


def buys(res) -> list:
    return [tr for tr in res.trades if tr.side == "BUY"]


# --------------------------------------------------------------------------- #
# Entry / square-off
# --------------------------------------------------------------------------- #


def test_bullish_day_sells_the_atm_put_and_squares_off():
    times = bar_times()
    chain = make_chain(times, pe={SPOT: 100.0}, ce={SPOT: 100.0})
    res = simulate_intraday_day(cfg(scale_lots_step=0), make_day(times, chain))
    assert res is not None
    entries = sells(res)
    assert entries and entries[0].opt_type == "PE"
    assert entries[0].strike == SPOT           # moneyness 0 == ATM
    assert entries[0].qty == 3 * LOT           # initial_lots
    assert entries[0].bar_time == times[0]     # first eligible bar (09:30)
    assert buys(res)[-1].note in ("square_off", "squareoff_end")
    # A normal square-off is not a halt — `done_reason` must stay empty so the
    # "halted" metric means the same thing as in the strangle engine.
    assert res.done_reason == ""
    assert res.date == TD.isoformat()
    assert res.expiry == EXPIRY.isoformat()


def test_bearish_day_sells_the_call():
    times = bar_times()
    chain = make_chain(times, pe={SPOT: 100.0}, ce={SPOT: 100.0})
    res = simulate_intraday_day(
        cfg(scale_lots_step=0), make_day(times, chain, bullish=False, st_dir=-1)
    )
    assert res is not None
    assert sells(res)[0].opt_type == "CE"


def test_itm_moneyness_selects_the_deeper_strike():
    times = bar_times()
    chain = make_chain(times, pe={SPOT: 100.0, SPOT + 100: 180.0})
    res = simulate_intraday_day(cfg(moneyness=-2, scale_lots_step=0), make_day(times, chain))
    assert res is not None
    # PE strike = ATM - moneyness*step = 24500 + 100
    assert sells(res)[0].strike == SPOT + 100


def test_no_trade_when_conditions_never_align():
    times = bar_times()
    chain = make_chain(times, pe={SPOT: 100.0}, ce={SPOT: 100.0})
    # SuperTrend bearish while the EMA stack is bullish — no side qualifies.
    res = simulate_intraday_day(cfg(), make_day(times, chain, bullish=True, st_dir=-1))
    assert res is not None
    assert res.trades == []
    assert res.realized == 0.0


def test_no_bars_returns_none():
    assert simulate_intraday_day(cfg(), make_day([], make_chain([]))) is None


# --------------------------------------------------------------------------- #
# Scale-in ladder
# --------------------------------------------------------------------------- #


def test_ladder_adds_at_the_same_strike_every_15_minutes():
    times = bar_times()
    chain = make_chain(times, pe={SPOT: 100.0})
    res = simulate_intraday_day(cfg(), make_day(times, chain))
    assert res is not None
    ladder = [tr for tr in sells(res) if tr.note.startswith("scale_in")]
    assert len(ladder) == 2                       # 3 -> 6 -> 9
    assert [tr.cum_lots for tr in ladder] == [6, 9]
    assert all(tr.strike == SPOT for tr in ladder)
    assert ladder[0].bar_time == times[0] + timedelta(minutes=15)


def test_ladder_stops_when_the_trend_breaks():
    times = bar_times()
    # SuperTrend flips bearish from bar 2 onward: the position exits, no ladder.
    st = [1, 1] + [-1] * (len(times) - 2)
    chain = make_chain(times, pe={SPOT: 100.0})
    res = simulate_intraday_day(cfg(), make_day(times, chain, st_dir=st))
    assert res is not None
    assert not [tr for tr in sells(res) if tr.note.startswith("scale_in")]


# --------------------------------------------------------------------------- #
# Exits
# --------------------------------------------------------------------------- #


def test_supertrend_flip_exits_the_position():
    times = bar_times()
    st = [1, 1, 1] + [-1] * (len(times) - 3)
    chain = make_chain(times, pe={SPOT: 100.0})
    res = simulate_intraday_day(cfg(scale_lots_step=0), make_day(times, chain, st_dir=st))
    assert res is not None
    exits = [r for r in res.leg_records if r.reason == "underlying_st_flip"]
    assert len(exits) == 1
    assert exits[0].exit_ist == times[3]


def test_unrealised_loss_stop_exits_on_a_premium_spike():
    times = bar_times()
    prices = [100.0, 100.0, 130.0] + [130.0] * (len(times) - 3)
    chain = make_chain(times, pe={SPOT: prices})
    res = simulate_intraday_day(cfg(scale_lots_step=0), make_day(times, chain))
    assert res is not None
    reasons = [r.reason for r in res.leg_records]
    assert "unreal_loss_stop" in reasons
    assert res.gross_pnl < 0


def test_day_loss_cap_halts_the_session_on_open_mark_to_market():
    times = bar_times()
    # 9 lots x 75 x Rs 20 adverse = Rs 13,500 unrealised, past the Rs 10,000 cap. The
    # per-position stops are relaxed so only the day cap can fire — proving the cap is
    # reachable while still positioned.
    prices = [100.0, 100.0, 121.0] + [121.0] * (len(times) - 3)
    chain = make_chain(times, pe={SPOT: prices})
    res = simulate_intraday_day(
        cfg(scale_lots_step=0, initial_lots=9, unreal_loss_pct=5.0,
            premium_rise_stop_pct=5.0, day_loss_limit=10_000.0),
        make_day(times, chain),
    )
    assert res is not None
    assert res.done_reason.startswith("day_loss")
    assert [r.reason for r in res.leg_records] == ["day_loss_cap"]
    assert res.leg_records[0].exit_ist == times[2]
    # Nothing re-opens after the cap.
    assert len(sells(res)) == 1


def test_sustained_ema20_break_exits_after_three_bars():
    times = bar_times()
    chain = make_chain(times, pe={SPOT: 100.0})
    day = make_day(times, chain)
    # From bar 1 onward, close below EMA20 while SuperTrend stays bullish.
    for b in day.decision_bars[1:]:
        b.inputs.ema20_5m = b.inputs.spot + 50
    res = simulate_intraday_day(cfg(scale_lots_step=0), day)
    assert res is not None
    assert [r.reason for r in res.leg_records] == ["ema20_break_sustained"]
    assert res.leg_records[0].exit_ist == times[3]   # bars 1,2,3 are the three breaks


def test_reentry_waits_for_the_cooloff():
    times = bar_times()
    st = [1, 1, -1, 1] + [1] * (len(times) - 4)
    chain = make_chain(times, pe={SPOT: 100.0})
    res = simulate_intraday_day(
        cfg(scale_lots_step=0, reentry_cooloff_minutes=15), make_day(times, chain, st_dir=st)
    )
    assert res is not None
    opens = [tr for tr in sells(res) if tr.note.startswith(("entry", "reentry"))]
    assert len(opens) == 2
    # Exit at 09:40 (bar 2); re-entry no earlier than 09:55.
    assert opens[1].bar_time >= times[2] + timedelta(minutes=15)


# --------------------------------------------------------------------------- #
# Rollup to ATM
# --------------------------------------------------------------------------- #


def test_rollup_to_atm_when_premium_decays():
    times = bar_times()
    held = [100.0, 100.0, 15.0] + [15.0] * (len(times) - 3)
    chain = make_chain(times, pe={SPOT - 300: held, SPOT: 80.0})
    day = make_day(times, chain)
    res = simulate_intraday_day(
        cfg(scale_lots_step=0, moneyness=6, roll_target_min_prem=50.0), day
    )
    assert res is not None
    rolls = [tr for tr in sells(res) if tr.note == "rollup_atm"]
    assert len(rolls) == 1
    assert rolls[0].strike == SPOT           # rolled back to ATM
    assert rolls[0].cum_lots == 3            # lot count preserved


def test_rollup_skipped_when_the_atm_target_is_too_cheap():
    times = bar_times()
    held = [100.0, 100.0, 15.0] + [15.0] * (len(times) - 3)
    chain = make_chain(times, pe={SPOT - 300: held, SPOT: 30.0})
    res = simulate_intraday_day(
        cfg(scale_lots_step=0, moneyness=6, roll_target_min_prem=50.0),
        make_day(times, chain),
    )
    assert res is not None
    assert not [tr for tr in sells(res) if tr.note == "rollup_atm"]
    # The original leg is left exactly as it was — all-or-nothing.
    assert len([tr for tr in sells(res) if tr.note.startswith("entry")]) == 1


def test_rollup_respects_the_daily_cap():
    times = bar_times()
    held = [100.0, 100.0] + [15.0] * (len(times) - 2)
    chain = make_chain(times, pe={SPOT - 300: held, SPOT: 15.0, SPOT + 300: 80.0})
    res = simulate_intraday_day(
        cfg(scale_lots_step=0, moneyness=6, roll_trigger_prem=20.0,
            roll_target_min_prem=20.0, max_rolls_per_day=1),
        make_day(times, chain),
    )
    assert res is not None
    assert len([tr for tr in sells(res) if tr.note == "rollup_atm"]) <= 1


def test_rollup_disabled_leaves_the_decayed_leg_alone():
    times = bar_times()
    held = [100.0, 100.0, 15.0] + [15.0] * (len(times) - 3)
    chain = make_chain(times, pe={SPOT - 300: held, SPOT: 80.0})
    res = simulate_intraday_day(
        cfg(scale_lots_step=0, moneyness=6, roll_enabled=False), make_day(times, chain)
    )
    assert res is not None
    assert not [tr for tr in sells(res) if tr.note == "rollup_atm"]


# --------------------------------------------------------------------------- #
# Pricing, commissions, trace
# --------------------------------------------------------------------------- #


def test_fill_uses_the_signal_bars_own_price_no_look_ahead():
    times = bar_times()
    prices = [111.0] + [999.0] * (len(times) - 1)
    chain = make_chain(times, pe={SPOT: prices})
    res = simulate_intraday_day(cfg(scale_lots_step=0), make_day(times, chain))
    assert res is not None
    assert sells(res)[0].price == 111.0


def test_commissions_reduce_realised_pnl():
    times = bar_times()
    chain = make_chain(times, pe={SPOT: 100.0})

    def commission(_side: str, turnover: float) -> float:
        return 0.001 * turnover

    res = simulate_intraday_day(cfg(scale_lots_step=0), make_day(times, chain), commission)
    assert res is not None
    assert res.commission > 0
    assert res.realized == pytest.approx(res.gross_pnl - res.commission)


def test_decision_events_use_the_shared_vocabulary():
    times = bar_times()
    held = [100.0, 100.0, 15.0] + [15.0] * (len(times) - 3)
    chain = make_chain(times, pe={SPOT - 300: held, SPOT: 80.0})
    decisions: list[dict] = []
    simulate_intraday_day(
        cfg(moneyness=6, roll_target_min_prem=50.0), make_day(times, chain),
        decisions=decisions,
    )
    events = {d["event"] for d in decisions}
    assert events <= {"entry", "scale_in", "exit", "st_flip", "rollup", "reentry"}
    assert "entry" in events
    assert all(d["date"] == TD.isoformat() for d in decisions)


def test_trace_records_one_row_per_processed_bar():
    times = bar_times()
    chain = make_chain(times, pe={SPOT: 100.0})
    trace: list = []
    simulate_intraday_day(cfg(), make_day(times, chain), trace=trace)
    assert 0 < len(trace) <= len(times)
    assert trace[0].ist_dt == times[0]


def test_hedge_is_bought_and_closed_with_the_short():
    times = bar_times()
    chain = make_chain(times, pe={SPOT: 100.0, SPOT - 1000: 3.0})
    res = simulate_intraday_day(
        cfg(scale_lots_step=0, hedge_enabled=True, hedge_prem_min=2.0, hedge_prem_max=5.0),
        make_day(times, chain),
    )
    assert res is not None
    hedge_open = [tr for tr in buys(res) if tr.note.startswith("hedge ")]
    hedge_close = [tr for tr in sells(res) if tr.note.startswith("hedge_exit")]
    assert len(hedge_open) == 1
    assert hedge_open[0].strike == SPOT - 1000
    assert len(hedge_close) == 1


def test_lot_size_for_date_matches_the_strangle_engine():
    # Comparability: both engines must size a 2024 day identically.
    c = IntradayDirectionalConfig(underlying="NIFTY")
    assert c.for_date(date(2024, 6, 1)).lot_size == 25
    assert c.for_date(date(2025, 6, 1)).lot_size == 75
    assert c.for_date(date(2026, 6, 1)).lot_size == 65
