"""Regression tests for ``strangle_sim.close_partial_leg``.

The 30% tiered stop closes half a leg and keeps the rest open. ``Leg.avg_entry`` is a
*derived property* (``total_cost / total_qty``, see ``pdp.backtest.sim``), so the average
had to be snapshotted before ``total_qty`` was rewritten. It wasn't: qty halved, cost
didn't, and the remainder's entry price doubled. That inflated every subsequent
take-profit and premium-stop computed off the remainder — on 2026-07-21 it turned a ~+400
take-profit into +10,316 and fired a TP that should never have fired, which in turn kept
the day trading past a day-loss halt it should have hit.

These assertions are on the *invariants*, not on one day's numbers, so they keep holding
if the sizing/stop policy is retuned.
"""
from __future__ import annotations

from datetime import date, datetime

from pdp.backtest.strangle_config import StrangleConfig
from pdp.backtest.strangle_sim import DecisionBar, StrangleDayData, simulate_strangle_day
from pdp.signals.bias import BiasInputs, CamLevels, TimeframeEMA

TD = date(2026, 6, 2)
SPOT = 20_000.0


def _t(hh: int, mm: int) -> datetime:
    return datetime(2026, 6, 2, hh, mm)


def _bear_ema(price: float = SPOT) -> TimeframeEMA:
    return TimeframeEMA(price=price, ema9=price + 10, ema20=price + 20, ema50=price + 30)


def _bear_bias(spot: float = SPOT) -> BiasInputs:
    """All-bear inputs -> COMPLETE_BEAR -> the ratio table sells CE only."""
    return BiasInputs(
        spot=spot,
        ema_1h=_bear_ema(spot), ema_15m=_bear_ema(spot), ema_5m=_bear_ema(spot),
        cam_daily=CamLevels(r3=spot + 400, r4=spot + 450, s3=spot + 50, s4=spot + 10),
        cam_weekly=CamLevels(r3=spot + 500, r4=spot + 550, s3=spot + 80, s4=spot + 20),
        pdh=spot + 600, pdl=spot + 100, pwh=spot + 650, pwl=spot + 120,
        orb_high=spot + 300, orb_low=spot + 40, pcr=0.7,
        st_1h=(-1, -1),  # agreeing 1h SuperTrend so the extreme-bucket guard permits it
    )


def _bars(times: list[datetime]) -> list[DecisionBar]:
    return [DecisionBar(ist_dt=t, open=SPOT, high=SPOT, low=SPOT, close=SPOT, bias=_bear_bias())
            for t in times]


def _chain(ce_series: dict[float, list[tuple[datetime, float]]],
           pe_flat: dict[float, float], times: list[datetime]):
    """CE side varies over time; PE side is a flat backdrop (never traded when bearish)."""
    chain: dict[str, dict[float, list]] = {"CE": {}, "PE": {}}
    for stk, pts in ce_series.items():
        chain["CE"][stk] = [(t, p, p, p, p) for t, p in pts]
    for stk, prem in pe_flat.items():
        chain["PE"][stk] = [(t, prem, prem, prem, prem) for t in times]
    return chain


_PE_FLAT = {20000.0: 120.0, 19950.0: 90.0, 19900.0: 60.0}

# Entry at 10:15 sells CE 20000 @ 100. Premium then rises through the 30% half-stop
# (>=130) and later falls back so the *remainder* would take profit at 50% of its credit.
_TIMES = [_t(10, 15), _t(10, 20), _t(10, 25), _t(10, 30)]
_CE_SERIES = {
    20000.0: [(_t(10, 15), 100.0), (_t(10, 20), 135.0), (_t(10, 25), 135.0), (_t(10, 30), 48.0)],
    # Far strikes priced under the premium floor so the premium picker stays at ATM,
    # and above roll_trigger_prem so no rollup fires and muddies the trace.
    20050.0: [(t, 45.0) for t in _TIMES],
    20100.0: [(t, 30.0) for t in _TIMES],
}


