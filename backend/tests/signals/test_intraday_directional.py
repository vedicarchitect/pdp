"""Unit tests for the pure intraday-directional decision core.

Everything here runs without a DB, a broker, or Mongo — the point of the core is
that both the live strategy and the backtest engine can be reasoned about through
these tests alone.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta

import pytest

from pdp.signals.bias import CamLevels
from pdp.signals.intraday_directional import (
    COND_EMA,
    COND_ORB,
    COND_SUPERTREND,
    COND_VWAP,
    EntryBlock,
    ExitReason,
    IntradayInputs,
    IntradayParams,
    IntradayState,
    Side,
    entry_conditions,
    evaluate_entry,
    evaluate_exit,
    evaluate_rollup,
    evaluate_scale_in,
    rollup_target_acceptable,
    unrealized_pnl,
    update_sustained_trackers,
)

DAY = date(2026, 7, 20)


def at(hh: int, mm: int) -> datetime:
    return datetime(DAY.year, DAY.month, DAY.day, hh, mm)


def bull_inputs(**over) -> IntradayInputs:
    """A bar where every bullish (sell-PE) condition passes."""
    base = dict(
        ist_dt=at(10, 0),
        spot=100.0,
        bar_high=100.5,
        bar_low=99.5,
        ema9_5m=99.0,
        ema20_5m=98.0,
        ema9_prev_5m=98.5,
        ema20_prev_5m=98.0,
        ema9_15m=99.0,
        ema20_15m=98.0,
        st_5m_dir=1,
        st_15m_dir=1,
        session_vwap=97.0,
        orb_high=101.0,
        orb_low=96.0,
        cam=CamLevels(r3=110.0, r4=115.0, s3=90.0, s4=85.0),
        option_st_dir=-1,
    )
    base.update(over)
    return IntradayInputs(**base)  # type: ignore[arg-type]


def bear_inputs(**over) -> IntradayInputs:
    """A bar where every bearish (sell-CE) condition passes."""
    base = dict(
        ist_dt=at(10, 0),
        spot=100.0,
        bar_high=100.5,
        bar_low=99.5,
        ema9_5m=101.0,
        ema20_5m=102.0,
        ema9_prev_5m=101.5,
        ema20_prev_5m=102.0,
        ema9_15m=101.0,
        ema20_15m=102.0,
        st_5m_dir=-1,
        st_15m_dir=-1,
        session_vwap=103.0,
        orb_high=104.0,
        orb_low=99.0,
        cam=CamLevels(r3=110.0, r4=115.0, s3=90.0, s4=85.0),
        option_st_dir=-1,
    )
    base.update(over)
    return IntradayInputs(**base)  # type: ignore[arg-type]


def opened_state(side: Side = Side.PE, *, lots: int = 3, entry: float = 100.0,
                 t: datetime | None = None, option_st: int | None = -1) -> IntradayState:
    st = IntradayState()
    st.on_open(side, lots, entry, 24500.0, t or at(10, 0), option_st_dir=option_st)
    return st


# --------------------------------------------------------------------------- #
# Entry
# --------------------------------------------------------------------------- #


def test_bullish_entry_opens_short_pe():
    sig, block, conds = evaluate_entry(bull_inputs(), IntradayParams(), IntradayState())
    assert block is None
    assert sig is not None
    assert sig.side is Side.PE
    assert sig.lots == 3
    assert all(conds["PE"].values())


def test_bearish_entry_opens_short_ce():
    sig, block, _ = evaluate_entry(bear_inputs(), IntradayParams(), IntradayState())
    assert block is None
    assert sig is not None
    assert sig.side is Side.CE


@pytest.mark.parametrize(
    ("override", "failing"),
    [
        ({"spot": 95.0}, COND_ORB),          # below ORB low
        ({"session_vwap": 101.0}, COND_VWAP),  # spot below VWAP
        ({"st_5m_dir": -1}, COND_SUPERTREND),
        ({"ema9_5m": 97.0}, COND_EMA),       # EMA9 below EMA20
    ],
)
def test_each_bullish_condition_blocks_independently(override, failing):
    inp = bull_inputs(**override)
    conds = entry_conditions(inp, IntradayParams(), Side.PE)
    assert conds[failing] is False
    sig, block, _ = evaluate_entry(inp, IntradayParams(), IntradayState())
    assert sig is None
    assert block is EntryBlock.CONDITIONS_UNMET


@pytest.mark.parametrize(
    "missing",
    ["orb_low", "session_vwap", "st_5m_dir", "ema9_5m", "ema20_5m", "ema9_prev_5m"],
)
def test_missing_input_fails_closed(missing):
    inp = bull_inputs(**{missing: None})
    sig, block, _ = evaluate_entry(inp, IntradayParams(), IntradayState())
    assert sig is None, f"{missing}=None must not open a position"
    assert block is EntryBlock.CONDITIONS_UNMET


def test_ema_already_above_and_rising_qualifies_without_a_cross():
    # No cross (prev 9 already above prev 20) but 9 is rising.
    inp = bull_inputs(ema9_5m=99.0, ema9_prev_5m=98.8, ema20_prev_5m=98.0)
    assert entry_conditions(inp, IntradayParams(), Side.PE)[COND_EMA] is True


def test_ema_above_but_falling_and_no_cross_is_rejected():
    inp = bull_inputs(ema9_5m=99.0, ema9_prev_5m=99.5, ema20_prev_5m=98.0)
    assert entry_conditions(inp, IntradayParams(), Side.PE)[COND_EMA] is False


def test_fresh_cross_qualifies_even_while_falling_is_impossible():
    # prev9 <= prev20 and now 9 > 20 == a genuine cross up.
    inp = bull_inputs(ema9_5m=99.0, ema9_prev_5m=97.5, ema20_prev_5m=98.0)
    assert entry_conditions(inp, IntradayParams(), Side.PE)[COND_EMA] is True


def test_no_entry_before_the_orb_window_closes():
    sig, block, conds = evaluate_entry(
        bull_inputs(ist_dt=at(9, 25)), IntradayParams(), IntradayState()
    )
    assert sig is None
    assert block is EntryBlock.BEFORE_ENTRY_WINDOW
    assert conds == {}


def test_no_entry_at_or_after_squareoff():
    _, block, _ = evaluate_entry(
        bull_inputs(ist_dt=at(15, 15)), IntradayParams(), IntradayState()
    )
    assert block is EntryBlock.AT_OR_AFTER_SQUAREOFF


def test_only_one_position_at_a_time():
    state = opened_state(Side.PE)
    _, block, _ = evaluate_entry(bear_inputs(), IntradayParams(), state)
    assert block is EntryBlock.ALREADY_POSITIONED


def test_both_sides_can_never_qualify_on_one_bar():
    inp = bull_inputs()
    params = IntradayParams()
    pe = entry_conditions(inp, params, Side.PE)
    ce = entry_conditions(inp, params, Side.CE)
    assert not (all(pe.values()) and all(ce.values()))


def test_15m_confirmation_gate_blocks_when_15m_disagrees():
    params = IntradayParams(require_15m_confirm=True)
    inp = bull_inputs(ema9_15m=97.0, st_15m_dir=-1)
    assert not all(entry_conditions(inp, params, Side.PE).values())
    assert all(entry_conditions(bull_inputs(), params, Side.PE).values())


def test_atm_option_vwap_gate_fails_closed_when_unevaluated():
    params = IntradayParams(atm_option_vwap_gate=True)
    assert entry_conditions(bull_inputs(), params, Side.PE)[COND_VWAP] is False
    ok = bull_inputs(atm_option_vwap_ok=True)
    assert entry_conditions(ok, params, Side.PE)[COND_VWAP] is True


# --------------------------------------------------------------------------- #
# Re-entry cooloff
# --------------------------------------------------------------------------- #


def test_reentry_blocked_during_cooloff():
    state = IntradayState()
    state.on_exit(at(10, 30), ExitReason.UNDERLYING_ST_FLIP)
    _, block, _ = evaluate_entry(bull_inputs(ist_dt=at(10, 40)), IntradayParams(), state)
    assert block is EntryBlock.REENTRY_COOLOFF


def test_reentry_allowed_after_cooloff():
    state = IntradayState()
    state.on_exit(at(10, 30), ExitReason.UNDERLYING_ST_FLIP)
    sig, block, _ = evaluate_entry(bull_inputs(ist_dt=at(10, 50)), IntradayParams(), state)
    assert block is None
    assert sig is not None


@pytest.mark.parametrize("reason", [ExitReason.DAY_LOSS_CAP, ExitReason.SQUARE_OFF])
def test_day_ending_exits_block_all_further_entries(reason):
    state = IntradayState()
    state.on_exit(at(11, 0), reason)
    assert state.day_ended is True
    _, block, _ = evaluate_entry(bull_inputs(ist_dt=at(14, 0)), IntradayParams(), state)
    assert block is EntryBlock.DAY_ENDED


# --------------------------------------------------------------------------- #
# Scale-in ladder
# --------------------------------------------------------------------------- #


def test_ladder_progresses_3_6_9():
    params = IntradayParams()
    state = opened_state(Side.PE, lots=3, t=at(10, 0))

    first = evaluate_scale_in(bull_inputs(ist_dt=at(10, 15)), params, state)
    assert first is not None and first.lots == 3
    state.on_scale(first.lots, 100.0, at(10, 15))
    assert state.lots == 6

    second = evaluate_scale_in(bull_inputs(ist_dt=at(10, 30)), params, state)
    assert second is not None and second.lots == 3
    state.on_scale(second.lots, 100.0, at(10, 30))
    assert state.lots == 9

    assert evaluate_scale_in(bull_inputs(ist_dt=at(10, 45)), params, state) is None


def test_scale_in_not_due_before_the_interval():
    state = opened_state(Side.PE, t=at(10, 0))
    assert evaluate_scale_in(bull_inputs(ist_dt=at(10, 10)), IntradayParams(), state) is None


def test_scale_in_skipped_when_conditions_break():
    state = opened_state(Side.PE, t=at(10, 0))
    broken = bull_inputs(ist_dt=at(10, 15), st_5m_dir=-1)
    assert evaluate_scale_in(broken, IntradayParams(), state) is None
    # Skipped, not deferred: the clock still runs from the last actual add, so the
    # next healthy bar past the interval scales.
    assert evaluate_scale_in(bull_inputs(ist_dt=at(10, 20)), IntradayParams(), state) is not None


def test_scale_in_never_exceeds_max_lots():
    params = IntradayParams(initial_lots=3, scale_lots_step=5, max_lots=6)
    state = opened_state(Side.PE, lots=3, t=at(10, 0))
    sig = evaluate_scale_in(bull_inputs(ist_dt=at(10, 15)), params, state)
    assert sig is not None and sig.lots == 3


def test_scale_in_averages_the_entry_price():
    state = opened_state(Side.PE, lots=3, entry=100.0, t=at(10, 0))
    state.on_scale(3, 80.0, at(10, 15))
    assert state.lots == 6
    assert state.avg_entry == pytest.approx(90.0)


# --------------------------------------------------------------------------- #
# Exits — priority and each rule
# --------------------------------------------------------------------------- #


def test_day_loss_cap_wins_over_everything():
    params = IntradayParams()
    state = opened_state(Side.PE)
    state.ema_break_bars = 99
    # SuperTrend also flipped, and the premium doubled — cap still wins.
    sig = evaluate_exit(
        bull_inputs(st_5m_dir=-1), params, state, ltp=500.0, day_pnl=-10_000.0
    )
    assert sig is not None and sig.reason is ExitReason.DAY_LOSS_CAP


def test_squareoff_beats_position_rules():
    state = opened_state(Side.PE)
    sig = evaluate_exit(
        bull_inputs(ist_dt=at(15, 15), st_5m_dir=-1),
        IntradayParams(),
        state,
        ltp=100.0,
        day_pnl=0.0,
    )
    assert sig is not None and sig.reason is ExitReason.SQUARE_OFF


def test_day_ending_reasons_fire_even_when_flat():
    sig = evaluate_exit(
        bull_inputs(ist_dt=at(15, 20)),
        IntradayParams(),
        IntradayState(),
        ltp=None,
        day_pnl=0.0,
    )
    assert sig is not None and sig.reason is ExitReason.SQUARE_OFF


def test_unreal_loss_stop_fires_before_premium_doubled():
    state = opened_state(Side.PE, entry=100.0)
    sig = evaluate_exit(bull_inputs(), IntradayParams(), state, ltp=125.0, day_pnl=0.0)
    assert sig is not None and sig.reason is ExitReason.UNREAL_LOSS_STOP


def test_premium_rise_stop_is_reachable_when_unreal_stop_is_relaxed():
    params = IntradayParams(unreal_loss_pct=5.0, premium_rise_stop_pct=1.0)
    state = opened_state(Side.PE, entry=100.0)
    sig = evaluate_exit(bull_inputs(), params, state, ltp=210.0, day_pnl=0.0)
    assert sig is not None and sig.reason is ExitReason.PREMIUM_RISE_STOP


def test_premium_stops_abstain_without_a_price():
    state = opened_state(Side.PE, entry=100.0)
    assert evaluate_exit(bull_inputs(), IntradayParams(), state, ltp=None, day_pnl=0.0) is None


def test_premium_stops_abstain_on_zero_entry_price():
    state = opened_state(Side.PE, entry=0.0)
    state.lots = 3
    state.side = Side.PE
    assert evaluate_exit(bull_inputs(), IntradayParams(), state, ltp=500.0, day_pnl=0.0) is None


def test_underlying_supertrend_flip_exits():
    state = opened_state(Side.PE)
    sig = evaluate_exit(
        bull_inputs(st_5m_dir=-1), IntradayParams(), state, ltp=100.0, day_pnl=0.0
    )
    assert sig is not None and sig.reason is ExitReason.UNDERLYING_ST_FLIP


def test_option_chart_supertrend_flip_exits():
    state = opened_state(Side.PE, option_st=-1)
    sig = evaluate_exit(
        bull_inputs(option_st_dir=1), IntradayParams(), state, ltp=100.0, day_pnl=0.0
    )
    assert sig is not None and sig.reason is ExitReason.OPTION_ST_FLIP


def test_option_chart_green_at_entry_does_not_exit_immediately():
    state = opened_state(Side.PE, option_st=1)
    sig = evaluate_exit(
        bull_inputs(option_st_dir=1), IntradayParams(), state, ltp=100.0, day_pnl=0.0
    )
    assert sig is None


def test_option_supertrend_abstains_when_unavailable():
    state = opened_state(Side.PE, option_st=-1)
    sig = evaluate_exit(
        bull_inputs(option_st_dir=None), IntradayParams(), state, ltp=100.0, day_pnl=0.0
    )
    assert sig is None


# --------------------------------------------------------------------------- #
# Sustained trackers
# --------------------------------------------------------------------------- #


def test_three_consecutive_wrong_side_closes_exit():
    params = IntradayParams()
    state = opened_state(Side.PE)
    for i in range(3):
        inp = bull_inputs(ist_dt=at(10, 5 * (i + 1)), spot=97.0, ema20_5m=98.0)
        update_sustained_trackers(inp, params, state)
    assert state.ema_break_bars == 3
    sig = evaluate_exit(
        bull_inputs(spot=97.0, ema20_5m=98.0), params, state, ltp=100.0, day_pnl=0.0
    )
    assert sig is not None and sig.reason is ExitReason.EMA20_BREAK_SUSTAINED


def test_interrupted_ema_break_resets_the_counter():
    params = IntradayParams()
    state = opened_state(Side.PE)
    update_sustained_trackers(bull_inputs(spot=97.0, ema20_5m=98.0), params, state)
    update_sustained_trackers(bull_inputs(spot=97.0, ema20_5m=98.0), params, state)
    assert state.ema_break_bars == 2
    update_sustained_trackers(bull_inputs(spot=99.0, ema20_5m=98.0), params, state)
    assert state.ema_break_bars == 0


def test_camarilla_rejection_sustained_for_30_minutes_exits():
    params = IntradayParams()
    state = opened_state(Side.PE)
    cam = CamLevels(r3=110.0, r4=115.0, s3=90.0, s4=85.0)
    # Touch R3 and close back below it.
    update_sustained_trackers(
        bull_inputs(spot=109.0, bar_high=110.2, cam=cam, ema20_5m=100.0), params, state
    )
    assert state.cam_reject_level == 110.0
    for _ in range(5):
        update_sustained_trackers(
            bull_inputs(spot=108.0, bar_high=109.0, cam=cam, ema20_5m=100.0), params, state
        )
    assert state.cam_reject_bars == 6  # 30 min / 5 min bars
    sig = evaluate_exit(bull_inputs(), params, state, ltp=100.0, day_pnl=0.0)
    assert sig is not None and sig.reason is ExitReason.CAM_REJECTION_SUSTAINED


def test_camarilla_rejection_resets_when_price_reclaims_the_level():
    params = IntradayParams()
    state = opened_state(Side.PE)
    cam = CamLevels(r3=110.0, r4=115.0, s3=90.0, s4=85.0)
    update_sustained_trackers(
        bull_inputs(spot=109.0, bar_high=110.2, cam=cam, ema20_5m=100.0), params, state
    )
    assert state.cam_reject_bars == 1
    update_sustained_trackers(
        bull_inputs(spot=111.0, bar_high=111.5, cam=cam, ema20_5m=100.0), params, state
    )
    assert state.cam_reject_bars == 0
    assert state.cam_reject_level is None


def test_trackers_clear_when_flat():
    state = IntradayState()
    state.ema_break_bars = 5
    state.cam_reject_bars = 5
    update_sustained_trackers(bull_inputs(), IntradayParams(), state)
    assert state.ema_break_bars == 0
    assert state.cam_reject_bars == 0


def test_bearish_position_breaks_on_closes_above_ema20():
    params = IntradayParams()
    state = opened_state(Side.CE)
    for _ in range(3):
        update_sustained_trackers(bear_inputs(spot=105.0, ema20_5m=102.0), params, state)
    assert state.ema_break_bars == 3


# --------------------------------------------------------------------------- #
# Rollup to ATM
# --------------------------------------------------------------------------- #


def test_rollup_triggers_below_the_premium_floor():
    state = opened_state(Side.PE, lots=6)
    sig = evaluate_rollup(IntradayParams(), state, ltp=15.0, now_ist=at(13, 0))
    assert sig is not None
    assert sig.lots == 6  # lot count preserved
    assert sig.side is Side.PE


def test_no_rollup_above_the_trigger():
    state = opened_state(Side.PE)
    assert evaluate_rollup(IntradayParams(), state, ltp=25.0, now_ist=at(13, 0)) is None


def test_rollup_respects_the_daily_cap():
    params = IntradayParams(max_rolls_per_day=2)
    state = opened_state(Side.PE)
    state.rolls_today = 2
    assert evaluate_rollup(params, state, ltp=15.0, now_ist=at(13, 0)) is None


def test_rollup_blocked_after_the_cutoff():
    state = opened_state(Side.PE)
    sig = evaluate_rollup(IntradayParams(), state, ltp=15.0, now_ist=at(14, 50))
    assert sig is None


def test_rollup_target_must_clear_the_minimum_premium():
    params = IntradayParams(roll_target_min_prem=50.0)
    assert rollup_target_acceptable(60.0, params) is True
    assert rollup_target_acceptable(40.0, params) is False
    assert rollup_target_acceptable(None, params) is False


def test_roll_preserves_lots_and_counts_the_roll():
    state = opened_state(Side.PE, lots=6, entry=100.0)
    state.on_roll(24600.0, 70.0, at(13, 0), option_st_dir=-1)
    assert state.lots == 6
    assert state.avg_entry == 70.0
    assert state.strike == 24600.0
    assert state.rolls_today == 1


def test_rollup_disabled_by_config():
    state = opened_state(Side.PE)
    params = IntradayParams(roll_enabled=False)
    assert evaluate_rollup(params, state, ltp=5.0, now_ist=at(13, 0)) is None


# --------------------------------------------------------------------------- #
# P&L + params
# --------------------------------------------------------------------------- #


def test_unrealized_pnl_sign_for_a_short():
    state = opened_state(Side.PE, lots=3, entry=100.0)
    assert unrealized_pnl(state, 80.0, 75) == pytest.approx(20.0 * 3 * 75)
    assert unrealized_pnl(state, 120.0, 75) == pytest.approx(-20.0 * 3 * 75)


def test_unpriced_leg_reports_no_phantom_pnl():
    state = opened_state(Side.PE, lots=3, entry=0.0)
    assert unrealized_pnl(state, 120.0, 75) == 0.0


def test_cam_reject_bars_derived_from_the_timeframe():
    assert IntradayParams(timeframe_min=5, cam_reject_minutes=30).cam_reject_bars == 6
    assert IntradayParams(timeframe_min=15, cam_reject_minutes=30).cam_reject_bars == 2


@pytest.mark.parametrize(
    "kwargs",
    [
        {"timeframe_min": 0},
        {"initial_lots": 0},
        {"max_lots": 1, "initial_lots": 3},
        {"day_loss_limit": 0.0},
        {"unreal_loss_pct": 0.0},
        {"ema_break_bars": 0},
        {"entry_after_ist": time(16, 0)},
        {"roll_target_min_prem": 5.0, "roll_trigger_prem": 20.0},
    ],
)
def test_invalid_params_rejected(kwargs):
    with pytest.raises(ValueError):
        IntradayParams(**kwargs).validate()


def test_state_reset_clears_everything():
    state = opened_state(Side.PE, lots=9)
    state.rolls_today = 2
    state.ema_break_bars = 2
    state.on_exit(at(12, 0), ExitReason.SQUARE_OFF)
    state.reset_for_day()
    assert not state.is_open
    assert state.rolls_today == 0
    assert state.day_ended is False
    assert state.last_exit_ist is None


def test_scale_in_stops_at_squareoff():
    state = opened_state(Side.PE, t=at(15, 0))
    assert evaluate_scale_in(bull_inputs(ist_dt=at(15, 15)), IntradayParams(), state) is None


def test_cooloff_measured_from_the_exit_not_the_entry():
    state = IntradayState()
    state.on_exit(at(10, 0), ExitReason.UNDERLYING_ST_FLIP)
    assert state.last_exit_ist == at(10, 0)
    inp = bull_inputs(ist_dt=at(10, 0) + timedelta(minutes=15))
    sig, block, _ = evaluate_entry(inp, IntradayParams(), state)
    assert block is None and sig is not None
