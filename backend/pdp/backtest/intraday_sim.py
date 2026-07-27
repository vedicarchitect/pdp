"""Intraday directional option-selling engine (pure per-day replay).

``simulate_intraday_day(cfg, data)`` replays one trade day and returns a ``DayResult``.
It is pure with respect to I/O — all market data arrives via ``IntradayDayData`` — so it
is unit-testable without a DB.

Every entry, scale-in, exit and rollup **decision** is delegated to
``pdp.signals.intraday_directional``; this module only executes those decisions against
the option chain and keeps the books. The live strategy calls the same core with the same
parameters, so the two paths cannot drift on logic — only on the data they are fed.

Results reuse ``pdp.backtest.sim``'s ``DayResult``/``Trade``/``LegRecord`` verbatim, so
the existing warehouse (``RunWriter``, ``BacktestStore``, ``aggregate``) and the
verdict/metric definitions apply unchanged — which is what makes a run here directly
comparable with a directional-strangle run over the same window.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime

from pdp.backtest.intraday_config import IntradayDirectionalConfig
from pdp.backtest.intraday_loader import IntradayDayData
from pdp.backtest.sim import (
    CommissionFn,
    DayResult,
    LegRecord,
    Trade,
    last_price,
    price_at,
    resolve_from_chain,
    select_strike,
)
from pdp.signals.intraday_directional import (
    EntryBlock,
    ExitReason,
    IntradayInputs,
    IntradayState,
    Side,
    evaluate_entry,
    evaluate_exit,
    evaluate_rollup,
    evaluate_scale_in,
    rollup_target_acceptable,
    unrealized_pnl,
    update_sustained_trackers,
)

__all__ = ["IntradayBarStatus", "simulate_intraday_day"]

# Nearest-strike resolution half-width, in strike steps. Matches the strangle engine so
# both make the same substitution when an exact strike has no bars.
_STRIKE_BAND = 2

# Worthless-expiry fallback when a strike never traded. Matches the strangle engine.
_WORTHLESS_PX = 0.01

# Map an ExitReason onto the shared decision-trace sub-reason vocabulary.
_EXIT_SUB: dict[ExitReason, str] = {
    ExitReason.DAY_LOSS_CAP: "day_loss_cap",
    ExitReason.SQUARE_OFF: "squareoff",
    ExitReason.UNREAL_LOSS_STOP: "stop_all",
    ExitReason.PREMIUM_RISE_STOP: "stop_all",
    ExitReason.UNDERLYING_ST_FLIP: "flip",
    ExitReason.OPTION_ST_FLIP: "flip",
    ExitReason.EMA20_BREAK_SUSTAINED: "flip",
    ExitReason.CAM_REJECTION_SUSTAINED: "flip",
}


def _zero_commission(_side: str, _turnover: float) -> float:
    return 0.0


def _sub_for(reason: str) -> str:
    """Map an exit reason onto the warehouse's shared sub-reason vocabulary."""
    try:
        return _EXIT_SUB[ExitReason(reason)]
    except ValueError:
        return reason


@dataclass(slots=True)
class IntradayBarStatus:
    """Per-bar trace row (opt-in), for monitor-style every-bar logging."""

    ist_dt: datetime
    spot: float
    side: str | None
    strike: float | None
    lots: int
    avg_entry: float
    ltp: float | None
    day_pnl: float
    session_vwap: float | None
    orb_high: float | None
    orb_low: float | None
    st_dir: int | None
    option_st_dir: int | None
    ema_break_bars: int
    cam_reject_bars: int
    action: str

    # ---- Forensic detail (EOD walkthrough report) --------------------------- #
    # All optional/defaulted — `format_status_line` and every existing consumer are
    # unaffected. The core already computes each of these and then dropped them.
    #
    # The full input set by reference (5m + 15m EMA pairs and their previous values,
    # st_15m_dir, Camarilla, bar high/low, the ATM-option VWAP read) rather than a
    # dozen re-flattened scalars that could drift from what the core actually saw.
    inputs: IntradayInputs | None = None
    # Per-side entry-condition map from `evaluate_entry` — {"PE"/"CE": {orb, vwap,
    # supertrend, ema} -> bool}. This is the single most useful thing the engine knew
    # and threw away: without it "no entry" is unexplainable after the fact.
    entry_conditions: dict[str, dict[str, bool]] = field(default_factory=dict)
    # Which session/state gate blocked before conditions were even evaluated
    # (`EntryBlock`: before_entry_window, reentry_cooloff, already_positioned, ...).
    entry_block: str | None = None
    # The winning `ExitSignal.detail` string when this bar exited — the numbers behind
    # the rule (e.g. the level breached and by how much), not just the rule's name.
    exit_detail: str = ""
    # Protective long attached to the short, if any.
    hedge_strike: float | None = None
    hedge_lots: int = 0
    # Session bookkeeping: rollups used so far, and minutes left on the re-entry
    # cool-off (0 when clear, None when no exit has happened yet).
    rolls_today: int = 0
    cooloff_left_min: int | None = None
    # Open-position MTM at this bar; `day_pnl` above is realised only.
    unrealized: float = 0.0
    done_reason: str = ""


