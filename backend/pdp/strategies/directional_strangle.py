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

Parity additions (chunk 4 strangle-execution-console):
  - Per-signal bias votes in bias_evaluated event
  - leg_status heartbeat after every bias_evaluated
  - Rollup: close short when LTP < roll_trigger_prem (20), reopen at next OTM with prem >= 50
  - Stop-gate: 3-bar cooldown (15 min) before re-entry after a stop
  - Weekly Camarilla: ind.pivots(sid, "1w") — seeded from 1w bar aggregation
  - Live PCR: not yet wired (no ind.pcr or accessible poller.latest_pcr)
  - Indicator timeframe audit on startup
"""

from __future__ import annotations

import asyncio
import collections
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from pdp.instruments.expiry_calendar import within_dte
from pdp.instruments.symbols import symbol_for
from pdp.settings import get_settings
from pdp.signals.bias import (
    BiasBucket,
    BiasInputs,
    BiasWeights,
    CamLevels,
    TimeframeEMA,
    score_bias,
)
from pdp.strategy.abc import Strategy
from pdp.strategy.log import StrangleEventType
from pdp.strategy.strikes import (
    STRIKE_STEP,
    nearest_weekly_expiry,
    resolve_otm_option,
)

if TYPE_CHECKING:
    from pdp.market.bars import BarClosed
    from pdp.strategy.context import StrategyContext
    from pdp.strategy.readiness import StrategyReadiness

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


def weights_from_params(p: dict[str, Any]) -> BiasWeights:
    """Build BiasWeights from strategy params.

    Shared by ``on_init`` and ``StrategyHost``'s load-time satisfiability check
    (``pdp.signals.bias.check_bias_satisfiability``) so both read identical
    defaults -- a duplicated copy would silently drift the moment either one's
    defaults changed without the other.
    """
    return BiasWeights(
        w_ema_1h=float(p.get("w_ema_1h", 2.5)),
        w_ema_15m=float(p.get("w_ema_15m", 2.0)),
        w_ema_5m=float(p.get("w_ema_5m", 1.5)),
        w_cam_daily=float(p.get("w_cam_daily", 1.0)),
        w_cam_weekly=float(p.get("w_cam_weekly", 1.0)),
        w_swing=float(p.get("w_swing", 1.0)),
        w_orb=float(p.get("w_orb", 1.0)),
        w_pcr=float(p.get("w_pcr", 1.0)),
        th_complete=float(p.get("th_complete", 0.85)),
        th_most=float(p.get("th_most", 0.60)),
        th_more=float(p.get("th_more", 0.30)),
    )


def _to_cam(pivot_state: Any) -> CamLevels | None:
    if pivot_state is None:
        return None
    return CamLevels(
        r3=pivot_state.cam_r3,
        r4=pivot_state.cam_r4,
        s3=pivot_state.cam_s3,
        s4=pivot_state.cam_s4,
    )


@dataclass
class OpenLeg:
    security_id: str
    segment: str
    opt_type: str  # "PE" or "CE"
    strike: float
    lots: int
    entry_price: Decimal
    is_hedge: bool = False  # True = far-OTM protective long
    is_momentum: bool = False  # True = ITM directional long (COMPLETE_* only)
    half_stopped: bool = False  # True after pct_stop_half partial close (shorts only)
    entry_time: datetime | None = None  # IST-aware open timestamp
    entry_reason: str = ""  # bucket@score at entry (e.g. "NEUTRAL@0.10")
    expiry: date | None = None  # resolved at open time; reused at close (no re-query)
    # Running LTP high/low the position has experienced since it was opened — the
    # trader-facing "day range" for the leg (updated on every on_tick for this sid).
    day_high: float | None = None
    day_low: float | None = None
    # Canonical, durable classifier: "short" | "hedge" | "momentum". Maps 1:1 onto
    # strategy_legs.leg_kind. `is_hedge`/`is_momentum` are kept as synced aliases so
    # existing read sites and OpenLeg(is_hedge=True) constructions keep working.
    kind: str | None = None

    def __post_init__(self) -> None:
        if self.kind is None:
            self.kind = "hedge" if self.is_hedge else ("momentum" if self.is_momentum else "short")
        else:
            self.is_hedge = self.kind == "hedge"
            self.is_momentum = self.kind == "momentum"


def _leg_pnl(leg: OpenLeg, price: float, lots: int, lot_size: int) -> float:
    """Single source of truth for the short/hedge/momentum P&L sign convention.

    Short legs profit when price falls (entry - price); hedge/momentum longs
    profit when price rises (price - entry). Used for both unrealized MTM
    (price = live LTP) and realized P&L at close (price = exit price).

    Guard: if entry_price is 0 (unresolved fill), MTM is 0 — never phantom.
    """
    entry = float(leg.entry_price)
    if entry <= 0:
        return 0.0
    if leg.is_hedge or leg.is_momentum:
        return (price - entry) * lots * lot_size
    return (entry - price) * lots * lot_size


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

        # Last-known-good lot size: YAML seeds it for the very first bar (before the
        # session-start DB resolution in `_maybe_resolve_lot_size` runs); after that the
        # instruments table is authoritative and YAML is only a sanity-check comparison.
        self._lot_size: int = int(p.get("lot_size", 65))
        self._lot_size_yaml: int | None = int(p["lot_size"]) if p.get("lot_size") is not None else None
        self._lot_size_day: date | None = None
        self._lot_size_degraded: bool = False
        self._scale_lots: int = int(p.get("scale_lots", 2))
        self._otm_steps: int = int(p.get("otm_steps", 2))
        self._hedge_prem_min: float = float(p.get("hedge_prem_min", 2.0))
        self._hedge_prem_max: float = float(p.get("hedge_prem_max", 5.0))
        self._hedge_scan_start: int = int(p.get("hedge_scan_start", 10))
        self._hedge_scan_end: int = int(p.get("hedge_scan_end", 22))
        self._strike_step: int = int(p.get("strike_step", STRIKE_STEP.get(self.underlying, 50)))

        self._take_profit_pct: float = float(p.get("take_profit_pct", 0.5))
        self._pct_stop_half: float = float(p.get("pct_stop_half", 0.30))
        self._pct_stop_all: float = float(p.get("pct_stop_all", 0.40))
        self._hedge_enabled: bool = bool(p.get("hedge_enabled", True))
        self._neutral_no_trade: bool = bool(p.get("neutral_no_trade", False))
        self._day_loss_limit: Decimal = Decimal(str(p.get("day_loss_limit", 15000)))
        self._entry_after_ist: time = _parse_hhmm(p.get("entry_after_ist", "10:15"))
        self._squareoff_ist: time = _parse_hhmm(p.get("squareoff_ist", "15:10"))

        # DTE window: open new legs only within `dte_max` calendar days of expiry.
        # None (default) = no filter. Reuses the same `within_dte` helper as the backtest.
        self._dte_max: int | None = int(p["dte_max"]) if p.get("dte_max") is not None else None

        # VIX gate — disabled by default (5yr data shows it costs Rs 33L and increases MaxDD)
        self._vix_gate_enabled: bool = bool(p.get("vix_gate_enabled", False))

        self._hedge_price_wait_s: float = float(p.get("hedge_price_wait_s", 2.0))

        # Momentum long: buy ITM+1 on COMPLETE_BULL/BEAR, close when |score| < threshold
        self._momentum_enabled: bool = bool(p.get("momentum_enabled", True))
        self._momentum_premium_target: int = int(p.get("momentum_premium_target", 50000))
        self._momentum_score_threshold: float = float(p.get("momentum_score_threshold", 0.5))

        # Bucket-change hysteresis: new bucket must persist for N bars before acting.
        self._bucket_confirm_bars: int = int(p.get("bucket_confirm_bars", 2))

        # Entry-side recovery: a side that fails to open (cold LTP, rejected order)
        # is retried within the same bucket episode instead of leaving the book
        # lopsided until the bucket changes. See `strangle-partial-entry-recovery`.
        self._entry_recovery_enabled: bool = bool(p.get("entry_recovery_enabled", True))
        self._entry_recovery_max_attempts: int = int(p.get("entry_recovery_max_attempts", 3))

        # Max seconds to wait for a freshly-subscribed option's first LTP before an open
        # aborts. A newly-subscribed F&O instrument may not have ticked within the ~1.2s
        # broker-fill budget; without this wait the first open of a session aborts cold and
        # (before the no-latch fix) the bucket latched with zero legs. See
        # `strangle-entry-fill-race-and-latch`.
        self._entry_ltp_wait_s: float = float(p.get("entry_ltp_wait_s", 4.0))

        # Rollup params: close short when LTP < roll_trigger_prem, reopen at >= roll_target_min_prem
        self._roll_trigger_prem: float = float(p.get("roll_trigger_prem", 20.0))
        self._roll_target_min_prem: float = float(p.get("roll_target_min_prem", 50.0))

        # Bias weights (dominant tren/cons walk-forward config)
        self._weights = weights_from_params(p)

        raw_rt: dict = p.get("ratio_table", {})
        self._ratio_table: dict[BiasBucket, tuple[int, int]] = (
            {BiasBucket(k): (int(v[0]), int(v[1])) for k, v in raw_rt.items()}
            if raw_rt
            else {
                BiasBucket.COMPLETE_BULL: (5, 0),
                BiasBucket.MOST_BULL: (4, 2),
                BiasBucket.MORE_BULL: (3, 2),
                BiasBucket.NEUTRAL: (3, 3),
                BiasBucket.MORE_BEAR: (2, 3),
                BiasBucket.MOST_BEAR: (2, 4),
                BiasBucket.COMPLETE_BEAR: (0, 5),
            }
        )

        # Runtime state
        # Single source of truth: one OpenLeg per security_id. The per-kind views
        # (_short_legs / _hedge_legs / _momentum_legs) are read-only projections;
        # opening/closing goes through _add_leg/_remove_leg so a duplicate
        # security_id is structurally rejected (one leg owns a security).
        self._legs: dict[str, OpenLeg] = {}
        # Per-sid locks serializing "check position cap, then open" so concurrent
        # opens on the same sid can't both pass the cap check and jointly exceed it.
        self._leg_locks: dict[str, asyncio.Lock] = {}
        self._current_bucket: str | None = None
        self._last_score: float = 0.0
        self._done_for_day: bool = False
        self._day_key: date | None = None
        self._last_readiness_state: str = "ok"
        # Separate from `_last_readiness_state` above (which check_readiness() itself
        # mutates on every call, before on_bar's own gate check ever sees it — using
        # the same flag for both made the gate's "emit once on transition" dead code).
        self._entry_gate_blocked: bool = False
        # Security ids whose in-memory lots disagree with the broker (drives the
        # readiness "Reconciliation" component). Recomputed fresh on every
        # `_reconcile_divergences` pass so a healed mismatch clears the gate rather
        # than latching for the session. `_divergence_shapes` is the session-long
        # alert de-dup — it rate-limits the critical event to once per
        # (sid, mem, broker) shape and is *not* reset when `_divergences` is.
        self._divergences: set[str] = set()
        self._divergence_shapes: set[str] = set()

        self._subscribed_option_sids: set[str] = set()
        self._halt_checked: bool = False  # checked once per day to avoid repeated Redis reads
        self._pending_bucket: str | None = None  # candidate new bucket awaiting confirmation
        self._pending_bucket_count: int = 0  # consecutive bars seen for pending bucket

        # Current bucket episode's intended composition + recovery bookkeeping.
        # Reset every time a bucket transition is confirmed and acted on (see
        # `_maybe_act_on_bucket`'s transition branch) -- never mutated elsewhere.
        self._bucket_target: dict[str, int] = {}  # {"PE": pe_lots, "CE": ce_lots} for this episode
        self._bucket_realized: set[str] = set()  # sides that opened >=1 short leg this episode
        self._recovery_attempts: dict[str, int] = {}  # per-side recovery attempt count this episode

        # Nearest tradeable expiry, cached once per bar day (for the DTE entry gate).
        self._expiry_cache: tuple[date, date | None] | None = None

        self._vix_now: float | None = None
        self._vix_day_open: float | None = None
        self._vix_day_high: float | None = None
        self._vix_recent: list[float] = []
        self._vix_spike_emitted: bool = False

        self._orb_high: float | None = None
        self._orb_low: float | None = None
        self._orb_unseeded: bool = False

        self._day_baseline: dict[str, Decimal] = {}
        self._touched_sids: set[str] = set()

        # LTP cache: updated on every tick for all subscribed options
        self._ltp_cache: dict[str, float] = {}

        # Activity ring buffer: last 200 canonical events; lost on restart (daily log is durable)
        self._activity: collections.deque[dict] = collections.deque(maxlen=200)

        # Stop-gate state: keyed by opt_type ("PE"/"CE")
        # Each entry: {"exit_px": float, "sid": str, "n_below": int}
        self._stop_gate: dict[str, dict] = {}

        # Set of security_ids currently being rolled (prevents re-entrant roll)
        self._rolling: set[str] = set()

        # Cache last spot for use in _roll_leg (on_tick doesn't have bar.close)
        self._last_spot: float | None = None

        # Session start timestamp
        self._started_at: datetime = datetime.now(tz=_IST)

        # Account identifier for canonical log events (paper fallback when env not set)
        self._account_id: str = get_settings().DHAN_CLIENT_ID or "paper"

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
            roll_trigger_prem=self._roll_trigger_prem,
            roll_target_min_prem=self._roll_target_min_prem,
        )

        # Timeframe key audit: check which indicator timeframes are warmed
        ind = ctx.indicators
        warmed: list[str] = []
        missing: list[str] = []
        for tf in ("5m", "15m", "1H"):
            if ind and ind.ema(self.sid, tf) is not None:
                warmed.append(tf)
            else:
                missing.append(tf)
        ctx.log.info(
            "strategy_warmup_check",
            warmed_timeframes=warmed,
            missing_timeframes=missing,
            strategy_id=self.strategy_id,
        )
        for tf in missing:
            ctx.log.warning(
                "strategy_warmup_warning",
                missing_timeframe=tf,
                strategy_id=self.strategy_id,
            )

        # Repair: re-base any currently-open PG positions with avg_price == 0
        await self._repair_zero_avg_positions()

        # Rehydrate open legs from the durable position ledger (restart safety)
        await self._rehydrate_legs()

    # ------------------------------------------------------------------ #
    # Leg structure — one OpenLeg per security_id                          #
    # ------------------------------------------------------------------ #

    @property
    def _short_legs(self) -> list[OpenLeg]:
        return [l for l in self._legs.values() if l.kind == "short"]

    @property
    def _hedge_legs(self) -> list[OpenLeg]:
        return [l for l in self._legs.values() if l.kind == "hedge"]

    @property
    def _momentum_legs(self) -> list[OpenLeg]:
        return [l for l in self._legs.values() if l.kind == "momentum"]

    def _add_leg(self, leg: OpenLeg) -> None:
        """Register a leg. A second leg for a security already tracked is a state
        divergence (the exact 4→8→16 growth mechanism) — reject it loudly."""
        from pdp.events.models import EventType

        existing = self._legs.get(leg.security_id)
        if existing is not None:
            self.ctx.emit_critical(
                EventType.LEG_STATE_DIVERGED,
                leg.security_id,
                "Duplicate leg for security",
                f"attempted to open a {leg.kind} leg for {leg.security_id} already "
                f"tracked as {existing.kind}",
                {"strategy_id": self.strategy_id},
            )
            raise ValueError(f"duplicate leg for security_id {leg.security_id}")
        self._legs[leg.security_id] = leg

    def _remove_leg(self, sid: str) -> None:
        self._legs.pop(sid, None)
        # Drop the cached LTP too — otherwise a rehydration-seeded stand-in (or a
        # stale real tick) could linger past this leg's lifetime and be mistaken
        # for a fresh price if the same sid is re-entered later in the session.
        self._ltp_cache.pop(sid, None)

    async def check_readiness(self) -> StrategyReadiness:
        from pdp.strategy.readiness import ReadinessComponent, StrategyReadiness
        from pdp.broker_sync.models import BrokerFund
        from sqlalchemy import select
        from datetime import datetime, UTC

        components = []
        is_paper = self._mode == "paper"

        # 1. State Reconciliation
        if len(self._divergences) > 0:
            components.append(ReadinessComponent(
                name="Reconciliation",
                state="blocked",
                reason=f"{len(self._divergences)} leg(s) diverged"
            ))
        else:
            components.append(ReadinessComponent(name="Reconciliation", state="ok", reason="State synchronized"))

        # 2. Broker Connection
        if is_paper:
            components.append(ReadinessComponent(name="Broker Sync", state="ok", reason="Paper mode (bypassed)"))
        else:
            last_refresh = None
            if self.ctx.session_maker:
                async with self.ctx.session_maker() as session:
                    row = await session.scalar(select(BrokerFund).where(BrokerFund.account_id == self._account_id))
                    if row is not None and row.synced_at is not None:
                        last_refresh = row.synced_at

            if last_refresh is None:
                components.append(ReadinessComponent(name="Broker Sync", state="blocked", reason="Broker sync never ran"))
            else:
                age = (datetime.now(UTC) - last_refresh).total_seconds()
                if age > 60:
                    components.append(ReadinessComponent(name="Broker Sync", state="degraded", reason=f"Stale broker state ({int(age)}s old)"))
                else:
                    components.append(ReadinessComponent(name="Broker Sync", state="ok", reason="Broker state fresh"))

        # 3. Indicators
        # NB: the engine keys suites by security_id, not the underlying *name*. Passing
        # self.underlying ("NIFTY") returned an empty summary, so this component always
        # reported "ok" and never actually gated on unconverged indicators — the whole
        # point of the check. Key by self.sid ("13"). See strangle-readiness-indicators-truthful.
        ind_blocked = []
        for tf in ["5m", "15m", "1H", "1w"]:
            summary = self.ctx.indicators.seeding_summary(self.sid, tf) if self.ctx.indicators else {}
            for (family, period), is_seeded in summary.items():
                if not is_seeded:
                    suffix = f"({period})" if period else ""
                    ind_blocked.append(f"{family.upper()}{suffix} on {tf}")

        if ind_blocked:
            components.append(ReadinessComponent(
                name="Indicators",
                state="blocked",
                reason=f"Unseeded: {', '.join(ind_blocked)}"
            ))
        else:
            components.append(ReadinessComponent(name="Indicators", state="ok", reason="Indicators seeded"))

        # 4. Chain (PCR)
        w_pcr = getattr(self._weights, "w_pcr", 0)
        if w_pcr > 0:
            pcr_val = self.ctx.chain_hub.get_pcr(self.underlying) if self.ctx.chain_hub else None
            if pcr_val is None:
                components.append(ReadinessComponent(name="Chain", state="blocked", reason="PCR unavailable"))
            else:
                components.append(ReadinessComponent(name="Chain", state="ok", reason="PCR available"))
        else:
            components.append(ReadinessComponent(name="Chain", state="ok", reason="PCR not required"))

        # 5. Bias Satisfiability — spot is the one input every bucket vote needs;
        # a null spot means score_bias() cannot run at all this bar.
        if self._last_spot is None:
            components.append(ReadinessComponent(name="Bias", state="blocked", reason="Spot price unavailable"))
        else:
            components.append(ReadinessComponent(name="Bias", state="ok", reason="Bias inputs satisfiable"))

        readiness = StrategyReadiness.evaluate(components)
        
        # Emit state change if it flipped
        if readiness.state != self._last_readiness_state:
            from pdp.events.models import EventType
            self.ctx.emit_critical(
                EventType.STRATEGY_READINESS_CHANGED,
                self.sid,
                "Readiness State Changed",
                f"Strategy readiness transitioned to {readiness.state}",
                {"previous": self._last_readiness_state, "current": readiness.state, "components": [{"name": c.name, "state": c.state, "reason": c.reason} for c in components]}
            )
            self._last_readiness_state = readiness.state
            
        return readiness

    async def on_bar(self, bar: BarClosed) -> None:
        if bar.security_id != self.sid:
            return

        ist = bar.bar_time.astimezone(_IST)
        bar_day = ist.date()
        now = ist.time()

        self._maybe_reset_day(bar_day)
        await self._maybe_resolve_lot_size(bar_day)

        # On first bar of each day, check Redis for a persisted halt marker.
        if not self._halt_checked:
            await self._maybe_restore_halt_marker()
            self._halt_checked = True

        # 15m bar: capture Opening Range on first bar of the session
        if bar.timeframe == "15m" and not self._orb_high and not self._orb_unseeded:
            expected_windows = (time(9, 15), time(9, 30))
            if now in expected_windows:
                self._orb_high = float(bar.high)
                self._orb_low = float(bar.low)
            else:
                self._orb_unseeded = True
                from pdp.events.models import EventType

                self.ctx.emit_critical(
                    EventType.INDICATOR_UNSEEDED,
                    self.sid,
                    "ORB unseeded",
                    "ORB not seeded from opening window",
                    {
                        "strategy_id": self.strategy_id,
                        "indicator": "ORB",
                        "expected_window": "09:15-09:30",
                        "seen_from": now.strftime("%H:%M"),
                    },
                )

        if bar.timeframe != "5m":
            return

        spot = float(bar.close)
        self._last_spot = spot

        if now >= self._squareoff_ist:
            if self._short_legs or self._hedge_legs or self._momentum_legs:
                await self._close_all("square_off")
            day_pnl = await self._day_realized()
            self._emit_event(StrangleEventType.SQUARE_OFF, reason="square_off", day_pnl=float(day_pnl))
            self._done_for_day = True
            return
        if self._done_for_day:
            return

        if now < self._entry_after_ist:
            self.log_heartbeat(bar.bar_time)
            return

        # Update stop-gate counters on each 5m bar
        self._update_stop_gates()

        day_realized = await self._day_realized()
        if day_realized <= -self._day_loss_limit:
            if self._short_legs or self._hedge_legs or self._momentum_legs:
                await self._close_all("day_loss_cap")
            day_pnl = await self._day_realized()
            self._emit_event(StrangleEventType.DAY_LOSS_CAP, reason="day_loss_cap", day_pnl=float(day_pnl))
            self._done_for_day = True
            # Persist halt so a same-day restart stays halted (cleared by day rollover).
            if self._day_key is not None and self.ctx.market is not None:
                await self.ctx.market.cache_set(self._halt_key(self._day_key), "1", ex=86400)
            return

        # DTE entry gate: new legs open only within `dte_max` days of expiry.
        # Existing legs are still managed (exits run in on_tick; bucket-change closes below).
        entry_allowed = await self._entry_within_dte(bar_day)


        readiness = await self.check_readiness()
        if readiness.is_blocked:
            if not self._entry_gate_blocked:
                self.ctx.log.warning("strategy_not_ready", components=[c.name for c in readiness.components if c.state == "blocked"])
                self._emit_event(StrangleEventType.STRATEGY_NOT_READY, reason=readiness.components[0].reason)
                self._entry_gate_blocked = True
            return

        if self._entry_gate_blocked:
            self.ctx.log.info("strategy_ready")
            self._entry_gate_blocked = False

        inp = self._build_bias_inputs(spot)
        result = score_bias(inp, weights=self._weights, ratio_table=self._ratio_table)
        self._last_score = result.score

        # Canonical bias_evaluated event (replaces ad-hoc log_heartbeat + ctx.log.info)
        self._emit_event(
            StrangleEventType.BIAS_EVALUATED,
            score=round(result.score, 3),
            bucket=result.bucket.value if result.bucket else None,
            gated=result.gated,
            reason="dte_gated" if not entry_allowed else result.reason,
            shorts=len(self._short_legs),
            momentum=len(self._momentum_legs),
            votes=result.votes,
            # Per-input vote/weight/abstained, keyed by input name -- queryable field
            # names in OpenSearch (breakdown.cam_weekly.abstained), not a formatted
            # string, so a permanently-abstaining input is visible in the log rather
            # than inferred from a suspicious bucket distribution.
            breakdown={
                name: {"vote": vb.vote, "weight": vb.weight, "abstained": vb.abstained}
                for name, vb in result.breakdown.items()
            },
        )

        # Leg status heartbeat after every bias_evaluated
        self._emit_leg_status()

        if result.gated:
            if "vix_spike_gt_5pct" in result.reason and not getattr(self, "_vix_spike_emitted", False):
                self._vix_spike_emitted = True
                from pdp.events.models import EventType

                self.ctx.emit_critical(
                    EventType.VIX_SPIKE,
                    self.sid,
                    "VIX Spike Detected",
                    f"VIX intraday spike exceeded 5%: {result.reason}",
                    {
                        "strategy_id": self.strategy_id,
                        "vix_open": self._vix_day_open,
                        "vix_high": self._vix_day_high,
                    },
                )
            return

        if result.bucket == BiasBucket.NEUTRAL and self._neutral_no_trade:
            if self._short_legs or self._hedge_legs:
                await self._close_shorts_and_hedges("neutral_skip")
            await self._maybe_close_momentum(result.score)
            return

        bucket_str = result.bucket.value
        pe_lots, ce_lots = self._ratio_for(result.bucket)

        if self._current_bucket != bucket_str:
            # Hysteresis: new bucket must persist for bucket_confirm_bars consecutive bars.
            if self._pending_bucket == bucket_str:
                self._pending_bucket_count += 1
            else:
                self._pending_bucket = bucket_str
                self._pending_bucket_count = 1

            if self._pending_bucket_count >= self._bucket_confirm_bars:
                # Confirmation met. Close any legs held for the old bucket first.
                if self._short_legs or self._hedge_legs:
                    self._emit_event(
                        StrangleEventType.BUCKET_CHANGE,
                        old_bucket=self._current_bucket,
                        new_bucket=bucket_str,
                    )
                    await self._close_shorts_and_hedges("bucket_change")

                # Commit the bucket transition ONLY when a leg actually opened. A DTE-gated
                # bar (legitimate no-trade) or a transient fill-price failure must not latch
                # `_current_bucket`, so the open is retried on the next bar rather than the
                # bucket sticking with zero legs for the rest of the day.
                if entry_allowed:
                    # New episode: reset intended composition + recovery bookkeeping
                    # before attempting the open, so a fresh commit starts clean.
                    self._bucket_target = {"PE": pe_lots, "CE": ce_lots}
                    self._bucket_realized = set()
                    self._recovery_attempts = {}
                    opened = await self._open_bucket(spot, pe_lots, ce_lots)
                    expected = (1 if pe_lots > 0 else 0) + (1 if ce_lots > 0 else 0)
                    if opened > 0:
                        self._current_bucket = bucket_str
                        self._pending_bucket = None
                        self._pending_bucket_count = 0
                        if opened < expected:
                            self._emit_event(
                                StrangleEventType.ENTRY_ABORTED,
                                bucket=bucket_str,
                                pe_lots=pe_lots,
                                ce_lots=ce_lots,
                                opened=opened,
                                reason="partial_open",
                            )
                        if self._entry_recovery_enabled and not self._lot_size_degraded:
                            await self._reconcile_bucket_composition(spot)
                    else:
                        # Nothing opened (e.g. cold LTP) — keep the pending bucket so the
                        # next 5m bar retries, and surface the abort so it is not invisible.
                        self._emit_event(
                            StrangleEventType.ENTRY_ABORTED,
                            bucket=bucket_str,
                            pe_lots=pe_lots,
                            ce_lots=ce_lots,
                            opened=0,
                            reason="fill_unresolved",
                        )
        else:
            # Bucket matches current — clear any pending confirmation and reconcile
            # composition: retry any side that never opened this episode.
            self._pending_bucket = None
            self._pending_bucket_count = 0
            if entry_allowed and self._entry_recovery_enabled and not self._lot_size_degraded:
                await self._reconcile_bucket_composition(spot)

        if self._momentum_enabled:
            if entry_allowed and result.bucket in _EXTREME_BUCKETS and not self._momentum_legs:
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

        # Update LTP cache for all option ticks
        self._ltp_cache[sid] = ltp

        # Maintain the running day high/low for every open leg on this sid (all leg
        # types) so the execution console can show the range the position has seen.
        for lg in self._short_legs + self._hedge_legs + self._momentum_legs:
            if lg.security_id != sid:
                continue
            lg.day_high = ltp if lg.day_high is None else max(lg.day_high, ltp)
            lg.day_low = ltp if lg.day_low is None else min(lg.day_low, ltp)

        # Only watch short legs (momentum longs exit on score signal, not premium)
        legs = [lg for lg in self._short_legs if lg.security_id == sid]
        for leg in legs:
            entry = float(leg.entry_price)
            if entry <= 0:
                continue

            # Rollup: close and reopen when premium decays below roll_trigger_prem.
            # Claim the roll atomically under the sid lock so two concurrent ticks
            # can't both pass the `not in _rolling` check and roll the same leg
            # twice. The lock is released before _roll_leg runs (it re-acquires the
            # same lock per close/open), so there is no non-reentrant deadlock.
            if ltp < self._roll_trigger_prem:
                async with self._lock_for(sid):
                    if sid in self._rolling:
                        return
                    self._rolling.add(sid)
                try:
                    await self._roll_leg(leg, old_ltp=ltp)
                finally:
                    self._rolling.discard(sid)
                return

            if ltp <= entry * self._take_profit_pct:
                await self._close_short_leg(
                    leg,
                    "take_profit",
                    event_type=StrangleEventType.TAKE_PROFIT,
                )
                await self._close_matching_hedge(leg)
                return
            if not leg.half_stopped and ltp >= entry * (1 + self._pct_stop_half):
                if leg.lots // 2 > 0:
                    # Partial close through the shared locked helper: side derives
                    # from the broker net_qty sign (never a hardcoded BUY), so a
                    # misclassified long leg is flattened with SELL, not grown.
                    closed = await self._partial_close(
                        leg,
                        leg.lots // 2,
                        "stop_half",
                        StrangleEventType.STOP_HALF,
                        ltp=ltp,
                    )
                    if closed:
                        leg.half_stopped = True
                        # Record stop gate for this side
                        self._stop_gate[leg.opt_type] = {
                            "exit_px": ltp,
                            "sid": sid,
                            "n_below": 0,
                        }
                        # leg.lots just changed (halved) — re-check stop-all against
                        # the now-smaller remaining position on the NEXT tick, not
                        # this one, so we never emit two terminal closes for one tick.
                        continue
                    # closed == False: broker held fewer lots than expected (e.g. a
                    # transient divergence) and nothing was actually reduced. Do not
                    # latch half_stopped — fall through so this same threshold can
                    # retry on a later tick once the broker position catches up.
            if ltp >= entry * (1 + self._pct_stop_all):
                # Record stop gate before closing
                self._stop_gate[leg.opt_type] = {
                    "exit_px": ltp,
                    "sid": sid,
                    "n_below": 0,
                }
                await self._close_short_leg(
                    leg,
                    "premium_stop",
                    event_type=StrangleEventType.STOP_ALL,
                )
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
    # Canonical event emission                                             #
    # ------------------------------------------------------------------ #

    def _emit_event(self, event_type: str, **fields: Any) -> None:
        """Emit a structured canonical event to structlog, daily log file, and activity buffer."""
        ist_now = datetime.now(tz=_IST).isoformat()
        record: dict[str, Any] = {
            "event_type": event_type,
            "strategy_id": self.strategy_id,
            "account_id": self._account_id,
            "snapshot_date": self._day_key.isoformat() if self._day_key else None,
            "ist_time": ist_now,
            "underlying": self.underlying,
            "spot": self._last_spot,
            "score": round(self._last_score, 3),
            "bucket": self._current_bucket,
            **fields,
        }
        self.ctx.log.info(
            event_type, **{k: str(v) if isinstance(v, Decimal) else v for k, v in record.items()}
        )

        # Durable DB-first persistence
        event_service = self.ctx._event_service
        if event_service is not None and event_service.writer is not None:
            mongo_doc = dict(record)
            mongo_doc["ts"] = datetime.now(UTC)  # needed for TTL
            self.ctx._event_service.writer.enqueue(mongo_doc)

        if self._slog:
            self._slog.write(record)
        self._activity.append(record)

    def _emit_leg_status(self) -> None:
        """Emit a leg_status snapshot after each bias_evaluated."""
        legs = []
        for lg in self._short_legs + self._hedge_legs:
            ltp = self._ltp_cache.get(lg.security_id)
            mtm: float | None = None
            if ltp is not None:
                mtm = round(_leg_pnl(lg, ltp, lg.lots, self._lot_size), 2)
            legs.append(
                {
                    "security_id": lg.security_id,
                    "opt_type": lg.opt_type,
                    "strike": lg.strike,
                    "lots": lg.lots,
                    "entry_price": float(lg.entry_price),
                    "ltp": ltp,
                    "mtm": mtm,
                    "is_hedge": lg.is_hedge,
                }
            )
        self._emit_event(StrangleEventType.LEG_STATUS, legs=legs)

    # ------------------------------------------------------------------ #
    # Stop-gate management                                                 #
    # ------------------------------------------------------------------ #

    def _update_stop_gates(self) -> None:
        """Called on each 5m bar: update cooldown counters; clear gates when safe to re-enter.

        Gates marked ready=True on bar N are removed at the START of bar N+1 so re-entry
        only becomes possible on the bar after the 3-bar cooldown completes (spec §3 scenario).
        """
        # Phase 1: clear gates that completed their cooldown on the previous bar
        to_clear = [ot for ot, g in self._stop_gate.items() if g.get("ready")]
        for opt_type in to_clear:
            del self._stop_gate[opt_type]
            self.ctx.log.info("stop_gate_cleared", opt_type=opt_type)

        # Phase 2: update remaining gates
        for opt_type, gate in self._stop_gate.items():
            ltp = self._ltp_cache.get(gate["sid"])
            if ltp is None:
                self._emit_event(StrangleEventType.STOP_GATE_WAIT, opt_type=opt_type, reason="no_ltp")
                continue
            if ltp < gate["exit_px"]:
                gate["n_below"] += 1
                if gate["n_below"] >= 3:
                    gate["ready"] = True  # will be cleared at start of NEXT bar
                    continue
            else:
                gate["n_below"] = 0
            self._emit_event(
                StrangleEventType.STOP_GATE_WAIT,
                opt_type=opt_type,
                exit_px=gate["exit_px"],
                ltp=ltp,
                n_below=gate["n_below"],
            )

    # ------------------------------------------------------------------ #
    # Bias input assembly                                                  #
    # ------------------------------------------------------------------ #

    def _build_bias_inputs(self, spot: float) -> BiasInputs:
        ind = self.ctx.indicators

        ema_5m = _to_tf_ema(ind.ema(self.sid, "5m"), spot) if ind else None
        ema_15m = _to_tf_ema(ind.ema(self.sid, "15m"), spot) if ind else None
        ema_1h = _to_tf_ema(ind.ema(self.sid, "1H"), spot) if ind else None

        pivot = ind.pivots(self.sid, "1D") if ind else None
        cam_daily = _to_cam(pivot)

        weekly_pivot = ind.pivots(self.sid, "1w") if ind else None
        cam_weekly = _to_cam(weekly_pivot)

        pl = ind.period_levels(self.sid, "5m") if ind else None

        # PCR: read from chain hub if wired (only available during live chain polling)
        pcr: float | None = None
        if self.ctx.chain_hub is not None:
            pcr = self.ctx.chain_hub.get_pcr(self.underlying)

        return BiasInputs(
            spot=spot,
            ema_1h=ema_1h,
            ema_15m=ema_15m,
            ema_5m=ema_5m,
            cam_daily=cam_daily,
            cam_weekly=cam_weekly,
            pdh=pl.pdh if pl else None,
            pdl=pl.pdl if pl else None,
            pwh=pl.pwh if pl else None,
            pwl=pl.pwl if pl else None,
            orb_high=self._orb_high,
            orb_low=self._orb_low,
            pcr=pcr,
            vix_now=self._vix_now if self._vix_gate_enabled else None,
            vix_day_open=self._vix_day_open if self._vix_gate_enabled else None,
            vix_day_high=self._vix_day_high if self._vix_gate_enabled else None,
            vix_recent=list(self._vix_recent) if self._vix_gate_enabled else [],
        )

    # ------------------------------------------------------------------ #
    # Leg open — shorts + protective hedges                               #
    # ------------------------------------------------------------------ #

    async def _resolve_current_expiry(self, bar_day: date) -> date | None:
        """Nearest tradeable expiry for the underlying, resolved once per bar day.

        Uses the same scrip-master lookup the strike resolver uses (never a hardcoded
        weekday). Cached per day so the DTE gate does not hit the DB on every bar.
        """
        if self._expiry_cache is not None and self._expiry_cache[0] == bar_day:
            return self._expiry_cache[1]
        expiry: date | None = None
        if self.ctx.session_maker is not None:
            async with self.ctx.session_maker() as sess:
                expiry = await nearest_weekly_expiry(sess, self.underlying)
        self._expiry_cache = (bar_day, expiry)
        return expiry

    async def _entry_within_dte(self, bar_day: date) -> bool:
        """Whether new-leg entry is allowed today under the DTE window.

        Reuses the shared ``within_dte`` helper so live and backtest agree exactly.
        ``dte_max=None`` disables the filter (always True).
        """
        if self._dte_max is None:
            return True
        expiry = await self._resolve_current_expiry(bar_day)
        return within_dte(bar_day, expiry, self._dte_max)

    async def _open_bucket(self, spot: float, pe_lots: int, ce_lots: int) -> int:
        """Open the bucket's PE/CE short legs; return how many short legs actually opened.

        The caller commits the bucket transition only when this returns > 0, so a
        transient fill-price failure retries on the next bar instead of latching the
        bucket for the rest of the day — see `strangle-entry-fill-race-and-latch`.
        """
        opened = 0
        if pe_lots > 0 and await self._open_short(spot, "PE", pe_lots):
            opened += 1
        if ce_lots > 0 and await self._open_short(spot, "CE", ce_lots):
            opened += 1
        return opened

    async def _reconcile_bucket_composition(self, spot: float) -> None:
        """Recover any bucket-required side that never opened this episode.

        Runs on the bucket-unchanged path (every bar) and once more immediately
        after the initial `_open_bucket` on a confirmed transition, so a same-bar
        partial abort is retried without waiting a full bar. A side is skipped
        when it already holds an open short leg, was realized then deliberately
        exited this episode (take-profit/roll), or is currently stop-gated --
        only a side that never successfully opened is retried. Bounded to
        `_entry_recovery_max_attempts` attempts per side per episode; on
        exhaustion emits one terminal `ENTRY_SIDE_UNFILLED` and stops retrying
        that side until the next bucket change. See `strangle-partial-entry-recovery`.
        """
        for side in ("PE", "CE"):
            target = self._bucket_target.get(side, 0)
            if target <= 0:
                continue
            if self._open_short_lots(side) > 0:
                continue
            if side in self._bucket_realized:
                continue
            if side in self._stop_gate:
                continue
            attempts = self._recovery_attempts.get(side, 0)
            if attempts >= self._entry_recovery_max_attempts:
                if attempts == self._entry_recovery_max_attempts:
                    self._recovery_attempts[side] = attempts + 1
                    self._emit_event(
                        StrangleEventType.ENTRY_SIDE_UNFILLED,
                        opt_type=side,
                        attempts=attempts,
                        bucket=self._current_bucket,
                    )
                continue
            self._recovery_attempts[side] = attempts + 1
            self._emit_event(
                StrangleEventType.ENTRY_RECOVERY_ATTEMPT,
                opt_type=side,
                attempt=attempts + 1,
                target_lots=target,
            )
            await self._open_short(spot, side, target)

    def _entry_reason(self) -> str:
        """`"<bucket>@<score>"` for a leg's `entry_reason`, guarded against an unset
        bucket so a leg opened before the first bias score never renders the
        literal `"None"`."""
        return f"{self._current_bucket or 'unknown'}@{self._last_score:.2f}"

    async def _seed_rehydrated_ltp(self, sid: str, entry_price: Decimal) -> None:
        """Prime `_ltp_cache[sid]` for a just-rehydrated leg so the console shows a
        price and non-blank P&L immediately, rather than `--` during the cold window
        after restart before the next live option tick lands.

        Prefers the live Redis LTP (via the market feed); falls back to the leg's avg
        entry price so P&L reads ~0 rather than blank. A later real tick overwrites
        this seed in `on_tick`. No-ops if neither source yields a positive price.
        """
        if self._ltp_cache.get(sid):
            return
        if self.ctx.market is not None:
            ltp, _ = await self.ctx.market.ltp_with_age(sid)
            if ltp and ltp > 0:
                self._ltp_cache[sid] = float(ltp)
                return
        if entry_price and entry_price > Decimal("0"):
            self._ltp_cache[sid] = float(entry_price)

    async def _await_option_ltp(self, sid: str) -> bool:
        """Wait up to `_entry_ltp_wait_s` for a freshly-subscribed option's first LTP.

        Returns True once a positive LTP is visible (in-process cache or market feed),
        so the subsequent MARKET order can fill on the first tick rather than aborting
        cold. Returns False if no tick arrives within the budget (caller still attempts
        the open; the existing fill-price fallbacks + abort path handle a cold leg).
        """
        deadline = asyncio.get_running_loop().time() + self._entry_ltp_wait_s
        while asyncio.get_running_loop().time() < deadline:
            cached = self._ltp_cache.get(sid)
            if cached and cached > 0:
                return True
            if self.ctx.market is not None:
                ltp, _ = await self.ctx.market.ltp_with_age(sid)
                if ltp and ltp > 0:
                    return True
            await asyncio.sleep(0.2)
        return False

    async def _resolve_fill_price(self, sid: str) -> Decimal | None:
        """Resolve a real fill reference price via four fallback layers.

        1. Broker avg (from PaperBroker / DhanBroker position)
        2. In-process LTP cache (updated on every on_tick)
        3. Market feed ltp_with_age (Redis)
        4. Last bar close (not implemented here — rare cold-start fallback)

        Returns None only if all four layers are exhausted.
        """
        # Layer 1: broker avg
        for _ in range(8):
            _, avg_px = await self.ctx.orders.get_position(sid)
            if avg_px and avg_px > 0:
                return avg_px
            await asyncio.sleep(0.15)
        _, avg_px = await self.ctx.orders.get_position(sid)
        if avg_px and avg_px > 0:
            return avg_px

        # Layer 2: in-process LTP cache
        ltp_cached = self._ltp_cache.get(sid)
        if ltp_cached and ltp_cached > 0:
            self.ctx.log.warning("fill_avg_px_ltp_fallback", sid=sid, source="ltp_cache", ltp=ltp_cached)
            return Decimal(str(ltp_cached))

        # Layer 3: market feed Redis
        if self.ctx.market is not None:
            ltp_feed, _ = await self.ctx.market.ltp_with_age(sid)
            if ltp_feed and ltp_feed > 0:
                self.ctx.log.warning("fill_avg_px_ltp_fallback", sid=sid, source="market_feed", ltp=float(ltp_feed))
                return Decimal(str(ltp_feed))

        self.ctx.log.warning("fill_avg_px_zero", sid=sid)
        return None

    async def _await_fill_avg_px(self, sid: str) -> Decimal | None:
        """Poll broker until filled then fall through to resolve_fill_price.

        Returns a Decimal > 0 on success, or None if all fallback layers are cold.
        Callers MUST check for None and abort the leg open rather than recording
        entry_price=0 which would make MTM compute as -ltp×qty.
        """
        return await self._resolve_fill_price(sid)

    async def _open_short(self, spot: float, opt_type: str, lots: int) -> bool:
        """Open one short OTM leg; return True iff the short leg remains open afterwards.

        Returns False on every skip/abort path (lot-size degraded, stop-gate, no
        instrument, cap-refused, order rejected, unresolved fill price) and also when a
        hedge failure squares the just-opened short (`naked_hedge_averted`) — the caller
        treats a False as "nothing opened" and retries on the next bar rather than
        latching the bucket. See `strangle-entry-fill-race-and-latch`.
        """
        if self._lot_size_degraded:
            return False
        # Stop-gate check: block re-entry for 3 bars after a stop on this side
        if opt_type in self._stop_gate:
            self._emit_event(StrangleEventType.STOP_GATE_WAIT, opt_type=opt_type, reason="open_blocked")
            return False

        if self.ctx.session_maker is None:
            return False

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
            return False

        sid = inst.security_id
        segment = inst.exchange_segment
        strike = float(inst.strike) if inst.strike is not None else 0.0

        # The cap check + order placement run under sid's lock so two concurrent
        # opens on the same sid (e.g. a rollup racing a bucket-change) can't both
        # pass the cap check and jointly exceed it — see _reserve_leg_lots.
        async with self._lock_for(sid):
            reserved_lots = await self._reserve_leg_lots(sid, opt_type, lots, "short leg")
            if reserved_lots is None:
                return False
            lots = reserved_lots

            await self._subscribe_option(sid, segment)
            # Give a freshly-subscribed option a bounded moment to produce its first tick,
            # so the MARKET order below fills instead of aborting cold (subscribe→fill race).
            await self._await_option_ltp(sid)
            await self._record_day_baseline(sid)

            order = await self._place(sid, segment, "SELL", lots)
            if order is None or order.status in ("CANCELLED", "REJECTED"):
                return False

            avg_px = await self._await_fill_avg_px(sid)
            if avg_px is None or avg_px <= 0:
                # Cannot resolve entry price — abort and square the leg.
                await self.ctx.orders.cancel_open_entry_orders(sid)
                from pdp.events.models import EventType

                self.ctx.emit_critical(
                    EventType.MISSING_LTP,
                    sid,
                    "Entry price unresolved",
                    f"short leg {sid} aborted: entry price could not be resolved after all fallbacks",
                    {"strategy_id": self.strategy_id, "opt_type": opt_type},
                )
                return False
            _reason = self._entry_reason()
            leg = OpenLeg(
                security_id=sid,
                segment=segment,
                opt_type=opt_type,
                strike=strike,
                lots=lots,
                entry_price=avg_px,
                entry_time=datetime.now(tz=_IST),
                entry_reason=_reason,
                expiry=inst.expiry,
            )
            try:
                self._add_leg(leg)
            except ValueError:
                # _add_leg already emitted LEG_STATE_DIVERGED critical. The broker
                # order above already filled — do not crash the whole strategy over
                # a leg we can't register; the orphan position surfaces via the next
                # _reconcile_divergences() poll instead of taking every other leg's
                # management offline with it.
                return False
            await self._persist_leg_open(leg)
            self._emit_event(
                StrangleEventType.LEG_OPEN,
                sid=sid,
                opt_type=opt_type,
                strike=strike,
                lots=lots,
                entry_price=float(avg_px),
                is_hedge=False,
                expiry=inst.expiry.isoformat() if inst.expiry else None,
            )

        if self._hedge_enabled:
            await self._open_hedge(opt_type, spot, lots, segment, short_leg=leg)

        # The hedge path squares the short (`naked_hedge_averted`) when it cannot price a
        # wing, so report success by whether the short leg is still tracked — a squared
        # short is "not opened" and must be retried, not latched. Mark realized only
        # once the short has survived the hedge step too: marking it earlier would let
        # a naked_hedge_averted square-off permanently block recovery for this side for
        # the rest of the episode, since a realized side is never retried (see
        # `strangle-partial-entry-recovery` review).
        opened = leg.security_id in self._legs
        if opened:
            self._bucket_realized.add(opt_type)
        return opened

    async def _open_hedge(
        self, opt_type: str, spot: float, lots: int, segment: str, short_leg: OpenLeg | None = None
    ) -> None:
        """Buy cheapest far-OTM wing priced in [hedge_prem_min, hedge_prem_max].

        Scans OTM strikes from hedge_scan_start to hedge_scan_end steps out from spot,
        picks the furthest-OTM strike whose LTP falls in the premium band.
        Falls back to the cheapest available if none qualifies.
        """
        if self._lot_size_degraded:
            return
        if self.ctx.session_maker is None:
            return

        async def _scan() -> Any | None:
            best = None
            cheapest = None
            cheapest_px = float("inf")
            for offset in range(self._hedge_scan_start, self._hedge_scan_end + 1):
                async with self.ctx.session_maker() as session:
                    inst = await resolve_otm_option(
                        session,
                        underlying=self.underlying,
                        spot=spot,
                        option_type=opt_type,
                        otm_steps=offset,
                        strike_step=self._strike_step,
                    )
                if inst is None:
                    continue
                h_sid = inst.security_id
                await self._subscribe_option(h_sid, segment)
                ltp, _ = await self.ctx.market.ltp_with_age(h_sid) if self.ctx.market else (None, None)
                if ltp is None or float(ltp) <= 0:
                    continue
                px = float(ltp)
                if px < cheapest_px:
                    cheapest_px, cheapest = px, inst
                if self._hedge_prem_min <= px <= self._hedge_prem_max:
                    best = inst
            return best or cheapest

        target = await _scan()
        if target is None:
            await asyncio.sleep(self._hedge_price_wait_s)
            target = await _scan()

        if target is None:
            self.ctx.log.warning("hedge_no_instrument", opt_type=opt_type, spot=spot)
            if short_leg is not None:
                await self._close_short_leg(
                    short_leg, "naked_hedge_averted", event_type=StrangleEventType.LEG_CLOSE
                )
            from pdp.events.models import EventType

            self.ctx.emit_critical(
                EventType.NAKED_POSITION,
                self.sid,
                "Naked short averted",
                "hedge unpriced after wait",
                {"strategy_id": self.strategy_id, "opt_type": opt_type},
            )
            return

        h_sid = target.security_id

        async with self._lock_for(h_sid):
            reserved_lots = await self._reserve_leg_lots(h_sid, opt_type, lots, "hedge leg")
            if reserved_lots is None:
                return
            lots = reserved_lots

            await self._record_day_baseline(h_sid)
            order = await self._place(h_sid, segment, "BUY", lots)
            if order is None or order.status in ("CANCELLED", "REJECTED"):
                return

            avg_px = await self._await_fill_avg_px(h_sid)
            if avg_px is None or avg_px <= 0:
                # Cannot resolve entry price for hedge — abort.
                await self.ctx.orders.cancel_open_entry_orders(h_sid)
                from pdp.events.models import EventType

                self.ctx.emit_critical(
                    EventType.MISSING_LTP,
                    h_sid,
                    "Hedge entry price unresolved",
                    f"hedge leg {h_sid} aborted: entry price could not be resolved",
                    {"strategy_id": self.strategy_id, "opt_type": opt_type},
                )
                return
            h_strike = float(target.strike) if target.strike is not None else 0.0
            _reason = self._entry_reason()
            hedge_leg = OpenLeg(
                security_id=h_sid,
                segment=segment,
                opt_type=opt_type,
                strike=h_strike,
                lots=lots,
                entry_price=avg_px,
                is_hedge=True,
                entry_time=datetime.now(tz=_IST),
                entry_reason=_reason,
                expiry=target.expiry,
            )
            try:
                self._add_leg(hedge_leg)
            except ValueError:
                # See _open_short's identical guard: the broker order already
                # filled, so swallow rather than crash every other leg's management.
                return
            await self._persist_leg_open(hedge_leg)
            self._emit_event(
                StrangleEventType.LEG_OPEN,
                sid=h_sid,
                opt_type=opt_type,
                strike=h_strike,
                lots=lots,
                entry_price=float(avg_px),
                is_hedge=True,
                expiry=target.expiry.isoformat() if target.expiry else None,
            )

    # ------------------------------------------------------------------ #
    # Momentum long — ITM+1 on COMPLETE_BULL / COMPLETE_BEAR             #
    # ------------------------------------------------------------------ #

    async def _open_momentum(self, spot: float, bucket: BiasBucket) -> None:
        """Buy ITM+1 option sized to momentum_premium_target (default Rs 50,000)."""
        if self._lot_size_degraded:
            return
        opt_type = "CE" if bucket == BiasBucket.COMPLETE_BULL else "PE"

        if self.ctx.session_maker is None:
            return

        async def _scan() -> tuple[Any, Any]:
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
                return None, None

            h_sid = inst.security_id
            await self._subscribe_option(h_sid, inst.exchange_segment)
            ltp, _ = await self.ctx.market.ltp_with_age(h_sid) if self.ctx.market else (None, None)
            return inst, ltp

        inst, ltp = await _scan()
        if inst is not None and (ltp is None or float(ltp) <= 0):
            await asyncio.sleep(self._hedge_price_wait_s)
            inst, ltp = await _scan()

        if inst is None or ltp is None or float(ltp) <= 0:
            self.ctx.log.warning("momentum_no_instrument", opt_type=opt_type, spot=spot)
            from pdp.events.models import EventType

            self.ctx.emit_critical(
                EventType.NAKED_POSITION,
                self.sid,
                "Momentum unpriced",
                "momentum unpriced after wait",
                {"strategy_id": self.strategy_id, "opt_type": opt_type},
            )
            return

        sid = inst.security_id
        segment = inst.exchange_segment
        strike = float(inst.strike) if inst.strike is not None else 0.0

        premium = float(ltp)
        lots = max(1, round(self._momentum_premium_target / (premium * self._lot_size))) if premium > 0 else 1

        async with self._lock_for(sid):
            # NOTE: _max_leg_lots() is derived from the ratio table (short/hedge
            # sizing), not momentum's premium-target formula — it's used here purely
            # as a safety backstop against unbounded growth, not a tuned momentum
            # ceiling. momentum_enabled is False in every live config today.
            reserved_lots = await self._reserve_leg_lots(sid, opt_type, lots, "momentum leg")
            if reserved_lots is None:
                return
            lots = reserved_lots

            await self._record_day_baseline(sid)
            order = await self._place(sid, segment, "BUY", lots)
            if order is None or order.status in ("CANCELLED", "REJECTED"):
                return

            avg_px = await self._await_fill_avg_px(sid)
            if avg_px is None or avg_px <= 0:
                await self.ctx.orders.cancel_open_entry_orders(sid)
                from pdp.events.models import EventType

                self.ctx.emit_critical(
                    EventType.MISSING_LTP,
                    sid,
                    "Momentum entry price unresolved",
                    f"momentum leg {sid} aborted: entry price could not be resolved",
                    {"strategy_id": self.strategy_id, "opt_type": opt_type},
                )
                return
            _reason = self._entry_reason()
            momentum_leg = OpenLeg(
                security_id=sid,
                segment=segment,
                opt_type=opt_type,
                strike=strike,
                lots=lots,
                entry_price=avg_px,
                is_momentum=True,
                entry_time=datetime.now(tz=_IST),
                entry_reason=_reason,
                expiry=inst.expiry,
            )
            try:
                self._add_leg(momentum_leg)
            except ValueError:
                # See _open_short's identical guard: the broker order already
                # filled, so swallow rather than crash every other leg's management.
                return
            await self._persist_leg_open(momentum_leg)
            self._emit_event(
                StrangleEventType.LEG_OPEN,
                sid=sid,
                opt_type=opt_type,
                strike=strike,
                lots=lots,
                entry_price=float(avg_px),
                is_momentum=True,
                premium=premium,
                target=self._momentum_premium_target,
                expiry=inst.expiry.isoformat() if inst.expiry else None,
            )

    async def _maybe_close_momentum(self, score: float) -> None:
        """Close all momentum longs when |score| falls below threshold."""
        if not self._momentum_legs:
            return
        if abs(score) < self._momentum_score_threshold:
            for leg in list(self._momentum_legs):
                await self._close_momentum_leg(leg, "score_exit")

    async def _close_momentum_leg(self, leg: OpenLeg, reason: str) -> None:
        await self._close_leg(leg, reason)

    # ------------------------------------------------------------------ #
    # Rollup                                                               #
    # ------------------------------------------------------------------ #

    async def _roll_leg(self, leg: OpenLeg, old_ltp: float) -> None:
        """Roll a decayed short (LTP < roll_trigger_prem) to the same OTM level.

        All-or-nothing: every precondition (spot, a resolvable instrument, and
        sufficient premium on it) is verified BEFORE the old short and its hedge
        are closed. A roll that cannot reopen therefore leaves the existing
        position exactly as it was, rather than closing it and stranding the
        strategy short-less (the leg-growth incident closed first, then failed to
        reopen, and the next bar opened *another* leg). The `_rolling` claim and
        its release are owned by the `on_tick` caller under the sid lock.
        """
        old_strike = leg.strike
        old_opt_type = leg.opt_type
        old_lots = leg.lots

        spot = self._last_spot
        if not spot or self.ctx.session_maker is None:
            self._emit_event(
                StrangleEventType.ROLLED,
                opt_type=old_opt_type,
                old_strike=old_strike,
                old_ltp=round(old_ltp, 2),
                lots=old_lots,
                result="skipped_no_spot",
            )
            return

        async with self.ctx.session_maker() as session:
            new_inst = await resolve_otm_option(
                session,
                underlying=self.underlying,
                spot=spot,
                option_type=old_opt_type,
                otm_steps=self._otm_steps,
                strike_step=self._strike_step,
            )
        if new_inst is None:
            self._emit_event(
                StrangleEventType.ROLLED,
                opt_type=old_opt_type,
                old_strike=old_strike,
                old_ltp=round(old_ltp, 2),
                lots=old_lots,
                result="no_instrument",
            )
            return

        ltp, _ = (
            await self.ctx.market.ltp_with_age(new_inst.security_id) if self.ctx.market else (None, None)
        )
        new_ltp = float(ltp) if ltp and ltp > 0 else 0.0
        new_strike = float(new_inst.strike or 0)

        if new_ltp < self._roll_target_min_prem:
            self._emit_event(
                StrangleEventType.ROLLED,
                opt_type=old_opt_type,
                old_strike=old_strike,
                old_ltp=round(old_ltp, 2),
                new_strike=new_strike,
                new_ltp=round(new_ltp, 2),
                lots=old_lots,
                result="skipped_low_prem",
            )
            return

        # All preconditions satisfied — only now mutate the book.
        await self._close_leg(leg, "roll")
        await self._close_matching_hedge(leg)
        legs_before = set(self._legs.keys())
        await self._open_short(spot, old_opt_type, old_lots)
        reopened = bool(set(self._legs.keys()) - legs_before)
        if not reopened:
            # _open_short can silently no-op (stop-gate, lot_size_degraded, cap
            # exhausted, unresolved fill price) — none of those raise, so the only
            # way to know the reopen actually landed a leg is to check the book.
            # Without this, ROLLED result="ok" would claim success while the
            # strategy sits naked on this side — the exact closed-then-failed-to-
            # reopen failure mode this rewrite's docstring says it prevents.
            from pdp.events.models import EventType

            self.ctx.emit_critical(
                EventType.NAKED_POSITION,
                leg.security_id,
                "Roll failed to reopen",
                f"rolled {old_opt_type} leg (old strike {old_strike}) closed, but "
                f"reopen produced no new leg — strategy is naked on this side",
                {"strategy_id": self.strategy_id, "opt_type": old_opt_type, "old_strike": old_strike},
            )
        self._emit_event(
            StrangleEventType.ROLLED,
            opt_type=old_opt_type,
            old_strike=old_strike,
            old_ltp=round(old_ltp, 2),
            new_strike=new_strike,
            new_ltp=round(new_ltp, 2),
            lots=old_lots,
            result="ok" if reopened else "reopen_failed",
        )

    # ------------------------------------------------------------------ #
    # Leg close                                                            #
    # ------------------------------------------------------------------ #

    def _leg_exit_fields(
        self,
        leg: OpenLeg,
        exit_px: float,
        reason: str,
        *,
        close_lots: int | None = None,
    ) -> dict[str, Any]:
        """Full round-trip economics for a terminal (or partial) leg close.

        P&L sign convention is the single shared `_leg_pnl` helper (also used by
        `state()`/`_compute_unrealized`/`_emit_leg_status` for unrealized MTM) so
        realized and unrealized P&L can never silently diverge for the same leg.
        `close_lots` overrides `leg.lots` for a partial close (e.g. stop_half).
        """
        lots = close_lots if close_lots is not None else leg.lots
        pnl = _leg_pnl(leg, exit_px, lots, self._lot_size)

        symbol: str | None = None
        if leg.expiry is not None:
            symbol = symbol_for(self.underlying, leg.expiry, leg.strike, leg.opt_type)

        return {
            "entry_price": float(leg.entry_price),
            "exit_price": exit_px,
            "lots": lots,
            "entry_time": leg.entry_time.isoformat() if leg.entry_time else None,
            "exit_time": datetime.now(tz=_IST).isoformat(),
            "pnl": round(pnl, 2),
            "opt_type": leg.opt_type,
            "strike": leg.strike,
            "is_hedge": leg.is_hedge,
            "is_momentum": leg.is_momentum,
            "expiry": leg.expiry.isoformat() if leg.expiry else None,
            "symbol": symbol,
        }

    async def _close_all(self, reason: str) -> None:
        """Close every open leg. Per-leg terminal events are emitted by
        `_close_short_leg`/`_close_hedge_leg`/`_close_momentum_leg`; the caller
        (`on_bar`) emits the single day summary event (SQUARE_OFF/DAY_LOSS_CAP)
        with the day's final realized total, whether or not any legs were open.
        """
        # Each _close_leg call prunes the leg on a successful close. A leg
        # rejected (e.g. unpriced LTP) deliberately stays so the next bar retries
        # it — _close_leg does not remove a leg it could not close.
        for leg in list(self._legs.values()):
            await self._close_leg(leg, reason)
        # The broker is the source of truth at square-off: close any position the
        # in-memory book never knew about (an orphan) instead of trusting _legs.
        for pos in await self._broker_positions():
            net = int(getattr(pos, "net_qty", 0) or 0)
            sid = getattr(pos, "security_id", None)
            if net == 0 or sid is None or sid in self._legs:
                continue
            from pdp.events.models import EventType

            self.ctx.emit_critical(
                EventType.LEG_STATE_DIVERGED,
                sid,
                "Orphan position at square-off",
                f"broker holds net_qty={net} for {sid} with no tracked leg",
                {"strategy_id": self.strategy_id, "reason": reason},
            )
            async with self._lock_for(sid):
                net2 = await self.ctx.orders.get_net_qty(sid)
                if net2 == 0:
                    continue
                side = "SELL" if net2 > 0 else "BUY"
                await self._place(
                    sid,
                    getattr(pos, "exchange_segment", "NSE_FNO"),
                    side,
                    abs(net2) // self._lot_size,
                )
        self._current_bucket = None
        self._stop_gate.clear()

    async def _close_shorts_and_hedges(self, reason: str) -> None:
        for leg in list(self._short_legs):
            await self._close_short_leg(leg, reason)
        for leg in list(self._hedge_legs):
            await self._close_hedge_leg(leg, reason)
        self._current_bucket = None

    async def _close_leg(
        self,
        leg: OpenLeg,
        reason: str,
        *,
        event_type: str = StrangleEventType.LEG_CLOSE,
    ) -> None:
        """Close any leg atomically and emit exactly one terminal event for it.

        The whole cancel → read net_qty → place sequence runs under the per-sid
        lock (the same lock the open path holds) so a concurrent open/close on
        the same security cannot interleave its read-modify-write with ours. Two
        invariants make the position unable to grow on a close:

        1. **Side from the broker sign, never from the leg's kind.** A rehydrated
           or contradicted leg can be misclassified; flattening a `net_qty>0`
           position always SELLs and a `net_qty<0` position always BUYs.
        2. **Close at most this leg's lots** (`min(leg.lots, broker_lots)`), so a
           divergence where the broker holds more never over-trades.

        `event_type` lets a caller tag the close (TAKE_PROFIT/STOP_ALL) instead of
        the generic LEG_CLOSE — callers must NOT also emit their own terminal
        event, or the ledger double-counts.
        """
        sid = leg.security_id
        ltp = self._ltp_cache.get(sid)
        if (ltp is None or float(ltp) <= 0) and reason != "expiry":
            from pdp.events.models import EventType

            self.ctx.emit_critical(
                EventType.CLOSE_UNPRICED,
                sid,
                "Close rejected",
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
                # net_qty != 0 (checked above) but rounds down to fewer than one
                # full lot — a genuine broker/memory divergence, not a clean
                # close. Placing no order here (nothing to sell/buy a fraction of
                # a lot) while still emitting a terminal close + removing the leg
                # would orphan the residual broker position with zero further
                # tracking. Flag it and leave the leg in place so the next
                # _reconcile_divergences() poll — and a human — see it. Record it
                # directly into the live `_divergences` set (not a pass-local one);
                # the next reconcile pass will recompute and either confirm or clear it.
                self._flag_divergence(self._divergences, sid, leg.lots, broker_lots)
                return
            # A short is expected to sit at net_qty<0, a hedge/momentum long at
            # net_qty>0. A sign that contradicts the leg's tracked kind is
            # evidence the durable state is wrong — alarm on it (but still
            # flatten by the real sign below, never grow the position).
            expected_sign = -1 if leg.kind == "short" else 1
            actual_sign = 1 if net_qty > 0 else -1
            if actual_sign != expected_sign:
                self._on_sign_contradiction(leg, net_qty, reason)
            side = "SELL" if net_qty > 0 else "BUY"
            await self._place(sid, leg.segment, side, close_lots)
            exit_px = self._ltp_cache.get(sid) or 0.0
            await self._unsubscribe_option(sid, leg.segment)
            self._emit_event(
                event_type,
                sid=sid,
                reason=reason,
                **self._leg_exit_fields(leg, exit_px, reason),
            )
            await self._persist_leg_close(sid)
            self._remove_leg(sid)

    def _on_sign_contradiction(self, leg: OpenLeg, net_qty: int, reason: str) -> None:
        """A leg's broker net_qty sign contradicts its tracked kind on close.

        This is a data-corruption alarm distinct from the risk-limit cap
        (`POSITION_SIZE_CAPPED`), so it gets its own `LEG_TYPE_CONTRADICTED`
        type — a dashboard counting cap events must not confuse "the cap did its
        job" with "leg-type tracking is broken". In live mode the underlying is
        halted for the session; paper emits and continues so the session's
        remaining behaviour is still observable.
        """
        from pdp.events.models import EventType

        self.ctx.emit_critical(
            EventType.LEG_TYPE_CONTRADICTED,
            leg.security_id,
            "Leg type contradicts broker sign",
            f"Leg {leg.security_id} tracked as {leg.kind} but broker net_qty is {net_qty} "
            "— flattening by the broker sign to avoid growing the position",
            {"strategy_id": self.strategy_id, "reason": reason, "net_qty": net_qty},
        )
        if self._mode == "live":
            self._done_for_day = True

    async def _persist_leg_open(self, leg: OpenLeg) -> None:
        """Durably record an open leg's *kind* + identity in PostgreSQL.

        Rehydration after a restart reads this table alone (see
        `_rehydrate_legs`); a leg's kind is what decides its closing direction,
        so it must survive a restart rather than living only in memory. Written
        right after the fill is confirmed, under the sid lock the caller already
        holds. (The broker owns the Position row in its own transaction, so this
        cannot literally share that transaction — it is a separate durable write
        immediately after the fill.)
        """
        if self.ctx.session_maker is None:
            return
        from pdp.orders.models import StrategyLeg

        async with self.ctx.session_maker() as s:
            s.add(
                StrategyLeg(
                    strategy_id=self.strategy_id,
                    security_id=leg.security_id,
                    leg_kind=leg.kind or "short",
                    opt_type=leg.opt_type,
                    strike=Decimal(str(leg.strike)),
                    expiry=leg.expiry,
                )
            )
            await s.commit()

    async def _persist_leg_close(self, sid: str) -> None:
        """Mark the leg's durable row closed (sets `closed_at`); never deletes,
        so the partial-unique index frees the sid for a future re-open."""
        if self.ctx.session_maker is None:
            return
        from sqlalchemy import func, update

        from pdp.orders.models import StrategyLeg

        async with self.ctx.session_maker() as s:
            await s.execute(
                update(StrategyLeg)
                .where(
                    StrategyLeg.strategy_id == self.strategy_id,
                    StrategyLeg.security_id == sid,
                    StrategyLeg.closed_at.is_(None),
                )
                .values(closed_at=func.now())
            )
            await s.commit()

    async def _close_short_leg(
        self,
        leg: OpenLeg,
        reason: str,
        *,
        event_type: str = StrangleEventType.LEG_CLOSE,
    ) -> None:
        await self._close_leg(leg, reason, event_type=event_type)

    async def _close_hedge_leg(
        self,
        leg: OpenLeg,
        reason: str,
        *,
        event_type: str = StrangleEventType.LEG_CLOSE,
    ) -> None:
        await self._close_leg(leg, reason, event_type=event_type)

    async def _partial_close(
        self,
        leg: OpenLeg,
        close_lots: int,
        reason: str,
        event_type: str,
        **extra: Any,
    ) -> bool:
        """Partially close a leg (e.g. stop_half) — same lock + broker-sign
        discipline as `_close_leg`, but the leg stays open with its lots reduced
        by however many were actually closed (never more than the broker holds).

        Returns whether an order was actually placed — callers must not latch a
        one-shot flag (e.g. ``half_stopped``) on this call without checking the
        return value, or a no-op (broker holds fewer lots than expected) would
        permanently disable the stop for a leg that was never actually reduced.
        """
        sid = leg.security_id
        async with self._lock_for(sid):
            net_qty = await self.ctx.orders.get_net_qty(sid)
            broker_lots = abs(net_qty) // self._lot_size
            n = min(close_lots, broker_lots)
            if n <= 0:
                return False
            # Capture exit economics BEFORE mutating leg.lots.
            exit_fields = self._leg_exit_fields(leg, self._ltp_cache.get(sid) or 0.0, reason, close_lots=n)
            side = "SELL" if net_qty > 0 else "BUY"
            await self._place(sid, leg.segment, side, n)
            leg.lots -= n
            self._emit_event(
                event_type,
                sid=sid,
                remaining=leg.lots,
                partial=True,
                **extra,
                **exit_fields,
            )
            return True

    async def _broker_positions(self) -> list[Any]:
        """Broker's own view of open positions for this strategy — the source of
        truth for square-off reconciliation. Tolerates a client without the
        method (returns nothing) so unit fakes need not implement it."""
        getter = getattr(self.ctx.orders, "get_positions", None)
        if getter is None:
            return []
        return list(await getter())

    def _flag_divergence(self, current: set[str], sid: str, mem_lots: int, broker_lots: int) -> None:
        """Record a memory-vs-broker lot mismatch for `sid` in the current pass's
        `current` set and emit `LEG_STATE_DIVERGED` once per distinct
        (sid, mem, broker) shape per session, so a persistent mismatch surfaces on
        the readiness endpoint without alert-storming (the failure mode
        POSITION_RECONCILE_MISMATCH had in paper).

        `current` (not `self._divergences`) is mutated so a healed mismatch can drop
        out of the readiness gate on the next pass; the alert de-dup lives in the
        session-long `self._divergence_shapes`, which is intentionally *not* reset."""
        current.add(sid)
        shape = f"{sid}:{mem_lots}:{broker_lots}"
        if shape in self._divergence_shapes:
            return
        self._divergence_shapes.add(shape)
        from pdp.events.models import EventType

        self.ctx.emit_critical(
            EventType.LEG_STATE_DIVERGED,
            sid,
            "Leg state diverged from broker",
            f"{sid}: in-memory {mem_lots} lots vs broker {broker_lots} lots",
            {"strategy_id": self.strategy_id, "mem_lots": mem_lots, "broker_lots": broker_lots},
        )

    async def _reconcile_divergences(self) -> None:
        """Compare every tracked leg's lots against the broker's net_qty (and flag
        any broker position with no tracked leg). Skipped when the order client
        cannot report positions, so a fake without `get_positions` is not treated
        as "everything diverged".

        The divergence set is recomputed from scratch each pass and assigned to
        `self._divergences` at the end, so a transient mismatch (e.g. a fill-timing
        race right after entry, where the positions row lags in-memory lots for a
        poll or two) clears the readiness Reconciliation component once it heals,
        instead of latching for the rest of the session. A genuinely persistent
        mismatch stays in the set every pass and still alerts exactly once per shape
        via `_divergence_shapes`."""
        if getattr(self.ctx.orders, "get_positions", None) is None:
            return
        broker: dict[str, int] = {}
        for pos in await self._broker_positions():
            bsid = getattr(pos, "security_id", None)
            if bsid is not None:
                broker[bsid] = int(getattr(pos, "net_qty", 0) or 0)
        current: set[str] = set()
        for lg in self._legs.values():
            broker_lots = abs(broker.get(lg.security_id, 0)) // self._lot_size
            if lg.lots != broker_lots:
                self._flag_divergence(current, lg.security_id, lg.lots, broker_lots)
        for bsid, net in broker.items():
            if net != 0 and bsid not in self._legs:
                self._flag_divergence(current, bsid, 0, abs(net) // self._lot_size)
        self._divergences = current

    async def _close_matching_hedge(self, short_leg: OpenLeg) -> None:
        matching = [h for h in self._hedge_legs if h.opt_type == short_leg.opt_type]
        for h in matching:
            await self._close_hedge_leg(h, "tp_hedge_close")

    # ------------------------------------------------------------------ #
    # Execution console state                                              #
    # ------------------------------------------------------------------ #

    async def state(self) -> dict[str, Any]:
        """Return current execution state for the REST console API."""
        # Reconcile against the broker on every poll so a memory/broker lot
        # mismatch (or an orphan broker position) is detected and surfaced on the
        # readiness endpoint rather than silently miscounted.
        await self._reconcile_divergences()
        day_realized = await self._day_realized()
        day_unrealized = self._compute_unrealized()
        legs = []
        for lg in self._short_legs + self._hedge_legs + self._momentum_legs:
            ltp = self._ltp_cache.get(lg.security_id)
            mtm: float | None = None
            if ltp is not None:
                mtm = round(_leg_pnl(lg, ltp, lg.lots, self._lot_size), 2)
            legs.append(
                {
                    "security_id": lg.security_id,
                    "opt_type": lg.opt_type,
                    "strike": lg.strike,
                    "lots": lg.lots,
                    "entry_price": float(lg.entry_price),
                    "entry_time": lg.entry_time.isoformat() if lg.entry_time else None,
                    "entry_reason": lg.entry_reason,
                    # Expiry is resolved at open time and preserved across rehydration;
                    # surface it so the console can show DTE. dte itself is computed in the
                    # monitor route (server-side, so the client needs no date library).
                    "expiry": lg.expiry.isoformat() if lg.expiry else None,
                    "ltp": ltp,
                    "mtm": mtm,
                    "day_high": lg.day_high,
                    "day_low": lg.day_low,
                    "is_hedge": lg.is_hedge,
                    "is_momentum": lg.is_momentum,
                    # Origin tag so the console can separate system-placed legs from
                    # manual broker positions (future: group-by-broker). All strategy
                    # legs are system-originated.
                    "origin": "system",
                }
            )
        day_realized_f = float(day_realized)
        return {
            "mode": self._mode,
            "strategy_id": self.strategy_id,
            "underlying": self.underlying,
            "bucket": self._current_bucket,
            "score": round(self._last_score, 3),
            "legs": legs,
            "day_realized": day_realized_f,
            "day_unrealized": day_unrealized,
            "day_pnl": round(day_realized_f + day_unrealized, 2),
            "done_for_day": self._done_for_day,
            "vix_now": self._vix_now,
            "n_open_legs": len(self._short_legs) + len(self._hedge_legs) + len(self._momentum_legs),
            "n_open_shorts": len(self._short_legs),
            "n_open_hedges": len(self._hedge_legs),
            "n_open_momentum": len(self._momentum_legs),
            "started_at": self._started_at.isoformat(),
        }

    def _compute_unrealized(self) -> float:
        total = 0.0
        for lg in self._short_legs + self._hedge_legs + self._momentum_legs:
            ltp = self._ltp_cache.get(lg.security_id)
            if ltp is not None:
                total += _leg_pnl(lg, ltp, lg.lots, self._lot_size)
        return round(total, 2)

    # ------------------------------------------------------------------ #
    # Day management                                                       #
    # ------------------------------------------------------------------ #

    def _halt_key(self, day: date) -> str:
        return f"halt:{self.strategy_id}:{day.isoformat()}"

    async def _maybe_restore_halt_marker(self) -> None:
        """On first bar of the day: restore _done_for_day from Redis if a halt marker exists."""
        if self._day_key is None or self.ctx.market is None:
            return
        raw = await self.ctx.market.cache_get(self._halt_key(self._day_key))
        if raw:
            self._done_for_day = True
            self.ctx.log.info("halt_marker_restored", day=str(self._day_key))

    def _maybe_reset_day(self, bar_day: date) -> None:
        if self._day_key != bar_day:
            self._day_key = bar_day
            self._done_for_day = False
            self._halt_checked = False
            self._orb_high = None
            self._orb_low = None
            self._orb_unseeded = False
            self._vix_day_open = None
            self._vix_day_high = None
            self._vix_recent.clear()
            self._vix_spike_emitted = False
            self._day_baseline.clear()
            self._touched_sids.clear()
            self._stop_gate.clear()
            self._pending_bucket = None
            self._pending_bucket_count = 0
            # _current_bucket is intentionally NOT reset: open legs persist across
            # trading days, so carrying the bucket forward prevents a spurious
            # close/reopen on the first bar of the new session.
            #
            # _recovery_attempts DOES reset daily even though the bucket episode
            # carries over: a side that exhausted entry_recovery_max_attempts and
            # was surfaced via ENTRY_SIDE_UNFILLED must not stay permanently
            # unrecoverable for as long as the bucket happens to persist -- the
            # transient cause (cold LTP, feed hiccup) from a prior day is long gone.
            # _bucket_realized is NOT reset: a side deliberately closed this episode
            # (take-profit/roll) must still never be resurrected just because a day
            # boundary passed.
            self._recovery_attempts = {}

    async def _maybe_resolve_lot_size(self, bar_day: date) -> None:
        """Resolve `self._lot_size` from the instruments table once per IST trading day.

        The instruments table (Dhan scrip master) is authoritative; YAML `lot_size` is
        advisory-only and only compared for a mismatch warning. On failure (empty table),
        `self._lot_size` keeps its last-known-good value so open legs still price/close
        correctly — only new entries are blocked (`_lot_size_degraded`) until the next
        bar's resolution succeeds.
        """
        if self._lot_size_day == bar_day or self.ctx.session_maker is None:
            return

        from pdp.strategy.strikes import lot_size_for_underlying

        async with self.ctx.session_maker() as session:
            resolved = await lot_size_for_underlying(session, self.underlying)

        if resolved is None:
            if not self._lot_size_degraded:
                from pdp.events.models import EventType

                self.ctx.emit_critical(
                    EventType.INDICATOR_UNSEEDED,
                    self.sid,
                    "Lot size unresolved",
                    f"{self.underlying}: no instruments-table row for lot size; new entries "
                    f"blocked, using last-known-good {self._lot_size} for existing legs",
                    {"strategy_id": self.strategy_id, "underlying": self.underlying},
                )
                self._lot_size_degraded = True
            return

        if self._lot_size_yaml is not None and self._lot_size_yaml != resolved:
            self.ctx.log.warning(
                "lot_size_yaml_mismatch",
                underlying=self.underlying,
                yaml_lot_size=self._lot_size_yaml,
                resolved_lot_size=resolved,
            )

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

    def _open_short_lots(self, opt_type: str) -> int:
        """Total lots currently held short on `opt_type` ("PE"/"CE")."""
        return sum(leg.lots for leg in self._short_legs if leg.opt_type == opt_type)

    def _max_leg_lots(self) -> int:
        """Largest lots a single fresh entry could ever request, per config.

        Used as a hard per-sid position-size ceiling — see `_reserve_leg_lots`.
        """
        if not self._ratio_table:
            return self._scale_lots
        widest = max((max(pe, ce) for pe, ce in self._ratio_table.values()), default=1)
        return widest * self._scale_lots

    def _lock_for(self, sid: str) -> asyncio.Lock:
        """Per-sid lock guarding the cap-check-then-place sequence in
        _open_short/_open_hedge/_open_momentum, so two concurrent opens on the
        same sid can't both pass `_reserve_leg_lots` and jointly exceed the cap."""
        lock = self._leg_locks.get(sid)
        if lock is None:
            lock = asyncio.Lock()
            self._leg_locks[sid] = lock
        return lock

    async def _reserve_leg_lots(self, sid: str, opt_type: str, lots: int, leg_kind: str) -> int | None:
        """Cap check for a fresh leg open on `sid` — caller MUST hold `_lock_for(sid)`
        across this call *and* the subsequent order placement (see call sites).

        A single sid must never exceed `_max_leg_lots()`. Without this, a stale or
        duplicated in-memory leg feeding a rollup (or any other unforeseen path that
        re-adds to an already-open sid) can silently compound a position across
        days/rolls instead of failing loud — this is exactly how a handful of legs
        grew to hundreds of lots in production before this guard existed.

        Returns the (possibly clipped) lots to open, or None if the cap already
        refuses any further addition — the caller must abort without opening.
        """
        existing_lots = abs(await self.ctx.orders.get_net_qty(sid)) // self._lot_size
        max_lots = self._max_leg_lots()
        if existing_lots >= max_lots:
            from pdp.events.models import EventType

            self.ctx.emit_critical(
                EventType.POSITION_SIZE_CAPPED,
                sid,
                "Position size capped",
                f"{leg_kind} {sid} already at {existing_lots} lots (cap {max_lots}); refused to add {lots} more",
                {
                    "strategy_id": self.strategy_id,
                    "opt_type": opt_type,
                    "existing_lots": existing_lots,
                    "requested_lots": lots,
                    "cap": max_lots,
                },
            )
            return None
        if existing_lots + lots > max_lots:
            capped_lots = max_lots - existing_lots
            from pdp.events.models import EventType

            self.ctx.emit_critical(
                EventType.POSITION_SIZE_CAPPED,
                sid,
                "Position size capped",
                f"{leg_kind} {sid} would grow to {existing_lots + lots} lots (cap {max_lots}); clipped to {capped_lots}",
                {
                    "strategy_id": self.strategy_id,
                    "opt_type": opt_type,
                    "existing_lots": existing_lots,
                    "requested_lots": lots,
                    "cap": max_lots,
                },
            )
            return capped_lots
        return lots

    async def _subscribe_option(self, sid: str, segment: str) -> None:
        if self.ctx.market is not None and sid not in self._subscribed_option_sids:
            if await self.ctx.market.subscribe(sid, segment):
                self._subscribed_option_sids.add(sid)

    async def _unsubscribe_option(self, sid: str, segment: str) -> None:
        if self.ctx.market is not None and sid in self._subscribed_option_sids:
            await self.ctx.market.unsubscribe(sid, segment)
            self._subscribed_option_sids.discard(sid)

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
                select(Instrument)
                .where(
                    Instrument.underlying == self.underlying,
                    Instrument.expiry == expiry,
                    Instrument.option_type == opt_type.upper(),
                    Instrument.strike == D(str(strike)),
                )
                .limit(1)
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
                "order_rejected",
                security_id=security_id,
                side=side,
                qty=qty,
                exc=str(exc),
            )
            return None

    # ------------------------------------------------------------------ #
    # Startup repair + rehydration                                         #
    # ------------------------------------------------------------------ #

    async def _repair_zero_avg_positions(self) -> None:
        """One-off startup repair: re-base any open PG positions with avg_price == 0.

        A zero avg_price causes every MTM computation to produce a phantom loss
        (-ltp × qty). On startup we detect these rows and attempt to set avg_price
        from the LTP cache (or market feed) so real-time P&L is correct going forward.
        """
        if self.ctx.session_maker is None:
            return
        try:
            from decimal import Decimal as D

            from sqlalchemy import select, update

            from pdp.orders.models import Position

            async with self.ctx.session_maker() as session:
                async with session.begin():
                    result = await session.scalars(
                        select(Position).where(
                            Position.strategy_id == self.strategy_id,
                            Position.net_qty != 0,
                            Position.avg_price == D("0"),
                        )
                    )
                    zero_rows = result.all()

            repaired = 0
            for pos in zero_rows:
                sid = pos.security_id
                # Try LTP cache first, then market feed
                ref_price: float | None = self._ltp_cache.get(sid)
                if not ref_price and self.ctx.market is not None:
                    ltp_dec, _ = await self.ctx.market.ltp_with_age(sid)
                    if ltp_dec and ltp_dec > 0:
                        ref_price = float(ltp_dec)
                if ref_price and ref_price > 0:
                    async with self.ctx.session_maker() as session:
                        async with session.begin():
                            await session.execute(
                                update(Position)
                                .where(
                                    Position.strategy_id == self.strategy_id,
                                    Position.security_id == sid,
                                    Position.avg_price == D("0"),
                                )
                                .values(avg_price=D(str(ref_price)))
                            )
                    repaired += 1
                    self.ctx.log.info("zero_avg_repaired", sid=sid, new_avg=ref_price)
                else:
                    self.ctx.log.warning("zero_avg_repair_no_ltp", sid=sid)
            if zero_rows:
                self.ctx.log.info(
                    "zero_avg_repair_done",
                    found=len(zero_rows),
                    repaired=repaired,
                    strategy_id=self.strategy_id,
                )
        except Exception as exc:
            self.ctx.log.warning("zero_avg_repair_failed", exc=str(exc))

    async def _rehydrate_legs(self) -> None:
        """Rebuild the in-memory leg book from PostgreSQL on startup.

        A leg's *kind* (which decides its closing direction) is read from the
        durable ``strategy_legs`` table written on open — never inferred, because
        the net_qty sign cannot tell a long hedge from a long momentum leg (the
        exact bug that restored a long SENSEX hedge as a short and grew it
        4→8→16 across restarts). A broker position with no durable leg row is an
        orphan: its kind is inferred from the sign as a best effort and a single
        ``LEG_TYPE_UNKNOWN`` is emitted so the gap is visible.

        Rehydration is total-or-raise and asserts an empty book first: it runs
        once, before any tick, and any failure aborts startup rather than serving
        ticks against a corrupt book (the old path swallowed its own failure,
        which is why "rehydration that never rehydrated" shipped).
        """
        if self._legs:
            raise RuntimeError("rehydrate_legs called with a non-empty leg book")
        if self.ctx.session_maker is None:
            return

        from decimal import Decimal as D

        from sqlalchemy import select

        from pdp.instruments.models import Instrument
        from pdp.orders.models import Position, StrategyLeg

        async with self.ctx.session_maker() as session:
            pos_result = await session.scalars(
                select(Position).where(
                    Position.strategy_id == self.strategy_id,
                    Position.net_qty != 0,
                )
            )
            open_positions = pos_result.all()
        if not open_positions:
            return

        async with self.ctx.session_maker() as session:
            leg_result = await session.scalars(
                select(StrategyLeg).where(
                    StrategyLeg.strategy_id == self.strategy_id,
                    StrategyLeg.closed_at.is_(None),
                )
            )
            leg_by_sid = {row.security_id: row for row in leg_result.all()}

        orphan_sids = {p.security_id for p in open_positions if p.security_id not in leg_by_sid}
        inst_by_sid: dict[str, Instrument] = {}
        if orphan_sids:
            async with self.ctx.session_maker() as session:
                inst_result = await session.scalars(
                    select(Instrument).where(Instrument.security_id.in_(orphan_sids))
                )
                inst_by_sid = {inst.security_id: inst for inst in inst_result.all()}

        rehydrated = 0
        for pos in open_positions:
            sid = pos.security_id
            leg_row = leg_by_sid.get(sid)
            if leg_row is not None:
                kind = leg_row.leg_kind
                opt_type = leg_row.opt_type
                strike = float(leg_row.strike)
                expiry = leg_row.expiry
            else:
                # Orphan: no durable leg row. Infer kind from the sign as a best
                # effort (a long could be a hedge OR a momentum leg) and flag it.
                kind = "short" if pos.net_qty < 0 else "hedge"
                inst = inst_by_sid.get(sid)
                opt_type = str((inst.option_type if inst else None) or "PE")
                strike = float((inst.strike if inst else None) or 0.0)
                expiry = inst.expiry if inst else None
                from pdp.events.models import EventType

                self.ctx.emit_critical(
                    EventType.LEG_TYPE_UNKNOWN,
                    sid,
                    "Rehydrated orphan leg",
                    f"broker position {sid} (net_qty={pos.net_qty}) has no durable "
                    f"strategy_leg row — classified {kind} by sign, may be wrong",
                    {"strategy_id": self.strategy_id, "net_qty": pos.net_qty},
                )

            lots = abs(pos.net_qty) // self._lot_size or 1
            entry_price = pos.avg_price if pos.avg_price and pos.avg_price > D("0") else D("0")

            # Subscribe the market feed so on_tick gets LTPs for these legs
            await self._subscribe_option(sid, pos.exchange_segment)
            self._add_leg(
                OpenLeg(
                    security_id=sid,
                    segment=pos.exchange_segment,
                    opt_type=opt_type,
                    strike=strike,
                    lots=lots,
                    entry_price=entry_price,
                    kind=kind,
                    entry_reason="rehydrated",
                    expiry=expiry,
                )
            )
            # Seed `_ltp_cache` so the console shows a price immediately instead of
            # `--` during the cold window after restart (the cache is otherwise only
            # advanced by on_tick, which lands only on the next live option tick).
            # Prefer the live Redis LTP; fall back to the position's avg entry price
            # so P&L reads ~0 rather than blank until the first fresh tick corrects it.
            await self._seed_rehydrated_ltp(sid, entry_price)
            # Baseline against the position's realized_pnl AT rehydrate time —
            # without this, _day_realized() has no baseline for this sid and
            # counts the leg's entire historical realized P&L as if it all
            # happened today (phantom day P&L on every restart).
            await self._record_day_baseline(sid)
            rehydrated += 1

        self.ctx.log.info(
            "rehydrate_legs_done",
            rehydrated=rehydrated,
            short=len(self._short_legs),
            hedge=len(self._hedge_legs),
            momentum=len(self._momentum_legs),
            strategy_id=self.strategy_id,
        )

