"""Config-driven SuperTrend option-selling backtest engine.

``simulate_day(config, day_data, commission_fn)`` replays one trade day for a single
``StrategyConfig`` and returns a ``DayResult``. It is pure with respect to I/O: all market data
arrives via ``DayData`` (resampled spot + prior session + the day's option chain), so the same
engine serves both ``backtest_multiday.py`` and the sweep harness, and is unit-testable without a DB.

Semantics (configurable):
  * Entry on the first SuperTrend flip of the day, sized at ``base_lots``.
  * Scale-in gated by ``scale_in_gate`` (option-premium prior-bar break by default).
  * Flip handling by ``flip_mode``:
      - ``strangle`` (default): close additional legs, keep the old base, open the opposite base,
        and resolve the resulting two-leg strangle by flip-candle extreme break — the short CE
        closes when NIFTY breaks the flip candle's high, the short PE when it breaks the low.
      - ``close_all`` (legacy): close everything, open the opposite base.
  * Roll-up, per-leg stop and day stop are toggles. Profit-lock and ST-touch are intentionally absent.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

from pdp.backtest.strategy_config import (
    FLIP_CLOSE_ALL,
    SCALE_ALWAYS,
    SCALE_PREMIUM_BREAK,
    SCALE_PREMIUM_NO_NEW_HIGH,
    StrategyConfig,
)
from pdp.indicators.registry import build_tracker
from pdp.indicators.snapshot import Snapshot
from pdp.indicators.supertrend import SuperTrendTracker

_IST = timedelta(hours=5, minutes=30)
_NEAREST_BAND = 10  # nearest-strike fallback half-width, in strike steps

# A bar tuple is (dt_ist_naive, open, high, low, close); high is index 2, low index 3, close index 4.
Bar = tuple


# ── Pricing helpers (ported from backtest_multiday, now shared) ───────────────
def price_at(bars: list[Bar], target: datetime, prefer: str = "open") -> float | None:
    """Price of the nearest bar at or before ``target`` (no look-ahead), within 15 min."""
    best, bd = None, timedelta(hours=99)
    for b in bars:
        if b[0] > target:
            continue
        d = abs(b[0] - target)
        if d < bd:
            bd, best = d, b
    if best is None or bd > timedelta(minutes=15):
        return None
    return best[1] if prefer == "open" else best[4]


def prev_curr_bars(bars: list[Bar], target: datetime) -> tuple[Bar | None, Bar | None]:
    """Return (prior_bar, current_bar) for the nearest bar at or before ``target`` (15-min tol)."""
    best_i, bd = None, timedelta(hours=99)
    for i, b in enumerate(bars):
        if b[0] > target:
            continue
        d = abs(b[0] - target)
        if d < bd:
            bd, best_i = d, i
    if best_i is None or bd > timedelta(minutes=15):
        return None, None
    return (bars[best_i - 1] if best_i > 0 else None), bars[best_i]


def select_strike(spot: float, opt_type: str, moneyness: int, step: int) -> int:
    """Signed-moneyness strike: ``>0`` OTM, ``0`` ATM, ``<0`` ITM.

    CE strike = ATM + moneyness*step (OTM is higher); PE strike = ATM - moneyness*step
    (OTM is lower). Negative moneyness inverts to in-the-money for each side.
    """
    atm = round(spot / step) * step
    if opt_type.upper() == "CE":
        return int(atm + moneyness * step)
    return int(atm - moneyness * step)


def resolve_from_chain(
    day_chain: dict[str, dict[float, list]],
    opt_type: str,
    target_strike: float,
    step: int,
    band: int = _NEAREST_BAND,
) -> tuple[float | None, list]:
    """Exact strike from the day's chain, else nearest available within ±band steps."""
    side = day_chain.get(opt_type.upper(), {})
    exact = side.get(float(target_strike))
    if exact:
        return float(target_strike), exact
    for s in range(1, band + 1):
        for cand in (target_strike + s * step, target_strike - s * step):
            bars = side.get(float(cand))
            if bars:
                return float(cand), bars
    return None, []


# ── Data + result models ──────────────────────────────────────────────────────
@dataclass
class DayData:
    """Everything ``simulate_day`` needs for one trade day (already resampled to the timeframe)."""

    trade_date: date
    expiry_date: date
    nifty_bars: list[dict]              # resampled spot, each {ts(UTC), open, high, low, close}
    prior_session_bars: list[dict]      # resampled prior session for ST warmup
    day_chain: dict[str, dict[float, list]]  # opt_type -> {strike: [(dt,o,h,lo,c), ...]}


