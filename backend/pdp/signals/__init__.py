"""Shared trading-signal logic consumed by both backtest and live strategies.

The bias engine (`bias.py`) is intentionally pure and decoupled from the
indicator-engine state classes: it takes plain numbers in and returns a
`BiasResult`. The live strategy and the backtest simulator each adapt their own
indicator snapshots into `BiasInputs`, guaranteeing identical decisions.
"""
from __future__ import annotations

from pdp.signals.bias import (
    BiasInputs,
    BiasResult,
    BiasWeights,
    CamLevels,
    TimeframeEMA,
    score_bias,
)

__all__ = [
    "BiasInputs",
    "BiasResult",
    "BiasWeights",
    "CamLevels",
    "TimeframeEMA",
    "score_bias",
]
