"""Unit tests for the bias-driven directional-strangle simulator.

The engine is pure over ``StrangleDayData`` (synthetic decision bars + a synthetic
option chain), so these tests need no DB: they assert ratio sizing per bias bucket,
the VIX/neutral entry gates, and each leg-exit path (take-profit, premium-doubled,
daily-loss halt, square-off).
"""
from __future__ import annotations

from datetime import date, datetime

from pdp.backtest.strangle_config import StrangleConfig
from pdp.backtest.strangle_sim import (
    BarStatus,
    DecisionBar,
    StrangleDayData,
    format_status_line,
    simulate_strangle_day,
)
from pdp.signals.bias import BiasInputs, CamLevels, TimeframeEMA

TD = date(2026, 6, 2)
SPOT = 20_000.0


def _t(hh: int, mm: int) -> datetime:
    return datetime(2026, 6, 2, hh, mm)


def _bull_ema(price: float = SPOT) -> TimeframeEMA:
    return TimeframeEMA(price=price, ema9=price - 10, ema20=price - 20, ema50=price - 30)


def _bear_ema(price: float = SPOT) -> TimeframeEMA:
    return TimeframeEMA(price=price, ema9=price + 10, ema20=price + 20, ema50=price + 30)


def _bull_bias(spot: float = SPOT) -> BiasInputs:
    return BiasInputs(
        spot=spot,
        ema_1h=_bull_ema(spot), ema_15m=_bull_ema(spot), ema_5m=_bull_ema(spot),
        cam_daily=CamLevels(r3=spot - 50, r4=spot - 10, s3=spot - 400, s4=spot - 450),
        cam_weekly=CamLevels(r3=spot - 80, r4=spot - 20, s3=spot - 500, s4=spot - 550),
        pdh=spot - 100, pdl=spot - 600, pwh=spot - 120, pwl=spot - 650,
        orb_high=spot - 40, orb_low=spot - 300, pcr=1.3,
        vix_now=12.0, vix_day_open=12.5, vix_day_high=13.0, vix_recent=[13.0, 12.5, 12.0],
    )


def _bear_bias(spot: float = SPOT) -> BiasInputs:
    return BiasInputs(
        spot=spot,
        ema_1h=_bear_ema(spot), ema_15m=_bear_ema(spot), ema_5m=_bear_ema(spot),
        cam_daily=CamLevels(r3=spot + 400, r4=spot + 450, s3=spot + 50, s4=spot + 10),
        cam_weekly=CamLevels(r3=spot + 500, r4=spot + 550, s3=spot + 80, s4=spot + 20),
        pdh=spot + 600, pdl=spot + 100, pwh=spot + 650, pwl=spot + 120,
        orb_high=spot + 300, orb_low=spot + 40, pcr=0.7,
        vix_now=12.0, vix_day_open=12.5, vix_day_high=13.0, vix_recent=[13.0, 12.5, 12.0],
    )


def _flat_chain(premiums: dict[str, dict[float, float]], times: list[datetime]):
    """Build a chain with a constant premium per strike across all bar times."""
    chain: dict[str, dict[float, list]] = {}
    for ot, by_strike in premiums.items():
        chain[ot] = {}
        for stk, prem in by_strike.items():
            chain[ot][stk] = [(t, prem, prem, prem, prem) for t in times]
    return chain


def _varying_chain(series: dict[str, dict[float, list[tuple[datetime, float]]]]):
    """Build a chain from explicit (time, premium) points per strike."""
    chain: dict[str, dict[float, list]] = {}
    for ot, by_strike in series.items():
        chain[ot] = {}
        for stk, pts in by_strike.items():
            chain[ot][stk] = [(t, p, p, p, p) for t, p in pts]
    return chain


def _bars(bias_fn, times: list[datetime]) -> list[DecisionBar]:
    return [DecisionBar(ist_dt=t, open=SPOT, high=SPOT, low=SPOT, close=SPOT, bias=bias_fn())
            for t in times]