@dataclass(slots=True)
class _OpenLeg:
    """The single directional short, plus its optional protective hedge."""

    opt_type: str
    strike: float
    bars: list
    lots: int
    entry_ist: datetime
    hedge_strike: float | None = None
    hedge_bars: list | None = None
    hedge_lots: int = 0
    hedge_cost: float = 0.0


def simulate_intraday_day(
    cfg: IntradayDirectionalConfig,
    data: IntradayDayData,
    commission_fn: CommissionFn | None = None,
    trace: list[IntradayBarStatus] | None = None,
    decisions: list[dict] | None = None,
) -> DayResult | None:
    """Replay one trade day. Returns a ``DayResult``, or ``None`` when the day has no bars.

    ``trace`` collects a status row per decision bar (bounded by bars — opt in).
    ``decisions`` collects why-entry/why-exit events using the warehouse's shared
    vocabulary (bounded by decisions — safe to leave on for every run).
    """
    commission_fn = commission_fn or _zero_commission
    bars = data.decision_bars
    if not bars:
        return None

    params = cfg.to_params()
    lot = cfg.lot_size
    td = data.trade_date
    state = IntradayState()

    leg: _OpenLeg | None = None
    trades: list[Trade] = []
    leg_records: list[LegRecord] = []
    day_pnl = 0.0
    done_reason = ""

    def log_decision(
        ist_dt: datetime,
        spot: float,
        event: str,
        *,
        action: str,
        sub_reason: str | None = None,
        extra: dict | None = None,
    ) -> None:
        if decisions is None:
            return
        leg_snap = (
            [{
                "opt_type": leg.opt_type,
                "strike": leg.strike,
                "lots": leg.lots,
                "avg_entry": state.avg_entry,
            }]
            if leg is not None
            else []
        )
        snapshot: dict = {"spot": spot, "day_pnl": day_pnl, "legs": leg_snap}
        if extra:
            snapshot.update(extra)
        decisions.append({
            "ts_ist": ist_dt,
            "date": td.isoformat(),
            "event": event,
            "sub_reason": sub_reason,
            "action": action,
            "snapshot": snapshot,
        })

    # ---------------------------------------------------------------- pricing --
    def option_px(sbars: list, ist_dt: datetime) -> float | None:
        return price_at(sbars, ist_dt, prefer="close")

    def close_px_for(sbars: list, ist_dt: datetime) -> float:
        """Exit price with the same fallbacks the strangle engine uses: last traded
        price for a strike that stopped trading, else worthless."""
        px = price_at(sbars, ist_dt, prefer="close")
        if px is None:
            px = last_price(sbars, ist_dt) or _WORTHLESS_PX
        return px

    def resolve_strike(opt_type: str, spot: float, moneyness: int) -> tuple[float | None, list]:
        target = float(select_strike(spot, opt_type, moneyness, cfg.strike_step))
        return resolve_from_chain(data.day_chain, opt_type, target, cfg.strike_step,
                                  band=_STRIKE_BAND)

    def select_hedge(opt_type: str, ist_dt: datetime) -> tuple[float | None, list]:
        """Furthest-OTM same-side strike priced inside the hedge band; else the
        cheapest available."""
        side_chain = data.day_chain.get(opt_type.upper(), {})
        ordered = sorted(side_chain.keys(), reverse=(opt_type.upper() == "CE"))
        cheapest: tuple[float, list] | None = None
        cheapest_px = float("inf")
        for stk in ordered:
            sbars = side_chain.get(stk, [])
            if not sbars:
                continue
            px = option_px(sbars, ist_dt)
            if px is None or px <= 0:
                continue
            if px < cheapest_px:
                cheapest_px, cheapest = px, (stk, sbars)
            if cfg.hedge_prem_min <= px <= cfg.hedge_prem_max:
                return stk, sbars
        return cheapest if cheapest is not None else (None, [])

    # ------------------------------------------------------------------ opens --
    def open_hedge(opt_type: str, ist_dt: datetime, spot: float, lots: int) -> None:
        if not cfg.hedge_enabled or leg is None or lots <= 0:
            return
        stk, hbars = select_hedge(opt_type, ist_dt)
        if stk is None or not hbars:
            return
        px = option_px(hbars, ist_dt)
        if px is None:
            return
        qty = lots * lot
        leg.hedge_strike = stk
        leg.hedge_bars = hbars
        leg.hedge_lots = lots
        leg.hedge_cost = px * qty
        trades.append(Trade(
            side="BUY", opt_type=opt_type, strike=stk, bar_time=ist_dt, qty=qty,
            price=px, nifty=spot, note=f"hedge {lots}{opt_type}", cum_lots=lots,
            avg_entry=px, day_pnl=day_pnl, commission_inr=commission_fn("BUY", qty * px),
        ))

    def close_hedge(ist_dt: datetime, spot: float, reason: str) -> None:
        nonlocal day_pnl
        if leg is None or leg.hedge_bars is None or leg.hedge_lots <= 0:
            return
        qty = leg.hedge_lots * lot
        px = close_px_for(leg.hedge_bars, ist_dt)
        entry_px = leg.hedge_cost / qty if qty else 0.0
        hedge_pnl = (px - entry_px) * qty          # long: exit - entry
        day_pnl += hedge_pnl
        trades.append(Trade(
            side="SELL", opt_type=leg.opt_type, strike=leg.hedge_strike or 0.0,
            bar_time=ist_dt, qty=qty, price=px, nifty=spot, note=f"hedge_exit {reason}",
            cum_lots=0, avg_entry=entry_px, leg_pnl=hedge_pnl, day_pnl=day_pnl,
            commission_inr=commission_fn("SELL", qty * px),
        ))
        leg.hedge_bars = None
        leg.hedge_lots = 0
        leg.hedge_cost = 0.0
        leg.hedge_strike = None

    def open_position(
        side: Side, ist_dt: datetime, spot: float, lots: int, note: str,
        *, event: str, sub_reason: str | None = None,
    ) -> bool:
        nonlocal leg
        stk, sbars = resolve_strike(side.value, spot, cfg.moneyness)
        if stk is None or not sbars:
            return False
        px = option_px(sbars, ist_dt)
        if not px:
            return False
        leg = _OpenLeg(opt_type=side.value, strike=stk, bars=sbars, lots=lots,
                       entry_ist=ist_dt)
        opt_st = _option_st(ist_dt)
        state.on_open(side, lots, px, stk, ist_dt, option_st_dir=opt_st)
        qty = lots * lot
        trades.append(Trade(
            side="SELL", opt_type=side.value, strike=stk, bar_time=ist_dt, qty=qty,
            price=px, nifty=spot, note=note, cum_lots=lots, avg_entry=px,
            day_pnl=day_pnl, commission_inr=commission_fn("SELL", qty * px),
        ))
        log_decision(ist_dt, spot, event, action=note, sub_reason=sub_reason,
                     extra={"opt_type": side.value, "strike": stk, "lots": lots})
        open_hedge(side.value, ist_dt, spot, lots)
        return True

    def scale_position(ist_dt: datetime, spot: float, add_lots: int) -> bool:
        if leg is None:
            return False
        px = option_px(leg.bars, ist_dt)
        if not px:
            return False
        state.on_scale(add_lots, px, ist_dt)
        leg.lots = state.lots
        qty = add_lots * lot
        trades.append(Trade(
            side="SELL", opt_type=leg.opt_type, strike=leg.strike, bar_time=ist_dt,
            qty=qty, price=px, nifty=spot, note=f"scale_in {add_lots}", cum_lots=state.lots,
            avg_entry=state.avg_entry, day_pnl=day_pnl,
            commission_inr=commission_fn("SELL", qty * px),
        ))
        log_decision(ist_dt, spot, "scale_in", action="ladder",
                     extra={"opt_type": leg.opt_type, "added_lots": add_lots,
                            "lots": state.lots})
        return True

    # ----------------------------------------------------------------- closes --
    def close_position(ist_dt: datetime, spot: float, reason: str,
                       *, log: bool = True) -> float:
        """Close the short (and its hedge) and book the P&L. Returns the leg's P&L."""
        nonlocal leg, day_pnl, done_reason
        if leg is None:
            return 0.0
        # Close the hedge first so its P&L is in day_pnl before any cap evaluation.
        close_hedge(ist_dt, spot, reason)
        px = close_px_for(leg.bars, ist_dt)
        qty = leg.lots * lot
        avg_entry = state.avg_entry
        leg_pnl = (avg_entry - px) * qty
        day_pnl += leg_pnl
        trades.append(Trade(
            side="BUY", opt_type=leg.opt_type, strike=leg.strike, bar_time=ist_dt,
            qty=qty, price=px, nifty=spot, note=reason, cum_lots=0, avg_entry=avg_entry,
            leg_pnl=leg_pnl, day_pnl=day_pnl, commission_inr=commission_fn("BUY", qty * px),
        ))
        leg_records.append(LegRecord(
            opt_type=leg.opt_type, strike=leg.strike, entry_ist=leg.entry_ist,
            exit_ist=ist_dt, lots=leg.lots, avg_entry=avg_entry, exit_px=px,
            leg_pnl=leg_pnl, reason=reason,
        ))
        if log:
            log_decision(ist_dt, spot, "exit", action=reason, sub_reason=_sub_for(reason),
                         extra={"opt_type": leg.opt_type, "leg_pnl": leg_pnl})
        leg = None
        return leg_pnl

    # ------------------------------------------------------------------ rolls --
    def try_roll(ist_dt: datetime, spot: float, ltp: float) -> bool:
        """Roll the decayed short back to ATM — all-or-nothing.

        Every precondition (a resolvable ATM strike priced at or above
        ``roll_target_min_prem``) is verified BEFORE the existing leg is closed, so a
        roll that cannot reopen leaves the position exactly as it was rather than
        leaving the day flat. This mirrors the live path's `_roll_leg` discipline.
        """
        nonlocal leg
        if leg is None:
            return False
        old_strike = leg.strike
        old_lots = leg.lots
        opt_type = leg.opt_type

        new_strike, new_bars = resolve_strike(opt_type, spot, 0)  # 0 == ATM
        if new_strike is None or not new_bars or new_strike == old_strike:
            log_decision(ist_dt, spot, "rollup", action="skipped_no_target",
                         sub_reason="premium_decay",
                         extra={"opt_type": opt_type, "old_strike": old_strike})
            return False
        new_px = option_px(new_bars, ist_dt)
        if new_px is None or not rollup_target_acceptable(new_px, params):
            log_decision(ist_dt, spot, "rollup", action="skipped_low_prem",
                         sub_reason="premium_decay",
                         extra={"opt_type": opt_type, "old_strike": old_strike,
                                "new_strike": new_strike, "new_ltp": new_px})
            return False

        # Preconditions satisfied — only now mutate the book. `close_position` does not
        # touch `state`, so side/lots survive the close and the roll stays one position.
        close_position(ist_dt, spot, "roll", log=False)
        leg = _OpenLeg(opt_type=opt_type, strike=new_strike, bars=new_bars,
                       lots=old_lots, entry_ist=ist_dt)
        state.on_roll(new_strike, new_px, ist_dt, option_st_dir=_option_st(ist_dt))
        qty = old_lots * lot
        trades.append(Trade(
            side="SELL", opt_type=opt_type, strike=new_strike, bar_time=ist_dt, qty=qty,
            price=new_px, nifty=spot, note="rollup_atm", cum_lots=old_lots,
            avg_entry=new_px, day_pnl=day_pnl,
            commission_inr=commission_fn("SELL", qty * new_px),
        ))
        log_decision(ist_dt, spot, "rollup", action="rollup_atm",
                     sub_reason="premium_decay",
                     extra={"opt_type": opt_type, "old_strike": old_strike,
                            "old_ltp": ltp, "new_strike": new_strike, "new_ltp": new_px,
                            "lots": old_lots, "rolls_today": state.rolls_today})
        open_hedge(opt_type, ist_dt, spot, old_lots)
        return True

    def _option_st(ist_dt: datetime) -> int | None:
        if not cfg.option_st_enabled or leg is None:
            return None
        return data.option_trend.direction_at(leg.opt_type, leg.strike, ist_dt)

    def _cooloff_left_min(ist_dt: datetime) -> int | None:
        """Whole minutes remaining on the post-exit re-entry cool-off (0 = clear)."""
        if state.last_exit_ist is None or params.reentry_cooloff_minutes <= 0:
            return None
        elapsed = (ist_dt - state.last_exit_ist).total_seconds() / 60.0
        return max(0, int(params.reentry_cooloff_minutes - elapsed))

    # ------------------------------------------------------------- replay loop --
    for bar in bars:
        ist_dt = bar.ist_dt
        spot = bar.close
        action = "hold"
        # Per-bar forensic detail, filled in by whichever branch runs below.
        bar_conds: dict[str, dict[str, bool]] = {}
        bar_block: EntryBlock | None = None

        # Enrich the pre-assembled inputs with the held strike's own SuperTrend.
        inp = replace(bar.inputs, option_st_dir=_option_st(ist_dt))
        ltp = option_px(leg.bars, ist_dt) if leg is not None else None

        # 1. Sustained-condition trackers advance exactly once per bar, before exits.
        update_sustained_trackers(inp, params, state)

        # 2. Exits take precedence over anything that would add risk. The day cap sees
        # realised P&L *plus* the open leg's MTM, otherwise it could never fire while
        # positioned — which is the only time it matters.
        total_pnl = day_pnl + unrealized_pnl(state, ltp, lot) if ltp is not None else day_pnl
        exit_sig = evaluate_exit(inp, params, state, ltp=ltp, day_pnl=total_pnl)
        if exit_sig is not None:
            if leg is not None:
                close_position(ist_dt, spot, exit_sig.reason.value)
            state.on_exit(ist_dt, exit_sig.reason)
            action = f"exit:{exit_sig.reason.value}"
            if exit_sig.reason in (ExitReason.DAY_LOSS_CAP, ExitReason.SQUARE_OFF):
                # `done_reason` marks an *abnormal* end so `aggregate()`'s "halted"
                # count means the same thing here as in the strangle engine. A normal
                # square-off is not a halt and must leave it empty, or every day would
                # be counted as halted and the two strategies stop being comparable.
                if exit_sig.reason is ExitReason.DAY_LOSS_CAP:
                    done_reason = f"day_loss ({day_pnl:+.0f})"
                _emit(trace, ist_dt, spot, inp, state, leg, ltp, day_pnl, action,
                      option_st=_option_st(ist_dt), lot=lot, exit_detail=exit_sig.detail,
                      cooloff_left_min=_cooloff_left_min(ist_dt), done_reason=done_reason)
                break
            _emit(trace, ist_dt, spot, inp, state, leg, ltp, day_pnl, action,
                  lot=lot, exit_detail=exit_sig.detail,
                  cooloff_left_min=_cooloff_left_min(ist_dt), done_reason=done_reason)
            continue

        # 3. Rollup to ATM on premium decay.
        if leg is not None:
            roll_sig = evaluate_rollup(params, state, ltp=ltp, now_ist=ist_dt)
            if roll_sig is not None and try_roll(ist_dt, spot, roll_sig.trigger_ltp):
                action = "rollup_atm"
                _emit(trace, ist_dt, spot, inp, state, leg, ltp, day_pnl, action,
                      option_st=_option_st(ist_dt), lot=lot,
                      cooloff_left_min=_cooloff_left_min(ist_dt), done_reason=done_reason)
                continue

        # 4. Scale-in ladder.
        if leg is not None:
            scale_sig = evaluate_scale_in(inp, params, state)
            if scale_sig is not None and scale_position(ist_dt, spot, scale_sig.lots):
                action = f"scale_in:{scale_sig.lots}"

        # 5. Entry / re-entry.
        if leg is None:
            sig, block, conds = evaluate_entry(inp, params, state)
            # Keep the per-side condition map and the block reason for the trace: this is
            # the only record of *why* a bar didn't enter, and re-deriving it after the
            # fact is impossible once the bar's inputs are gone.
            bar_conds, bar_block = conds, block
            if sig is not None:
                is_reentry = state.last_exit_ist is not None
                opened = open_position(
                    sig.side, ist_dt, spot, sig.lots,
                    note=f"{'reentry' if is_reentry else 'entry'} {sig.lots}{sig.side.value}",
                    event="reentry" if is_reentry else "entry",
                    sub_reason="cooloff" if is_reentry else None,
                )
                action = f"open:{sig.side.value}" if opened else "open_failed"
            elif block is EntryBlock.CONDITIONS_UNMET:
                action = "hold"

        _emit(trace, ist_dt, spot, inp, state, leg, ltp, day_pnl, action,
              option_st=_option_st(ist_dt), lot=lot,
              entry_conditions=bar_conds, entry_block=bar_block,
              cooloff_left_min=_cooloff_left_min(ist_dt), done_reason=done_reason)

    # Anything still open at the end of the series is squared off on the last bar.
    if leg is not None:
        last = bars[-1]
        close_position(last.ist_dt, data.spot_close, "squareoff_end")
        state.on_exit(last.ist_dt, ExitReason.SQUARE_OFF)

    commission_total = sum(t.commission_inr for t in trades)
    return DayResult(
        date=td.isoformat(),
        expiry=data.expiry_date.isoformat(),
        nifty_open=data.spot_open,
        nifty_close=data.spot_close,
        nifty_chg=data.spot_close - data.spot_open,
        trades=trades,
        leg_records=leg_records,
        gross_pnl=day_pnl,
        commission=commission_total,
        realized=day_pnl - commission_total,
        done_reason=done_reason,
        nifty_bars=len(bars),
    )


