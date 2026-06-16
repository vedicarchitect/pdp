"""Indicator registry: maps family name → (tracker class, default params).

Import this module to register all built-in families. External code calls
``build_tracker(name, params)`` to instantiate a tracker with merged defaults.
"""
from __future__ import annotations

from typing import Any

from pdp.indicators.ema import EMATracker
from pdp.indicators.fvg import FVGTracker
from pdp.indicators.market_profile import MarketProfileTracker
from pdp.indicators.pivots import PivotTracker
from pdp.indicators.psar import ParabolicSARTracker
from pdp.indicators.rsi import RSITracker
from pdp.indicators.volume_profile import VolumeProfileTracker
from pdp.indicators.vwap import VWAPTracker
from pdp.indicators.vwma import VWMATracker

# family_name -> (tracker_class, default_kwargs)
_REGISTRY: dict[str, tuple[type, dict[str, Any]]] = {}


def _register(name: str, cls: type, defaults: dict[str, Any]) -> None:
    _REGISTRY[name] = (cls, defaults)


_register("ema", EMATracker, {"periods": [9, 20, 50, 100, 200]})
_register("rsi", RSITracker, {"period": 14, "ma_period": 9})
_register("psar", ParabolicSARTracker, {"step": 0.02, "max_step": 0.2})
_register("vwap", VWAPTracker, {})
_register("vwma", VWMATracker, {"period": 20})
_register("pivots", PivotTracker, {})
_register("fvg", FVGTracker, {"max_gaps": 50})
_register("volume_profile", VolumeProfileTracker, {"bucket_size": 50.0, "value_area_pct": 0.70})
_register("market_profile", MarketProfileTracker, {"bucket_size": 50.0})


def build_tracker(family: str, params: dict[str, Any] | None = None) -> Any:
    """Instantiate a tracker for the given family, merging params over registry defaults."""
    if family not in _REGISTRY:
        raise KeyError(f"unknown indicator family: {family!r}. Available: {list(_REGISTRY)}")
    cls, defaults = _REGISTRY[family]
    merged = {**defaults, **(params or {})}
    return cls(**merged)


def available_families() -> list[str]:
    return list(_REGISTRY)
