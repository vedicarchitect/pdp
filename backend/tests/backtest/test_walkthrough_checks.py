"""Unit tests for the EOD walkthrough's invariant detectors.

Every detector gets a **positive** and a **negative** fixture. A detector that silently
stops firing is worse than no detector at all — the report would keep looking clean while
the bug it was written for came back.
"""
from __future__ import annotations

from datetime import date, datetime

import pytest

from pdp.backtest.intraday_config import IntradayDirectionalConfig
from pdp.backtest.intraday_sim import IntradayBarStatus
from pdp.backtest.sim import DayResult, LegRecord, Trade
from pdp.backtest.strangle_config import StrangleConfig
from pdp.backtest.strangle_sim import BarStatus, LegStatus
from pdp.backtest.walkthrough_checks import (
    Finding,
    check_intraday,
    check_strangle,
    rank,
)
from pdp.signals.bias import BiasBucket, BiasResult, VoteBreakdown

TD = date(2026, 6, 2)


def _t(hh: int, mm: int) -> datetime:
    return datetime(2026, 6, 2, hh, mm)


def _bias(
    *, present: float = 1.0, gate_reason: str = "vix_gate_disabled", gated: bool = False,
) -> BiasResult:
    return BiasResult(
        score=-0.8, bucket=BiasBucket.MOST_BEAR, pe_lots=2, ce_lots=4,
        gated=gated, reason="", present_weight_frac=present,
        breakdown={"ema_1h": VoteBreakdown(vote=-1, weight=2.0, abstained=False)},
        bucket_raw=BiasBucket.MOST_BEAR, gate_reason=gate_reason,
    )


def _bar(
    hh: int, mm: int, *, legs: list[LegStatus] | None = None, day_pnl: float = 0.0,
    done: bool = False, action: str = "hold", bias: BiasResult | None = None,
) -> BarStatus:
    return BarStatus(
        ist_dt=_t(hh, mm), spot=20_000.0, score=-0.8, bucket="most_bear", gated=False,
        reason="", votes={}, pcr=None, vix_now=None, cam_daily=None, cam_weekly=None,
        orb_high=None, orb_low=None, legs=legs or [], day_pnl=day_pnl, action=action,
        bias_result=bias if bias is not None else _bias(), done=done,
    )


def _leg(opt: str, strike: float, lots: int, entry: float, ltp: float | None,
         lot_size: int = 65, **kw) -> LegStatus:
    mtm = None if ltp is None else (entry - ltp) * lots * lot_size
    return LegStatus(opt_type=opt, strike=strike, lots=lots, avg_entry=entry,
                     ltp=ltp, mtm=kw.pop("mtm", mtm), **kw)


def _result(trades: list[Trade], *, legs: list[LegRecord] | None = None,
            gross: float | None = None, chg: float = 10.0,
            done_reason: str = "") -> DayResult:
    gross = sum((t.leg_pnl or 0.0) for t in trades) if gross is None else gross
    comm = sum(t.commission_inr for t in trades)
    return DayResult(
        date=TD.isoformat(), expiry=TD.isoformat(), nifty_open=20_000.0,
        nifty_close=20_000.0 + chg, nifty_chg=chg, trades=trades,
        leg_records=legs or [], gross_pnl=gross, commission=comm,
        realized=gross - comm, done_reason=done_reason, nifty_bars=75,
    )