def _emit(
    trace: list[IntradayBarStatus] | None,
    ist_dt: datetime,
    spot: float,
    inp: IntradayInputs,
    state: IntradayState,
    leg: _OpenLeg | None,
    ltp: float | None,
    day_pnl: float,
    action: str,
    option_st: int | None = None,
    *,
    lot: int = 0,
    entry_conditions: dict[str, dict[str, bool]] | None = None,
    entry_block: EntryBlock | None = None,
    exit_detail: str = "",
    cooloff_left_min: int | None = None,
    done_reason: str = "",
) -> None:
    """Record the bar's status *after* the action, so the row reflects the resulting
    position rather than the pre-decision snapshot."""
    if trace is None:
        return
    trace.append(IntradayBarStatus(
        ist_dt=ist_dt,
        spot=spot,
        side=state.side.value if state.side else None,
        strike=leg.strike if leg is not None else None,
        lots=state.lots,
        avg_entry=state.avg_entry,
        ltp=ltp,
        day_pnl=day_pnl,
        session_vwap=inp.session_vwap,
        orb_high=inp.orb_high,
        orb_low=inp.orb_low,
        st_dir=inp.st_5m_dir,
        option_st_dir=option_st if option_st is not None else inp.option_st_dir,
        ema_break_bars=state.ema_break_bars,
        cam_reject_bars=state.cam_reject_bars,
        action=action,
        inputs=inp,
        entry_conditions=entry_conditions or {},
        entry_block=entry_block.value if entry_block is not None else None,
        exit_detail=exit_detail,
        hedge_strike=leg.hedge_strike if leg is not None else None,
        hedge_lots=leg.hedge_lots if leg is not None else 0,
        rolls_today=state.rolls_today,
        cooloff_left_min=cooloff_left_min,
        unrealized=(unrealized_pnl(state, ltp, lot) if (ltp is not None and lot) else 0.0),
        done_reason=done_reason,
    ))
