"""Shared detector context + small stateful helpers (no I/O)."""
from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from pdp.events.config import EventConfig
    from pdp.indicators.snapshot import Snapshot
    from pdp.indicators.supertrend import SuperTrendState


@dataclass(slots=True)
class BarContext:
    """Everything a spot/indicator detector needs for one closed bar."""

    security_id: str
    underlying: str | None
    timeframe: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    bar_time: datetime
    snapshot: Snapshot | None
    supertrend: SuperTrendState | None
    ml_signal: Any
    cfg: EventConfig
    # (label, price) OI walls for the underlying, injected by EventService from the
    # latest option-chain analysis; used by the confluence detector.
    oi_levels: list[tuple[str, float]] = ()  # type: ignore[assignment]


class PrevStore:
    """Per-key memory of the previous scalar/relation, for cross/flip/label edges."""

    __slots__ = ("_v",)

    def __init__(self) -> None:
        self._v: dict[str, Any] = {}

    def get(self, key: str) -> Any:
        return self._v.get(key)

    def set(self, key: str, value: Any) -> None:
        self._v[key] = value

    def changed(self, key: str, value: Any) -> bool:
        """True when ``value`` differs from the stored one (after updating)."""
        prev = self._v.get(key)
        self._v[key] = value
        return prev is not None and prev != value

    def crossed(self, key: str, a: float, b: float) -> int:
        """Detect a→b crossing. Returns +1 (a crossed above b), -1 (below), 0 none.

        Stores the sign of (a - b) per key; only reports on a sign flip.
        """
        cur = 1 if a > b else (-1 if a < b else 0)
        prev = self._v.get(key)
        self._v[key] = cur
        if prev is None or cur == 0 or prev == 0 or cur == prev:
            return 0
        return cur


class RollingZ:
    """Bounded rolling window → z-score of the latest value vs the prior window."""

    __slots__ = ("_maxlen", "_w")

    def __init__(self, maxlen: int = 30) -> None:
        self._w: dict[str, deque[float]] = {}
        self._maxlen = maxlen

    def push(self, key: str, value: float) -> float | None:
        """Append ``value``; return its z-score vs the window *before* it, or None."""
        w = self._w.get(key)
        if w is None:
            w = self._w[key] = cast("deque[float]", deque(maxlen=self._maxlen))
        z: float | None = None
        if len(w) >= 8:
            mean = sum(w) / len(w)
            var = sum((x - mean) ** 2 for x in w) / len(w)
            std = math.sqrt(var)
            if std > 0:
                z = (value - mean) / std
        w.append(value)
        return z
