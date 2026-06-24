"""Bias-driven directional-strangle backtest engine.

``simulate_strangle_day(cfg, data, commission_fn)`` replays one trade day of the
directional-strangle strategy described in ``strategies/MultiTimeFrameSelling.txt``
and returns a ``DayResult``. Like ``sim.simulate_day`` it is pure with respect to
I/O: all market data and the per-bar multi-timeframe signal inputs arrive via
``StrangleDayData`` (assembled by the loader/runner), so the engine is unit
testable without a DB.

Semantics:
  * Each decision bar (signal timeframe, e.g. 5m) after ``entry_after_ist`` we
    score the bias from the bar's ``BiasInputs``. Entries are blocked while the
    VIX gate is active or the bucket is neutral (if ``neutral_no_trade``).
  * On entry we open a strangle sized by the bucket's PE:CE lot ratio; extreme
    buckets sell ATM, milder buckets pick strikes by premium (>floor) or delta.
  * Each bar we manage open legs: take-profit at a fraction of credit captured,
    a premium-doubled stop, and rollup when premium decays below the trigger.
  * On a confirmed bias sign flip we adjust (close the strangle to re-enter on
    the new lean). A daily-loss cap flattens and halts; square-off closes all.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from pdp.backtest.sim import (
    Bar,
    CommissionFn,
    DayResult,
    Leg,
    LegRecord,
    Trade,
    _zero_commission,
    price_at,
    resolve_from_chain,
    select_strike,
)
from pdp.backtest.strangle_config import STRIKE_DELTA, StrangleConfig
from pdp.signals.bias import BiasBucket, BiasInputs, BiasResult, score_bias

_EXTREME = (BiasBucket.COMPLETE_BULL, BiasBucket.COMPLETE_BEAR)


@dataclass
class DecisionBar:
    """One signal-timeframe bar plus the multi-timeframe bias inputs at its close."""

    ist_dt: datetime
    open: float
    high: float
    low: float
    close: float
    bias: BiasInputs


@dataclass
class StrangleDayData:
    """Everything ``simulate_strangle_day`` needs for one trade day."""

    trade_date: date
    expiry_date: date
    decision_bars: list[DecisionBar]
    day_chain: dict[str, dict[float, list]]  # opt_type -> {strike: [(dt,o,h,lo,c), ...]}
    nifty_open: float = 0.0
    nifty_close: float = 0.0


@dataclass
class LegStatus:
    """Per-leg snapshot at a bar (for every-minute status logging)."""

    opt_type: str
    strike: float
    lots: int
    avg_entry: float
    ltp: float | None
    mtm: float | None
    is_hedge: bool = False  # True for a protective long hedge leg


@dataclass
class BarStatus:
    """Full per-bar status: the bias conditions, gates, position, P&L, and action.

    This is the every-minute trace consumed by the backtest runner and mirrored
    by the live strategy's structlog heartbeat, so both surfaces show identical
    fields (score, each signal vote, VIX/PCR, open legs with LTP/MTM, day P&L).
    """

    ist_dt: datetime
    spot: float
    score: float
    bucket: str
    gated: bool
    reason: str            # bias reason (score/bucket/gate)
    votes: dict[str, int]  # per-signal conditions (-1/0/+1)
    pcr: float | None
    vix_now: float | None
    legs: list[LegStatus]
    day_pnl: float
    action: str            # what happened this bar: hold/entry/take_profit/roll/...


def format_status_line(s: BarStatus) -> str:
    """Compact one-line IST status for monitor-style every-minute logging."""
    legs = " ".join(
        f"{'+' if lg.is_hedge else '-'}{lg.lots}x{lg.opt_type}@{lg.strike:.0f}"
        f"(e{lg.avg_entry:.1f}/l{f'{lg.ltp:.1f}' if lg.ltp is not None else '-'}"
        f"/m{f'{lg.mtm:+.0f}' if lg.mtm is not None else '-'})"
        for lg in s.legs
    ) or "flat"
    cond = ",".join(f"{k}{'+' if v > 0 else ''}{v}" for k, v in s.votes.items()) or "-"
    vix = f"{s.vix_now:.2f}" if s.vix_now is not None else "-"
    pcr = f"{s.pcr:.2f}" if s.pcr is not None else "-"
    gate = " GATED" if s.gated else ""
    return (
        f"{s.ist_dt:%H:%M} spot={s.spot:.1f} score={s.score:+.3f} {s.bucket}{gate} "
        f"vix={vix} pcr={pcr} | [{cond}] | {legs} | day={s.day_pnl:+.0f} | {s.action}"
    )


def _select_premium_strike(
    day_chain: dict[str, dict[float, list]],
    opt_type: str,
    ist_dt: datetime,
    spot: float,
    cfg: StrangleConfig,
) -> tuple[float | None, list]:
    """Most-OTM same-side strike whose premium is still above ``premium_floor``.

    Premiums fall as strikes move OTM, so we walk outward and keep the furthest
    strike still above the floor (safer placement, premium just over the floor).
    """
    step = cfg.strike_step
    atm = round(spot / step) * step
    last_ok: tuple[float, list] | None = None
    for s in range(0, 21):  # ATM out to 20 steps
        target = float(select_strike(atm, opt_type, s, step))
        strike, bars = resolve_from_chain(day_chain, opt_type, target, step, band=2)
        if strike is None or not bars:
            continue
        prem = price_at(bars, ist_dt, prefer="close")
        if prem is None:
            continue
        if prem > cfg.premium_floor:
            last_ok = (strike, bars)
        elif last_ok is not None:
            break  # premium dropped below floor past a good strike — stop
    if last_ok is not None:
        return last_ok
    # Fallback: ATM (richest premium) even if below floor.
    target = float(select_strike(atm, opt_type, 0, step))
    return resolve_from_chain(day_chain, opt_type, target, step, band=2)


def _select_hedge_strike(
    day_chain: dict[str, dict[float, list]],
    opt_type: str,
    ist_dt: datetime,
    cfg: StrangleConfig,
) -> tuple[float | None, list]:
    """Protective long strike for ``opt_type``: furthest-OTM strike priced in the
    hedge band ``[hedge_prem_min, hedge_prem_max]``; if none qualifies, the cheapest
    available (least-premium, deepest-OTM) strike — the most protection the chain offers.
    """
    side = day_chain.get(opt_type.upper(), {})
    # Iterate furthest-OTM first (premiums rise as we walk back toward ATM):
    # CE OTM = higher strikes (descending), PE OTM = lower strikes (ascending).
    ordered = sorted(side.keys(), reverse=(opt_type.upper() == "CE"))
    cheapest: tuple[float, list] | None = None
    for stk in ordered:
        sbars = side.get(stk, [])
        prem = price_at(sbars, ist_dt, prefer="close") if sbars else None
        if prem is None or prem <= 0:
            continue
        if cheapest is None:
            cheapest = (stk, sbars)  # furthest-OTM available = least premium
        if cfg.hedge_prem_min <= prem <= cfg.hedge_prem_max:
            return stk, sbars  # furthest-OTM strike inside the hedge band
    if cheapest is not None:
        return cheapest
    return None, []


def _select_strike_for(
    cfg: StrangleConfig,
    bucket: BiasBucket,
    opt_type: str,
    day_chain: dict[str, dict[float, list]],
    ist_dt: datetime,
    spot: float,
) -> tuple[float | None, list]:
    """Resolve the strike+bars for one leg per the configured method and bucket."""
    if cfg.extreme_atm and bucket in _EXTREME:
        target = float(select_strike(spot, opt_type, 0, cfg.strike_step))  # ATM
        return resolve_from_chain(day_chain, opt_type, target, cfg.strike_step, band=2)
    if cfg.strike_method == STRIKE_DELTA:
        # Delta-based selection requires solving IV per candidate strike from the
        # bar premium; until that is wired in it falls back to the premium method
        # so configs remain runnable. Tracked as a follow-up.
        return _select_premium_strike(day_chain, opt_type, ist_dt, spot, cfg)
    return _select_premium_strike(day_chain, opt_type, ist_dt, spot, cfg)


def simulate_strangle_day(
    cfg: StrangleConfig,
    data: StrangleDayData,
    commission_fn: CommissionFn | None = None,
    trace: list[BarStatus] | None = None,
) -> DayResult | None:
    """Replay one trade day of the directional strangle. Returns a ``DayResult``.

    If ``trace`` is a list, a ``BarStatus`` is appended for every processed bar —
    the detailed every-minute status (bias score + each signal vote, VIX/PCR
    gates, open legs with LTP/MTM, day P&L, and the action taken).
    """
    commission_fn = commission_fn or _zero_commission
    lot = cfg.lot_size
    bars = data.decision_bars
    if not bars:
        return None

    nifty_open = data.nifty_open or bars[0].open
    nifty_close = data.nifty_close or bars[-1].close
    td = data.trade_date
    sqoff_dt = datetime.combine(td, cfg.squareoff_ist)
    entry_after_dt = datetime.combine(td, cfg.entry_after_ist)

    legs: dict[str, Leg] = {}
    hedges: dict[str, Leg] = {}  # protective long per short side (opt_type -> Leg)
    trades: list[Trade] = []
    leg_records: list[LegRecord] = []
    day_pnl = 0.0
    done = False
    done_reason = ""
    pos_sign = 0  # sign of bias score when the current position was opened

    def open_leg(opt_type: str, ist_dt: datetime, spot: float, lots: int,
                 bucket: BiasBucket, note: str) -> bool:
        if lots <= 0:
            return False
        strike, sbars = _select_strike_for(cfg, bucket, opt_type, data.day_chain, ist_dt, spot)
        if strike is None or not sbars:
            return False
        px = price_at(sbars, ist_dt, prefer="close")
        if not px:
            return False
        leg = Leg(opt_type=opt_type, strike=strike, bars=sbars, base_lots=lots,
                  entry_ist=ist_dt, lots=lots)
        leg.total_qty = lots * lot
        leg.total_cost = px * lots * lot
        legs[opt_type] = leg
        comm = commission_fn("SELL", lots * lot * px)
        trades.append(Trade(
            side="SELL", opt_type=opt_type, strike=strike, bar_time=ist_dt, qty=lots * lot,
            price=px, nifty=spot, note=note, cum_lots=lots, avg_entry=leg.avg_entry,
            day_pnl=day_pnl, commission_inr=comm,
        ))
        open_hedge(opt_type, ist_dt, spot, lots)
        return True

    def open_hedge(opt_type: str, ist_dt: datetime, spot: float, lots: int) -> None:
        """Buy a protective far-OTM long of the same side (1 hedge lot per short lot)."""
        if not cfg.hedge_enabled or lots <= 0:
            return
        strike, hbars = _select_hedge_strike(data.day_chain, opt_type, ist_dt, cfg)
        if strike is None or not hbars:
            return
        px = price_at(hbars, ist_dt, prefer="close")
        if px is None:
            return
        h = Leg(opt_type=opt_type, strike=strike, bars=hbars, base_lots=lots,
                entry_ist=ist_dt, lots=lots)
        h.total_qty = lots * lot
        h.total_cost = px * lots * lot
        hedges[opt_type] = h
        comm = commission_fn("BUY", lots * lot * px)
        trades.append(Trade(
            side="BUY", opt_type=opt_type, strike=strike, bar_time=ist_dt, qty=lots * lot,
            price=px, nifty=spot, note=f"hedge {lots}{opt_type}", cum_lots=lots,
            avg_entry=h.avg_entry, day_pnl=day_pnl, commission_inr=comm,
        ))

    def close_hedge(opt_type: str, ist_dt: datetime, spot: float, reason: str) -> None:
        """Sell the protective long back; its P&L (long: exit-entry) accrues to the day."""
        nonlocal day_pnl
        h = hedges.get(opt_type)
        if h is None:
            return
        exit_px = price_at(h.bars, ist_dt, prefer="close")
        if exit_px is None:
            return
        qty = h.total_qty
        hedge_pnl = (exit_px - h.avg_entry) * qty  # long: profit when premium rises
        day_pnl += hedge_pnl
        comm = commission_fn("SELL", qty * exit_px)
        trades.append(Trade(
            side="SELL", opt_type=opt_type, strike=h.strike, bar_time=ist_dt, qty=qty,
            price=exit_px, nifty=spot, note=f"hedge_close ({reason})", cum_lots=0,
            avg_entry=h.avg_entry, leg_pnl=hedge_pnl, day_pnl=day_pnl, commission_inr=comm,
        ))
        if h.entry_ist is not None:
            leg_records.append(LegRecord(
                opt_type=h.opt_type, strike=h.strike, entry_ist=h.entry_ist,
                exit_ist=ist_dt, lots=h.lots, avg_entry=h.avg_entry, exit_px=exit_px,
                leg_pnl=hedge_pnl, reason=f"hedge_close ({reason})",
            ))
        del hedges[opt_type]

    def close_leg(opt_type: str, ist_dt: datetime, spot: float, reason: str) -> None:
        nonlocal day_pnl, done, done_reason
        leg = legs.get(opt_type)
        if leg is None:
            return
        # Close the protective long first so hedge P&L is in day_pnl before the cap check.
        close_hedge(opt_type, ist_dt, spot, reason)
        close_px = price_at(leg.bars, ist_dt, prefer="close")
        if close_px is None:
            return
        qty = leg.total_qty
        leg_pnl = (leg.avg_entry - close_px) * qty
        day_pnl += leg_pnl
        comm = commission_fn("BUY", qty * close_px)
        trades.append(Trade(
            side="BUY", opt_type=opt_type, strike=leg.strike, bar_time=ist_dt, qty=qty,
            price=close_px, nifty=spot, note=reason, cum_lots=0, avg_entry=leg.avg_entry,
            leg_pnl=leg_pnl, day_pnl=day_pnl, commission_inr=comm,
        ))
        if leg.entry_ist is not None:
            leg_records.append(LegRecord(
                opt_type=leg.opt_type, strike=leg.strike, entry_ist=leg.entry_ist,
                exit_ist=ist_dt, lots=leg.lots, avg_entry=leg.avg_entry, exit_px=close_px,
                leg_pnl=leg_pnl, reason=reason,
            ))
        del legs[opt_type]
        if day_pnl <= -cfg.day_loss_limit and not done:
            done = True
            done_reason = f"day_loss ({day_pnl:+.0f})"

    def close_all(ist_dt: datetime, spot: float, reason: str) -> None:
        for ot in list(legs.keys()):
            close_leg(ot, ist_dt, spot, reason)

    def manage_legs(ist_dt: datetime, spot: float) -> None:
        """Per-bar exits on each open leg: take-profit, premium-doubled stop, rollup."""
        for ot in list(legs.keys()):
            leg = legs.get(ot)
            if leg is None:
                continue
            px = price_at(leg.bars, ist_dt, prefer="close")
            if px is None:
                continue
            captured = leg.mtm(px)  # profit when premium decays
            credit = leg.total_cost
            # Take-profit on captured fraction of credit.
            if credit > 0 and captured >= cfg.take_profit_pct * credit:
                close_leg(ot, ist_dt, spot, "take_profit")
                continue
            # Premium-doubled stop.
            if cfg.premium_double_stop and px >= 2.0 * leg.avg_entry:
                close_leg(ot, ist_dt, spot, "premium_doubled")
                continue
            # Rollup on premium decay.
            if cfg.roll_enabled and px < cfg.roll_trigger_prem:
                _roll_leg(ot, ist_dt, spot)

    def _roll_leg(opt_type: str, ist_dt: datetime, spot: float) -> None:
        leg = legs.get(opt_type)
        if leg is None:
            return
        lots = leg.lots
        roll_strike, roll_bars = _find_roll_target(
            data.day_chain, opt_type, ist_dt, leg.strike, cfg.roll_target_min_prem, cfg.strike_step
        )
        if roll_strike is None:
            return
        roll_px = price_at(roll_bars, ist_dt, prefer="close")
        if not roll_px:
            return
        close_leg(opt_type, ist_dt, spot, "roll")
        if done:
            return
        nl = Leg(opt_type=opt_type, strike=roll_strike, bars=roll_bars,
                 base_lots=lots, entry_ist=ist_dt, lots=lots)
        nl.total_qty = lots * lot
        nl.total_cost = roll_px * lots * lot
        legs[opt_type] = nl
        comm = commission_fn("SELL", lots * lot * roll_px)
        trades.append(Trade(
            side="SELL", opt_type=opt_type, strike=roll_strike, bar_time=ist_dt, qty=lots * lot,
            price=roll_px, nifty=spot, note=f"roll {lots}L", cum_lots=lots,
            avg_entry=nl.avg_entry, day_pnl=day_pnl, commission_inr=comm,
        ))
        open_hedge(opt_type, ist_dt, spot, lots)  # re-establish protection on the rolled short

    def emit(ist_dt: datetime, spot: float, bias: BiasResult | None, action: str) -> None:
        """Append the every-minute status for this bar (no-op if no trace requested)."""
        if trace is None:
            return
        leg_snaps: list[LegStatus] = []
        for ot in ("PE", "CE"):
            leg = legs.get(ot)
            if leg is not None:
                ltp = price_at(leg.bars, ist_dt, prefer="close")
                leg_snaps.append(LegStatus(
                    opt_type=ot, strike=leg.strike, lots=leg.lots, avg_entry=leg.avg_entry,
                    ltp=ltp, mtm=(leg.mtm(ltp) if ltp is not None else None),
                ))
            hg = hedges.get(ot)
            if hg is not None:
                hltp = price_at(hg.bars, ist_dt, prefer="close")
                leg_snaps.append(LegStatus(
                    opt_type=ot, strike=hg.strike, lots=hg.lots, avg_entry=hg.avg_entry,
                    ltp=hltp,
                    mtm=((hltp - hg.avg_entry) * hg.total_qty if hltp is not None else None),
                    is_hedge=True,
                ))
        trace.append(BarStatus(
            ist_dt=ist_dt, spot=spot,
            score=bias.score if bias else 0.0,
            bucket=bias.bucket.value if bias else "-",
            gated=bias.gated if bias else False,
            reason=bias.reason if bias else action,
            votes=dict(bias.votes) if bias else {},
            pcr=db.bias.pcr, vix_now=db.bias.vix_now,
            legs=leg_snaps, day_pnl=day_pnl, action=action,
        ))

    for db in bars:
        ist_dt, spot = db.ist_dt, db.close

        if ist_dt >= sqoff_dt:
            close_all(ist_dt, db.open, "squareoff")
            emit(ist_dt, spot, None, "squareoff")
            break
        if done:
            emit(ist_dt, spot, None, "halted")
            continue

        # Manage existing legs first (exits can fire any bar once in a position).
        action = "hold"
        if legs:
            n_before = len(trades)
            manage_legs(ist_dt, spot)
            if len(trades) > n_before:
                action = ";".join(t.note for t in trades[n_before:])
            if done:
                emit(ist_dt, spot, None, action)
                continue

        bias: BiasResult = score_bias(db.bias, cfg.weights, _ratio_table(cfg))

        # Adjustment: confirmed bias sign flip vs the open position -> re-enter.
        if legs and cfg.adjustment_on_flip and pos_sign != 0:
            cur_sign = _sign(bias.score)
            if cur_sign != 0 and cur_sign != pos_sign:
                close_all(ist_dt, spot, "trend_flip")
                pos_sign = 0
                emit(ist_dt, spot, bias, "trend_flip")
                continue

        # Entry gate: after the 10:15 1h candle, flat, not VIX-gated.
        if not legs and ist_dt >= entry_after_dt:
            if bias.gated:
                action = "gated"
            elif cfg.neutral_no_trade and bias.bucket is BiasBucket.NEUTRAL:
                action = "neutral_skip"
            else:
                pe_lots, ce_lots = cfg.ratio_for(bias.bucket)
                opened = False
                if pe_lots > 0:
                    opened |= open_leg("PE", ist_dt, spot, pe_lots, bias.bucket,
                                       f"open {pe_lots}PE [{bias.bucket.value}]")
                if ce_lots > 0:
                    opened |= open_leg("CE", ist_dt, spot, ce_lots, bias.bucket,
                                       f"open {ce_lots}CE [{bias.bucket.value}]")
                if opened:
                    pos_sign = _sign(bias.score)
                    action = ";".join(t.note for t in trades if t.bar_time == ist_dt) or "entry"

        emit(ist_dt, spot, bias, action)

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
        nifty_bars=len(bars),
    )


def _ratio_table(cfg: StrangleConfig) -> dict[BiasBucket, tuple[int, int]]:
    return {BiasBucket(k): (int(v[0]), int(v[1])) for k, v in cfg.ratio_table.items()}


def _sign(x: float) -> int:
    return 1 if x > 0 else (-1 if x < 0 else 0)


def _find_roll_target(
    day_chain: dict[str, dict[float, list]],
    opt_type: str,
    ist_dt: datetime,
    current_strike: float,
    min_prem: float,
    step: int,
) -> tuple[float | None, list]:
    """Furthest-OTM same-side strike (skipping the held one) with premium > ``min_prem``."""
    side = day_chain.get(opt_type.upper(), {})
    ordered = sorted(side.keys(), reverse=(opt_type.upper() == "CE"))
    for stk in ordered:
        if stk == current_strike:
            continue
        sbars: list[Bar] = side.get(stk, [])
        prem = price_at(sbars, ist_dt, prefer="close") if sbars else None
        if prem is not None and prem > min_prem:
            return stk, sbars
    return None, []