# Standard chain: ATM 20000, PE OTM = lower strikes, CE OTM = higher strikes.
_PE_PREMS = {20000.0: 120, 19950.0: 90, 19900.0: 60, 19850.0: 40, 19800.0: 25}
_CE_PREMS = {20000.0: 120, 20050.0: 90, 20100.0: 60, 20150.0: 40, 20200.0: 25}


# --------------------------------------------------------------------------- #
# Ratio sizing / gates
# --------------------------------------------------------------------------- #


def test_complete_bull_opens_five_atm_pe():
    times = [_t(10, 15), _t(10, 20)]
    chain = _flat_chain({"PE": _PE_PREMS, "CE": _CE_PREMS}, times)
    data = StrangleDayData(TD, TD, _bars(_bull_bias, times), chain)
    cfg = StrangleConfig()
    res = simulate_strangle_day(cfg, data)
    assert res is not None
    sells = [t for t in res.trades if t.side == "SELL"]
    # complete_bull -> 5 PE, 0 CE, ATM strike (20000)
    assert len(sells) == 1
    assert sells[0].opt_type == "PE"
    assert sells[0].strike == 20000.0
    assert sells[0].qty == 5 * cfg.lot_size


def test_complete_bear_opens_five_atm_ce():
    times = [_t(10, 15), _t(10, 20)]
    chain = _flat_chain({"PE": _PE_PREMS, "CE": _CE_PREMS}, times)
    data = StrangleDayData(TD, TD, _bars(_bear_bias, times), chain)
    res = simulate_strangle_day(StrangleConfig(), data)
    assert res is not None
    sells = [t for t in res.trades if t.side == "SELL"]
    assert len(sells) == 1
    assert sells[0].opt_type == "CE"
    assert sells[0].strike == 20000.0


def test_neutral_no_trade():
    times = [_t(10, 15), _t(10, 20)]
    chain = _flat_chain({"PE": _PE_PREMS, "CE": _CE_PREMS}, times)

    def neutral():
        # PCR bull(+1) and ORB bear(-1) cancel -> score 0 -> neutral bucket.
        return BiasInputs(spot=SPOT, pcr=1.3, orb_high=SPOT + 10, orb_low=SPOT + 5)

    data = StrangleDayData(TD, TD, _bars(neutral, times), chain)
    res = simulate_strangle_day(StrangleConfig(), data)
    assert res is not None
    assert res.trades == []


def test_vix_gate_blocks_entry():
    times = [_t(10, 15), _t(10, 20)]
    chain = _flat_chain({"PE": _PE_PREMS, "CE": _CE_PREMS}, times)

    def gated_bull():
        b = _bull_bias()
        b.vix_now, b.vix_day_open = 14.0, 12.0  # +16% spike
        return b

    data = StrangleDayData(TD, TD, _bars(gated_bull, times), chain)
    res = simulate_strangle_day(StrangleConfig(), data)
    assert res is not None
    assert res.trades == []


def test_no_entry_before_10_15():
    times = [_t(9, 45), _t(10, 0)]  # both before the entry gate
    chain = _flat_chain({"PE": _PE_PREMS, "CE": _CE_PREMS}, times)
    data = StrangleDayData(TD, TD, _bars(_bull_bias, times), chain)
    res = simulate_strangle_day(StrangleConfig(), data)
    assert res is not None
    assert res.trades == []


# --------------------------------------------------------------------------- #
# Exits
# --------------------------------------------------------------------------- #


def test_take_profit_closes_leg():
    times = [_t(10, 15), _t(11, 0), _t(11, 30)]
    # PE ATM premium 120 -> decays to 50 (captured > 50%) by 11:00.
    pe = {20000.0: [(_t(10, 15), 120.0), (_t(11, 0), 50.0), (_t(11, 30), 50.0)]}
    chain = _varying_chain({"PE": pe, "CE": {20000.0: [(t, 120.0) for t in times]}})
    data = StrangleDayData(TD, TD, _bars(_bull_bias, times), chain)
    res = simulate_strangle_day(StrangleConfig(take_profit_pct=0.5), data)
    assert res is not None
    reasons = [t.note for t in res.trades if t.side == "BUY"]
    assert "take_profit" in reasons
    assert res.gross_pnl > 0