@dataclass
class Leg:
    opt_type: str
    strike: float
    bars: list = field(repr=False, default_factory=list)
    total_qty: int = 0
    total_cost: float = 0.0
    lots: int = 0
    base_lots: int = 0
    entry_ist: datetime | None = None

    @property
    def avg_entry(self) -> float:
        return self.total_cost / self.total_qty if self.total_qty else 0.0

    def mtm(self, px: float) -> float:
        return (self.avg_entry - px) * self.total_qty


@dataclass
class Trade:
    side: str
    opt_type: str
    strike: float
    bar_time: datetime
    qty: int
    price: float
    nifty: float
    note: str = ""
    cum_lots: int = 0
    avg_entry: float = 0.0
    leg_pnl: float | None = None
    day_pnl: float = 0.0
    commission_inr: float = 0.0


@dataclass
class LegRecord:
    opt_type: str
    strike: float
    entry_ist: datetime
    exit_ist: datetime
    lots: int
    avg_entry: float
    exit_px: float
    leg_pnl: float
    reason: str


@dataclass
class DayResult:
    date: str
    expiry: str
    nifty_open: float
    nifty_close: float
    nifty_chg: float
    trades: list[Trade]
    leg_records: list[LegRecord]
    gross_pnl: float
    commission: float
    realized: float
    done_reason: str
    nifty_bars: int


CommissionFn = Callable[[str, float], float]  # (side, turnover_inr) -> commission_inr


def _zero_commission(_side: str, _turnover: float) -> float:
    return 0.0


