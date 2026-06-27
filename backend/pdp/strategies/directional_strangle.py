"""DirectionalStrangle — bias-driven multi-leg option selling with momentum longs.

Reuses ``pdp.signals.bias.score_bias()`` so live decisions are identical to the backtest
replay given the same indicator values.

Default config (dominant walk-forward winner: tren/cons/tp0.5/H, scale×2, neutral 3:3):
  - Trend-weighted EMA bias, conservative thresholds, 50 % take-profit, hedge ON
  - Scale×2 across the full ratio table; neutral bucket trades 3PE:3CE
  - OTM-step strike selection (otm_steps=2)

Momentum long (COMPLETE_BULL / COMPLETE_BEAR only):
  - Buy ITM+1 CE on COMPLETE_BULL, ITM+1 PE on COMPLETE_BEAR
  - Target premium spend = momentum_premium_target (default Rs 50,000)
  - Close when |score| drops below momentum_score_threshold (default 0.5)

Lifecycle per IST session:
  1. Subscribe NIFTY 5m/15m/1h bars + India VIX ticks.
  2. After entry_after_ist (10:15): compute BiasInputs -> score_bias -> open legs per bucket.
  3. Bucket change -> close current shorts+hedges, reopen per new bucket.
  4. on_tick: per-leg take-profit (TP%) and premium stop (half@30%, all@40%).
  5. Day-loss cap: flatten all + halt when day realized P&L <= -day_loss_limit.
  6. Square-off: close all remaining legs at squareoff_ist (15:10 IST).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from pdp.signals.bias import (
    BiasBucket,
    BiasInputs,
    BiasWeights,
    CamLevels,
    TimeframeEMA,
    score_bias,
)
from pdp.strategy.abc import Strategy
from pdp.strategy.strikes import (
    STRIKE_STEP,
    nearest_weekly_expiry,
    resolve_otm_option,
)

if TYPE_CHECKING:
    from pdp.market.bars import BarClosed
    from pdp.strategy.context import StrategyContext

_IST = ZoneInfo("Asia/Kolkata")
_VIX_RECENT_WINDOW = 3

_EXTREME_BUCKETS = {BiasBucket.COMPLETE_BULL, BiasBucket.COMPLETE_BEAR}


def _parse_hhmm(v: str) -> time:
    hh, mm = v.split(":")
    return time(int(hh), int(mm))


def _to_tf_ema(ema_state: Any, price: float) -> TimeframeEMA | None:
    if ema_state is None:
        return None
    v = getattr(ema_state, "values", {})
    if 9 not in v or 20 not in v or 50 not in v:
        return None
    return TimeframeEMA(price=price, ema9=v[9], ema20=v[20], ema50=v[50])


def _to_cam(pivot_state: Any) -> CamLevels | None:
    if pivot_state is None:
        return None
    return CamLevels(
        r3=pivot_state.cam_r3, r4=pivot_state.cam_r4,
        s3=pivot_state.cam_s3, s4=pivot_state.cam_s4,
    )


@dataclass
class OpenLeg:
    security_id: str
    segment: str
    opt_type: str           # "PE" or "CE"
    strike: float
    lots: int
    entry_price: Decimal
    is_hedge: bool = False      # True = far-OTM protective long
    is_momentum: bool = False   # True = ITM directional long (COMPLETE_* only)
    half_stopped: bool = False  # True after pct_stop_half partial close (shorts only)


class DirectionalStrangle(Strategy):

    # ------------------------------------------------------------------ #
    # Initialisation                                                       #
    # ------------------------------------------------------------------ #

    async def on_init(self, ctx: StrategyContext) -> None:
        self.ctx = ctx
        p = ctx.params

        self.underlying: str = p.get("underlying", "NIFTY")
        self.sid: str = str(p.get("underlying_security_id", "13"))
        self.index_segment: str = p.get("index_segment", "IDX_I")
        self.option_segment: str = p.get("option_segment", "NSE_FNO")
        self._vix_sid: str = str(p.get("vix_security_id", "21"))

        self._lot_size: int = int(p.get("lot_size", 65))
        self._scale_lots: int = int(p.get("scale_lots", 2))
        self._otm_steps: int = int(p.get("otm_steps", 2))
        self._hedge_prem_min: float = float(p.get("hedge_prem_min", 2.0))
        self._hedge_prem_max: float = float(p.get("hedge_prem_max", 5.0))
        self._hedge_scan_start: int = int(p.get("hedge_scan_start", 10))
        self._hedge_scan_end: int = int(p.get("hedge_scan_end", 22))
        self._strike_step: int = int(
            p.get("strike_step", STRIKE_STEP.get(self.underlying, 50))
        )

        self._take_profit_pct: float = float(p.get("take_profit_pct", 0.5))
        self._pct_stop_half: float = float(p.get("pct_stop_half", 0.30))
        self._pct_stop_all: float = float(p.get("pct_stop_all", 0.40))
        self._hedge_enabled: bool = bool(p.get("hedge_enabled", True))
        self._neutral_no_trade: bool = bool(p.get("neutral_no_trade", False))
        self._day_loss_limit: Decimal = Decimal(str(p.get("day_loss_limit", 15000)))
        self._entry_after_ist: time = _parse_hhmm(p.get("entry_after_ist", "10:15"))
        self._squareoff_ist: time = _parse_hhmm(p.get("squareoff_ist", "15:10"))

        # VIX gate — disabled by default (5yr data shows it costs Rs 33L and increases MaxDD)
        self._vix_gate_enabled: bool = bool(p.get("vix_gate_enabled", False))

        # Momentum long: buy ITM+1 on COMPLETE_BULL/BEAR, close when |score| < threshold
        self._momentum_enabled: bool = bool(p.get("momentum_enabled", True))
        self._momentum_premium_target: int = int(p.get("momentum_premium_target", 50000))
        self._momentum_score_threshold: float = float(p.get("momentum_score_threshold", 0.5))

        # Bias weights (dominant tren/cons walk-forward config)
        self._weights = BiasWeights(
            w_ema_1h=float(p.get("w_ema_1h", 2.5)),
            w_ema_15m=float(p.get("w_ema_15m", 2.0)),
            w_ema_5m=float(p.get("w_ema_5m", 1.5)),
            w_cam_daily=float(p.get("w_cam_daily", 1.0)),
            w_cam_weekly=float(p.get("w_cam_weekly", 1.0)),
            w_swing=float(p.get("w_swing", 1.0)),
            w_vwap=float(p.get("w_vwap", 1.0)),
            w_orb=float(p.get("w_orb", 1.0)),
            w_pcr=float(p.get("w_pcr", 1.0)),
            th_complete=float(p.get("th_complete", 0.85)),
            th_most=float(p.get("th_most", 0.60)),
            th_more=float(p.get("th_more", 0.30)),
        )

        raw_rt: dict = p.get("ratio_table", {})
        self._ratio_table: dict[BiasBucket, tuple[int, int]] = (
            {BiasBucket(k): (int(v[0]), int(v[1])) for k, v in raw_rt.items()}
            if raw_rt
            else {
                BiasBucket.COMPLETE_BULL: (5, 0),
                BiasBucket.MOST_BULL:     (4, 2),
                BiasBucket.MORE_BULL:     (3, 2),
                BiasBucket.NEUTRAL:       (3, 3),
                BiasBucket.MORE_BEAR:     (2, 3),
                BiasBucket.MOST_BEAR:     (2, 4),
                BiasBucket.COMPLETE_BEAR: (0, 5),
            }
        )

        # Runtime state
        self._short_legs: list[OpenLeg] = []
        self._hedge_legs: list[OpenLeg] = []
        self._momentum_legs: list[OpenLeg] = []
        self._current_bucket: str | None = None
        self._last_score: float = 0.0
        self._done_for_day = False
        self._day_key: date | None = None
        self._subscribed_option_sids: set[str] = set()

        self._vix_now: float | None = None
        self._vix_day_open: float | None = None
        self._vix_day_high: float | None = None
        self._vix_recent: list[float] = []

        self._orb_high: float | None = None
        self._orb_low: float | None = None

        self._day_baseline: dict[str, Decimal] = {}
        self._touched_sids: set[str] = set()

        if ctx.market is not None:
            await ctx.market.subscribe(self.sid, self.index_segment)
            await ctx.market.subscribe(self._vix_sid, self.index_segment)

        ctx.log.info(
            "directional_strangle_init",
            underlying=self.underlying,
            scale_lots=self._scale_lots,
            hedge=self._hedge_enabled,
            momentum=self._momentum_enabled,
            tp_pct=self._take_profit_pct,
            neutral_no_trade=self._neutral_no_trade,
            entry_after=self._entry_after_ist.isoformat(),
            squareoff=self._squareoff_ist.isoformat(),
        )

    # ------------------------------------------------------------------ #
    # Bar handler                                                          #
    # ------------------------------------------------------------------ #

    async def on_bar(self, bar: BarClosed) -> None:
        if bar.security_id != self.sid:
            return

        ist = bar.bar_time.astimezone(_IST)
        bar_day = ist.date()
        now = ist.time()

        self._maybe_reset_day(bar_day)

        # 15m bar: capture Opening Range on first bar of the session
        if bar.timeframe == "15m" and not self._orb_high:
            self._orb_high = float(bar.high)
            self._orb_low = float(bar.low)

        if bar.timeframe != "5m":
            return

        spot = float(bar.close)

        if now >= self._squareoff_ist:
            if self._short_legs or self._hedge_legs or self._momentum_legs:
                await self._close_all("square_off")
            self._done_for_day = True
            return
        if self._done_for_day:
            return

        if now < self._entry_after_ist:
            self.log_heartbeat(bar.bar_time)
            return

        day_pnl = await self._day_realized()
        if day_pnl <= -self._day_loss_limit:
            if self._short_legs or self._hedge_legs or self._momentum_legs:
                await self._close_all("day_loss_cap")
            self.ctx.log.info("day_loss_cap_halt", day_pnl=str(day_pnl))
            self._done_for_day = True
            return

        inp = self._build_bias_inputs(spot)
        result = score_bias(inp, weights=self._weights, ratio_table=self._ratio_table)
        self._last_score = result.score

        self.log_heartbeat(bar.bar_time)
        self.ctx.log.info(
            "bias_evaluated",
            score=round(result.score, 3),
            bucket=result.bucket,
            gated=result.gated,
            reason=result.reason,
            shorts=len(self._short_legs),
            momentum=len(self._momentum_legs),
        )

        if result.gated:
            return

        if result.bucket == BiasBucket.NEUTRAL and self._neutral_no_trade:
            if self._short_legs or self._hedge_legs:
                await self._close_shorts_and_hedges("neutral_skip")
            await self._maybe_close_momentum(result.score)
            return

        bucket_str = result.bucket.value
        pe_lots, ce_lots = self._ratio_for(result.bucket)

        if self._current_bucket != bucket_str:
            if self._short_legs or self._hedge_legs:
                await self._close_shorts_and_hedges("bucket_change")
            self._current_bucket = bucket_str
            await self._open_bucket(spot, pe_lots, ce_lots)

        if self._momentum_enabled:
            if result.bucket in _EXTREME_BUCKETS and not self._momentum_legs:
                await self._open_momentum(spot, result.bucket)
            await self._maybe_close_momentum(result.score)

    # ------------------------------------------------------------------ #
    # Tick handler — take-profit and premium stop for short legs           #
    # ------------------------------------------------------------------ #

    async def on_tick(self, tick: Any) -> None:
        if getattr(tick, "security_id", None) == self._vix_sid:
            ltp = getattr(tick, "ltp", None)
            if ltp and float(ltp) > 0:
                self._update_vix(float(ltp))
            return

        if self._done_for_day:
            return

        sid = getattr(tick, "security_id", None)
        ltp_raw = getattr(tick, "ltp", None)
        if sid is None or ltp_raw is None:
            return
        ltp = float(ltp_raw)
        if ltp <= 0:
            return

        # Only watch short legs (momentum longs exit on score signal, not premium)
        legs = [lg for lg in self._short_legs if lg.security_id == sid]
        for leg in legs:
            entry = float(leg.entry_price)
            if entry <= 0:
                continue
            if ltp <= entry * self._take_profit_pct:
                self.ctx.log.info("take_profit", sid=sid, ltp=ltp, entry=entry)
                await self._close_short_leg(leg, "take_profit")
                await self._close_matching_hedge(leg)
                return
            if not leg.half_stopped and ltp >= entry * (1 + self._pct_stop_half):
                close_lots = leg.lots // 2
                if close_lots > 0:
                    await self._place(sid, leg.segment, "BUY", close_lots)
                    leg.lots -= close_lots
                    leg.half_stopped = True
                    self.ctx.log.info("stop_half", sid=sid, ltp=ltp, remaining=leg.lots)
                    self.log_decision("stop_half", "premium_stop_half",
                                      security_id=sid, ltp=ltp, remaining_lots=leg.lots)
            if ltp >= entry * (1 + self._pct_stop_all):
                self.ctx.log.info("stop_all", sid=sid, ltp=ltp, entry=entry)
                await self._close_short_leg(leg, "premium_stop")
                await self._close_matching_hedge(leg)

    # ------------------------------------------------------------------ #
    # Shutdown                                                             #
    # ------------------------------------------------------------------ #

    async def on_shutdown(self) -> None:
        if self.ctx.market is None:
            return
        for sid in list(self._subscribed_option_sids):
            try:
                await self.ctx.market.unsubscribe(sid, self.option_segment)
            except Exception as exc:
                self.ctx.log.warning("unsubscribe_failed", security_id=sid, exc=str(exc))

    # ------------------------------------------------------------------ #
    # Heartbeat                                                            #
    # ------------------------------------------------------------------ #

    def heartbeat_fields(self) -> dict:
        return {
            "bucket": self._current_bucket,
            "score": round(self._last_score, 3),
            "open_shorts": len(self._short_legs),
            "open_hedges": len(self._hedge_legs),
            "open_momentum": len(self._momentum_legs),
            "done_for_day": self._done_for_day,
            "vix_now": self._vix_now,
            "orb_set": self._orb_high is not None,
        }

    # ------------------------------------------------------------------ #
    # Bias input assembly                                                  #
    # ------------------------------------------------------------------ #

    def _build_bias_inputs(self, spot: float) -> BiasInputs:
        ind = self.ctx.indicators

        ema_5m = _to_tf_ema(ind.ema(self.sid, "5m"), spot) if ind else None
        ema_15m = _to_tf_ema(ind.ema(self.sid, "15m"), spot) if ind else None
        ema_1h = _to_tf_ema(ind.ema(self.sid, "1h"), spot) if ind else None

        pivot = ind.pivots(self.sid, "5m") if ind else None
        cam_daily = _to_cam(pivot)

        pl = ind.period_levels(self.sid, "5m") if ind else None
        vwap_s = ind.vwap(self.sid, "5m") if ind else None

        return BiasInputs(
            spot=spot,
            ema_1h=ema_1h,
            ema_15m=ema_15m,
            ema_5m=ema_5m,
            cam_daily=cam_daily,
            cam_weekly=None,
            pdh=pl.pdh if pl else None,
            pdl=pl.pdl if pl else None,
            pwh=pl.pwh if pl else None,
            pwl=pl.pwl if pl else None,
            vwap=vwap_s.vwap if vwap_s else None,
            orb_high=self._orb_high,
            orb_low=self._orb_low,
            pcr=None,
            vix_now=self._vix_now if self._vix_gate_enabled else None,
            vix_day_open=self._vix_day_open if self._vix_gate_enabled else None,
            vix_day_high=self._vix_day_high if self._vix_gate_enabled else None,
            vix_recent=list(self._vix_recent) if self._vix_gate_enabled else [],
        )

    # ------------------------------------------------------------------ #
    # Leg open — shorts + protective hedges                               #
    # ------------------------------------------------------------------ #

    async def _open_bucket(self, spot: float, pe_lots: int, ce_lots: int) -> None:
        if pe_lots > 0:
            await self._open_short(spot, "PE", pe_lots)
        if ce_lots > 0:
            await self._open_short(spot, "CE", ce_lots)

    async def _open_short(self, spot: float, opt_type: str, lots: int) -> None:
        if self.ctx.session_maker is None:
            return

        async with self.ctx.session_maker() as session:
            inst = await resolve_otm_option(
                session,
                underlying=self.underlying,
                spot=spot,
                option_type=opt_type,
                otm_steps=self._otm_steps,
                strike_step=self._strike_step,
            )
        if inst is None:
            self.ctx.log.warning("short_no_instrument", opt_type=opt_type, spot=spot)
            return

        sid = inst.security_id
        segment = inst.exchange_segment
        strike = float(inst.strike) if inst.strike is not None else 0.0

        await self._subscribe_option(sid, segment)
        await self._record_day_baseline(sid)

        order = await self._place(sid, segment, "SELL", lots)
        if order is None or order.status in ("CANCELLED", "REJECTED"):
            return

        _, avg_px = await self.ctx.orders.get_position(sid)
        self._short_legs.append(OpenLeg(
            security_id=sid, segment=segment, opt_type=opt_type,
            strike=strike, lots=lots, entry_price=avg_px,
        ))
        self.ctx.log.info("short_opened", opt_type=opt_type, strike=strike, lots=lots, sid=sid)
        self.log_decision("open", "bucket_entry",
                          opt_type=opt_type, strike=strike, lots=lots, security_id=sid)

        if self._hedge_enabled:
            await self._open_hedge(opt_type, spot, lots, segment)

    async def _open_hedge(self, opt_type: str, spot: float,
                          lots: int, segment: str) -> None:
        """Buy cheapest far-OTM wing priced in [hedge_prem_min, hedge_prem_max].

        Scans OTM strikes from hedge_scan_start to hedge_scan_end steps out from spot,
        picks the furthest-OTM strike whose LTP falls in the premium band.
        Falls back to the cheapest available if none qualifies.
        """
        if self.ctx.session_maker is None:
            return

        best_inst = None      # furthest-OTM within band (preferred)
        cheapest_inst = None  # absolute cheapest (fallback)
        cheapest_px = float("inf")

        for offset in range(self._hedge_scan_start, self._hedge_scan_end + 1):
            async with self.ctx.session_maker() as session:
                inst = await resolve_otm_option(
                    session, underlying=self.underlying, spot=spot,
                    option_type=opt_type, otm_steps=offset,
                    strike_step=self._strike_step,
                )
            if inst is None:
                continue
            h_sid = inst.security_id
            await self._subscribe_option(h_sid, segment)
            ltp, _ = (
                await self.ctx.market.ltp_with_age(h_sid)
                if self.ctx.market else (None, None)
            )
            if ltp is None or float(ltp) <= 0:
                continue
            px = float(ltp)
            if px < cheapest_px:
                cheapest_px, cheapest_inst = px, inst
            if self._hedge_prem_min <= px <= self._hedge_prem_max:
                best_inst = inst  # keep updating — last hit = furthest-OTM in band

        target = best_inst or cheapest_inst
        if target is None:
            self.ctx.log.warning("hedge_no_instrument", opt_type=opt_type, spot=spot)
            return

        h_sid = target.security_id
        order = await self._place(h_sid, segment, "BUY", lots)
        if order is None or order.status in ("CANCELLED", "REJECTED"):
            return

        _, avg_px = await self.ctx.orders.get_position(h_sid)
        h_strike = float(target.strike) if target.strike is not None else 0.0
        self._hedge_legs.append(OpenLeg(
            security_id=h_sid, segment=segment, opt_type=opt_type,
            strike=h_strike, lots=lots, entry_price=avg_px, is_hedge=True,
        ))
        self.ctx.log.info("hedge_opened", opt_type=opt_type, strike=h_strike, sid=h_sid)

    # ------------------------------------------------------------------ #
    # Momentum long — ITM+1 on COMPLETE_BULL / COMPLETE_BEAR             #
    # ------------------------------------------------------------------ #

    async def _open_momentum(self, spot: float, bucket: BiasBucket) -> None:
        """Buy ITM+1 option sized to momentum_premium_target (default Rs 50,000)."""
        opt_type = "CE" if bucket == BiasBucket.COMPLETE_BULL else "PE"

        if self.ctx.session_maker is None:
            return

        async with self.ctx.session_maker() as session:
            # otm_steps=-1 selects the first ITM strike (one step into the money)
            inst = await resolve_otm_option(
                session,
                underlying=self.underlying,
                spot=spot,
                option_type=opt_type,
                otm_steps=-1,
                strike_step=self._strike_step,
            )
        if inst is None:
            self.ctx.log.warning("momentum_no_instrument", opt_type=opt_type, spot=spot)
            return

        sid = inst.security_id
        segment = inst.exchange_segment
        strike = float(inst.strike) if inst.strike is not None else 0.0

        await self._subscribe_option(sid, segment)

        ltp, _ = (
            await self.ctx.market.ltp_with_age(sid)
            if self.ctx.market else (None, None)
        )
        premium = float(ltp) if ltp and ltp > 0 else 0.0
        lots = (
            max(1, round(self._momentum_premium_target / (premium * self._lot_size)))
            if premium > 0 else 1
        )

        await self._record_day_baseline(sid)
        order = await self._place(sid, segment, "BUY", lots)
        if order is None or order.status in ("CANCELLED", "REJECTED"):
            return

        _, avg_px = await self.ctx.orders.get_position(sid)
        self._momentum_legs.append(OpenLeg(
            security_id=sid, segment=segment, opt_type=opt_type,
            strike=strike, lots=lots, entry_price=avg_px, is_momentum=True,
        ))
        self.ctx.log.info(
            "momentum_opened", opt_type=opt_type, strike=strike, lots=lots,
            sid=sid, premium=premium, target=self._momentum_premium_target,
        )
        self.log_decision("open", "momentum_itm",
                          opt_type=opt_type, strike=strike, lots=lots, security_id=sid)

    async def _maybe_close_momentum(self, score: float) -> None:
        """Close all momentum longs when |score| falls below threshold."""
        if not self._momentum_legs:
            return
        if abs(score) < self._momentum_score_threshold:
            for leg in list(self._momentum_legs):
                await self._close_momentum_leg(leg, "score_exit")
            self._momentum_legs.clear()

    async def _close_momentum_leg(self, leg: OpenLeg, reason: str) -> None:
        await self.ctx.orders.cancel_open_entry_orders(leg.security_id)
        net_qty = await self.ctx.orders.get_net_qty(leg.security_id)
        if net_qty == 0:
            return
        sell_lots = abs(net_qty) // self._lot_size
        if sell_lots > 0:
            await self._place(leg.security_id, leg.segment, "SELL", sell_lots)
        self.ctx.log.info("momentum_closed", sid=leg.security_id, reason=reason)
        self.log_decision(reason, "momentum_closed", security_id=leg.security_id)

    # ------------------------------------------------------------------ #
    # Leg close                                                            #
    # ------------------------------------------------------------------ #

    async def _close_all(self, reason: str) -> None:
        for leg in list(self._short_legs):
            await self._close_short_leg(leg, reason)
        for leg in list(self._hedge_legs):
            await self._close_hedge_leg(leg, reason)
        for leg in list(self._momentum_legs):
            await self._close_momentum_leg(leg, reason)
        self._short_legs.clear()
        self._hedge_legs.clear()
        self._momentum_legs.clear()
        self._current_bucket = None
        self.log_decision(reason, "all_legs_closed")

    async def _close_shorts_and_hedges(self, reason: str) -> None:
        for leg in list(self._short_legs):
            await self._close_short_leg(leg, reason)
        for leg in list(self._hedge_legs):
            await self._close_hedge_leg(leg, reason)
        self._short_legs.clear()
        self._hedge_legs.clear()
        self._current_bucket = None

    async def _close_short_leg(self, leg: OpenLeg, reason: str) -> None:
        await self.ctx.orders.cancel_open_entry_orders(leg.security_id)
        net_qty = await self.ctx.orders.get_net_qty(leg.security_id)
        if net_qty == 0:
            self._short_legs = [l for l in self._short_legs if l is not leg]
            return
        close_lots = abs(net_qty) // self._lot_size
        if close_lots > 0:
            await self._place(leg.security_id, leg.segment, "BUY", close_lots)
        self.ctx.log.info("short_closed", sid=leg.security_id, reason=reason)
        self.log_decision(reason, "short_closed", security_id=leg.security_id)
        self._short_legs = [l for l in self._short_legs if l is not leg]

    async def _close_hedge_leg(self, leg: OpenLeg, reason: str) -> None:
        await self.ctx.orders.cancel_open_entry_orders(leg.security_id)
        net_qty = await self.ctx.orders.get_net_qty(leg.security_id)
        if net_qty == 0:
            self._hedge_legs = [l for l in self._hedge_legs if l is not leg]
            return
        sell_lots = abs(net_qty) // self._lot_size
        if sell_lots > 0:
            await self._place(leg.security_id, leg.segment, "SELL", sell_lots)
        self.ctx.log.info("hedge_closed", sid=leg.security_id, reason=reason)
        self._hedge_legs = [l for l in self._hedge_legs if l is not leg]

    async def _close_matching_hedge(self, short_leg: OpenLeg) -> None:
        matching = [h for h in self._hedge_legs if h.opt_type == short_leg.opt_type]
        for h in matching:
            await self._close_hedge_leg(h, "tp_hedge_close")

    # ------------------------------------------------------------------ #
    # Day management                                                       #
    # ------------------------------------------------------------------ #

    def _maybe_reset_day(self, bar_day: date) -> None:
        if self._day_key != bar_day:
            self._day_key = bar_day
            self._done_for_day = False
            self._orb_high = None
            self._orb_low = None
            self._vix_day_open = None
            self._vix_day_high = None
            self._vix_recent.clear()
            self._day_baseline.clear()
            self._touched_sids.clear()

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

    # ------------------------------------------------------------------ #
    # VIX                                                                  #
    # ------------------------------------------------------------------ #

    def _update_vix(self, ltp: float) -> None:
        self._vix_now = ltp
        if self._vix_day_open is None:
            self._vix_day_open = ltp
        if self._vix_day_high is None or ltp > self._vix_day_high:
            self._vix_day_high = ltp
        self._vix_recent.append(ltp)
        if len(self._vix_recent) > _VIX_RECENT_WINDOW:
            self._vix_recent.pop(0)

    # ------------------------------------------------------------------ #
    # Helpers                                                              #
    # ------------------------------------------------------------------ #

    def _ratio_for(self, bucket: BiasBucket) -> tuple[int, int]:
        pe, ce = self._ratio_table.get(bucket, (1, 1))
        return pe * self._scale_lots, ce * self._scale_lots

    async def _subscribe_option(self, sid: str, segment: str) -> None:
        if self.ctx.market is not None and sid not in self._subscribed_option_sids:
            if await self.ctx.market.subscribe(sid, segment):
                self._subscribed_option_sids.add(sid)

    async def _find_exact_option(self, opt_type: str, strike: int) -> Any:
        """Fetch instrument row by exact strike for the nearest weekly expiry."""
        if self.ctx.session_maker is None:
            return None
        from decimal import Decimal as D
        from sqlalchemy import select
        from pdp.instruments.models import Instrument

        async with self.ctx.session_maker() as sess:
            expiry = await nearest_weekly_expiry(sess, self.underlying)
            if expiry is None:
                return None
            result = await sess.execute(
                select(Instrument).where(
                    Instrument.underlying == self.underlying,
                    Instrument.expiry == expiry,
                    Instrument.option_type == opt_type.upper(),
                    Instrument.strike == D(str(strike)),
                ).limit(1)
            )
            return result.scalar_one_or_none()

    async def _place(self, security_id: str, segment: str, side: str, lots: int) -> Any:
        qty = lots * self._lot_size
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
                "order_rejected", security_id=security_id, side=side, qty=qty, exc=str(exc),
            )
            return None