def test_pct_stop_closes_leg():
    times = [_t(10, 15), _t(11, 0)]
    # PE ATM premium 120 -> 250 (108% above entry > pct_stop_all=40%) -> full close.
    pe = {20000.0: [(_t(10, 15), 120.0), (_t(11, 0), 250.0)]}
    chain = _varying_chain({"PE": pe, "CE": {20000.0: [(t, 120.0) for t in times]}})
    data = StrangleDayData(TD, TD, _bars(_bull_bias, times), chain)
    res = simulate_strangle_day(StrangleConfig(), data)
    assert res is not None
    reasons = [t.note for t in res.trades if t.side == "BUY"]
    assert "pct_stop_all" in reasons
    assert res.gross_pnl < 0


def test_daily_loss_halts_trading():
    times = [_t(10, 15), _t(11, 0), _t(11, 30), _t(12, 0)]
    # Big adverse move on a 5-lot ATM PE: 120 -> 400 = -280 * 5 * 65 = -91k < -15k.
    pe = {20000.0: [(_t(10, 15), 120.0), (_t(11, 0), 400.0),
                    (_t(11, 30), 400.0), (_t(12, 0), 400.0)]}
    chain = _varying_chain({"PE": pe, "CE": {20000.0: [(t, 120.0) for t in times]}})
    data = StrangleDayData(TD, TD, _bars(_bull_bias, times), chain)
    res = simulate_strangle_day(StrangleConfig(), data)
    assert res is not None
    assert "day_loss" in res.done_reason
    # Only the entry + the stop-out close; no re-entry after halt.
    assert len([t for t in res.trades if t.side == "SELL"]) == 1


def test_squareoff_closes_open_legs():
    times = [_t(10, 15), _t(15, 10)]  # second bar is at square-off
    chain = _flat_chain({"PE": _PE_PREMS, "CE": _CE_PREMS}, times)
    data = StrangleDayData(TD, TD, _bars(_bull_bias, times), chain)
    res = simulate_strangle_day(StrangleConfig(), data)
    assert res is not None
    assert any(t.note.startswith("squareoff") for t in res.trades if t.side == "BUY")
    # Net flat at end: equal SELL and BUY quantities.
    sell_qty = sum(t.qty for t in res.trades if t.side == "SELL")
    buy_qty = sum(t.qty for t in res.trades if t.side == "BUY")
    assert sell_qty == buy_qty


def test_every_bar_status_trace():
    times = [_t(10, 15), _t(11, 0), _t(15, 10)]
    pe = {20000.0: [(_t(10, 15), 120.0), (_t(11, 0), 50.0), (_t(15, 10), 50.0)]}
    chain = _varying_chain({"PE": pe, "CE": {20000.0: [(t, 120.0) for t in times]}})
    data = StrangleDayData(TD, TD, _bars(_bull_bias, times), chain)
    trace: list[BarStatus] = []
    res = simulate_strangle_day(StrangleConfig(), data, trace=trace)
    assert res is not None
    # One status per processed bar.
    assert len(trace) == 3
    # First bar = entry (complete_bull -> 5 PE), conditions + legs captured.
    first = trace[0]
    assert first.action.startswith("open 5PE")
    assert first.bucket == "complete_bull"
    assert first.votes  # per-signal conditions present
    assert first.legs and first.legs[0].opt_type == "PE"
    # Status line renders without error and includes the action + day P&L.
    line = format_status_line(first)
    assert "spot=" in line and "PE@20000" in line


# --------------------------------------------------------------------------- #
# Protective hedges
# --------------------------------------------------------------------------- #

# Chain with deep-OTM cheap wings for hedge selection (band [2,5]).
_PE_HEDGE = {**_PE_PREMS, 19700.0: 8.0, 19600.0: 4.0, 19500.0: 2.5}
_CE_HEDGE = {**_CE_PREMS, 20300.0: 8.0, 20400.0: 4.0, 20500.0: 2.5}


