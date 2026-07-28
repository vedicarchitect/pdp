"""Intraday directional option-selling strategy (live/paper).

Sells a PE in an uptrend / a CE in a downtrend, gated on the opening range, session
VWAP, SuperTrend(10,2) and EMA9/20 alignment; sizes with a 15-minute 3→6→9 lot ladder;
exits on eight rules; rolls a decayed leg back to ATM.

Every decision is delegated to ``pdp.signals.intraday_directional`` — the same pure core
``pdp.backtest.intraday_sim`` calls — so live and backtest cannot disagree on logic. This
module owns only I/O: reading indicators, resolving strikes, placing and reconciling
orders, and persisting leg state.

Indicator inputs are **consumed, never recomputed** (rule #4):
  * EMA 9/20            -> ``ctx.indicators.ema(sid, tf).values``
  * SuperTrend(10,2)    -> ``ctx.indicators.supertrend_variants(sid, tf)["st_10_2"]``
    (NOT ``ctx.indicators.supertrend()``, which is the engine-wide SUPERTREND_PERIOD)
  * Camarilla S3/S4/R3/R4 -> ``ctx.indicators.pivots(sid, "1D")``
  * Opening range       -> the 15m bar stamped 09:15 IST, tracked here (no such family)
  * Session VWAP        -> accumulated here from 1m bars (the spot index has no volume,
    so ``VWAPTracker`` can never converge on it)
  * Option-chart ST     -> ``atm_suite.option_trend_read`` over the held strike's bars

Leg-lifecycle invariants inherited from live incidents (see `pdp/strategies/CLAUDE.md`):
one leg per security via ``_add_leg``/``_remove_leg``; a per-sid lock across every
broker read-modify-write; close side derived from the broker's net_qty sign, never the
leg's kind; never close more lots than the broker holds; durable leg identity in
``strategy_leg``; shared fill confirmation via ``pdp.strategy.fills``; a per-sid lot cap
inside the lock; and unattended reconciliation on a timer.
"""
from __future__ import annotations

import asyncio
import collections
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from pdp.instruments.expiry_calendar import within_dte
from pdp.signals.intraday_directional import (
    VWAP_OFF,
    VWAP_SESSION_TWAP,
    VWAP_SOURCES,
    CamLevels,
    ExitReason,
    IntradayInputs,
    IntradayParams,
    IntradayState,
    Side,
    evaluate_entry,
    evaluate_exit,
    evaluate_price_exit,
    evaluate_rollup,
    evaluate_scale_in,
    rollup_target_acceptable,
    unrealized_pnl,
    update_sustained_trackers,
)
from pdp.strategy import fills
from pdp.strategy.abc import Strategy
from pdp.strategy.context import StrategyContext
from pdp.strategy.log import IntradayEventType
from pdp.strategy.readiness import ReadinessComponent, StrategyReadiness
from pdp.strategy.strikes import (
    STRIKE_STEP,
    lot_size_for_underlying,
    nearest_expiry,
    resolve_otm_option,
)

_IST = ZoneInfo("Asia/Kolkata")
_ACTIVITY_MAX = 200


def _parse_hhmm(value: Any, default: str) -> Any:
    from datetime import time as _time

    raw = str(value or default)
    hh, mm = raw.split(":")
    return _time(int(hh), int(mm))


@dataclass
class LiveLeg:
    """One open option position. ``kind`` is durable — a broker net_qty sign alone
    cannot distinguish a long hedge from anything else."""

    security_id: str
    segment: str
    opt_type: str
    strike: float
    lots: int
    entry_price: Decimal
    entry_time: datetime
    kind: str = "short"          # "short" | "hedge"
    expiry: date | None = None

    @property
    def is_hedge(self) -> bool:
        return self.kind == "hedge"


def params_from_config(p: dict) -> IntradayParams:
    """Build the shared core's parameters from a strategy YAML ``params`` block.

    Module-level so a config check can construct the same parameters the running
    strategy will use, without instantiating it — and so defaults live in exactly one
    place (``IntradayParams``), never duplicated here.
    """
    d = IntradayParams()
    return IntradayParams(
        timeframe_min=int(p.get("timeframe_min", d.timeframe_min)),
        confirm_timeframe_min=int(p.get("confirm_timeframe_min", d.confirm_timeframe_min)),
        entry_after_ist=_parse_hhmm(p.get("entry_after_ist"), "09:30"),
        squareoff_ist=_parse_hhmm(p.get("squareoff_ist"), "15:15"),
        initial_lots=int(p.get("initial_lots", d.initial_lots)),
        scale_lots_step=int(p.get("scale_lots_step", d.scale_lots_step)),
        max_lots=int(p.get("max_lots", d.max_lots)),
        scale_in_minutes=int(p.get("scale_in_minutes", d.scale_in_minutes)),
        reentry_cooloff_minutes=int(
            p.get("reentry_cooloff_minutes", d.reentry_cooloff_minutes)
        ),
        day_loss_limit=float(p.get("day_loss_limit", d.day_loss_limit)),
        premium_rise_stop_pct=float(p.get("premium_rise_stop_pct", d.premium_rise_stop_pct)),
        unreal_loss_pct=float(p.get("unreal_loss_pct", d.unreal_loss_pct)),
        ema_break_bars=int(p.get("ema_break_bars", d.ema_break_bars)),
        cam_reject_minutes=int(p.get("cam_reject_minutes", d.cam_reject_minutes)),
        cam_touch_eps=float(p.get("cam_touch_eps", d.cam_touch_eps)),
        roll_enabled=bool(p.get("roll_enabled", d.roll_enabled)),
        roll_trigger_prem=float(p.get("roll_trigger_prem", d.roll_trigger_prem)),
        roll_target_min_prem=float(p.get("roll_target_min_prem", d.roll_target_min_prem)),
        max_rolls_per_day=int(p.get("max_rolls_per_day", d.max_rolls_per_day)),
        roll_cutoff_ist=_parse_hhmm(p.get("roll_cutoff_ist"), "14:45"),
        require_15m_confirm=bool(p.get("require_15m_confirm", d.require_15m_confirm)),
        atm_option_vwap_gate=bool(p.get("atm_option_vwap_gate", d.atm_option_vwap_gate)),
    )


