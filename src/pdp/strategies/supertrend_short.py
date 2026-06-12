"""SuperTrend(3,1) intraday option-selling paper strategy.

On the NIFTY 5-minute bar, sell an OTM option aligned with the SuperTrend direction:
green (up) -> short PE, red (down) -> short CE. A direction flip buys back the open leg and
opens the opposite side. While the trend holds, scale in one lot per bar up to a cap. No
entries before the start time; flatten all at the square-off time. Paper-only.

Schedule and sizing live in the YAML ``params`` block — see strategies/supertrend_short.yaml.
"""
from __future__ import annotations

from datetime import date, time
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from pdp.strategy.abc import Strategy
from pdp.strategy.strikes import resolve_otm_option

if TYPE_CHECKING:
    from pdp.market.bars import BarClosed
    from pdp.strategy.context import StrategyContext

_IST = ZoneInfo("Asia/Kolkata")


def _parse_hhmm(value: str) -> time:
    hh, mm = value.split(":")
    return time(int(hh), int(mm))


class SuperTrendShort(Strategy):
    async def on_init(self, ctx: StrategyContext) -> None:
        self.ctx = ctx
        p = ctx.params
        self.underlying: str = p.get("underlying", "NIFTY")
        self.sid: str = str(p.get("underlying_security_id", "13"))
        self.index_segment: str = p.get("index_segment", "IDX_I")
        self.timeframe: str = p.get("timeframe", "5m")
        self.option_segment: str = p.get("option_segment", "NSE_FNO")
        self.otm_steps: int = int(p.get("otm_steps", 1))
        self.strike_step: int | None = (
            int(p["strike_step"]) if p.get("strike_step") is not None else None
        )
        self.lot_size: int = int(p.get("lot_size", 65))
        self.start_lots: int = int(p.get("start_lots", 2))
        self.add_lots: int = int(p.get("add_lots", 1))
        self.max_lots: int = int(p.get("max_lots", 5))
        self.start_t: time = _parse_hhmm(p.get("start_ist", "09:30"))
        self.squareoff_t: time = _parse_hhmm(p.get("square_off_ist", "15:10"))
        # Risk controls (mirror backtest_multiday.py LEG_STOP_PER_LOT / DAY_STOP_LOSS).
        self.leg_stop_per_lot: Decimal = Decimal(str(p.get("leg_stop_per_lot", 1000)))
        self.day_stop: Decimal = Decimal(str(p.get("day_stop", 10000)))

        self._direction: int | None = None
        self._current: dict[str, Any] | None = None
        self._subscribed: set[str] = set()
        self._done_for_day = False
        self._last_bar_time = None
        # Daily realized-P&L tracking for the day stop. Baseline per security captured
        # at first touch each IST day so the cap measures *today's* realized P&L only.
        self._day_key: date | None = None
        self._day_baseline: dict[str, Decimal] = {}
        self._touched: set[str] = set()
        self._cached_day_pnl: Decimal = Decimal("0")  # updated each bar for heartbeat

        # Ensure the underlying index feed is on so bars (and thus SuperTrend) flow.
        if ctx.market is not None:
            await ctx.market.subscribe(self.sid, self.index_segment)

        ctx.log.info(
            "supertrend_short_init",
            underlying=self.underlying,
            timeframe=self.timeframe,
            start=self.start_t.isoformat(),
            square_off=self.squareoff_t.isoformat(),
            lots=f"{self.start_lots}->{self.max_lots}",
            leg_stop_per_lot=str(self.leg_stop_per_lot),
            day_stop=str(self.day_stop),
        )

        # Recover open-leg state from the ledger if a DB session is available.
        # _direction is intentionally NOT recovered — it is derived from the first bar.
        _strategy_id = getattr(ctx.orders, "strategy_id", None)
        if ctx.session_maker is not None and _strategy_id is not None:
            from datetime import datetime

            from pdp.strategy.recovery import recover_strategy_state

            _today_ist = datetime.now(_IST).date()
            _recovered, _day_baseline = await recover_strategy_state(
                ctx,
                strategy_id=_strategy_id,
                lot_size=self.lot_size,
                today_ist=_today_ist,
            )
            if _recovered is not None:
                self._current = _recovered
            if _day_baseline:
                self._day_baseline = _day_baseline
                self._touched = set(_day_baseline.keys())
                # Mark today as initialised so _maybe_reset_day doesn't wipe recovery.
                self._day_key = _today_ist

    async def on_bar(self, bar: BarClosed) -> None:
        if bar.security_id != self.sid or bar.timeframe != self.timeframe:
            return
        if self._last_bar_time == bar.bar_time:
            return  # de-dup repeated dispatch of the same bar
        self._last_bar_time = bar.bar_time

        self._maybe_reset_day(bar)

        # Gate on the bar's own IST timestamp (not wall-clock), so live and backtest
        # schedule identically and the strategy can be driven deterministically.
        now = bar.bar_time.astimezone(_IST).time()

        # End-of-day square-off takes priority.
        if now >= self.squareoff_t:
            if self._current is not None:
                await self._close_current("square_off")
            self._done_for_day = True
            return
        if self._done_for_day:
            return

        st = self.ctx.indicators.supertrend(self.sid, self.timeframe) if self.ctx.indicators else None
        if st is None or st.direction is None:
            return
        self._direction = st.direction

        # No new entries before the start of the trading window.
        if now < self.start_t:
            return

        # Heartbeat: one per bar inside the trading window, before decisions.
        self.log_heartbeat(bar.bar_time)

        # Daily loss cap: once cumulative realized P&L has reached -day_stop, flatten any
        # open leg and trade no more today. Realized P&L from a stop-driven close lands in
        # the ledger after its cover fills, so this is caught at the start of a later bar.
        day_real = await self._day_realized()
        self._cached_day_pnl = day_real
        if day_real <= -self.day_stop:
            if self._current is not None:
                await self._close_current("day_stop")
            self._done_for_day = True
            return

        # Per-leg stop: close the open leg if its unrealized MTM loss has reached the
        # per-lot limit. No new entry on the stop bar (the next bar's signal decides).
        if self._current is not None and await self._leg_stop_hit():
            await self._close_current("leg_stop")
            return

        desired = "PE" if st.direction > 0 else "CE"

        if self._current is None:
            await self._open(bar, desired, self.start_lots)
        elif self._current["option_type"] != desired:
            await self._close_current("flip")
            await self._open(bar, desired, self.start_lots)
        elif self._current["lots"] < self.max_lots:
            await self._add(self.add_lots)

    # ------------------------------------------------------------------ #
    # Risk controls                                                       #
    # ------------------------------------------------------------------ #

    def _maybe_reset_day(self, bar: BarClosed) -> None:
        """Reset daily accumulators when the bar crosses into a new IST day."""
        bar_day = bar.bar_time.astimezone(_IST).date()
        if self._day_key != bar_day:
            self._day_key = bar_day
            self._day_baseline.clear()
            self._touched.clear()
            self._done_for_day = False

    async def _day_realized(self) -> Decimal:
        """Cumulative realized P&L across legs touched today (ledger-authoritative).

        For each security touched today, subtract the realized P&L it carried at first
        touch so only *today's* realized P&L counts toward the cap.
        """
        total = Decimal("0")
        for sid in self._touched:
            rp = await self.ctx.orders.get_realized_pnl(sid)
            total += rp - self._day_baseline.get(sid, Decimal("0"))
        return total

    async def _leg_stop_hit(self) -> bool:
        """True when the open leg's unrealized MTM loss has reached the per-lot stop."""
        c = self._current
        if c is None:
            return False
        net_qty, avg = await self.ctx.orders.get_position(c["security_id"])
        if net_qty >= 0 or avg <= 0:
            return False  # not (yet) short, or no average to mark against
        ltp = await self.ctx.market.ltp(c["security_id"]) if self.ctx.market else None
        if ltp is None or ltp <= 0:
            return False  # stale/zero price — never stop on a bogus quote
        mtm = (avg - ltp) * Decimal(abs(net_qty))  # loss is negative when ltp > avg
        limit = self.leg_stop_per_lot * Decimal(int(c["lots"]))
        return mtm <= -limit

    async def on_shutdown(self) -> None:
        if self.ctx.market is None:
            return
        for sid in list(self._subscribed):
            try:
                await self.ctx.market.unsubscribe(sid, self.option_segment)
            except Exception as exc:  # pragma: no cover - best-effort cleanup
                self.ctx.log.warning("unsubscribe_failed", security_id=sid, exc=str(exc))

    def heartbeat_fields(self) -> dict:
        return {
            "st_direction": self._direction,
            "open_leg": dict(self._current) if self._current else None,
            "done_for_day": self._done_for_day,
            "day_pnl": str(self._cached_day_pnl),
        }

    # ------------------------------------------------------------------ #
    # Internal                                                            #
    # ------------------------------------------------------------------ #

    async def _open(self, bar: BarClosed, option_type: str, lots: int) -> None:
        spot = float(bar.close)
        inst = None
        if self.ctx.session_maker is not None:
            async with self.ctx.session_maker() as session:
                inst = await resolve_otm_option(
                    session,
                    underlying=self.underlying,
                    spot=spot,
                    option_type=option_type,
                    otm_steps=self.otm_steps,
                    strike_step=self.strike_step,
                )
        if inst is None:
            self.ctx.log.warning("open_skipped_no_instrument", option_type=option_type, spot=spot)
            return

        sid = inst.security_id
        segment = inst.exchange_segment
        # Subscribe the option feed first so the paper engine receives ticks to fill on.
        if self.ctx.market is not None and sid not in self._subscribed:
            if await self.ctx.market.subscribe(sid, segment):
                self._subscribed.add(sid)

        # Record today's realized-P&L baseline for this security so the day stop only
        # counts P&L accrued today (the ledger's realized_pnl is cumulative).
        if sid not in self._day_baseline:
            self._day_baseline[sid] = await self.ctx.orders.get_realized_pnl(sid)
        self._touched.add(sid)

        order = await self._place(sid, segment, "SELL", lots)
        if order is None:
            return
        if order.status in ("CANCELLED", "REJECTED"):
            self.ctx.log.warning(
                "open_sell_terminal", security_id=sid, order_id=order.id, status=order.status
            )
            return
        self._current = {
            "security_id": sid,
            "segment": segment,
            "option_type": option_type,
            "strike": float(inst.strike) if inst.strike is not None else None,
            "lots": lots,
        }
        self.ctx.log.info(
            "leg_opened",
            option_type=option_type,
            security_id=sid,
            strike=self._current["strike"],
            lots=lots,
        )
        self.log_decision(
            "open", "new_entry",
            option_type=option_type,
            security_id=sid,
            strike=self._current["strike"],
            lots=lots,
        )

    async def _add(self, add_lots: int) -> None:
        c = self._current
        assert c is not None
        order = await self._place(c["security_id"], c["segment"], "SELL", add_lots)
        if order is None:
            return
        if order.status in ("CANCELLED", "REJECTED"):
            self.ctx.log.warning(
                "scale_sell_terminal", security_id=c["security_id"], order_id=order.id, status=order.status
            )
            return
        c["lots"] += add_lots
        self.ctx.log.info("leg_scaled", security_id=c["security_id"], lots=c["lots"])
        self.log_decision(
            "scale", "add_lots",
            security_id=c["security_id"],
            add_lots=add_lots,
            lots=c["lots"],
        )

    async def _close_current(self, reason: str) -> None:
        c = self._current
        if c is None:
            return
        await self.ctx.orders.cancel_open_entry_orders(c["security_id"])
        net_qty = await self.ctx.orders.get_net_qty(c["security_id"])
        if net_qty == 0:
            self.ctx.log.info(
                "close_skipped_no_position", security_id=c["security_id"], reason=reason
            )
            self._current = None
            return
        close_lots = abs(net_qty) // self.lot_size
        order = await self._place(c["security_id"], c["segment"], "BUY", close_lots)
        if order is None:
            return  # keep the leg so a later bar / square-off retries the cover
        self.ctx.log.info("leg_closed", security_id=c["security_id"], lots=c["lots"], reason=reason)
        self.log_decision(reason, "position_closed", security_id=c["security_id"], lots=c["lots"])
        self._current = None

    async def _place(self, security_id: str, segment: str, side: str, lots: int):
        qty = lots * self.lot_size
        try:
            return await self.ctx.orders.place_order(
                security_id=security_id,
                exchange_segment=segment,
                side=side,
                qty=qty,
                order_type="MARKET",
                product="MIS",
            )
        except Exception as exc:
            self.ctx.log.warning(
                "order_rejected", security_id=security_id, side=side, qty=qty, exc=str(exc)
            )
            return None