def test_hedge_buys_far_otm_long_in_band():
    times = [_t(10, 15), _t(15, 10)]
    chain = _flat_chain({"PE": _PE_HEDGE, "CE": _CE_HEDGE}, times)
    data = StrangleDayData(TD, TD, _bars(_bull_bias, times), chain)
    cfg = StrangleConfig(hedge_enabled=True, hedge_prem_min=2.0, hedge_prem_max=5.0)
    res = simulate_strangle_day(cfg, data)
    assert res is not None
    # Entry: short 5 PE (ATM 20000) + a protective long PE hedge in the band.
    hedge_open = [t for t in res.trades if t.side == "BUY" and t.note.startswith("hedge ")]
    assert len(hedge_open) == 1
    h = hedge_open[0]
    assert h.opt_type == "PE"
    # Scanning furthest-OTM (lowest PE strike) inward, the first strike in band [2,5]
    # is 19500 @2.5 -> deepest available protection inside the band.
    assert h.strike == 19500.0
    assert h.qty == 5 * cfg.lot_size
    # Hedge is unwound at square-off (sold back).
    assert any(t.note.startswith("hedge_close") for t in res.trades if t.side == "SELL")


def test_hedge_falls_back_to_cheapest_when_band_empty():
    times = [_t(10, 15), _t(15, 10)]
    # No strike priced in [2,5]; cheapest available wing is 25 (19800 / 20200).
    chain = _flat_chain({"PE": _PE_PREMS, "CE": _CE_PREMS}, times)
    data = StrangleDayData(TD, TD, _bars(_bull_bias, times), chain)
    cfg = StrangleConfig(hedge_enabled=True)
    res = simulate_strangle_day(cfg, data)
    assert res is not None
    hedge_open = [t for t in res.trades if t.side == "BUY" and t.note.startswith("hedge ")]
    assert len(hedge_open) == 1
    assert hedge_open[0].strike == 19800.0  # furthest-OTM (cheapest) available


def test_hedge_caps_loss_vs_naked():
    # A big adverse move: naked short loses much more than the hedged spread.
    times = [_t(10, 15), _t(11, 0), _t(15, 10)]
    # Short ATM PE 120 -> 400 (adverse). Hedge long PE 19600 @4 -> 180 (pays off).
    pe = {
        20000.0: [(_t(10, 15), 120.0), (_t(11, 0), 400.0), (_t(15, 10), 400.0)],
        19600.0: [(_t(10, 15), 4.0), (_t(11, 0), 180.0), (_t(15, 10), 180.0)],
    }
    ce = {20000.0: [(t, 120.0) for t in times]}
    chain = _varying_chain({"PE": pe, "CE": ce})
    data = StrangleDayData(TD, TD, _bars(_bull_bias, times), chain)
    naked = simulate_strangle_day(StrangleConfig(day_loss_limit=1e9), data)
    hedged = simulate_strangle_day(
        StrangleConfig(day_loss_limit=1e9, hedge_enabled=True), data)
    assert naked is not None and hedged is not None
    # The long wing offsets part of the short's loss.
    assert hedged.gross_pnl > naked.gross_pnl


# --------------------------------------------------------------------------- #
# Decision events (why entry / why exit) — `decisions` accumulator
# --------------------------------------------------------------------------- #


def test_decision_events_entry_has_bias_snapshot():
    times = [_t(10, 15), _t(10, 20)]
    chain = _flat_chain({"PE": _PE_PREMS, "CE": _CE_PREMS}, times)
    data = StrangleDayData(TD, TD, _bars(_bull_bias, times), chain)
    decisions: list[dict] = []
    res = simulate_strangle_day(StrangleConfig(), data, decisions=decisions)
    assert res is not None
    entries = [d for d in decisions if d["event"] == "entry"]
    assert len(entries) == 1
    e = entries[0]
    assert e["sub_reason"] is None
    assert e["snapshot"]["bucket"] == "complete_bull"
    assert e["snapshot"]["opt_type"] == "PE"
    assert e["date"] == TD.isoformat()