class IntradayDirectional(Strategy):
    """Live/paper intraday directional option seller."""

    # ------------------------------------------------------------------ #
    # Lifecycle                                                           #
    # ------------------------------------------------------------------ #

    async def on_init(self, ctx: StrategyContext) -> None:
        self.ctx = ctx
        p = self.params

        self.underlying: str = str(p.get("underlying", "NIFTY"))
        self.sid: str = str(p.get("underlying_security_id", "13"))
        self.index_segment: str = str(p.get("index_segment", "IDX_I"))
        self.option_segment: str = str(p.get("option_segment", "NSE_FNO"))

        self._params: IntradayParams = params_from_config(p)
        self._params.validate()

        self._strike_step: int = int(
            p.get("strike_step", STRIKE_STEP.get(self.underlying, 50))
        )
        self._moneyness: int = int(p.get("moneyness", 0))
        self._dte_max: int | None = p.get("dte_max", 6)
        self._orb_start = _parse_hhmm(p.get("orb_start_ist"), "09:15")
        self._orb_minutes: int = int(p.get("orb_minutes", 15))
        # Clock at which the opening range has finished forming and may be consulted.
        self._orb_ready_at = (
            datetime.combine(date(2000, 1, 1), self._orb_start)
            + timedelta(minutes=self._orb_minutes)
        ).time()
        self._option_st_enabled: bool = bool(p.get("option_st_enabled", True))
        # Honoured here as well as in the backtest config so the two paths cannot disagree
        # on what a config means. Note that VWAP is a mandatory AND condition in
        # `entry_conditions`, so `off` leaves `session_vwap=None` and therefore blocks
        # every entry — it is a kill switch, not a "skip this gate" toggle.
        self._vwap_source: str = str(p.get("vwap_source", VWAP_SESSION_TWAP))
        if self._vwap_source not in VWAP_SOURCES:
            raise ValueError(
                f"vwap_source must be one of {VWAP_SOURCES}, got {self._vwap_source!r}"
            )
        self._hedge_enabled: bool = bool(p.get("hedge_enabled", False))
        self._hedge_prem_min: float = float(p.get("hedge_prem_min", 2.0))
        self._hedge_prem_max: float = float(p.get("hedge_prem_max", 5.0))
        self._hedge_scan_start: int = int(p.get("hedge_scan_start", 10))
        self._hedge_scan_end: int = int(p.get("hedge_scan_end", 22))
        self._entry_ltp_wait_s: float = float(p.get("entry_ltp_wait_s", 2.0))
        self._reconcile_interval_s: float = float(p.get("reconcile_interval_s", 60.0))

        # Lot size: the instruments table is authoritative; YAML is advisory only.
        self._lot_size_yaml: int | None = (
            int(p["lot_size"]) if p.get("lot_size") is not None else None
        )
        self._lot_size: int = self._lot_size_yaml or 75
        self._lot_size_day: date | None = None
        self._lot_size_degraded: bool = False

        # --- position state -------------------------------------------------
        self._legs: dict[str, LiveLeg] = {}
        self._leg_locks: dict[str, asyncio.Lock] = {}
        self._ltp_cache: dict[str, float] = {}
        self._subscribed_option_sids: set[str] = set()
        self._core = IntradayState()
        self._rolling: set[str] = set()

        # --- session state --------------------------------------------------
        self._day_key: date | None = None
        self._halt_checked: bool = False
        self._done_for_day: bool = False
        self._orb_high: float | None = None
        self._orb_low: float | None = None
        self._orb_unseeded: bool = False
        self._vwap_sum: float = 0.0
        self._vwap_n: int = 0
        self._prev_ema: tuple[float | None, float | None] = (None, None)
        # (bar stamp, ema9, ema20, st_dir) per closed confirmation-timeframe bar.
        self._conf_snaps: list[tuple[datetime, float | None, float | None, int | None]] = []
        self._day_baseline: dict[str, Decimal] = {}
        self._touched_sids: set[str] = set()
        self._last_spot: float | None = None
        self._activity: collections.deque = collections.deque(maxlen=_ACTIVITY_MAX)
        self._expiry: date | None = None

        if ctx.market is not None:
            await ctx.market.subscribe(self.sid, self.index_segment)

        await self._rehydrate_legs()
        self._reconcile_task = asyncio.create_task(self._reconcile_loop())

        ctx.log.info(
            "intraday_directional_init",
            underlying=self.underlying,
            moneyness=self._moneyness,
            lots=f"{self._params.initial_lots}->{self._params.max_lots}",
            dte_max=self._dte_max,
            day_loss_limit=self._params.day_loss_limit,
            roll=self._params.roll_enabled,
            hedge=self._hedge_enabled,
        )

    async def on_shutdown(self) -> None:
        task = getattr(self, "_reconcile_task", None)
        if task is not None:
            task.cancel()

    # ------------------------------------------------------------------ #
    # Leg bookkeeping (invariant 1)                                       #
    # ------------------------------------------------------------------ #

    def _add_leg(self, leg: LiveLeg) -> None:
        """Register a leg. Refuses a duplicate security_id rather than letting two leg
        records track one broker position."""
        if leg.security_id in self._legs:
            from pdp.events.models import EventType

            self.ctx.emit_critical(
                EventType.LEG_STATE_DIVERGED,
                leg.security_id,
                "Duplicate leg refused",
                f"{leg.security_id} already tracked as "
                f"{self._legs[leg.security_id].kind}; refusing to add a second record",
                {"strategy_id": self.strategy_id},
            )
            raise ValueError(f"duplicate leg for {leg.security_id}")
        self._legs[leg.security_id] = leg

    def _remove_leg(self, sid: str) -> None:
        self._legs.pop(sid, None)
        self._ltp_cache.pop(sid, None)

    @property
    def _short_leg(self) -> LiveLeg | None:
        for leg in self._legs.values():
            if leg.kind == "short":
                return leg
        return None

    @property
    def _hedge_leg(self) -> LiveLeg | None:
        for leg in self._legs.values():
            if leg.kind == "hedge":
                return leg
        return None

    def _lock_for(self, sid: str) -> asyncio.Lock:
        """Per-sid lock guarding every broker read-modify-write on that security, held
        by both the open and the close path. Not re-entrant — a roll must release its
        claim before calling close/open."""
        lock = self._leg_locks.get(sid)
        if lock is None:
            lock = asyncio.Lock()
            self._leg_locks[sid] = lock
        return lock

    # ------------------------------------------------------------------ #
    # Bars                                                                #
    # ------------------------------------------------------------------ #

    async def on_bar(self, bar: Any) -> None:
        if bar.security_id != self.sid:
            return
        ist = bar.bar_time.astimezone(_IST)
        bar_day = ist.date()
        self._maybe_reset_day(bar_day)
        await self._maybe_resolve_lot_size(bar_day)
        if not self._halt_checked:
            await self._maybe_restore_halt_marker()
            self._halt_checked = True

        tf = bar.timeframe
        # Session VWAP proxy accumulates on 1m closes — the same series and the same
        # arithmetic the backtest loader uses, so both paths agree bar for bar.
        if tf == "1m":
            if self._vwap_source != VWAP_OFF:
                self._vwap_sum += (
                    float(bar.high) + float(bar.low) + float(bar.close)
                ) / 3.0
                self._vwap_n += 1
            return

        conf_tf = f"{self._params.confirm_timeframe_min}m"
        if tf == conf_tf:
            self._maybe_capture_orb(ist, bar)
            self._snapshot_confirmation(ist, conf_tf)
            return

        if tf != f"{self._params.timeframe_min}m":
            return

        spot = float(bar.close)
        self._last_spot = spot
        if self._done_for_day:
            return

        inp = await self._build_inputs(ist, bar, spot)

        # Trackers advance exactly once per decision bar, before exits are evaluated.
        update_sustained_trackers(inp, self._params, self._core)

        ltp = self._short_ltp()
        day_pnl = await self._day_pnl(ltp)

        exit_sig = evaluate_exit(inp, self._params, self._core, ltp=ltp, day_pnl=day_pnl)
        if exit_sig is not None:
            await self._handle_exit(exit_sig, ist)
            return

        if not await self._entry_allowed(bar_day):
            return

        readiness = await self.check_readiness()
        if readiness.is_blocked:
            self._emit(IntradayEventType.STRATEGY_NOT_READY,
                       reason=[c.reason for c in readiness.components if c.state == "blocked"])
            return

        # Rollup before scaling: a decayed leg should be moved, not added to.
        roll_sig = evaluate_rollup(self._params, self._core, ltp=ltp, now_ist=ist)
        if roll_sig is not None and await self._try_roll(ist, spot, roll_sig.trigger_ltp):
            return

        scale_sig = evaluate_scale_in(inp, self._params, self._core)
        if scale_sig is not None:
            await self._scale_in(ist, scale_sig.lots)

        if not self._core.is_open:
            sig, block, conds = evaluate_entry(inp, self._params, self._core)
            if sig is not None:
                await self._open_position(ist, spot, sig.side, sig.lots)
            else:
                self._emit(IntradayEventType.ENTRY_BLOCKED, reason=str(block),
                           conditions=conds, spot=spot)

    def _maybe_capture_orb(self, ist: datetime, bar: Any) -> None:
        """Capture the opening range from the candle stamped ``orb_start_ist``.

        Strictly that one candle — a session whose 09:15 bar never arrives leaves the
        range un-seeded and blocks the day, rather than silently using a later bar as
        if it were the opening range.
        """
        if self._orb_high is not None:
            return
        if ist.time() == self._orb_start:
            self._orb_high = float(bar.high)
            self._orb_low = float(bar.low)
            self._emit(IntradayEventType.ORB_CAPTURED,
                       orb_high=self._orb_high, orb_low=self._orb_low)
        elif ist.time() > self._orb_start and not self._orb_unseeded:
            self._orb_unseeded = True
            from pdp.events.models import EventType

            self.ctx.emit_critical(
                EventType.INDICATOR_UNSEEDED,
                self.sid,
                "Opening range unseeded",
                f"no {self._orb_start} {self._params.confirm_timeframe_min}m bar observed; "
                "entries blocked for the session",
                {"strategy_id": self.strategy_id},
            )

    def _snapshot_confirmation(self, ist: datetime, conf_tf: str) -> None:
        """Record the confirmation-timeframe reads as of this closed confirmation bar.

        The engine's *current* state cannot be read directly at decision time without
        making the answer depend on whether the host happened to dispatch the 15m bar
        before or after the 5m bar that closes with it. Snapshotting at the confirmation
        bar and gating on its stamp removes that dependency — and matches
        ``intraday_loader``'s ``conf_cutoff`` exactly.
        """
        ind = self.ctx.indicators
        if ind is None:
            return
        ema = ind.ema(self.sid, conf_tf)
        vals = ema.values if ema is not None else {}
        self._conf_snaps.append(
            (ist, vals.get(9), vals.get(20), self._st_dir(conf_tf))
        )
        del self._conf_snaps[:-4]  # only the most recent few can ever be current

    def _confirmation_as_of(
        self, ist: datetime
    ) -> tuple[float | None, float | None, int | None]:
        """The newest confirmation snapshot whose bar had *closed* by ``ist``."""
        span = timedelta(minutes=self._params.confirm_timeframe_min)
        for stamp, ema9, ema20, st_dir in reversed(self._conf_snaps):
            if stamp + span <= ist:
                return ema9, ema20, st_dir
        return None, None, None

    async def _build_inputs(
        self, ist: datetime, bar: Any, spot: float
    ) -> IntradayInputs:
        """Read every indicator from the engine (never recompute) and assemble the
        core's input struct."""
        ind = self.ctx.indicators
        tf = f"{self._params.timeframe_min}m"

        ema9 = ema20 = None
        st_dir = None
        cam: CamLevels | None = None
        # Confirmation-timeframe reads come from the snapshot taken when that bar closed,
        # never from the engine's live state — see `_snapshot_confirmation`.
        ema9_c, ema20_c, st_conf = self._confirmation_as_of(ist)
        if ind is not None:
            ema_state = ind.ema(self.sid, tf)
            if ema_state is not None:
                ema9 = ema_state.values.get(9)
                ema20 = ema_state.values.get(20)
            st_dir = self._st_dir(tf)
            piv = ind.pivots(self.sid, "1D")
            if piv is not None:
                cam = CamLevels(
                    r3=piv.cam_r3, r4=piv.cam_r4, s3=piv.cam_s3, s4=piv.cam_s4
                )

        prev9, prev20 = self._prev_ema
        self._prev_ema = (ema9, ema20)

        # The opening range is only *knowable* once its candle has closed. The 15m ORB
        # bar and the decision bar preceding the close (e.g. 09:25) close at the same
        # instant, and inter-timeframe delivery order is not guaranteed — gating on the
        # clock rather than on "have we captured it yet" makes this bar-for-bar identical
        # to ``intraday_loader``'s ``orb_ready_at`` no matter which bar the host hands
        # over first.
        orb_visible = ist.time() >= self._orb_ready_at

        return IntradayInputs(
            ist_dt=ist.replace(tzinfo=None),
            spot=spot,
            bar_high=float(bar.high),
            bar_low=float(bar.low),
            ema9_5m=ema9,
            ema20_5m=ema20,
            ema9_prev_5m=prev9,
            ema20_prev_5m=prev20,
            ema9_15m=ema9_c,
            ema20_15m=ema20_c,
            st_5m_dir=st_dir,
            st_15m_dir=st_conf,
            session_vwap=(self._vwap_sum / self._vwap_n) if self._vwap_n else None,
            orb_high=self._orb_high if orb_visible else None,
            orb_low=self._orb_low if orb_visible else None,
            cam=cam,
            option_st_dir=await self._option_st_dir(ist),
        )

    def _st_dir(self, tf: str) -> int | None:
        """SuperTrend(10,2) direction from the matrix variants.

        Deliberately not ``ctx.indicators.supertrend()`` — that returns the engine-wide
        SUPERTREND_PERIOD/MULTIPLIER (3/1 by default), not the (10,2) this strategy is
        specified against.
        """
        ind = self.ctx.indicators
        if ind is None:
            return None
        variants = ind.supertrend_variants(self.sid, tf) or {}
        st = variants.get("st_10_2")
        return st.direction if st is not None else None

    async def _option_st_dir(self, ist: datetime) -> int | None:
        """SuperTrend(10,2) on the *held* strike's own decision-timeframe chart."""
        leg = self._short_leg
        if not self._option_st_enabled or leg is None or self.ctx.option_bars_col is None:
            return None
        from pdp.strategy.atm_suite import option_trend_read

        since = ist.replace(hour=9, minute=15, second=0, microsecond=0)
        try:
            read = await option_trend_read(
                self.ctx.option_bars_col, leg.security_id,
                since=since, tf=f"{self._params.timeframe_min}m",
            )
        except Exception as exc:
            self.ctx.log.warning("option_trend_read_failed", sid=leg.security_id, err=str(exc))
            return None
        if read is None or read.st is None:
            return None
        fast, _slow = read.st
        return fast

    # ------------------------------------------------------------------ #
    # Ticks — premium stops and the roll trigger run between bars         #
    # ------------------------------------------------------------------ #

    async def on_tick(self, tick: Any) -> None:
        sid = tick.security_id
        ltp = float(tick.ltp)
        self._ltp_cache[sid] = ltp
        leg = self._short_leg
        if leg is None or leg.security_id != sid or self._done_for_day:
            return

        now = datetime.now(tz=_IST)
        day_pnl = await self._day_pnl(ltp)
        sig = evaluate_price_exit(
            self._params, self._core, ltp=ltp, day_pnl=day_pnl,
            now_ist=now.replace(tzinfo=None),
        )
        if sig is not None:
            await self._handle_exit(sig, now)
            return

        roll = evaluate_rollup(
            self._params, self._core, ltp=ltp, now_ist=now.replace(tzinfo=None)
        )
        if roll is not None and self._last_spot is not None:
            if sid in self._rolling:
                return
            self._rolling.add(sid)
            try:
                await self._try_roll(now, self._last_spot, roll.trigger_ltp)
            finally:
                self._rolling.discard(sid)

    def _short_ltp(self) -> float | None:
        leg = self._short_leg
        if leg is None:
            return None
        px = self._ltp_cache.get(leg.security_id)
        return px if px and px > 0 else None

    async def _day_pnl(self, ltp: float | None) -> float:
        """Realised P&L plus the open leg's mark-to-market.

        The day cap is an *exit* rule, so it must see open MTM — checking realised P&L
        alone would make it unreachable while positioned.
        """
        realized = float(await self._day_realized())
        if ltp is None:
            return realized
        return realized + unrealized_pnl(self._core, ltp, self._lot_size)

    # ------------------------------------------------------------------ #
    # Open / scale / close                                                #
    # ------------------------------------------------------------------ #

    async def _place(self, sid: str, segment: str, side: str, lots: int) -> Any:
        qty = lots * self._lot_size
        try:
            return await self.ctx.orders.place_order(
                security_id=sid, exchange_segment=segment, side=side,
                qty=qty, order_type="MARKET", product="MIS",
            )
        except Exception as exc:
            self.ctx.log.warning("order_rejected", sid=sid, side=side, lots=lots, err=str(exc))
            return None

    async def _resolve_strike(self, spot: float, opt_type: str, moneyness: int) -> Any:
        if self.ctx.session_maker is None:
            return None
        async with self.ctx.session_maker() as session:
            return await resolve_otm_option(
                session, underlying=self.underlying, spot=spot, option_type=opt_type,
                otm_steps=moneyness, strike_step=self._strike_step,
            )

    async def _fill_or_abort(self, sid: str, order: Any) -> Decimal | None:
        """Resolve the fill price, and if it cannot be read, prove the order was
        actually cancelled before discarding the leg (shared with the strangle)."""
        avg_px = await fills.await_fill_avg_px(self.ctx, self._ltp_cache, sid)
        if avg_px is not None and avg_px > 0:
            return avg_px
        avg_px = await fills.confirm_fill_or_recover(self.ctx, sid, order)
        if avg_px is not None and avg_px > 0:
            return avg_px
        from pdp.events.models import EventType

        self.ctx.emit_critical(
            EventType.MISSING_LTP, sid, "Entry price unresolved",
            f"leg {sid} aborted: entry price unresolved after all fallbacks",
            {"strategy_id": self.strategy_id},
        )
        return None

    async def _open_position(
        self, ist: datetime, spot: float, side: Side, lots: int
    ) -> bool:
        if self._lot_size_degraded:
            return False
        inst = await self._resolve_strike(spot, side.value, self._moneyness)
        if inst is None:
            self._emit(IntradayEventType.ENTRY_ABORTED, reason="no_instrument",
                       opt_type=side.value, spot=spot)
            return False

        sid = inst.security_id
        segment = inst.exchange_segment
        strike = float(inst.strike) if inst.strike is not None else 0.0

        async with self._lock_for(sid):
            lots = await self._cap_lots(sid, lots)
            if lots <= 0:
                return False
            await self._subscribe_option(sid, segment)
            await fills.await_option_ltp(
                self.ctx, self._ltp_cache, sid, self._entry_ltp_wait_s
            )
            await self._record_day_baseline(sid)

            order = await self._place(sid, segment, "SELL", lots)
            if order is None or order.status in ("CANCELLED", "REJECTED"):
                self._emit(IntradayEventType.ENTRY_ABORTED, reason="order_rejected", sid=sid)
                return False
            avg_px = await self._fill_or_abort(sid, order)
            if avg_px is None:
                return False

            leg = LiveLeg(
                security_id=sid, segment=segment, opt_type=side.value, strike=strike,
                lots=lots, entry_price=avg_px, entry_time=ist, kind="short",
                expiry=inst.expiry,
            )
            try:
                self._add_leg(leg)
            except ValueError:
                return False
            await self._persist_leg_open(leg)

        self._core.on_open(
            side, lots, float(avg_px), strike, ist.replace(tzinfo=None),
            option_st_dir=await self._option_st_dir(ist),
        )
        self._emit(IntradayEventType.LEG_OPEN, sid=sid, opt_type=side.value, strike=strike,
                   lots=lots, entry_price=float(avg_px))
        if self._hedge_enabled:
            await self._open_hedge(side.value, spot, lots, segment)
        return True

    async def _scale_in(self, ist: datetime, add_lots: int) -> bool:
        leg = self._short_leg
        if leg is None or self._lot_size_degraded:
            return False
        sid = leg.security_id
        async with self._lock_for(sid):
            add_lots = await self._cap_lots(sid, add_lots)
            if add_lots <= 0:
                return False
            order = await self._place(sid, leg.segment, "SELL", add_lots)
            if order is None or order.status in ("CANCELLED", "REJECTED"):
                return False
            avg_px = await self._fill_or_abort(sid, order)
            if avg_px is None:
                return False
            leg.lots += add_lots
        self._core.on_scale(add_lots, float(avg_px), ist.replace(tzinfo=None))
        self._emit(IntradayEventType.SCALE_IN, sid=sid, added_lots=add_lots,
                   lots=self._core.lots, avg_entry=self._core.avg_entry)
        return True

    async def _open_hedge(self, opt_type: str, spot: float, lots: int, segment: str) -> None:
        """Buy the furthest-OTM wing priced inside the hedge band, else the cheapest."""
        if self.ctx.session_maker is None or self.ctx.market is None:
            return
        best = None
        cheapest = None
        cheapest_px = float("inf")
        for offset in range(self._hedge_scan_start, self._hedge_scan_end + 1):
            inst = await self._resolve_strike(spot, opt_type, offset)
            if inst is None:
                continue
            await self._subscribe_option(inst.security_id, segment)
            ltp, _ = await self.ctx.market.ltp_with_age(inst.security_id)
            if ltp is None or float(ltp) <= 0:
                continue
            px = float(ltp)
            if px < cheapest_px:
                cheapest_px, cheapest = px, inst
            if self._hedge_prem_min <= px <= self._hedge_prem_max:
                best = inst
        target = best or cheapest
        if target is None:
            self.ctx.log.warning("hedge_no_instrument", opt_type=opt_type, spot=spot)
            return

        h_sid = target.security_id
        async with self._lock_for(h_sid):
            hedge_lots = await self._cap_lots(h_sid, lots)
            if hedge_lots <= 0:
                return
            await self._record_day_baseline(h_sid)
            order = await self._place(h_sid, segment, "BUY", hedge_lots)
            if order is None or order.status in ("CANCELLED", "REJECTED"):
                return
            avg_px = await self._fill_or_abort(h_sid, order)
            if avg_px is None:
                return
            leg = LiveLeg(
                security_id=h_sid, segment=segment, opt_type=opt_type,
                strike=float(target.strike or 0), lots=hedge_lots, entry_price=avg_px,
                entry_time=datetime.now(tz=_IST), kind="hedge", expiry=target.expiry,
            )
            try:
                self._add_leg(leg)
            except ValueError:
                return
            await self._persist_leg_open(leg)
        self._emit(IntradayEventType.LEG_OPEN, sid=h_sid, opt_type=opt_type,
                   strike=leg.strike, lots=hedge_lots, entry_price=float(avg_px),
                   is_hedge=True)

    async def _close_leg(self, leg: LiveLeg, reason: str) -> None:
        """Close one leg atomically, emitting exactly one terminal event.

        Two invariants make the position unable to grow on a close: the side derives
        from the broker's net_qty **sign**, never the leg's recorded kind; and at most
        this leg's lots are closed, so a divergence where the broker holds more never
        over-trades.
        """
        sid = leg.security_id
        ltp = self._ltp_cache.get(sid)
        if (ltp is None or ltp <= 0) and reason != "expiry":
            from pdp.events.models import EventType

            self.ctx.emit_critical(
                EventType.CLOSE_UNPRICED, sid, "Close rejected",
                f"{leg.kind} leg unpriced (LTP {ltp}) on close attempt",
                {"strategy_id": self.strategy_id, "reason": reason},
            )
            return

        async with self._lock_for(sid):
            await self.ctx.orders.cancel_open_entry_orders(sid)
            net_qty = await self.ctx.orders.get_net_qty(sid)
            if net_qty == 0:
                self._remove_leg(sid)
                return
            broker_lots = abs(net_qty) // self._lot_size
            close_lots = min(leg.lots, broker_lots)
            if close_lots == 0:
                from pdp.events.models import EventType

                self.ctx.emit_critical(
                    EventType.LEG_STATE_DIVERGED, sid, "Leg/broker divergence",
                    f"{sid}: memory {leg.lots} lots, broker {broker_lots} — leaving tracked",
                    {"strategy_id": self.strategy_id},
                )
                return
            expected_sign = -1 if leg.kind == "short" else 1
            actual_sign = 1 if net_qty > 0 else -1
            if actual_sign != expected_sign:
                from pdp.events.models import EventType

                self.ctx.emit_critical(
                    EventType.LEG_TYPE_CONTRADICTED, sid, "Leg type contradicts broker sign",
                    f"Leg {sid} tracked as {leg.kind} but broker net_qty is {net_qty} — "
                    "flattening by the broker sign to avoid growing the position",
                    {"strategy_id": self.strategy_id, "reason": reason, "net_qty": net_qty},
                )
                if self._mode == "live":
                    self._done_for_day = True
            side = "SELL" if net_qty > 0 else "BUY"
            await self._place(sid, leg.segment, side, close_lots)
            exit_px = self._ltp_cache.get(sid) or 0.0
            await self._unsubscribe_option(sid, leg.segment)
            self._emit(IntradayEventType.LEG_CLOSE, sid=sid, reason=reason,
                       opt_type=leg.opt_type, strike=leg.strike, lots=close_lots,
                       entry_price=float(leg.entry_price), exit_price=float(exit_px),
                       is_hedge=leg.is_hedge)
            await self._persist_leg_close(sid)
            self._remove_leg(sid)

    async def _close_all(self, reason: str) -> None:
        """Close the hedge last so the short is never left naked mid-sequence."""
        for leg in [lg for lg in self._legs.values() if lg.kind == "short"]:
            await self._close_leg(leg, reason)
        for leg in [lg for lg in self._legs.values() if lg.kind == "hedge"]:
            await self._close_leg(leg, reason)

    async def _handle_exit(self, sig: Any, now: datetime) -> None:
        await self._close_all(sig.reason.value)
        self._core.on_exit(now.replace(tzinfo=None), sig.reason)
        event = (
            IntradayEventType.DAY_LOSS_CAP if sig.reason is ExitReason.DAY_LOSS_CAP
            else IntradayEventType.SQUARE_OFF if sig.reason is ExitReason.SQUARE_OFF
            else IntradayEventType.LEG_CLOSE
        )
        self._emit(event, reason=sig.reason.value, detail=sig.detail)
        if sig.reason in (ExitReason.DAY_LOSS_CAP, ExitReason.SQUARE_OFF):
            self._done_for_day = True
            if sig.reason is ExitReason.DAY_LOSS_CAP:
                await self._persist_halt_marker()

    # ------------------------------------------------------------------ #
    # Rollup to ATM                                                       #
    # ------------------------------------------------------------------ #

    async def _try_roll(self, now: datetime, spot: float, trigger_ltp: float) -> bool:
        """Roll the decayed short back to ATM — all-or-nothing.

        Every precondition (a resolvable ATM strike priced at or above
        ``roll_target_min_prem``) is verified BEFORE the existing leg is closed, so a
        roll that cannot reopen leaves the position exactly as it was rather than
        leaving the strategy flat. The 2026-07-09 leg-growth incident was precisely a
        close-then-fail-to-reopen.
        """
        leg = self._short_leg
        if leg is None:
            return False
        old_lots = leg.lots
        opt_type = leg.opt_type

        new_inst = await self._resolve_strike(spot, opt_type, 0)  # 0 == ATM
        if new_inst is None or new_inst.security_id == leg.security_id:
            self._emit(IntradayEventType.ROLLED, result="skipped_no_target",
                       opt_type=opt_type, old_strike=leg.strike)
            return False
        await self._subscribe_option(new_inst.security_id, new_inst.exchange_segment)
        ltp, _ = (
            await self.ctx.market.ltp_with_age(new_inst.security_id)
            if self.ctx.market else (None, None)
        )
        new_px = float(ltp) if ltp and ltp > 0 else None
        if not rollup_target_acceptable(new_px, self._params):
            self._emit(IntradayEventType.ROLLED, result="skipped_low_prem",
                       opt_type=opt_type, old_strike=leg.strike,
                       new_strike=float(new_inst.strike or 0), new_ltp=new_px)
            return False

        # Preconditions satisfied — only now mutate the book.
        await self._close_leg(leg, "roll")
        hedge = self._hedge_leg
        if hedge is not None:
            await self._close_leg(hedge, "roll")
        opened = await self._open_position(now, spot, Side(opt_type), old_lots)
        if not opened:
            from pdp.events.models import EventType

            self.ctx.emit_critical(
                EventType.NAKED_POSITION, self.sid, "Roll failed to reopen",
                f"{opt_type} leg closed for a roll but the reopen did not land a leg",
                {"strategy_id": self.strategy_id, "opt_type": opt_type},
            )
            self._emit(IntradayEventType.ROLLED, result="reopen_failed", opt_type=opt_type)
            return False
        self._core.on_roll(
            float(new_inst.strike or 0), self._core.avg_entry,
            now.replace(tzinfo=None), option_st_dir=await self._option_st_dir(now),
        )
        self._emit(IntradayEventType.ROLLED, result="ok", opt_type=opt_type,
                   old_ltp=trigger_ltp, new_strike=float(new_inst.strike or 0),
                   lots=old_lots, rolls_today=self._core.rolls_today)
        return True

    # ------------------------------------------------------------------ #
    # Risk / session                                                      #
    # ------------------------------------------------------------------ #

    async def _cap_lots(self, sid: str, lots: int) -> int:
        """Per-security hard lot cap, checked inside the caller's sid lock so two
        concurrent opens cannot jointly exceed it."""
        existing = abs(await self.ctx.orders.get_net_qty(sid)) // self._lot_size
        cap = self._params.max_lots
        if existing >= cap:
            from pdp.events.models import EventType

            self.ctx.emit_critical(
                EventType.POSITION_SIZE_CAPPED, sid, "Position size capped",
                f"{sid} already at {existing} lots (cap {cap}); refused to add {lots}",
                {"strategy_id": self.strategy_id, "existing_lots": existing, "cap": cap},
            )
            return 0
        return min(lots, cap - existing)

    async def _entry_allowed(self, bar_day: date) -> bool:
        if self._orb_unseeded or self._lot_size_degraded:
            return False
        if self._dte_max is None:
            return True
        if self._expiry is None and self.ctx.session_maker is not None:
            async with self.ctx.session_maker() as session:
                self._expiry = await nearest_expiry(session, self.underlying)
        return within_dte(bar_day, self._expiry, self._dte_max)

    def _halt_key(self, day: date) -> str:
        return f"halt:{self.strategy_id}:{day.isoformat()}"

    async def _maybe_restore_halt_marker(self) -> None:
        if self._day_key is None or self.ctx.market is None:
            return
        if await self.ctx.market.cache_get(self._halt_key(self._day_key)):
            self._done_for_day = True
            self._core.day_ended = True
            self.ctx.log.info("halt_marker_restored", day=str(self._day_key))

    async def _persist_halt_marker(self) -> None:
        if self._day_key is None or self.ctx.market is None:
            return
        await self.ctx.market.cache_set(self._halt_key(self._day_key), "1", ex=86400)

    def _maybe_reset_day(self, bar_day: date) -> None:
        if self._day_key == bar_day:
            return
        self._day_key = bar_day
        self._done_for_day = False
        self._halt_checked = False
        self._orb_high = None
        self._orb_low = None
        self._orb_unseeded = False
        self._vwap_sum = 0.0
        self._vwap_n = 0
        self._prev_ema = (None, None)
        self._conf_snaps.clear()
        self._day_baseline.clear()
        self._touched_sids.clear()
        self._expiry = None
        self._core.reset_for_day()

    async def _maybe_resolve_lot_size(self, bar_day: date) -> None:
        """Resolve the lot size from the instruments table once per IST day. YAML is
        advisory; a failure blocks new entries while keeping open legs priceable."""
        if self._lot_size_day == bar_day or self.ctx.session_maker is None:
            return
        async with self.ctx.session_maker() as session:
            resolved = await lot_size_for_underlying(session, self.underlying)
        if resolved is None:
            if not self._lot_size_degraded:
                from pdp.events.models import EventType

                self.ctx.emit_critical(
                    EventType.INDICATOR_UNSEEDED, self.sid, "Lot size unresolved",
                    f"{self.underlying}: no instruments-table row; new entries blocked, "
                    f"using last-known-good {self._lot_size}",
                    {"strategy_id": self.strategy_id},
                )
                self._lot_size_degraded = True
            return
        if self._lot_size_yaml is not None and self._lot_size_yaml != resolved:
            self.ctx.log.warning("lot_size_yaml_mismatch", underlying=self.underlying,
                                 yaml_lot_size=self._lot_size_yaml, resolved_lot_size=resolved)
        self._lot_size = resolved
        self._lot_size_day = bar_day
        self._lot_size_degraded = False

    async def _day_realized(self) -> Decimal:
        total = Decimal("0")
        for sid in self._touched_sids:
            rp = await self.ctx.orders.get_realized_pnl(sid)
            total += rp - self._day_baseline.get(sid, Decimal("0"))
        return total

    async def _record_day_baseline(self, sid: str) -> None:
        if sid not in self._day_baseline:
            self._day_baseline[sid] = await self.ctx.orders.get_realized_pnl(sid)
        self._touched_sids.add(sid)

    async def _subscribe_option(self, sid: str, segment: str) -> None:
        if self.ctx.market is not None and sid not in self._subscribed_option_sids:
            if await self.ctx.market.subscribe(sid, segment):
                self._subscribed_option_sids.add(sid)

    async def _unsubscribe_option(self, sid: str, segment: str) -> None:
        if self.ctx.market is not None and sid in self._subscribed_option_sids:
            await self.ctx.market.unsubscribe(sid, segment)
            self._subscribed_option_sids.discard(sid)

    # ------------------------------------------------------------------ #
    # Durability + reconciliation                                         #
    # ------------------------------------------------------------------ #

    async def _persist_leg_open(self, leg: LiveLeg) -> None:
        """Durably record the leg's *kind* and identity — rehydration reads this table
        alone, and the kind decides the closing direction."""
        if self.ctx.session_maker is None:
            return
        from pdp.orders.models import StrategyLeg

        async with self.ctx.session_maker() as s:
            s.add(StrategyLeg(
                strategy_id=self.strategy_id, security_id=leg.security_id,
                leg_kind=leg.kind, opt_type=leg.opt_type,
                strike=Decimal(str(leg.strike)), expiry=leg.expiry,
            ))
            await s.commit()

    async def _persist_leg_close(self, sid: str) -> None:
        """Mark the durable row closed; never delete, so the partial-unique index frees
        the sid for a future re-open."""
        if self.ctx.session_maker is None:
            return
        from sqlalchemy import func, update

        from pdp.orders.models import StrategyLeg

        async with self.ctx.session_maker() as s:
            await s.execute(
                update(StrategyLeg)
                .where(StrategyLeg.strategy_id == self.strategy_id,
                       StrategyLeg.security_id == sid,
                       StrategyLeg.closed_at.is_(None))
                .values(closed_at=func.now())
            )
            await s.commit()

    async def _rehydrate_legs(self) -> None:
        """Restore open legs from the durable table after a restart."""
        if self.ctx.session_maker is None:
            return
        from sqlalchemy import select

        from pdp.orders.models import StrategyLeg

        async with self.ctx.session_maker() as s:
            rows = (await s.execute(
                select(StrategyLeg).where(
                    StrategyLeg.strategy_id == self.strategy_id,
                    StrategyLeg.closed_at.is_(None),
                )
            )).scalars().all()

        for row in rows:
            net_qty = await self.ctx.orders.get_net_qty(row.security_id)
            if net_qty == 0:
                await self._persist_leg_close(row.security_id)
                continue
            _, avg_px = await self.ctx.orders.get_position(row.security_id)
            leg = LiveLeg(
                security_id=row.security_id, segment=self.option_segment,
                opt_type=row.opt_type or "PE", strike=float(row.strike or 0),
                lots=abs(net_qty) // self._lot_size,
                entry_price=avg_px or Decimal("0"),
                entry_time=datetime.now(tz=_IST), kind=row.leg_kind or "short",
                expiry=row.expiry,
            )
            try:
                self._add_leg(leg)
            except ValueError:
                continue
            await self._subscribe_option(leg.security_id, leg.segment)
            if leg.kind == "short" and leg.lots > 0:
                self._core.on_open(
                    Side(leg.opt_type), leg.lots, float(leg.entry_price), leg.strike,
                    datetime.now(tz=_IST).replace(tzinfo=None),
                )
        if rows:
            self.ctx.log.info("legs_rehydrated", count=len(self._legs))

    async def _reconcile_loop(self) -> None:
        """Surface leg/broker divergence on a timer, not only when a console polls."""
        while True:
            try:
                await asyncio.sleep(self._reconcile_interval_s)
                await self._reconcile_divergences()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.ctx.log.warning("reconcile_failed", err=str(exc))

    async def _reconcile_divergences(self) -> None:
        for sid, leg in list(self._legs.items()):
            net_qty = await self.ctx.orders.get_net_qty(sid)
            broker_lots = abs(net_qty) // self._lot_size
            if broker_lots != leg.lots:
                from pdp.events.models import EventType

                self.ctx.emit_critical(
                    EventType.LEG_STATE_DIVERGED, sid, "Leg/broker divergence",
                    f"{sid}: memory {leg.lots} lots, broker {broker_lots} lots",
                    {"strategy_id": self.strategy_id, "memory_lots": leg.lots,
                     "broker_lots": broker_lots},
                )

    # ------------------------------------------------------------------ #
    # Readiness / console                                                 #
    # ------------------------------------------------------------------ #

    async def check_readiness(self) -> StrategyReadiness:
        comps: list[ReadinessComponent] = []
        ind = self.ctx.indicators
        tf = f"{self._params.timeframe_min}m"

        ema = ind.ema(self.sid, tf) if ind else None
        if ema is None or 9 not in ema.values or 20 not in ema.values:
            comps.append(ReadinessComponent("ema", "blocked", f"EMA 9/20 unseeded on {tf}"))
        else:
            comps.append(ReadinessComponent("ema", "ok"))

        comps.append(
            ReadinessComponent("supertrend", "ok") if self._st_dir(tf) is not None
            else ReadinessComponent("supertrend", "blocked", f"st_10_2 unseeded on {tf}")
        )
        comps.append(
            ReadinessComponent("orb", "ok") if self._orb_high is not None
            else ReadinessComponent("orb", "blocked", "opening range not captured")
        )
        comps.append(
            ReadinessComponent("vwap", "ok") if self._vwap_n > 0
            else ReadinessComponent("vwap", "blocked", "session VWAP has no 1m bars yet")
        )
        piv = ind.pivots(self.sid, "1D") if ind else None
        comps.append(
            ReadinessComponent("pivots", "ok") if piv is not None
            else ReadinessComponent("pivots", "degraded", "daily Camarilla unseeded")
        )
        comps.append(
            ReadinessComponent("lot_size", "blocked", "instruments table has no lot size")
            if self._lot_size_degraded else ReadinessComponent("lot_size", "ok")
        )
        return StrategyReadiness.evaluate(comps)

    def _emit(self, event_type: str, **fields: Any) -> None:
        record = {
            "ts": datetime.now(tz=_IST).isoformat(),
            "strategy_id": self.strategy_id,
            "event_type": str(event_type),
            **fields,
        }
        self.ctx.log.info(str(event_type), **fields)
        self._activity.append(record)
        if self._slog is not None:
            self._slog.write(record)
        svc = getattr(self.ctx, "_event_service", None)
        writer = getattr(svc, "writer", None) if svc is not None else None
        if writer is not None:
            try:
                writer.enqueue(record)
            except Exception:  # noqa: S110 — observability must never break trading
                pass

    async def state(self) -> dict:
        """Console snapshot."""
        leg = self._short_leg
        ltp = self._short_ltp()
        return {
            "strategy_id": self.strategy_id,
            "underlying": self.underlying,
            "mode": self._mode,
            "done_for_day": self._done_for_day,
            "orb_high": self._orb_high,
            "orb_low": self._orb_low,
            "session_vwap": (self._vwap_sum / self._vwap_n) if self._vwap_n else None,
            "side": self._core.side.value if self._core.side else None,
            "lots": self._core.lots,
            "avg_entry": self._core.avg_entry,
            "strike": leg.strike if leg else None,
            "ltp": ltp,
            "unrealized": unrealized_pnl(self._core, ltp, self._lot_size) if ltp else 0.0,
            "day_realized": float(await self._day_realized()),
            "rolls_today": self._core.rolls_today,
            "ema_break_bars": self._core.ema_break_bars,
            "cam_reject_bars": self._core.cam_reject_bars,
            "legs": [
                {"sid": lg.security_id, "kind": lg.kind, "opt_type": lg.opt_type,
                 "strike": lg.strike, "lots": lg.lots,
                 "entry_price": float(lg.entry_price)}
                for lg in self._legs.values()
            ],
            "recent_events": list(self._activity)[-20:],
        }


    def heartbeat_fields(self) -> dict[str, Any]:
        return {
            "side": self._core.side.value if self._core.side else None,
            "lots": self._core.lots,
            "orb": [self._orb_low, self._orb_high],
            "done_for_day": self._done_for_day,
        }