def _sell(hh: int, mm: int, opt: str = "CE", strike: float = 20_000.0,
          price: float = 100.0, qty: int = 325) -> Trade:
    # `cum_lots > 0` and `leg_pnl is None` are what mark a fill as opening risk
    # (see `_opens_risk`) — a hedge close is also a SELL but has neither.
    return Trade(side="SELL", opt_type=opt, strike=strike, bar_time=_t(hh, mm),
                 qty=qty, price=price, nifty=20_000.0, note="entry", avg_entry=price,
                 cum_lots=qty // 65)


def _buy(hh: int, mm: int, *, opt: str = "CE", strike: float = 20_000.0,
         price: float = 50.0, qty: int = 325, note: str = "take_profit",
         basis: float = 100.0, day_pnl: float = 0.0) -> Trade:
    return Trade(side="BUY", opt_type=opt, strike=strike, bar_time=_t(hh, mm), qty=qty,
                 price=price, nifty=20_000.0, note=note, avg_entry=basis,
                 leg_pnl=(basis - price) * qty, day_pnl=day_pnl)


def _ids(findings: list[Finding]) -> set[str]:
    return {f.id for f in findings}


CFG = StrangleConfig()


# --------------------------------------------------------------------------- #
# Ordering
# --------------------------------------------------------------------------- #


def test_rank_orders_most_severe_first():
    out = rank([
        Finding(id="a", severity="info", title=""),
        Finding(id="b", severity="critical", title=""),
        Finding(id="c", severity="medium", title=""),
    ])
    assert [f.id for f in out] == ["b", "c", "a"]


def test_unknown_severity_is_rejected():
    with pytest.raises(ValueError, match="unknown severity"):
        Finding(id="x", severity="catastrophic", title="")


# --------------------------------------------------------------------------- #
# F-AVG-DRIFT — the generic form of the close_partial_leg bug
# --------------------------------------------------------------------------- #


def test_avg_entry_drift_without_a_fill_is_critical():
    trace = [
        _bar(10, 15, legs=[_leg("CE", 20_000.0, 5, 100.0, 100.0)]),
        _bar(10, 20, legs=[_leg("CE", 20_000.0, 3, 166.67, 100.0)]),  # basis moved, no fill
    ]
    out = check_strangle(CFG, _result([_sell(10, 15)]), trace, [])
    assert "F-AVG-DRIFT" in _ids(out)
    assert out[0].severity == "critical"


def test_avg_entry_drift_is_silent_when_a_fill_explains_it():
    """A scale-in legitimately moves the average — that must not be reported."""
    trace = [
        _bar(10, 15, legs=[_leg("CE", 20_000.0, 5, 100.0, 100.0)]),
        _bar(10, 20, legs=[_leg("CE", 20_000.0, 8, 110.0, 100.0)]),
    ]
    trades = [_sell(10, 15), _sell(10, 20, price=126.0)]
    assert "F-AVG-DRIFT" not in _ids(check_strangle(CFG, _result(trades), trace, []))


def test_avg_entry_steady_across_a_partial_close_is_clean():
    """The fixed engine keeps the basis — the detector must agree."""
    trace = [
        _bar(10, 15, legs=[_leg("CE", 20_000.0, 5, 100.0, 135.0)]),
        _bar(10, 20, legs=[_leg("CE", 20_000.0, 3, 100.0, 135.0)]),
    ]
    trades = [_sell(10, 15), _buy(10, 20, price=135.0, qty=130, note="pct_stop_half")]
    assert "F-AVG-DRIFT" not in _ids(check_strangle(CFG, _result(trades), trace, []))


# --------------------------------------------------------------------------- #
# F-MTM-RECON
# --------------------------------------------------------------------------- #


def test_mtm_inconsistent_with_lots_is_flagged():
    bad = _leg("CE", 20_000.0, 3, 100.0, 80.0, mtm=99_999.0)
    out = check_strangle(CFG, _result([_sell(10, 15)]), [_bar(10, 15, legs=[bad])], [])
    assert "F-MTM-RECON" in _ids(out)


def test_mtm_consistent_with_lots_is_clean():
    good = _leg("CE", 20_000.0, 3, 100.0, 80.0)  # mtm derived from lots x lot_size
    out = check_strangle(CFG, _result([_sell(10, 15)]), [_bar(10, 15, legs=[good])], [])
    assert "F-MTM-RECON" not in _ids(out)


# --------------------------------------------------------------------------- #
# F-PNL-RECON
# --------------------------------------------------------------------------- #


def test_pnl_that_does_not_reconcile_is_critical():
    res = _result([_sell(10, 15), _buy(11, 0)], gross=999.0)
    assert "F-PNL-RECON" in _ids(check_strangle(CFG, res, [], []))


def test_pnl_that_reconciles_is_clean():
    res = _result([_sell(10, 15), _buy(11, 0)])
    assert "F-PNL-RECON" not in _ids(check_strangle(CFG, res, [], []))


# --------------------------------------------------------------------------- #
# F-HALT-BREACH
# --------------------------------------------------------------------------- #


def test_trading_past_the_day_loss_cap_is_flagged():
    trace = [_bar(13, 0, day_pnl=-CFG.day_loss_limit - 1, done=False)]
    assert "F-HALT-BREACH" in _ids(check_strangle(CFG, _result([]), trace, []))


def test_entry_after_the_halt_is_flagged():
    trace = [_bar(13, 0, day_pnl=-CFG.day_loss_limit - 1, done=True)]
    res = _result([_sell(14, 0)])
    assert "F-HALT-BREACH" in _ids(check_strangle(CFG, res, trace, []))


def test_no_halt_breach_when_within_the_cap():
    trace = [_bar(13, 0, day_pnl=-100.0, done=False)]
    assert "F-HALT-BREACH" not in _ids(check_strangle(CFG, _result([]), trace, []))


def test_closing_a_hedge_after_the_halt_is_not_a_new_position():
    """Selling back a protective long is a SELL, but it removes risk rather than adding it.

    Every square-off after a halted day emits one of these; counting them made the
    detector fire on days that behaved correctly.
    """
    hedge_close = Trade(side="SELL", opt_type="CE", strike=24_150.0, bar_time=_t(15, 10),
                        qty=650, price=18.45, nifty=23_757.0,
                        note="hedge_close (squareoff)", cum_lots=0, avg_entry=13.80,
                        leg_pnl=3_022.0, day_pnl=-17_680.0)
    trace = [_bar(12, 20, day_pnl=-CFG.day_loss_limit - 1, done=True)]
    res = _result([_sell(10, 15), hedge_close])
    assert "F-HALT-BREACH" not in _ids(check_strangle(CFG, res, trace, []))


# --------------------------------------------------------------------------- #
# F-TP-MATH
# --------------------------------------------------------------------------- #


def test_take_profit_far_from_target_is_flagged():
    # Entry 100 -> exit 10 captures 90%, against a 50% target.
    res = _result([_sell(10, 15), _buy(11, 0, price=10.0)])
    assert "F-TP-MATH" in _ids(check_strangle(CFG, res, [], []))


def test_take_profit_at_target_is_clean():
    res = _result([_sell(10, 15), _buy(11, 0, price=50.0)])  # exactly 50%
    assert "F-TP-MATH" not in _ids(check_strangle(CFG, res, [], []))


def test_modest_take_profit_overshoot_is_bar_discretisation_not_a_finding():
    """TP fires on the first bar past the target, so 59% on a 50% target is normal."""
    res = _result([_sell(10, 15), _buy(11, 0, price=41.0)])  # 59% captured
    assert "F-TP-MATH" not in _ids(check_strangle(CFG, res, [], []))


def test_take_profit_firing_below_target_is_always_flagged():
    """Under-target is never discretisation — the trigger used the wrong credit."""
    res = _result([_sell(10, 15), _buy(11, 0, price=70.0)])  # only 30% captured
    assert "F-TP-MATH" in _ids(check_strangle(CFG, res, [], []))


# --------------------------------------------------------------------------- #
# F-STOP-RESET / F-ROLL-INWARD
# --------------------------------------------------------------------------- #


def test_roll_of_a_losing_leg_is_flagged():
    res = _result([_sell(10, 15), _buy(12, 40, price=150.0, note="roll")])
    assert "F-STOP-RESET" in _ids(check_strangle(CFG, res, [], []))


def test_roll_of_a_decayed_leg_is_not_a_stop_reset():
    res = _result([_sell(10, 15), _buy(12, 40, price=15.0, note="roll")])
    assert "F-STOP-RESET" not in _ids(check_strangle(CFG, res, [], []))


def test_roll_toward_spot_is_flagged():
    dec = [{"ts_ist": _t(12, 40), "event": "rollup",
            "snapshot": {"opt_type": "CE", "from_strike": 20_400.0,
                         "to_strike": 20_100.0, "spot": 20_000.0}}]
    out = check_strangle(CFG, _result([]), [_bar(12, 40)], dec)
    assert "F-ROLL-INWARD" in _ids(out)


def test_roll_away_from_spot_is_clean():
    dec = [{"ts_ist": _t(12, 40), "event": "rollup",
            "snapshot": {"opt_type": "CE", "from_strike": 20_100.0,
                         "to_strike": 20_400.0, "spot": 20_000.0}}]
    out = check_strangle(CFG, _result([]), [_bar(12, 40)], dec)
    assert "F-ROLL-INWARD" not in _ids(out)


# --------------------------------------------------------------------------- #
# F-STRADDLE
# --------------------------------------------------------------------------- #


def test_both_sides_at_one_strike_is_a_straddle():
    legs = [_leg("PE", 20_000.0, 6, 71.0, 70.0), _leg("CE", 20_000.0, 6, 68.0, 70.0)]
    out = check_strangle(CFG, _result([]), [_bar(10, 30, legs=legs)], [])
    assert "F-STRADDLE" in _ids(out)


def test_different_strikes_are_a_strangle():
    legs = [_leg("PE", 19_900.0, 6, 71.0, 70.0), _leg("CE", 20_100.0, 6, 68.0, 70.0)]
    out = check_strangle(CFG, _result([]), [_bar(10, 30, legs=legs)], [])
    assert "F-STRADDLE" not in _ids(out)


# --------------------------------------------------------------------------- #
# F-PRICE-SRC
# --------------------------------------------------------------------------- #


def test_squareoff_spot_disagreeing_with_the_decision_bar_is_flagged():
    t = _buy(15, 10, note="squareoff")
    t.nifty = 20_050.0                       # priced off the bar open
    trace = [_bar(15, 10)]                   # decision-bar spot is 20,000
    assert "F-PRICE-SRC" in _ids(check_strangle(CFG, _result([_sell(10, 15), t]), trace, []))


def test_squareoff_spot_matching_the_decision_bar_is_clean():
    t = _buy(15, 10, note="squareoff")
    assert "F-PRICE-SRC" not in _ids(
        check_strangle(CFG, _result([_sell(10, 15), t]), [_bar(15, 10)], []))


def test_a_sub_point_squareoff_spot_difference_is_not_worth_reporting():
    t = _buy(15, 10, note="squareoff")
    t.nifty = 20_000.05
    assert "F-PRICE-SRC" not in _ids(
        check_strangle(CFG, _result([_sell(10, 15), t]), [_bar(15, 10)], []))


# --------------------------------------------------------------------------- #
# F-QUORUM / F-DEAD-INPUT / F-VIX-ACTIVE
# --------------------------------------------------------------------------- #


def test_entry_below_the_quorum_floor_is_flagged():
    thin = _bias(present=0.10)
    out = check_strangle(CFG, _result([_sell(10, 15)]), [_bar(10, 15, bias=thin)], [])
    assert "F-QUORUM" in _ids(out)


def test_entry_above_the_quorum_floor_is_clean():
    out = check_strangle(CFG, _result([_sell(10, 15)]), [_bar(10, 15)], [])
    assert "F-QUORUM" not in _ids(out)


def test_a_weighted_input_that_never_votes_is_flagged():
    dead = _bias()
    dead.breakdown = {"cam_weekly": VoteBreakdown(vote=None, weight=1.5, abstained=True)}
    out = check_strangle(CFG, _result([]), [_bar(10, 15, bias=dead)], [])
    assert "F-DEAD-INPUT" in _ids(out)


def test_vix_gate_evaluating_while_disabled_is_flagged():
    """Regression guard: with the gate off, no caller may still evaluate it."""
    assert not CFG.weights.vix_gate_enabled
    armed = _bias(gate_reason="vix_at_day_high", gated=True)
    out = check_strangle(CFG, _result([]), [_bar(10, 15, bias=armed)], [])
    assert "F-VIX-ACTIVE" in _ids(out)


def test_vix_gate_disabled_reason_is_clean():
    out = check_strangle(CFG, _result([]), [_bar(10, 15)], [])
    assert "F-VIX-ACTIVE" not in _ids(out)


# --------------------------------------------------------------------------- #
# F-STALE-BAR / F-FLAT-MOVE
# --------------------------------------------------------------------------- #


def test_a_frozen_premium_is_flagged_as_a_data_gap():
    trace = [_bar(10, h, legs=[_leg("CE", 20_000.0, 5, 100.0, 88.0)]) for h in range(20)]
    assert "F-STALE-BAR" in _ids(check_strangle(CFG, _result([]), trace, []))


def test_a_moving_premium_is_not_a_data_gap():
    trace = [_bar(10, m, legs=[_leg("CE", 20_000.0, 5, 100.0, 88.0 + m)])
             for m in range(20)]
    assert "F-STALE-BAR" not in _ids(check_strangle(CFG, _result([]), trace, []))


def test_zero_trades_on_a_big_move_is_reported():
    out = check_strangle(CFG, _result([], chg=-159.0), [], [])
    assert "F-FLAT-MOVE" in _ids(out)


def test_zero_trades_on_a_quiet_day_is_not_reported():
    out = check_strangle(CFG, _result([], chg=-12.0), [], [])
    assert "F-FLAT-MOVE" not in _ids(out)


# --------------------------------------------------------------------------- #
# Intraday
# --------------------------------------------------------------------------- #

ICFG = IntradayDirectionalConfig()


def _ibar(hh: int, mm: int, *, conds: dict[str, dict[str, bool]] | None = None,
          action: str = "hold", **kw) -> IntradayBarStatus:
    return IntradayBarStatus(
        ist_dt=_t(hh, mm), spot=20_000.0, side=None, strike=None, lots=0,
        avg_entry=0.0, ltp=None, day_pnl=0.0, session_vwap=None, orb_high=None,
        orb_low=None, st_dir=None, option_st_dir=None, ema_break_bars=0,
        cam_reject_bars=0, action=action, entry_conditions=conds or {}, **kw
    )


def test_a_condition_never_true_all_day_is_reported():
    trace = [_ibar(10, m, conds={"PE": {"orb": False, "vwap": True},
                                 "CE": {"orb": False, "vwap": False}})
             for m in (0, 5, 10)]
    assert "F-COND-NEVER" in _ids(check_intraday(ICFG, _result([]), trace, []))


def test_conditions_that_do_fire_are_not_reported():
    trace = [_ibar(10, m, conds={"PE": {"orb": True, "vwap": True},
                                 "CE": {"orb": False, "vwap": False}})
             for m in (0, 5, 10)]
    assert "F-COND-NEVER" not in _ids(check_intraday(ICFG, _result([]), trace, []))


def test_intraday_entry_after_the_day_loss_halt_is_flagged():
    trace = [_ibar(13, 0, done_reason="day_loss (-20000)")]
    res = _result([_sell(14, 0)], done_reason="day_loss (-20000)")
    assert "F-HALT-BREACH" in _ids(check_intraday(ICFG, res, trace, []))


def test_intraday_clean_day_produces_no_halt_finding():
    trace = [_ibar(13, 0)]
    assert "F-HALT-BREACH" not in _ids(check_intraday(ICFG, _result([]), trace, []))
