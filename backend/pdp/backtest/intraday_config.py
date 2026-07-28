"""Configuration for the intraday directional option-selling backtest.

``IntradayDirectionalConfig`` captures every knob ``pdp.backtest.intraday_sim`` needs.
The decision knobs are a flat mirror of ``pdp.signals.intraday_directional.IntradayParams``
and are handed to the shared core via :meth:`to_params`, so a value means the same thing
in the backtest YAML, in the live strategy YAML, and inside the core.

It is dict/YAML-constructable so configs are data and can be swept without editing
source — mirroring ``StrangleConfig``. It deliberately reuses ``strangle_config``'s
lot-size history and security-id map so notional sizing is identical era-for-era to the
directional strangle, which is what makes the two strategies comparable.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, time
from pathlib import Path
from typing import Any

import yaml

from pdp.backtest.strangle_config import SECURITY_IDS, lot_size_for_date
from pdp.signals.intraday_directional import (
    VWAP_OFF,
    VWAP_SESSION_TWAP,
    VWAP_SOURCES,
    IntradayParams,
)

# `VWAP_*` are defined by the shared decision core and re-exported here for the loader
# and existing call sites — the core is the one place both engines agree on semantics.
__all__ = [
    "SECURITY_IDS",
    "VWAP_OFF",
    "VWAP_SESSION_TWAP",
    "VWAP_SOURCES",
    "IntradayDirectionalConfig",
    "lot_size_for_date",
]

# Default strike step per underlying, matching pdp.strategy.strikes.STRIKE_STEP.
_STRIKE_STEPS: dict[str, int] = {"NIFTY": 50, "BANKNIFTY": 100, "SENSEX": 100}


def _parse_hhmm(value: str | time) -> time:
    if isinstance(value, time):
        return value
    hh, mm = str(value).split(":")
    return time(int(hh), int(mm))


@dataclass
class IntradayDirectionalConfig:
    """All knobs for one intraday-directional variant."""

    # -- Instrument ---------------------------------------------------------- #
    underlying: str = "NIFTY"
    security_id: str = "13"
    strike_step: int = 50
    lot_size: int = 75

    # -- Timeframes ---------------------------------------------------------- #
    timeframe_min: int = 5
    confirm_timeframe_min: int = 15

    # -- Session (IST) ------------------------------------------------------- #
    # Entries only after the 09:15-09:30 opening-range candle has closed.
    entry_after_ist: time = field(default_factory=lambda: time(9, 30))
    squareoff_ist: time = field(default_factory=lambda: time(15, 15))
    orb_start_ist: time = field(default_factory=lambda: time(9, 15))
    orb_minutes: int = 15

    # -- Strike selection ---------------------------------------------------- #
    # Signed moneyness: 0 = ATM, negative = ITM (the source spec prefers ATM or 1-2 ITM),
    # positive = OTM. Passed straight to ``pdp.backtest.sim.select_strike``.
    moneyness: int = 0
    # Only trade days whose nearest real expiry is within this many calendar days.
    # The source spec requires DTE strictly < 7, i.e. dte_max = 6.
    dte_max: int | None = 6

    # -- Sizing ladder ------------------------------------------------------- #
    initial_lots: int = 3
    scale_lots_step: int = 3
    max_lots: int = 9
    scale_in_minutes: int = 15

    # -- Re-entry ------------------------------------------------------------ #
    reentry_cooloff_minutes: int = 15

    # -- Exits --------------------------------------------------------------- #
    day_loss_limit: float = 10_000.0
    premium_rise_stop_pct: float = 1.0   # 1.0 == premium doubles (source spec's "1%" read as 100%)
    unreal_loss_pct: float = 0.20
    ema_break_bars: int = 3
    cam_reject_minutes: int = 30
    cam_touch_eps: float = 0.001

    # -- Rollup to ATM on premium decay -------------------------------------- #
    roll_enabled: bool = True
    roll_trigger_prem: float = 20.0
    roll_target_min_prem: float = 50.0
    max_rolls_per_day: int = 2
    roll_cutoff_ist: time = field(default_factory=lambda: time(14, 45))

    # -- Optional gates ------------------------------------------------------ #
    require_15m_confirm: bool = False
    atm_option_vwap_gate: bool = False

    # -- Session VWAP source ------------------------------------------------- #
    # The spot index carries no traded volume, so a true VWAP can never converge on it.
    # ``session_twap`` is a session-anchored cumulative mean of typical price (h+l+c)/3
    # over the underlying's 1m bars — identical on the live and backtest paths.
    vwap_source: str = VWAP_SESSION_TWAP

    # -- Indicator parameters ------------------------------------------------ #
    ema_fast: int = 9
    ema_slow: int = 20
    st_period: int = 10
    st_mult: float = 2.0
    # SuperTrend(st_period, st_mult) on the sold option's own decision-tf chart.
    option_st_enabled: bool = True

    # -- Protective hedge ---------------------------------------------------- #
    hedge_enabled: bool = False
    hedge_prem_min: float = 2.0
    hedge_prem_max: float = 5.0

    def __post_init__(self) -> None:
        self.entry_after_ist = _parse_hhmm(self.entry_after_ist)
        self.squareoff_ist = _parse_hhmm(self.squareoff_ist)
        self.orb_start_ist = _parse_hhmm(self.orb_start_ist)
        self.roll_cutoff_ist = _parse_hhmm(self.roll_cutoff_ist)
        self.validate()

    # -- validation ---------------------------------------------------------- #
    def validate(self) -> None:
        if self.underlying not in SECURITY_IDS:
            raise ValueError(
                f"underlying must be one of {sorted(SECURITY_IDS)}, got {self.underlying}"
            )
        if self.strike_step < 1:
            raise ValueError(f"strike_step must be >= 1, got {self.strike_step}")
        if self.lot_size < 1:
            raise ValueError(f"lot_size must be >= 1, got {self.lot_size}")
        if self.confirm_timeframe_min < self.timeframe_min:
            raise ValueError(
                f"confirm_timeframe_min must be >= timeframe_min, got "
                f"{self.confirm_timeframe_min} < {self.timeframe_min}"
            )
        if self.orb_minutes < 1:
            raise ValueError(f"orb_minutes must be >= 1, got {self.orb_minutes}")
        if self.dte_max is not None and self.dte_max < 0:
            raise ValueError(f"dte_max must be >= 0 or None, got {self.dte_max}")
        if self.vwap_source not in VWAP_SOURCES:
            raise ValueError(
                f"vwap_source must be one of {VWAP_SOURCES}, got {self.vwap_source}"
            )
        if self.ema_fast < 1 or self.ema_slow <= self.ema_fast:
            raise ValueError(
                f"require 1 <= ema_fast < ema_slow, got fast={self.ema_fast} slow={self.ema_slow}"
            )
        if self.st_period < 1:
            raise ValueError(f"st_period must be >= 1, got {self.st_period}")
        if self.st_mult <= 0:
            raise ValueError(f"st_mult must be > 0, got {self.st_mult}")
        if self.hedge_enabled and not 0.0 < self.hedge_prem_min <= self.hedge_prem_max:
            raise ValueError(
                f"hedge premiums must satisfy 0 < min <= max, got "
                f"({self.hedge_prem_min}, {self.hedge_prem_max})"
            )
        # Everything the shared core owns is validated by the core itself, so the
        # rules can never drift between the config and the engine that reads it.
        self.to_params().validate()

    # -- shared-core bridge --------------------------------------------------- #
    def to_params(self) -> IntradayParams:
        """Project the decision knobs onto the shared core's parameter object."""
        return IntradayParams(
            timeframe_min=self.timeframe_min,
            confirm_timeframe_min=self.confirm_timeframe_min,
            entry_after_ist=self.entry_after_ist,
            squareoff_ist=self.squareoff_ist,
            initial_lots=self.initial_lots,
            scale_lots_step=self.scale_lots_step,
            max_lots=self.max_lots,
            scale_in_minutes=self.scale_in_minutes,
            reentry_cooloff_minutes=self.reentry_cooloff_minutes,
            day_loss_limit=self.day_loss_limit,
            premium_rise_stop_pct=self.premium_rise_stop_pct,
            unreal_loss_pct=self.unreal_loss_pct,
            ema_break_bars=self.ema_break_bars,
            cam_reject_minutes=self.cam_reject_minutes,
            cam_touch_eps=self.cam_touch_eps,
            roll_enabled=self.roll_enabled,
            roll_trigger_prem=self.roll_trigger_prem,
            roll_target_min_prem=self.roll_target_min_prem,
            max_rolls_per_day=self.max_rolls_per_day,
            roll_cutoff_ist=self.roll_cutoff_ist,
            require_15m_confirm=self.require_15m_confirm,
            atm_option_vwap_gate=self.atm_option_vwap_gate,
        )

    def for_date(self, trade_date: date) -> IntradayDirectionalConfig:
        """A copy whose ``lot_size`` is the exchange-mandated size on *trade_date*.

        Uses the same lot-size history as the strangle engine so a cross-strategy
        comparison over one window sizes both books identically.
        """
        lot = lot_size_for_date(self.underlying, trade_date)
        if lot == self.lot_size:
            return self
        return IntradayDirectionalConfig.from_dict({**self.to_dict(), "lot_size": lot})

    # -- (de)serialization ---------------------------------------------------- #
    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> IntradayDirectionalConfig:
        d = dict(d)
        known = set(cls.__dataclass_fields__)
        unknown = set(d) - known
        if unknown:
            raise ValueError(f"unknown IntradayDirectionalConfig keys: {sorted(unknown)}")
        # Keep security_id / strike_step consistent with the underlying unless the
        # caller set them explicitly.
        underlying = str(d.get("underlying", cls.underlying)).upper()
        d.setdefault("security_id", SECURITY_IDS.get(underlying, "13"))
        d.setdefault("strike_step", _STRIKE_STEPS.get(underlying, 50))
        return cls(**d)

    @classmethod
    def from_yaml(cls, path: str | Path) -> IntradayDirectionalConfig:
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"IntradayDirectionalConfig YAML not found: {path}")
        with p.open() as f:
            data = yaml.safe_load(f)
        return cls.from_dict(data)

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        for key in ("entry_after_ist", "squareoff_ist", "orb_start_ist", "roll_cutoff_ist"):
            out[key] = getattr(self, key).strftime("%H:%M")
        return out

    def to_yaml(self, path: str | Path) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("w") as f:
            yaml.safe_dump(self.to_dict(), f, default_flow_style=False, sort_keys=True)

    @property
    def timeframe(self) -> str:
        return f"{self.timeframe_min}m"
