"""Intraday directional option-selling decision core (pure, deterministic).

Codifies ``strategies/intraday-directional.md``: sell a PE in an uptrend / a CE in a
downtrend, gated on a four-condition AND (opening range, session VWAP, SuperTrend(10,2)
and EMA9/20 alignment), sized by a 15-minute scale-in ladder, and exited by eight rules
in a fixed priority order.

Design goals mirror ``pdp.signals.bias``:

- **Pure**: no I/O, no globals, deterministic. Identical inputs -> identical decisions.
  This is what makes the backtest (``pdp.backtest.intraday_sim``) and the live strategy
  (``pdp.strategies.intraday_directional``) agree — neither reimplements any of it.
- **Decoupled**: takes plain floats via ``IntradayInputs``, not indicator-engine state
  objects, so it is trivially unit-testable from both sides.

**Fail-closed rule.** Every entry opens a *short* option position, so a condition whose
input is missing (``None``) evaluates as **not satisfied** rather than being skipped or
renormalised away. This is deliberately stricter than ``bias.py``'s abstention model:
there, a missing vote drops out of a weighted average; here, a missing input blocks the
trade outright.

Sign convention: ``+1`` = bullish/rising, ``-1`` = bearish/falling. A short PE is a
bullish position (``Side.PE``); a short CE is a bearish one (``Side.CE``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from enum import StrEnum
from math import ceil

from pdp.signals.bias import CamLevels

# Session-VWAP sources. Lives here, not in the backtest config, because both the live
# strategy and the backtest engine must agree on what a value means — and the live
# strategy must not import the backtest package to find out.
#
# `off` leaves `session_vwap` as None. VWAP is a mandatory AND condition in
# `entry_conditions`, so under the fail-closed rule `off` blocks every entry: it is a
# kill switch, not a "skip this gate" toggle.
VWAP_SESSION_TWAP = "session_twap"
VWAP_OFF = "off"
VWAP_SOURCES = (VWAP_SESSION_TWAP, VWAP_OFF)

__all__ = [
    "VWAP_OFF",
    "VWAP_SESSION_TWAP",
    "VWAP_SOURCES",
    "CamLevels",
    "EntryBlock",
    "EntrySignal",
    "ExitReason",
    "ExitSignal",
    "IntradayInputs",
    "IntradayParams",
    "IntradayState",
    "RollupSignal",
    "ScaleSignal",
    "Side",
    "entry_conditions",
    "evaluate_entry",
    "evaluate_exit",
    "evaluate_price_exit",
    "evaluate_rollup",
    "evaluate_scale_in",
    "rollup_target_acceptable",
    "unrealized_pnl",
    "update_sustained_trackers",
]


class Side(StrEnum):
    """Which option is sold. ``PE`` is the bullish position, ``CE`` the bearish one."""

    PE = "PE"
    CE = "CE"

    @property
    def bias(self) -> int:
        """+1 when this position profits from the underlying holding up, -1 otherwise."""
        return 1 if self is Side.PE else -1


class ExitReason(StrEnum):
    """Why a position closed. Ordered here as they are evaluated (highest first)."""

    DAY_LOSS_CAP = "day_loss_cap"
    SQUARE_OFF = "square_off"
    UNREAL_LOSS_STOP = "unreal_loss_stop"
    PREMIUM_RISE_STOP = "premium_rise_stop"
    UNDERLYING_ST_FLIP = "underlying_st_flip"
    OPTION_ST_FLIP = "option_st_flip"
    EMA20_BREAK_SUSTAINED = "ema20_break_sustained"
    CAM_REJECTION_SUSTAINED = "cam_rejection_sustained"


class EntryBlock(StrEnum):
    """Why an entry did not happen — recorded in the decision trace."""

    DAY_ENDED = "day_ended"
    BEFORE_ENTRY_WINDOW = "before_entry_window"
    AT_OR_AFTER_SQUAREOFF = "at_or_after_squareoff"
    ALREADY_POSITIONED = "already_positioned"
    REENTRY_COOLOFF = "reentry_cooloff"
    CONDITIONS_UNMET = "conditions_unmet"


# Condition keys, stable across both paths so the decision trace is comparable.
COND_ORB = "orb"
COND_VWAP = "vwap"
COND_SUPERTREND = "supertrend"
COND_EMA = "ema"
CONDITION_KEYS = (COND_ORB, COND_VWAP, COND_SUPERTREND, COND_EMA)


# --------------------------------------------------------------------------- #
# Inputs
# --------------------------------------------------------------------------- #


@dataclass(slots=True)
class IntradayInputs:
    """Everything the core needs at one decision instant (one closed decision bar).

    Any field may be ``None`` when its data is unavailable. Unlike ``bias.BiasInputs``,
    a missing field here **blocks** the condition that reads it rather than abstaining.

    ``ist_dt`` is the bar's IST close time — never wall-clock — so backtest and live
    make session decisions identically.
    """

    ist_dt: datetime
    spot: float

    # Decision-bar OHLC (needed for Camarilla touch/rejection detection).
    bar_high: float | None = None
    bar_low: float | None = None

    # 5m EMA pair plus the previous bar's values, for cross/slope detection.
    ema9_5m: float | None = None
    ema20_5m: float | None = None
    ema9_prev_5m: float | None = None
    ema20_prev_5m: float | None = None

    # 15m confirmation EMA pair.
    ema9_15m: float | None = None
    ema20_15m: float | None = None

    # SuperTrend(10,2) direction (+1 bullish / -1 bearish) on the underlying.
    st_5m_dir: int | None = None
    st_15m_dir: int | None = None

    # Session VWAP (see IntradayParams.vwap_source — the default is a session TWAP
    # proxy, because the spot index carries no traded volume).
    session_vwap: float | None = None

    # Opening range from the 15m candle stamped 09:15 IST.
    orb_high: float | None = None
    orb_low: float | None = None

    # Camarilla S3/S4/R3/R4 from the previous session's high/low/close.
    cam: CamLevels | None = None

    # SuperTrend(10,2) direction on the *sold option's* own 5m chart. For a short,
    # +1 (option trending up) is the adverse direction.
    option_st_dir: int | None = None

    # Optional additive gate: is the sold/ATM option trading below its own VWAP?
    # None means "not evaluated"; only consulted when params.atm_option_vwap_gate.
    atm_option_vwap_ok: bool | None = None


# --------------------------------------------------------------------------- #
# Parameters
# --------------------------------------------------------------------------- #


@dataclass(slots=True)
class IntradayParams:
    """Every knob the decision core reads. Mirrored by the backtest config and the
    live YAML ``params`` block under the same names, so a value means the same thing
    on both paths."""

    # Timeframes
    timeframe_min: int = 5
    confirm_timeframe_min: int = 15

    # Session (IST)
    entry_after_ist: time = field(default_factory=lambda: time(9, 30))
    squareoff_ist: time = field(default_factory=lambda: time(15, 15))

    # Sizing ladder
    initial_lots: int = 3
    scale_lots_step: int = 3
    max_lots: int = 9
    scale_in_minutes: int = 15

    # Re-entry
    reentry_cooloff_minutes: int = 15

    # Exits
    day_loss_limit: float = 10_000.0
    premium_rise_stop_pct: float = 1.0   # 1.0 == premium doubles
    unreal_loss_pct: float = 0.20
    ema_break_bars: int = 3              # consecutive wrong-side 5m closes
    cam_reject_minutes: int = 30
    cam_touch_eps: float = 0.001         # fractional proximity counting as a "touch"

    # Rollup to ATM on premium decay
    roll_enabled: bool = True
    roll_trigger_prem: float = 20.0
    roll_target_min_prem: float = 50.0
    max_rolls_per_day: int = 2
    roll_cutoff_ist: time = field(default_factory=lambda: time(14, 45))

    # Confirmation / optional gates
    require_15m_confirm: bool = False
    atm_option_vwap_gate: bool = False

    def bars_for_minutes(self, minutes: int) -> int:
        """Decision bars spanning *minutes*, rounded up, never below 1."""
        return max(1, ceil(minutes / max(1, self.timeframe_min)))

    @property
    def cam_reject_bars(self) -> int:
        return self.bars_for_minutes(self.cam_reject_minutes)

    def validate(self) -> None:
        if self.timeframe_min < 1:
            raise ValueError(f"timeframe_min must be >= 1, got {self.timeframe_min}")
        if self.initial_lots < 1:
            raise ValueError(f"initial_lots must be >= 1, got {self.initial_lots}")
        if self.max_lots < self.initial_lots:
            raise ValueError(
                f"max_lots must be >= initial_lots, got max={self.max_lots} "
                f"initial={self.initial_lots}"
            )
        if self.scale_lots_step < 0:
            raise ValueError(f"scale_lots_step must be >= 0, got {self.scale_lots_step}")
        if self.scale_in_minutes < 1:
            raise ValueError(f"scale_in_minutes must be >= 1, got {self.scale_in_minutes}")
        if self.reentry_cooloff_minutes < 0:
            raise ValueError(
                f"reentry_cooloff_minutes must be >= 0, got {self.reentry_cooloff_minutes}"
            )
        if self.day_loss_limit <= 0:
            raise ValueError(f"day_loss_limit must be > 0, got {self.day_loss_limit}")
        if self.premium_rise_stop_pct <= 0:
            raise ValueError(
                f"premium_rise_stop_pct must be > 0, got {self.premium_rise_stop_pct}"
            )
        if self.unreal_loss_pct <= 0:
            raise ValueError(f"unreal_loss_pct must be > 0, got {self.unreal_loss_pct}")
        if self.ema_break_bars < 1:
            raise ValueError(f"ema_break_bars must be >= 1, got {self.ema_break_bars}")
        if self.cam_reject_minutes < 1:
            raise ValueError(f"cam_reject_minutes must be >= 1, got {self.cam_reject_minutes}")
        if self.cam_touch_eps < 0:
            raise ValueError(f"cam_touch_eps must be >= 0, got {self.cam_touch_eps}")
        if self.entry_after_ist >= self.squareoff_ist:
            raise ValueError(
                f"entry_after_ist must be before squareoff_ist, got "
                f"{self.entry_after_ist} >= {self.squareoff_ist}"
            )
        if self.roll_enabled:
            if self.roll_trigger_prem <= 0:
                raise ValueError(f"roll_trigger_prem must be > 0, got {self.roll_trigger_prem}")
            if self.roll_target_min_prem < self.roll_trigger_prem:
                raise ValueError(
                    f"roll_target_min_prem must be >= roll_trigger_prem, got "
                    f"{self.roll_target_min_prem} < {self.roll_trigger_prem}"
                )
            if self.max_rolls_per_day < 0:
                raise ValueError(f"max_rolls_per_day must be >= 0, got {self.max_rolls_per_day}")


# --------------------------------------------------------------------------- #
# Mutable per-session state
# --------------------------------------------------------------------------- #


@dataclass(slots=True)
class IntradayState:
    """Position + sustained-condition trackers for one session.

    The trackers (``ema_break_bars``, ``cam_reject_bars``) are the reason this is a
    shared object rather than each path keeping its own counters: a sustained-break
    rule is path-dependent, so live and backtest must advance it with the same
    function at the same point in the bar cycle (see ``update_sustained_trackers``).
    """

    side: Side | None = None
    lots: int = 0
    avg_entry: float = 0.0
    strike: float | None = None
    entry_ist: datetime | None = None
    last_scale_ist: datetime | None = None

    # Sustained-condition counters
    ema_break_bars: int = 0
    cam_reject_bars: int = 0
    cam_reject_level: float | None = None

    # Option-chart SuperTrend direction observed at entry, so an exit fires on a
    # *flip* rather than on a state that was already true when the trade was opened.
    option_st_at_entry: int | None = None

    # Session bookkeeping
    rolls_today: int = 0
    last_exit_ist: datetime | None = None
    day_ended: bool = False

    @property
    def is_open(self) -> bool:
        return self.side is not None and self.lots > 0

    def reset_for_day(self) -> None:
        """Clear everything at an IST day rollover."""
        self.side = None
        self.lots = 0
        self.avg_entry = 0.0
        self.strike = None
        self.entry_ist = None
        self.last_scale_ist = None
        self.ema_break_bars = 0
        self.cam_reject_bars = 0
        self.cam_reject_level = None
        self.option_st_at_entry = None
        self.rolls_today = 0
        self.last_exit_ist = None
        self.day_ended = False

    def on_open(
        self,
        side: Side,
        lots: int,
        price: float,
        strike: float,
        ist_dt: datetime,
        *,
        option_st_dir: int | None = None,
    ) -> None:
        self.side = side
        self.lots = lots
        self.avg_entry = price
        self.strike = strike
        self.entry_ist = ist_dt
        self.last_scale_ist = ist_dt
        self.ema_break_bars = 0
        self.cam_reject_bars = 0
        self.cam_reject_level = None
        self.option_st_at_entry = option_st_dir

    def on_scale(self, lots: int, price: float, ist_dt: datetime) -> None:
        """Add *lots* filled at *price*, updating the volume-weighted average entry."""
        total = self.lots + lots
        if total <= 0:
            return
        self.avg_entry = ((self.avg_entry * self.lots) + (price * lots)) / total
        self.lots = total
        self.last_scale_ist = ist_dt

    def on_roll(self, strike: float, price: float, ist_dt: datetime,
                *, option_st_dir: int | None = None) -> None:
        """Re-anchor to a new strike after a rollup. Lot count is preserved."""
        self.strike = strike
        self.avg_entry = price
        self.last_scale_ist = ist_dt
        self.rolls_today += 1
        self.ema_break_bars = 0
        self.cam_reject_bars = 0
        self.cam_reject_level = None
        self.option_st_at_entry = option_st_dir

    def on_exit(self, ist_dt: datetime, reason: ExitReason | None = None) -> None:
        self.side = None
        self.lots = 0
        self.avg_entry = 0.0
        self.strike = None
        self.entry_ist = None
        self.last_scale_ist = None
        self.ema_break_bars = 0
        self.cam_reject_bars = 0
        self.cam_reject_level = None
        self.option_st_at_entry = None
        self.last_exit_ist = ist_dt
        if reason in (ExitReason.DAY_LOSS_CAP, ExitReason.SQUARE_OFF):
            self.day_ended = True


# --------------------------------------------------------------------------- #
# Signals
# --------------------------------------------------------------------------- #


@dataclass(slots=True)
class EntrySignal:
    side: Side
    lots: int
    conditions: dict[str, bool]


@dataclass(slots=True)
class ScaleSignal:
    side: Side
    lots: int
    conditions: dict[str, bool]


@dataclass(slots=True)
class ExitSignal:
    reason: ExitReason
    detail: str = ""


@dataclass(slots=True)
class RollupSignal:
    side: Side
    lots: int
    from_strike: float | None
    trigger_ltp: float


# --------------------------------------------------------------------------- #
# Entry
# --------------------------------------------------------------------------- #


def _ema_condition(
    ema9: float | None,
    ema20: float | None,
    ema9_prev: float | None,
    ema20_prev: float | None,
    bullish: bool,
) -> bool:
    """EMA9/20 alignment: a fresh cross, or already aligned and sloping the right way.

    Missing history fails closed — a bar with no previous EMA pair cannot establish
    either a cross or a slope.
    """
    if ema9 is None or ema20 is None or ema9_prev is None or ema20_prev is None:
        return False
    if bullish:
        if not ema9 > ema20:
            return False
        crossed = ema9_prev <= ema20_prev
        sloping = ema9 > ema9_prev
        return crossed or sloping
    if not ema9 < ema20:
        return False
    crossed = ema9_prev >= ema20_prev
    sloping = ema9 < ema9_prev
    return crossed or sloping


def entry_conditions(
    inp: IntradayInputs, params: IntradayParams, side: Side
) -> dict[str, bool]:
    """The four entry conditions for *side*, each independently reported.

    Returned even when the overall gate fails, so the decision trace records exactly
    which condition blocked the trade.
    """
    bullish = side is Side.PE

    if bullish:
        orb_ok = inp.orb_low is not None and inp.spot > inp.orb_low
        vwap_ok = inp.session_vwap is not None and inp.spot > inp.session_vwap
        st_ok = inp.st_5m_dir is not None and inp.st_5m_dir > 0
    else:
        orb_ok = inp.orb_high is not None and inp.spot < inp.orb_high
        vwap_ok = inp.session_vwap is not None and inp.spot < inp.session_vwap
        st_ok = inp.st_5m_dir is not None and inp.st_5m_dir < 0

    ema_ok = _ema_condition(
        inp.ema9_5m, inp.ema20_5m, inp.ema9_prev_5m, inp.ema20_prev_5m, bullish
    )

    if params.require_15m_confirm:
        if inp.ema9_15m is None or inp.ema20_15m is None or inp.st_15m_dir is None:
            ema_ok = False
            st_ok = False
        else:
            aligned_15m = (
                inp.ema9_15m > inp.ema20_15m if bullish else inp.ema9_15m < inp.ema20_15m
            )
            ema_ok = ema_ok and aligned_15m
            st_ok = st_ok and (inp.st_15m_dir > 0 if bullish else inp.st_15m_dir < 0)

    if params.atm_option_vwap_gate:
        # Additive filter: the option being bid up above its own VWAP is adverse for
        # a seller. `None` means "not evaluated" and fails closed like any other
        # missing input.
        vwap_ok = vwap_ok and inp.atm_option_vwap_ok is True

    return {
        COND_ORB: orb_ok,
        COND_VWAP: vwap_ok,
        COND_SUPERTREND: st_ok,
        COND_EMA: ema_ok,
    }


def _entry_block(
    inp: IntradayInputs, params: IntradayParams, state: IntradayState
) -> EntryBlock | None:
    if state.day_ended:
        return EntryBlock.DAY_ENDED
    now = inp.ist_dt.time()
    if now < params.entry_after_ist:
        return EntryBlock.BEFORE_ENTRY_WINDOW
    if now >= params.squareoff_ist:
        return EntryBlock.AT_OR_AFTER_SQUAREOFF
    if state.is_open:
        return EntryBlock.ALREADY_POSITIONED
    if state.last_exit_ist is not None and params.reentry_cooloff_minutes > 0:
        elapsed = inp.ist_dt - state.last_exit_ist
        if elapsed < timedelta(minutes=params.reentry_cooloff_minutes):
            return EntryBlock.REENTRY_COOLOFF
    return None


def evaluate_entry(
    inp: IntradayInputs, params: IntradayParams, state: IntradayState
) -> tuple[EntrySignal | None, EntryBlock | None, dict[str, dict[str, bool]]]:
    """Decide whether to open a position on this bar.

    Returns ``(signal, block_reason, per_side_conditions)``. Exactly one of *signal*
    and *block_reason* is non-``None``. The condition map is always returned — an
    empty dict when a session/state gate blocked before conditions were evaluated —
    so the caller can log why nothing happened without re-deriving it.

    Only one side can qualify at a time: the ORB, VWAP and SuperTrend conditions are
    mutually exclusive between PE and CE, so a simultaneous pass is impossible. The
    PE side is still checked first for determinism.
    """
    block = _entry_block(inp, params, state)
    if block is not None:
        return None, block, {}

    per_side: dict[str, dict[str, bool]] = {}
    for side in (Side.PE, Side.CE):
        conds = entry_conditions(inp, params, side)
        per_side[side.value] = conds
        if all(conds.values()):
            return (
                EntrySignal(side=side, lots=params.initial_lots, conditions=conds),
                None,
                per_side,
            )
    return None, EntryBlock.CONDITIONS_UNMET, per_side


# --------------------------------------------------------------------------- #
# Scale-in
# --------------------------------------------------------------------------- #


def evaluate_scale_in(
    inp: IntradayInputs, params: IntradayParams, state: IntradayState
) -> ScaleSignal | None:
    """Add to the open leg when the ladder interval has elapsed and the trend holds.

    A scale-in whose conditions have broken is **skipped, not deferred** — the clock
    is not advanced, so the next interval is measured from the last actual add. Lots
    are added at the leg's existing strike; the caller updates the average entry via
    ``IntradayState.on_scale``.
    """
    if not state.is_open or state.side is None:
        return None
    if state.day_ended:
        return None
    if params.scale_lots_step <= 0 or state.lots >= params.max_lots:
        return None
    now = inp.ist_dt.time()
    if now >= params.squareoff_ist:
        return None

    anchor = state.last_scale_ist or state.entry_ist
    if anchor is None:
        return None
    if inp.ist_dt - anchor < timedelta(minutes=params.scale_in_minutes):
        return None

    conds = entry_conditions(inp, params, state.side)
    if not all(conds.values()):
        return None

    add = min(params.scale_lots_step, params.max_lots - state.lots)
    if add <= 0:
        return None
    return ScaleSignal(side=state.side, lots=add, conditions=conds)


# --------------------------------------------------------------------------- #
# Sustained-condition trackers
# --------------------------------------------------------------------------- #


def _cam_levels_for(side: Side, cam: CamLevels) -> list[float]:
    """Levels that threaten *side*: resistance for a bullish position, support for a
    bearish one."""
    return [cam.r3, cam.r4] if side is Side.PE else [cam.s3, cam.s4]


def update_sustained_trackers(
    inp: IntradayInputs, params: IntradayParams, state: IntradayState
) -> None:
    """Advance the EMA20-break and Camarilla-rejection counters for one decision bar.

    Must be called **exactly once per closed decision bar, before ``evaluate_exit``**,
    on both paths. Calling it twice for one bar, or skipping a bar, changes when the
    sustained exits fire — which is precisely the kind of drift the shared core exists
    to prevent.
    """
    if not state.is_open or state.side is None:
        state.ema_break_bars = 0
        state.cam_reject_bars = 0
        state.cam_reject_level = None
        return

    bullish = state.side is Side.PE

    # --- Rule 1: sustained close on the wrong side of the 20-EMA -----------------
    if inp.ema20_5m is None:
        # Unknown EMA cannot evidence a break; hold the counter rather than
        # resetting it, so a one-bar data hole doesn't silently restart the clock.
        pass
    else:
        wrong_side = inp.spot < inp.ema20_5m if bullish else inp.spot > inp.ema20_5m
        state.ema_break_bars = state.ema_break_bars + 1 if wrong_side else 0

    # --- Rule 4: sustained rejection from a Camarilla level ----------------------
    if inp.cam is None:
        state.cam_reject_bars = 0
        state.cam_reject_level = None
        return

    if state.cam_reject_level is not None:
        # Already tracking a rejection — it persists while price stays rejected.
        level = state.cam_reject_level
        still_rejected = inp.spot < level if bullish else inp.spot > level
        if still_rejected:
            state.cam_reject_bars += 1
        else:
            state.cam_reject_bars = 0
            state.cam_reject_level = None
        return

    # Look for a fresh rejection: price reached a threatening level this bar and
    # closed back away from it.
    high = inp.bar_high if inp.bar_high is not None else inp.spot
    low = inp.bar_low if inp.bar_low is not None else inp.spot
    eps = params.cam_touch_eps
    for level in _cam_levels_for(state.side, inp.cam):
        if bullish:
            touched = high >= level * (1.0 - eps)
            rejected = inp.spot < level
        else:
            touched = low <= level * (1.0 + eps)
            rejected = inp.spot > level
        if touched and rejected:
            state.cam_reject_level = level
            state.cam_reject_bars = 1
            return


# --------------------------------------------------------------------------- #
# Exits
# --------------------------------------------------------------------------- #


def unrealized_pnl(state: IntradayState, ltp: float, lot_size: int) -> float:
    """Unrealised P&L of the open short, in rupees.

    Returns ``0.0`` for an unpriced leg (``avg_entry <= 0``) rather than a phantom
    value — the single source of P&L sign for this strategy, mirroring the invariant
    that a zero entry price must never fabricate MTM.
    """
    if not state.is_open or state.avg_entry <= 0 or lot_size <= 0:
        return 0.0
    return (state.avg_entry - ltp) * state.lots * lot_size


def evaluate_price_exit(
    params: IntradayParams,
    state: IntradayState,
    *,
    ltp: float | None,
    day_pnl: float,
    now_ist: datetime,
) -> ExitSignal | None:
    """The four exit rules that need only a price, a clock and the day's P&L.

    Split out so the live path can evaluate them on every tick — where they belong,
    since a premium spike between two 5-minute bars is exactly what they guard — while
    the bar path gets them for free through :func:`evaluate_exit`. One implementation,
    two cadences; the tick path must never re-derive these comparisons itself.
    """
    if day_pnl <= -params.day_loss_limit:
        return ExitSignal(
            ExitReason.DAY_LOSS_CAP,
            f"day_pnl={day_pnl:.2f} <= -{params.day_loss_limit:.2f}",
        )

    if now_ist.time() >= params.squareoff_ist:
        return ExitSignal(ExitReason.SQUARE_OFF, f"at {now_ist.time().isoformat()}")

    if not state.is_open:
        return None

    # Both premium stops compare the option's price to its average entry; a
    # non-positive entry price cannot yield a meaningful ratio, so both abstain.
    if ltp is not None and ltp > 0 and state.avg_entry > 0:
        rise = (ltp - state.avg_entry) / state.avg_entry
        if rise >= params.unreal_loss_pct:
            return ExitSignal(
                ExitReason.UNREAL_LOSS_STOP,
                f"premium +{rise:.1%} >= {params.unreal_loss_pct:.1%}",
            )
        if rise >= params.premium_rise_stop_pct:
            return ExitSignal(
                ExitReason.PREMIUM_RISE_STOP,
                f"premium +{rise:.1%} >= {params.premium_rise_stop_pct:.1%}",
            )
    return None


def evaluate_exit(
    inp: IntradayInputs,
    params: IntradayParams,
    state: IntradayState,
    *,
    ltp: float | None,
    day_pnl: float,
) -> ExitSignal | None:
    """The eight exit rules in fixed priority order; the first match wins.

    ``day_pnl`` is the session's **total** P&L — realised plus the open position's
    mark-to-market — and is negative for a loss. It must include open MTM: the daily
    cap is specified as an *exit* rule, so checking realised P&L alone would make it
    unreachable while positioned (the only way to realise a loss is to close, and
    closing is what the rule is supposed to trigger). Callers compute it as
    ``realised + unrealized_pnl(state, ltp, lot_size)``.

    ``ltp`` is the sold option's traded price, or ``None`` when unavailable — the
    premium-based rules abstain rather than firing on a guess.

    The two day-ending reasons (``DAY_LOSS_CAP``, ``SQUARE_OFF``) are returned even
    when flat, because they end the session rather than merely closing a position:
    the caller closes whatever is open and marks the day done via
    ``IntradayState.on_exit``. All other reasons require an open position.
    """
    price_sig = evaluate_price_exit(
        params, state, ltp=ltp, day_pnl=day_pnl, now_ist=inp.ist_dt
    )
    if price_sig is not None:
        return price_sig

    if not state.is_open or state.side is None:
        return None

    # Underlying SuperTrend flip. The entry gate guarantees ST agreed with the
    # position at open, so any disagreement now is a flip.
    if inp.st_5m_dir is not None and inp.st_5m_dir != state.side.bias:
        return ExitSignal(
            ExitReason.UNDERLYING_ST_FLIP, f"st_5m={inp.st_5m_dir} vs {state.side.value}"
        )

    # Option-chart SuperTrend flip. Adverse for any short is the option trending UP
    # (+1). Compared against the direction observed at entry so a position opened
    # while the option chart was already green is not exited on the very next bar —
    # the rule is "flips colour", not "is green".
    if (
        inp.option_st_dir is not None
        and inp.option_st_dir > 0
        and state.option_st_at_entry is not None
        and state.option_st_at_entry != inp.option_st_dir
    ):
        return ExitSignal(
            ExitReason.OPTION_ST_FLIP,
            f"option st {state.option_st_at_entry} -> {inp.option_st_dir}",
        )

    if state.ema_break_bars >= params.ema_break_bars:
        return ExitSignal(
            ExitReason.EMA20_BREAK_SUSTAINED,
            f"{state.ema_break_bars} consecutive wrong-side closes",
        )

    if state.cam_reject_bars >= params.cam_reject_bars:
        level = state.cam_reject_level
        return ExitSignal(
            ExitReason.CAM_REJECTION_SUSTAINED,
            f"rejected from {level} for {state.cam_reject_bars} bars",
        )

    return None


# --------------------------------------------------------------------------- #
# Rollup to ATM
# --------------------------------------------------------------------------- #


def evaluate_rollup(
    params: IntradayParams,
    state: IntradayState,
    *,
    ltp: float | None,
    now_ist: datetime,
) -> RollupSignal | None:
    """Signal a roll of the decayed leg back to ATM.

    Only the *trigger* is decided here. Whether the roll can actually complete
    depends on the ATM contract's price, which needs chain access — the caller
    checks that with ``rollup_target_acceptable`` and MUST verify it **before**
    closing the existing leg, so a roll that cannot reopen leaves the position
    untouched rather than flat.
    """
    if not params.roll_enabled or not state.is_open or state.side is None:
        return None
    if state.day_ended or ltp is None or ltp <= 0:
        return None
    if ltp >= params.roll_trigger_prem:
        return None
    if state.rolls_today >= params.max_rolls_per_day:
        return None
    now = now_ist.time()
    if now >= params.roll_cutoff_ist or now >= params.squareoff_ist:
        return None
    return RollupSignal(
        side=state.side,
        lots=state.lots,
        from_strike=state.strike,
        trigger_ltp=ltp,
    )


def rollup_target_acceptable(new_ltp: float | None, params: IntradayParams) -> bool:
    """Whether the prospective ATM contract is rich enough to roll into."""
    return new_ltp is not None and new_ltp >= params.roll_target_min_prem