def _run(cfg: StrangleConfig | None = None):
    cfg = cfg or StrangleConfig.from_dict({"roll_enabled": False})
    data = StrangleDayData(TD, TD, _bars(_TIMES), _chain(_CE_SERIES, _PE_FLAT, _TIMES))
    res = simulate_strangle_day(cfg, data)
    assert res is not None
    return cfg, res


def test_partial_close_preserves_avg_entry():
    """The half-stop must leave the remainder's basis at the original entry price."""
    _cfg, res = _run()
    sells = [t for t in res.trades if t.side == "SELL"]
    assert sells, "expected an opening CE sell"
    entry_px = sells[0].price
    assert entry_px == 100.0

    partials = [t for t in res.trades if t.side == "BUY" and t.note == "pct_stop_half"]
    assert len(partials) == 1, "expected exactly one half-stop"

    # Every trade recorded AFTER the half-stop must still carry the ORIGINAL average
    # entry -- not a doubled one. This is the invariant the bug violated.
    after = res.trades[res.trades.index(partials[0]) + 1:]
    assert after, "expected the remainder to be closed later in the day"
    for t in after:
        if t.side == "BUY":
            assert t.avg_entry == entry_px, (
                f"remainder basis drifted from {entry_px} to {t.avg_entry} after a partial close"
            )


def test_partial_close_halves_pnl_not_price():
    """Closing half the lots realises half the P&L a full close would have."""
    cfg, res = _run()
    sells = [t for t in res.trades if t.side == "SELL"]
    partial = next(t for t in res.trades if t.side == "BUY" and t.note == "pct_stop_half")
    lots_in = sells[0].qty // cfg.lot_size
    lots_out = partial.qty // cfg.lot_size
    assert lots_out == lots_in // 2
    # Short leg: pnl = (entry - exit) * qty. A rising premium means a loss.
    assert partial.leg_pnl == (sells[0].price - partial.price) * partial.qty
    assert partial.leg_pnl < 0


def test_remainder_take_profit_is_not_inflated():
    """The remainder's TP is measured against its real credit, not a doubled one.

    With entry 100 and the premium falling to 48, the remainder captures
    (100 - 48) * qty. If the basis had doubled to 200 the captured figure would be
    (200 - 48) * qty -- ~3x larger, and the phantom profit would mask a day-loss halt.
    """
    _cfg, res = _run()
    entry_px = next(t for t in res.trades if t.side == "SELL").price
    closes = [t for t in res.trades if t.side == "BUY" and t.note != "pct_stop_half"]
    assert closes, "expected the remainder to close (take_profit or squareoff)"
    final = closes[-1]
    assert final.leg_pnl == (entry_px - final.price) * final.qty


def test_half_stop_is_one_shot_per_leg():
    """A side may be half-stopped once per leg, mirroring live's OpenLeg.half_stopped.

    The premium stays above the half-stop threshold for two consecutive bars; without the
    latch the (correctly sized) remainder gets half-stopped again on the second one.
    """
    _cfg, res = _run()
    partials = [t for t in res.trades if t.note == "pct_stop_half"]
    assert len(partials) == 1


def test_partial_close_can_trip_the_day_loss_cap():
    """A partial close moves day P&L, so it must be able to halt the day like a full one."""
    cfg = StrangleConfig.from_dict({
        "roll_enabled": False,
        # Half of 5 lots (floor) = 2 lots x 65 x (100 - 135) = -4,550 -> below this cap.
        "day_loss_limit": 4_000.0,
    })
    _cfg, res = _run(cfg)
    partial = next(t for t in res.trades if t.note == "pct_stop_half")
    assert partial.day_pnl <= -4_000.0
    assert res.done_reason.startswith("day_loss"), (
        f"day-loss cap not tripped by a partial close (done_reason={res.done_reason!r})"
    )