# ── Engine ────────────────────────────────────────────────────────────────────
def simulate_day(
    cfg: StrategyConfig,
    data: DayData,
    commission_fn: CommissionFn | None = None,
) -> DayResult | None:
    """Replay one trade day under ``cfg``. Returns a ``DayResult`` (or None if no spot bars)."""
    commission_fn = commission_fn or _zero_commission
    lot = cfg.lot_size

    nifty_bars = data.nifty_bars
    if not nifty_bars:
        return None
    nifty_open = float(nifty_bars[0]["open"])
    nifty_close = float(nifty_bars[-1]["close"])

    # SuperTrend, warmed with the prior session so the line is continuous across the day boundary.
    tracker = SuperTrendTracker(period=cfg.st_period, multiplier=cfg.st_multiplier)
    for wb in data.prior_session_bars:
        wts = wb["ts"] if wb["ts"].tzinfo else wb["ts"].replace(tzinfo=UTC)
        tracker.update(wb["high"], wb["low"], wb["close"], bar_time=wts)

    # Suite indicator bundle: built from cfg.suite_indicators, warmed with prior session.
    suite_bundle: dict[str, Any] = {}
    if cfg.suite_indicators:
        for _ind in cfg.suite_indicators:
            _fam = _ind.get("family") if isinstance(_ind, dict) else str(_ind)
            if _fam:
                _params = {k: v for k, v in _ind.items() if k != "family"} if isinstance(_ind, dict) else {}
                try:
                    suite_bundle[_fam] = build_tracker(_fam, _params)
                except KeyError:
                    pass
        for wb in data.prior_session_bars:
            _wts = wb["ts"] if wb["ts"].tzinfo else wb["ts"].replace(tzinfo=UTC)
            for _ft in suite_bundle.values():
                _ft.update(wb["high"], wb["low"], wb["close"], wb.get("volume", 0.0), _wts)

    # Build the in-session series: (ist_dt, open, high, low, close, st_state, suite_snapshot).
    series = []
    for b in nifty_bars:
        ts_utc = b["ts"] if b["ts"].tzinfo else b["ts"].replace(tzinfo=UTC)
        ist_dt = (ts_utc + _IST).replace(tzinfo=None)
        st = tracker.update(b["high"], b["low"], b["close"], bar_time=ts_utc)
        suite_snap: Snapshot | None = None
        if suite_bundle:
            _skw = {_fam: _ft.update(b["high"], b["low"], b["close"], b.get("volume", 0.0), ts_utc)
                    for _fam, _ft in suite_bundle.items()}
            suite_snap = Snapshot(**_skw)
        series.append(
            (ist_dt, float(b["open"]), float(b["high"]), float(b["low"]), float(b["close"]), st, suite_snap)
        )

    td = data.trade_date
    start_dt = datetime(td.year, td.month, td.day, cfg.start_ist.hour, cfg.start_ist.minute)
    sqoff_dt = datetime(td.year, td.month, td.day, cfg.squareoff_ist.hour, cfg.squareoff_ist.minute)

    legs: dict[str, Leg] = {}        # at most one CE and one PE
    active: str | None = None        # the trend-aligned, scalable side
    flip_high: float | None = None   # flip candle extremes arming strangle resolution
    flip_low: float | None = None
    trades: list[Trade] = []
    leg_records: list[LegRecord] = []
    day_pnl = 0.0
    done = False
    done_reason = ""
    first_flip_seen = False
    _ema_confirm_count: int = 0        # consecutive bars with fast-EMA breach
    _ema_confirm_leg: str | None = None  # which leg the counter belongs to

    def in_strangle() -> bool:
        return len(legs) == 2

    def open_leg(opt_type: str, ist_dt: datetime, bar_close: float, lots: int, note: str) -> bool:
        nonlocal active
        target = float(select_strike(bar_close, opt_type, cfg.moneyness, cfg.strike_step))
        strike, bars = resolve_from_chain(data.day_chain, opt_type, target, cfg.strike_step)
        if strike is None or not bars:
            return False
        px = price_at(bars, ist_dt, prefer="close")
        if not px:
            return False
        leg = Leg(opt_type=opt_type, strike=strike, bars=bars, base_lots=lots, entry_ist=ist_dt)
        leg.total_qty = lots * lot
        leg.total_cost = px * lots * lot
        leg.lots = lots
        legs[opt_type] = leg
        comm = commission_fn("SELL", lots * lot * px)
        trades.append(Trade(
            side="SELL", opt_type=opt_type, strike=strike, bar_time=ist_dt, qty=lots * lot,
            price=px, nifty=bar_close, note=note, cum_lots=lots, avg_entry=leg.avg_entry,
            day_pnl=day_pnl, commission_inr=comm,
        ))
        return True

    def close_leg(
        opt_type: str, ist_dt: datetime, nifty_px: float, reason: str, lots: int | None = None
    ) -> None:
        """Close ``lots`` (default all) of a leg, booking realized P&L and a leg record."""
        nonlocal day_pnl, done, done_reason, active
        leg = legs.get(opt_type)
        if leg is None:
            return
        close_lots = leg.lots if lots is None else min(lots, leg.lots)
        if close_lots <= 0:
            return
        qty = close_lots * lot
        close_px = price_at(leg.bars, ist_dt, prefer="close")
        if not close_px:
            return
        leg_pnl = (leg.avg_entry - close_px) * qty
        day_pnl += leg_pnl
        comm = commission_fn("BUY", qty * close_px)
        trades.append(Trade(
            side="BUY", opt_type=opt_type, strike=leg.strike, bar_time=ist_dt, qty=qty,
            price=close_px, nifty=nifty_px, note=reason, cum_lots=leg.lots - close_lots,
            avg_entry=leg.avg_entry, leg_pnl=leg_pnl, day_pnl=day_pnl, commission_inr=comm,
        ))
        if close_lots == leg.lots:
            if leg.entry_ist is not None:
                leg_records.append(LegRecord(
                    opt_type=leg.opt_type, strike=leg.strike, entry_ist=leg.entry_ist,
                    exit_ist=ist_dt, lots=leg.lots, avg_entry=leg.avg_entry, exit_px=close_px,
                    leg_pnl=leg_pnl, reason=reason,
                ))
            del legs[opt_type]
            if active == opt_type:
                active = None
        else:
            avg = leg.avg_entry  # capture BEFORE reducing qty (avg_entry is total_cost/total_qty)
            leg.total_qty -= qty
            leg.total_cost = avg * leg.total_qty  # avg unchanged on partial close
            leg.lots -= close_lots
        if day_pnl <= -cfg.day_stop and not done:
            done = True
            done_reason = f"day_stop ({day_pnl:+.0f})"

    def close_all(ist_dt: datetime, nifty_px: float, reason: str) -> None:
        for ot in list(legs.keys()):
            close_leg(ot, ist_dt, nifty_px, reason)

    for ist_dt, bar_open, bar_high, bar_low, bar_close, st, _suite_snap in series:
        if st is None:
            continue
        if ist_dt < start_dt:
            continue
        if not first_flip_seen and getattr(st, "flipped", False):
            first_flip_seen = True

        # Square-off takes priority.
        if ist_dt >= sqoff_dt:
            close_all(ist_dt, bar_open, "squareoff")
            break
        if done:
            continue

        desired = "PE" if st.direction > 0 else "CE"

        # ── Strangle resolution by flip-candle extreme break ──────────────────
        # CE (down-aligned) closes on a high break; PE (up-aligned) on a low break.
        if in_strangle() and flip_high is not None and flip_low is not None:
            if "CE" in legs and bar_high >= flip_high:
                close_leg("CE", ist_dt, bar_close, "strangle_break_up")
            if "PE" in legs and bar_low <= flip_low:
                close_leg("PE", ist_dt, bar_close, "strangle_break_down")
            if not in_strangle():
                # One (or both) legs resolved this bar; the survivor (if any) becomes active.
                flip_high = flip_low = None
                active = next(iter(legs), None)
                continue
            # Still a strangle: wait for the break — no entry/scale/flip/roll this bar.
            continue

        # ── Per-leg MTM stop on the active leg ────────────────────────────────
        if active is not None and active in legs:
            leg = legs[active]
            mtm_px = price_at(leg.bars, ist_dt, prefer="close")
            if mtm_px is not None:
                if leg.mtm(mtm_px) <= -(cfg.leg_stop_per_lot * leg.lots):
                    close_leg(active, ist_dt, bar_close, "leg_stop")
                    _ema_confirm_count = 0
                    _ema_confirm_leg = None
                    continue

        # ── EMA early-exit (PE exits on close < EMA; CE exits on close > EMA) ─
        if (active is not None and active in legs
                and (cfg.early_exit_ema_fast is not None or cfg.early_exit_ema_slow is not None)
                and _suite_snap is not None and _suite_snap.ema is not None):
            ema_vals = _suite_snap.ema.values
            if _ema_confirm_leg != active:
                _ema_confirm_count = 0
                _ema_confirm_leg = active
            # Slow EMA: instant 1-bar exit.
            if cfg.early_exit_ema_slow is not None:
                eslow = ema_vals.get(cfg.early_exit_ema_slow)
                if eslow is not None:
                    if (active == "PE" and bar_close < eslow) or (active == "CE" and bar_close > eslow):
                        close_leg(active, ist_dt, bar_close, "ema_slow_exit")
                        _ema_confirm_count = 0
                        _ema_confirm_leg = None
                        continue
            # Fast EMA: needs confirm_bars consecutive close breaches.
            if cfg.early_exit_ema_fast is not None:
                efast = ema_vals.get(cfg.early_exit_ema_fast)
                if efast is not None:
                    breach = (active == "PE" and bar_close < efast) or (active == "CE" and bar_close > efast)
                    if breach:
                        _ema_confirm_count += 1
                        if _ema_confirm_count >= cfg.early_exit_ema_confirm_bars:
                            close_leg(active, ist_dt, bar_close, "ema_fast_exit")
                            _ema_confirm_count = 0
                            _ema_confirm_leg = None
                            continue
                    else:
                        _ema_confirm_count = 0

        # ── Flip ──────────────────────────────────────────────────────────────
        if active is not None and active in legs and legs[active].opt_type != desired:
            _ema_confirm_count = 0
            _ema_confirm_leg = None
            old = active
            if cfg.flip_mode == FLIP_CLOSE_ALL:
                close_leg(old, ist_dt, bar_open, "flip")
                if done:
                    continue
                if first_flip_seen:
                    open_leg(desired, ist_dt, bar_close, cfg.base_lots, f"open {cfg.base_lots}L")
                    active = desired if desired in legs else None
                continue
            # FLIP_STRANGLE: trim old to base, keep it, open opposite base, arm the strangle.
            extra = legs[old].lots - legs[old].base_lots
            if extra > 0:
                close_leg(old, ist_dt, bar_close, "flip_trim", lots=extra)
            if open_leg(desired, ist_dt, bar_close, cfg.base_lots, f"flip_open {cfg.base_lots}L"):
                flip_high, flip_low = bar_high, bar_low
                active = None  # neither side is "active" (scalable) during the strangle
            else:
                # Could not open the opposite leg; keep the trimmed old base as the active leg.
                active = old
            continue

        if not first_flip_seen:
            continue

        # ── Roll-up on premium decay (active, aligned leg) ────────────────────
        if cfg.roll_enabled and active is not None and active in legs and legs[active].opt_type == desired:
            leg = legs[active]
            prem = price_at(leg.bars, ist_dt, prefer="close")
            if prem is not None and prem < cfg.roll_trigger_prem:
                roll_strike, roll_bars = _find_roll_target(
                    data.day_chain, desired, ist_dt, leg.strike, cfg.roll_target_min_prem
                )
                if roll_strike is not None:
                    close_leg(active, ist_dt, bar_close, "roll")
                    if not done:
                        roll_px = price_at(roll_bars, ist_dt, prefer="close")
                        if roll_px:
                            nl = Leg(opt_type=desired, strike=roll_strike, bars=roll_bars,
                                     base_lots=cfg.base_lots, entry_ist=ist_dt)
                            nl.total_qty = cfg.base_lots * lot
                            nl.total_cost = roll_px * cfg.base_lots * lot
                            nl.lots = cfg.base_lots
                            legs[desired] = nl
                            active = desired
                            comm = commission_fn("SELL", cfg.base_lots * lot * roll_px)
                            trades.append(Trade(
                                side="SELL", opt_type=desired, strike=roll_strike, bar_time=ist_dt,
                                qty=cfg.base_lots * lot, price=roll_px, nifty=bar_close,
                                note=f"roll {cfg.base_lots}L", cum_lots=cfg.base_lots,
                                avg_entry=nl.avg_entry, day_pnl=day_pnl, commission_inr=comm,
                            ))
                    continue

        # ── Entry ─────────────────────────────────────────────────────────────
        if active is None and desired not in legs:
            if open_leg(desired, ist_dt, bar_close, cfg.base_lots, f"open {cfg.base_lots}L"):
                active = desired
            continue

        # ── Scale-in (active aligned leg, under max) ──────────────────────────
        if (active is not None and active in legs
                and legs[active].opt_type == desired and legs[active].lots < cfg.max_lots):
            leg = legs[active]
            if _scale_gate_open(cfg, leg.bars, ist_dt):
                add_px = price_at(leg.bars, ist_dt, prefer="close")
                if add_px:
                    leg.total_qty += cfg.add_lots * lot
                    leg.total_cost += add_px * cfg.add_lots * lot
                    leg.lots += cfg.add_lots
                    comm = commission_fn("SELL", cfg.add_lots * lot * add_px)
                    trades.append(Trade(
                        side="SELL", opt_type=desired, strike=leg.strike, bar_time=ist_dt,
                        qty=cfg.add_lots * lot, price=add_px, nifty=bar_close,
                        note=f"scale +{cfg.add_lots}L -> {leg.lots}L", cum_lots=leg.lots,
                        avg_entry=leg.avg_entry, day_pnl=day_pnl, commission_inr=comm,
                    ))

    # Any legs still open at end of series (square-off should normally have flattened them).
    if legs:
        close_all(sqoff_dt, nifty_close, "squareoff_end")

    commission_total = sum(t.commission_inr for t in trades)
    return DayResult(
        date=td.isoformat(),
        expiry=data.expiry_date.isoformat(),
        nifty_open=nifty_open,
        nifty_close=nifty_close,
        nifty_chg=nifty_close - nifty_open,
        trades=trades,
        leg_records=leg_records,
        gross_pnl=day_pnl,
        commission=commission_total,
        realized=day_pnl - commission_total,
        done_reason=done_reason,
        nifty_bars=len(nifty_bars),
    )


