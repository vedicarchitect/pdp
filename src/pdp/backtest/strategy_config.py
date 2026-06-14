"""Configurable SuperTrend option-selling strategy parameters.

``StrategyConfig`` captures every knob the backtest engine (``pdp.backtest.sim``) needs so a
variant can be described as data and swept without editing source. It is dict-constructable
(``from_dict`` / ``to_dict``) so a frontend can persist and replay configs later.

Scope: backtest only. The live/paper strategy is configured separately via its YAML.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import time
from typing import Any

# Signal timeframes the resampler + warehouse support (minutes).
SUPPORTED_TIMEFRAMES = (3, 5, 15, 30, 60)

# Scale-in gate modes.
SCALE_PREMIUM_BREAK = "premium_break"          # add when option premium breaks prior bar's low (NEW)
SCALE_PREMIUM_NO_NEW_HIGH = "premium_no_new_high"  # legacy: add unless premium made a new high
SCALE_ALWAYS = "always"                          # add every bar while under max lots
_SCALE_MODES = (SCALE_PREMIUM_BREAK, SCALE_PREMIUM_NO_NEW_HIGH, SCALE_ALWAYS)

# Flip handling modes.
FLIP_STRANGLE = "strangle"      # close additional legs, keep old base, open opposite base (NEW)
FLIP_CLOSE_ALL = "close_all"    # legacy: close everything, open opposite
_FLIP_MODES = (FLIP_STRANGLE, FLIP_CLOSE_ALL)


def _parse_hhmm(value: str | time) -> time:
    if isinstance(value, time):
        return value
    hh, mm = str(value).split(":")
    return time(int(hh), int(mm))


@dataclass
class StrategyConfig:
    """All knobs for one SuperTrend option-selling variant.

    ``moneyness`` is a signed strike offset in ``strike_step`` units: ``>0`` OTM, ``0`` ATM,
    ``<0`` ITM (interpreted per option type in ``sim.select_strike``).
    """

    # SuperTrend
    st_period: int = 3
    st_multiplier: float = 1.0
    # Signal timeframe (minutes)
    timeframe_min: int = 5
    # Strike selection
    moneyness: int = 1          # +1 = OTM-1 (legacy default)
    strike_step: int = 50
    # Sizing
    base_lots: int = 2
    add_lots: int = 1
    max_lots: int = 5
    lot_size: int = 65
    # Session window (IST)
    start_ist: time = field(default_factory=lambda: time(9, 30))
    squareoff_ist: time = field(default_factory=lambda: time(15, 10))
    # Risk
    leg_stop_per_lot: float = 3_000.0
    day_stop: float = 20_000.0
    # Roll-up on premium decay
    roll_enabled: bool = True
    roll_trigger_prem: float = 20.0
    roll_target_min_prem: float = 50.0
    # Behaviour modes
    scale_in_gate: str = SCALE_PREMIUM_BREAK
    flip_mode: str = FLIP_STRANGLE

    def __post_init__(self) -> None:
        self.start_ist = _parse_hhmm(self.start_ist)
        self.squareoff_ist = _parse_hhmm(self.squareoff_ist)
        self.validate()

    # -- validation -------------------------------------------------------- #
    def validate(self) -> None:
        if self.st_period < 1:
            raise ValueError(f"st_period must be >= 1, got {self.st_period}")
        if self.st_multiplier <= 0:
            raise ValueError(f"st_multiplier must be > 0, got {self.st_multiplier}")
        if self.timeframe_min not in SUPPORTED_TIMEFRAMES:
            raise ValueError(
                f"timeframe_min must be one of {SUPPORTED_TIMEFRAMES}, got {self.timeframe_min}"
            )
        if self.base_lots < 1:
            raise ValueError(f"base_lots must be >= 1, got {self.base_lots}")
        if self.add_lots < 0:
            raise ValueError(f"add_lots must be >= 0, got {self.add_lots}")
        if self.max_lots < self.base_lots:
            raise ValueError(
                f"max_lots ({self.max_lots}) must be >= base_lots ({self.base_lots})"
            )
        if self.lot_size < 1:
            raise ValueError(f"lot_size must be >= 1, got {self.lot_size}")
        if self.strike_step < 1:
            raise ValueError(f"strike_step must be >= 1, got {self.strike_step}")
        if self.scale_in_gate not in _SCALE_MODES:
            raise ValueError(f"scale_in_gate must be one of {_SCALE_MODES}, got {self.scale_in_gate}")
        if self.flip_mode not in _FLIP_MODES:
            raise ValueError(f"flip_mode must be one of {_FLIP_MODES}, got {self.flip_mode}")

    # -- (de)serialization ------------------------------------------------- #
    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> StrategyConfig:
        """Build a config from a plain dict (unknown keys rejected)."""
        known = {f for f in cls.__dataclass_fields__}  # noqa: C416
        unknown = set(d) - known
        if unknown:
            raise ValueError(f"unknown StrategyConfig keys: {sorted(unknown)}")
        return cls(**d)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict; times become ``HH:MM`` strings (JSON/frontend friendly)."""
        out = asdict(self)
        out["start_ist"] = self.start_ist.strftime("%H:%M")
        out["squareoff_ist"] = self.squareoff_ist.strftime("%H:%M")
        return out

    @property
    def timeframe(self) -> str:
        """Signal timeframe label, e.g. ``"5m"``."""
        return f"{self.timeframe_min}m"

    # -- factories --------------------------------------------------------- #
    @classmethod
    def legacy(cls) -> StrategyConfig:
        """The pre-refactor backtest_multiday.py configuration (regression anchor).

        ST(3,1), 5m, OTM-1, base 2 / add 1 / max 5, legacy scale-in and flip rules, roll on.
        """
        return cls(
            st_period=3,
            st_multiplier=1.0,
            timeframe_min=5,
            moneyness=1,
            strike_step=50,
            base_lots=2,
            add_lots=1,
            max_lots=5,
            lot_size=65,
            start_ist=time(9, 30),
            squareoff_ist=time(15, 10),
            leg_stop_per_lot=3_000.0,
            day_stop=20_000.0,
            roll_enabled=True,
            roll_trigger_prem=20.0,
            roll_target_min_prem=50.0,
            scale_in_gate=SCALE_PREMIUM_NO_NEW_HIGH,
            flip_mode=FLIP_CLOSE_ALL,
        )

    def label(self) -> str:
        """Compact one-line identity for sweep tables, e.g. ``ST(10,2) 15m OTM1``."""
        if self.moneyness > 0:
            mny = f"OTM{self.moneyness}"
        elif self.moneyness < 0:
            mny = f"ITM{abs(self.moneyness)}"
        else:
            mny = "ATM"
        mult = int(self.st_multiplier) if float(self.st_multiplier).is_integer() else self.st_multiplier
        return f"ST({self.st_period},{mult}) {self.timeframe} {mny}"