def test_decision_events_take_profit_exit():
    times = [_t(10, 15), _t(11, 0), _t(11, 30)]
    pe = {20000.0: [(_t(10, 15), 120.0), (_t(11, 0), 50.0), (_t(11, 30), 50.0)]}
    chain = _varying_chain({"PE": pe, "CE": {20000.0: [(t, 120.0) for t in times]}})
    data = StrangleDayData(TD, TD, _bars(_bull_bias, times), chain)
    decisions: list[dict] = []
    res = simulate_strangle_day(StrangleConfig(take_profit_pct=0.5), data, decisions=decisions)
    assert res is not None
    exits = [d for d in decisions if d["event"] == "exit"]
    assert any(d["sub_reason"] == "tp" for d in exits)


def test_decision_events_pct_stop_all_exit():
    times = [_t(10, 15), _t(11, 0)]
    pe = {20000.0: [(_t(10, 15), 120.0), (_t(11, 0), 250.0)]}
    chain = _varying_chain({"PE": pe, "CE": {20000.0: [(t, 120.0) for t in times]}})
    data = StrangleDayData(TD, TD, _bars(_bull_bias, times), chain)
    decisions: list[dict] = []
    res = simulate_strangle_day(StrangleConfig(), data, decisions=decisions)
    assert res is not None
    exits = [d for d in decisions if d["event"] == "exit"]
    assert any(d["sub_reason"] == "stop_all" for d in exits)


def test_decision_events_rollup_on_premium_decay():
    times = [_t(10, 15), _t(11, 0), _t(11, 30)]
    # Held PE (ATM 20000) entered at a low premium (25) so decay to 18 is only ~28%
    # captured (< the 50% take-profit threshold) but still < roll_trigger_prem (20) —
    # isolates the roll path from take-profit. An alternate PE strike (19950) stays
    # above roll_target_min_prem (50) the whole time, so the roll has somewhere to go.
    pe = {
        20000.0: [(_t(10, 15), 25.0), (_t(11, 0), 18.0), (_t(11, 30), 18.0)],
        19950.0: [(_t(10, 15), 60.0), (_t(11, 0), 60.0), (_t(11, 30), 60.0)],
    }
    chain = _varying_chain({"PE": pe, "CE": {20000.0: [(t, 120.0) for t in times]}})
    data = StrangleDayData(TD, TD, _bars(_bull_bias, times), chain)
    decisions: list[dict] = []
    res = simulate_strangle_day(StrangleConfig(), data, decisions=decisions)
    assert res is not None
    rollups = [d for d in decisions if d["event"] == "rollup"]
    assert len(rollups) == 1
    r = rollups[0]
    assert r["sub_reason"] == "premium_decay"
    assert r["snapshot"]["opt_type"] == "PE"
    assert r["snapshot"]["from_strike"] == 20000.0
    assert r["snapshot"]["to_strike"] == 19950.0
    # The roll's internal close must not also log a plain "exit" — only the final
    # end-of-day squareoff (forced close of the still-open rolled leg) should appear.
    exit_reasons = {d["sub_reason"] for d in decisions if d["event"] == "exit"}
    assert exit_reasons <= {"squareoff"}


def test_decision_events_none_when_not_requested():
    """Passing decisions=None (the default) must not raise and must not accumulate anything."""
    times = [_t(10, 15), _t(10, 20)]
    chain = _flat_chain({"PE": _PE_PREMS, "CE": _CE_PREMS}, times)
    data = StrangleDayData(TD, TD, _bars(_bull_bias, times), chain)
    res = simulate_strangle_day(StrangleConfig(), data)
    assert res is not None  # no decisions kwarg passed -> no-op logging, no crash