def _scale_gate_open(cfg: StrategyConfig, bars: list[Bar], ist_dt: datetime) -> bool:
    """Whether the scale-in gate permits adding a lot this bar (on the option premium series)."""
    if cfg.scale_in_gate == SCALE_ALWAYS:
        return True
    prior, curr = prev_curr_bars(bars, ist_dt)
    if prior is None or curr is None:
        return False
    if cfg.scale_in_gate == SCALE_PREMIUM_BREAK:
        # Add only when the premium broke the prior bar's low (decay continuing in our favour).
        return curr[3] < prior[3]
    if cfg.scale_in_gate == SCALE_PREMIUM_NO_NEW_HIGH:
        # Legacy: add unless the premium made a new high this bar.
        return not (curr[2] > prior[2])
    return False


def _find_roll_target(
    day_chain: dict[str, dict[float, list]],
    opt_type: str,
    ist_dt: datetime,
    current_strike: float,
    min_prem: float,
) -> tuple[float | None, list]:
    """Furthest-OTM same-side strike (skipping the held one) with close premium > ``min_prem``."""
    side = day_chain.get(opt_type.upper(), {})
    ordered = sorted(side.keys(), reverse=(opt_type.upper() == "CE"))
    for stk in ordered:
        if stk == current_strike:
            continue
        bars = side.get(stk, [])
        prem = price_at(bars, ist_dt, prefer="close") if bars else None
        if prem is not None and prem > min_prem:
            return stk, bars
    return None, []
