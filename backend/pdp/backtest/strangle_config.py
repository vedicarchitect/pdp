"""Configuration for the bias-driven directional-strangle backtest.

``StrangleConfig`` captures every knob ``pdp.backtest.strangle_sim`` needs: the
bias weights/thresholds (delegated to ``pdp.signals.bias.BiasWeights``), the
PE:CE ratio table per bias bucket, strike-selection method, and the leg-exit
rules from ``strategies/MultiTimeFrameSelling.txt`` (rollup, take-profit,
premium-doubled stop, trend-flip adjustment, daily-loss cap).

It is dict/YAML-constructable so configs are data and can be swept / walk-forward
optimized without editing source — mirroring ``StrategyConfig``.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, time
from pathlib import Path
from typing import Any

import yaml

from pdp.signals.bias import DEFAULT_RATIO_TABLE, BiasBucket, BiasWeights

# Lot-size history per underlying — (effective_from, lot_size). Last entry covers "now".
_LOT_HISTORY: dict[str, list[tuple[date, int]]] = {
    "NIFTY": [
        (date(2000, 1, 1),  75),   # pre-Jul 2021 baseline
        (date(2021, 7, 1),  50),   # reduced: NIFTY crossed 15k–16k
        (date(2024, 4, 1),  25),   # halved: NIFTY near 22k+
        (date(2025, 1, 1),  75),   # SEBI min contract value → ₹15L
        (date(2026, 1, 1),  65),   # periodic review realignment
    ],
    "BANKNIFTY": [
        (date(2000, 1, 1),  25),   # pre-Nov 2019 baseline
        (date(2019, 11, 1), 20),   # increased margin: BN near 32k
        (date(2021, 7, 1),  25),   # reverted after SEBI review
        (date(2024, 4, 1),  15),   # halved: BN near 48k+
        (date(2025, 1, 1),  30),   # SEBI min contract value → ₹15L
    ],
    "SENSEX": [
        (date(2000, 1, 1),  10),   # BSE SENSEX options lot size (stable)
        (date(2025, 1, 1),  20),   # SEBI min contract value → ₹15L
    ],
}

# Security IDs on Dhan IDX_I segment.
SECURITY_IDS: dict[str, str] = {
    "NIFTY": "13",
    "BANKNIFTY": "25",
    "SENSEX": "51",
}

# Weekly expiry weekday per underlying (Python weekday: Mon=0 … Fri=4).
EXPIRY_WEEKDAY: dict[str, int] = {
    "NIFTY": 1,      # Tuesday
    "BANKNIFTY": 3,  # Thursday
    "SENSEX": 4,     # Friday
}


def lot_size_for_date(underlying: str, trade_date: date) -> int:
    """Return the exchange-mandated lot size for *underlying* on *trade_date*."""
    history = _LOT_HISTORY.get(underlying, _LOT_HISTORY["NIFTY"])
    lot = history[0][1]
    for eff_date, size in history:
        if trade_date >= eff_date:
            lot = size
    return lot


def nifty_lot_size(trade_date: date) -> int:
    """Kept for backward-compat; prefer lot_size_for_date('NIFTY', date)."""
    return lot_size_for_date("NIFTY", trade_date)

STRIKE_PREMIUM = "premium"  # nearest strike with premium > premium_floor
STRIKE_DELTA = "delta"      # strike nearest target_delta (IV solved from premium)
_STRIKE_METHODS = (STRIKE_PREMIUM, STRIKE_DELTA)


def _parse_hhmm(value: str | time) -> time:
    if isinstance(value, time):
        return value
    hh, mm = str(value).split(":")
    return time(int(hh), int(mm))


@dataclass
class StrangleConfig:
    """All knobs for one directional-strangle variant."""

    # Underlying index and its Dhan spot security ID.
    underlying: str = "NIFTY"
    security_id: str = "13"

    # Signal/decision timeframe (minutes)
    timeframe_min: int = 5
    strike_step: int = 50
    lot_size: int = 65

    # Strike selection
    strike_method: str = STRIKE_PREMIUM
    premium_floor: float = 50.0   # premium > this (premium method)
    target_delta: float = 0.6     # delta method target
    extreme_atm: bool = True      # complete-bull/bear buckets sell ATM (per doc)
    otm_steps: int = 2            # OTM offset for non-extreme buckets (fallback)

    # Session (IST). Entries only AFTER the 10:15 1h candle completes (doc rule).
    entry_after_ist: time = field(default_factory=lambda: time(10, 15))
    squareoff_ist: time = field(default_factory=lambda: time(15, 10))

    # Leg lifecycle / exits
    roll_enabled: bool = True
    roll_trigger_prem: float = 20.0     # rollup when premium < this
    roll_target_min_prem: float = 50.0  # new strike must have premium >= this
    take_profit_pct: float = 0.5        # close leg at this fraction of credit captured
    take_profit_extreme_only: bool = False  # TP only on complete_bull/bear; let balanced legs run
    # Tiered premium stop (replaces premium_doubled 2x rule).
    # At pct_stop_half: close half the lots, keep the rest open (re-entry allowed).
    # At pct_stop_all:  close all remaining lots (re-entry allowed on bias signal).
    pct_stop_enabled: bool = True
    pct_stop_half: float = 0.30         # close half when price >= entry * (1 + this)
    pct_stop_all: float = 0.40          # close all  when price >= entry * (1 + this)
    adjustment_on_flip: bool = True     # roll tested side on bias sign flip
    day_loss_limit: float = 15_000.0    # flatten + halt when day P&L <= -this

    # Protective hedges — buy a far-OTM same-side long per short leg (defined-risk
    # spread instead of a naked short). Hedge strike = furthest-OTM strike whose
    # premium is in [hedge_prem_min, hedge_prem_max]; if none, the cheapest
    # available (least-premium) strike. Run with/without to compare.
    hedge_enabled: bool = False
    hedge_prem_min: float = 2.0
    hedge_prem_max: float = 5.0

    # Session filter — only trade on days where calendar DTE ≤ this.
    # DTE 0 = expiry day, DTE 1 = day before (Mon for Tue-expiry NIFTY weekly).
    # DTE 2 = Sunday (non-trading), so dte_max=1 vs dte_max=2 is equivalent in practice.
    # None = no filter (all trading days).
    dte_max: int | None = None

    # Position sizing
    scale_lots: int = 1  # multiply every ratio_table value by this (1=unchanged, 2=double, ...)

    # Momentum long — buy ITM+1 option on COMPLETE_BULL/BEAR, close when |score| < threshold
    momentum_enabled: bool = False
    momentum_premium_target: float = 50_000.0  # target Rs spend on the ITM long
    momentum_score_threshold: float = 0.5      # close when |score| drops below this

    # Behaviour
    neutral_no_trade: bool = True       # skip the neutral bucket

    # Bias engine
    weights: BiasWeights = field(default_factory=BiasWeights)
    # bucket name -> (pe_lots, ce_lots)
    ratio_table: dict[str, tuple[int, int]] = field(
        default_factory=lambda: {b.value: r for b, r in DEFAULT_RATIO_TABLE.items()}
    )

    def __post_init__(self) -> None:
        self.entry_after_ist = _parse_hhmm(self.entry_after_ist)
        self.squareoff_ist = _parse_hhmm(self.squareoff_ist)
        self.validate()

    # -- validation -------------------------------------------------------- #
    def validate(self) -> None:
        if self.timeframe_min < 1:
            raise ValueError(f"timeframe_min must be >= 1, got {self.timeframe_min}")
        if self.strike_step < 1:
            raise ValueError(f"strike_step must be >= 1, got {self.strike_step}")
        if self.lot_size < 1:
            raise ValueError(f"lot_size must be >= 1, got {self.lot_size}")
        if self.strike_method not in _STRIKE_METHODS:
            raise ValueError(f"strike_method must be one of {_STRIKE_METHODS}, got {self.strike_method}")
        if not 0.0 < self.take_profit_pct:
            raise ValueError(f"take_profit_pct must be > 0, got {self.take_profit_pct}")
        if self.pct_stop_enabled:
            if not 0.0 < self.pct_stop_half < self.pct_stop_all:
                raise ValueError(
                    f"pct_stop_half must be < pct_stop_all and both > 0; "
                    f"got half={self.pct_stop_half} all={self.pct_stop_all}"
                )
        if self.scale_lots < 1:
            raise ValueError(f"scale_lots must be >= 1, got {self.scale_lots}")
        if self.day_loss_limit <= 0:
            raise ValueError(f"day_loss_limit must be > 0, got {self.day_loss_limit}")
        if self.hedge_enabled and not 0.0 < self.hedge_prem_min <= self.hedge_prem_max:
            raise ValueError(
                f"hedge premiums must satisfy 0 < min <= max, got "
                f"({self.hedge_prem_min}, {self.hedge_prem_max})"
            )
        for name, ratio in self.ratio_table.items():
            if name not in BiasBucket.__members__.values() and name not in {b.value for b in BiasBucket}:
                raise ValueError(f"unknown bias bucket in ratio_table: {name}")
            if len(ratio) != 2 or ratio[0] < 0 or ratio[1] < 0:
                raise ValueError(f"ratio for {name} must be (pe_lots>=0, ce_lots>=0), got {ratio}")

    def ratio_for(self, bucket: BiasBucket) -> tuple[int, int]:
        pe, ce = self.ratio_table[bucket.value]
        return int(pe) * self.scale_lots, int(ce) * self.scale_lots

    # -- (de)serialization ------------------------------------------------- #
    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> StrangleConfig:
        d = dict(d)
        known = set(cls.__dataclass_fields__)
        unknown = set(d) - known
        if unknown:
            raise ValueError(f"unknown StrangleConfig keys: {sorted(unknown)}")
        if "weights" in d and isinstance(d["weights"], dict):
            d["weights"] = BiasWeights(**d["weights"])
        if "ratio_table" in d and isinstance(d["ratio_table"], dict):
            d["ratio_table"] = {k: (int(v[0]), int(v[1])) for k, v in d["ratio_table"].items()}
        return cls(**d)

    @classmethod
    def from_yaml(cls, path: str | Path) -> StrangleConfig:
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"StrangleConfig YAML not found: {path}")
        with p.open() as f:
            data = yaml.safe_load(f)
        return cls.from_dict(data)

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["entry_after_ist"] = self.entry_after_ist.strftime("%H:%M")
        out["squareoff_ist"] = self.squareoff_ist.strftime("%H:%M")
        out["ratio_table"] = {k: list(v) for k, v in self.ratio_table.items()}
        return out

    def to_yaml(self, path: str | Path) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("w") as f:
            yaml.safe_dump(self.to_dict(), f, default_flow_style=False, sort_keys=True)

    @property
    def timeframe(self) -> str:
        return f"{self.timeframe_min}m"