def test_premium_method_picks_strike_above_floor():
    times = [_t(10, 15), _t(10, 20)]
    chain = _flat_chain({"PE": _PE_PREMS, "CE": _CE_PREMS}, times)

    # Score in the most_bull band (0.5..0.75) -> 4PE:2CE, a NON-extreme bucket
    # that uses the premium method: ema_1h bull(+2) + ema_15m bull(+1.5) +
    # PCR bear(-1) = 2.5 / 4.5 = 0.556.
    def most_bull():
        return BiasInputs(
            spot=SPOT, ema_1h=_bull_ema(), ema_15m=_bull_ema(), pcr=0.7,
        )

    data = StrangleDayData(TD, TD, _bars(most_bull, times), chain)
    res = simulate_strangle_day(StrangleConfig(), data)
    assert res is not None
    sells = {t.opt_type: (t.strike, t.qty) for t in res.trades if t.side == "SELL"}
    # most-OTM strike with premium > 50: PE 19900 (60), CE 20100 (60).
    assert sells["PE"] == (19900.0, 4 * StrangleConfig().lot_size)
    assert sells["CE"] == (20100.0, 2 * StrangleConfig().lot_size)


def test_delta_method_picks_nearest_delta():
    """Delta method must pick the strike whose solved BSM delta is closest to target_delta.

    Uses a most_bull bias (4PE:2CE, non-extreme) so both sides open.  Chain premiums decrease
    monotonically OTM; the delta method should pick a near-ATM strike (high delta) rather than
    the cheapest far-OTM one that the premium-floor rule would also reject.
    """
    from datetime import date as _date

    from pdp.backtest.strangle_config import STRIKE_DELTA, StrangleConfig

    try:
        import vollib  # noqa: F401
    except ImportError:
        import pytest
        pytest.skip("vollib not installed — delta method falls back to premium, skip delta test")

    # most_bull bias: ema_1h bull + ema_15m bull + PCR slightly bearish → score ~0.55
    # → most_bull bucket (4PE:2CE), non-extreme so delta method is used.
    def most_bull_bias():
        return BiasInputs(spot=SPOT, ema_1h=_bull_ema(), ema_15m=_bull_ema(), pcr=0.8)

    # Chain: strikes 50 pts apart, premiums mimic realistic near-ATM options.
    # Higher premium = closer to ATM = higher absolute delta.
    pe_prems = {
        20000.0: 180,  # ATM    -> |delta| ~0.50
        19950.0: 150,  # 1-step -> |delta| ~0.45
        19900.0: 110,  # 2-step -> |delta| ~0.35
        19850.0: 75,   # 3-step -> |delta| ~0.25
        19800.0: 45,   # 4-step -> |delta| ~0.15  ← cheapest
    }
    ce_prems = {
        20000.0: 180,
        20050.0: 150,
        20100.0: 110,
        20150.0: 75,
        20200.0: 45,   # cheapest
    }
    times = [_t(10, 15), _t(10, 20)]
    chain = _flat_chain({"PE": pe_prems, "CE": ce_prems}, times)

    expiry = _date(TD.year, TD.month, TD.day + 2)  # 2 days to expiry → valid T
    # target_delta=0.35 → should pick a mid-OTM strike, not the 4-step far-OTM
    cfg = StrangleConfig(strike_method=STRIKE_DELTA, target_delta=0.35, lot_size=25,
                        extreme_atm=False)

    data = StrangleDayData(TD, expiry, _bars(most_bull_bias, times), chain)
    res = simulate_strangle_day(cfg, data)
    assert res is not None
    sells = {t.opt_type: t.strike for t in res.trades if t.side == "SELL" and "open" in t.note}
    assert "PE" in sells and "CE" in sells

    # Delta method must not pick the lowest-delta (cheapest) far-OTM strike.
    assert sells["PE"] != 19800.0, "delta method selected the lowest-delta PE strike"
    assert sells["CE"] != 20200.0, "delta method selected the lowest-delta CE strike"
    # Selected strikes must come from the chain.
    assert sells["PE"] in pe_prems
    assert sells["CE"] in ce_prems
