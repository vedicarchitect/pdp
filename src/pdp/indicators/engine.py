"""Live indicator engine.

Holds one ``SuperTrendTracker`` per ``(security_id, timeframe)`` (backward-compatible) and,
for pairs that have been configured with suite families, a bundle of suite trackers.
``on_bar(bar)`` updates both and caches a ``Snapshot``.

Backward-compatible public surface:
  - ``get(sid, tf)``          → SuperTrendState | None   (unchanged)
  - ``seed_from_bars(bars)``  → int                      (unchanged)

New surface:
  - ``configure_suite(sid, tf, indicators)`` — register which families to compute
  - ``get_snapshot(sid, tf)`` → Snapshot | None
  - ``get_ema(sid, tf)``      → EMAState | None
  - ``get_rsi(sid, tf)``      → RSIState | None
  (etc. — one getter per family)
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

import structlog

from pdp.indicators.snapshot import Snapshot
from pdp.indicators.supertrend import SuperTrendState, SuperTrendTracker

if TYPE_CHECKING:
    from pdp.indicators.ema import EMAState
    from pdp.indicators.fvg import FVGState
    from pdp.indicators.market_profile import MarketProfileState
    from pdp.indicators.pivots import PivotState
    from pdp.indicators.psar import ParabolicSARState
    from pdp.indicators.rsi import RSIState
    from pdp.indicators.volume_profile import VolumeProfileState
    from pdp.indicators.vwap import VWAPState
    from pdp.indicators.vwma import VWMAState
    from pdp.market.bars import BarClosed

log = structlog.get_logger()

# Snapshot field names that correspond to indicator family names
_SUITE_FAMILIES = frozenset({
    "ema", "rsi", "psar", "vwap", "vwma",
    "pivots", "fvg", "volume_profile", "market_profile",
})


class IndicatorEngine:
    def __init__(
        self,
        st_period: int = 3,
        st_multiplier: float = 1,
        timeframes: list[str] | None = None,
    ) -> None:
        self._period = st_period
        self._multiplier = st_multiplier
        # When set, only these timeframes are tracked; None = all timeframes.
        self._timeframes: set[str] | None = set(timeframes) if timeframes else None
        # SuperTrend (unchanged)
        self._trackers: dict[tuple[str, str], SuperTrendTracker] = {}
        self._latest: dict[tuple[str, str], SuperTrendState] = {}
        # Suite: per-(sid, tf) bundle of family trackers
        self._suite_trackers: dict[tuple[str, str], dict[str, Any]] = {}
        self._snapshots: dict[tuple[str, str], Snapshot] = {}

    # ── Configuration ──────────────────────────────────────────────────────────

    def configure_suite(self, sid: str, tf: str, indicators: list[dict[str, Any]]) -> None:
        """Register which indicator families to compute for ``(sid, tf)``.

        ``indicators`` is a list of dicts each containing at least a ``family`` key and
        optional family-specific params (e.g. ``{"family": "ema", "periods": [9, 20]}``).
        Families not listed will not be built and incur no per-bar cost.
        """
        from pdp.indicators.registry import build_tracker

        key = (sid, tf)
        bundle: dict[str, Any] = {}
        for cfg in indicators:
            family = cfg.get("family") if isinstance(cfg, dict) else str(cfg)
            if not family or family not in _SUITE_FAMILIES:
                log.warning("indicator_suite_unknown_family", family=family)
                continue
            params = {k: v for k, v in cfg.items() if k != "family"} if isinstance(cfg, dict) else {}
            try:
                bundle[family] = build_tracker(family, params)
            except Exception as exc:
                log.warning("indicator_suite_build_failed", family=family, exc=str(exc))

        if bundle:
            existing = self._suite_trackers.get(key, {})
            # Union: add families not already registered (first writer wins per family)
            merged = {**bundle, **existing}
            self._suite_trackers[key] = merged
            log.debug("indicator_suite_configured", sid=sid, tf=tf, families=list(merged))

    # ── Hot-path update ────────────────────────────────────────────────────────

    def on_bar(self, bar: BarClosed) -> SuperTrendState | None:
        """Update SuperTrend + suite trackers for this bar's (security, timeframe).

        Returns the SuperTrend state (None until seeded) for backward compatibility.
        """
        if self._timeframes is not None and bar.timeframe not in self._timeframes:
            return None

        key = (bar.security_id, bar.timeframe)

        # SuperTrend (unchanged path)
        tracker = self._trackers.get(key)
        if tracker is None:
            tracker = SuperTrendTracker(self._period, self._multiplier)
            self._trackers[key] = tracker
        state = tracker.update(bar.high, bar.low, bar.close, bar.bar_time)
        if state is not None:
            self._latest[key] = state

        # Suite (only for configured (sid, tf) pairs)
        bundle = self._suite_trackers.get(key)
        if bundle:
            h = float(bar.high)
            lo = float(bar.low)
            c = float(bar.close)
            v = float(bar.volume)
            t = bar.bar_time
            kwargs: dict[str, Any] = {}
            for family, ftracker in bundle.items():
                kwargs[family] = ftracker.update(h, lo, c, v, t)
            self._snapshots[key] = Snapshot(**kwargs)

        return state

    def get(self, security_id: str, timeframe: str) -> SuperTrendState | None:
        """Latest computed SuperTrend for the pair, or None if not yet seeded."""
        return self._latest.get((security_id, timeframe))

    def seed_from_bars(self, bars: list[BarClosed]) -> int:
        """Feed a chronologically-ordered list of historical bars through on_bar().

        Returns the number of bars processed. Callers are responsible for sorting
        and fetching bars; this method only drives the tracker state forward.
        """
        count = 0
        for bar in bars:
            self.on_bar(bar)
            count += 1
        return count

    # ── Suite getters ─────────────────────────────────────────────────────────

    def get_snapshot(self, security_id: str, timeframe: str) -> Snapshot | None:
        return self._snapshots.get((security_id, timeframe))

    def get_ema(self, security_id: str, timeframe: str) -> EMAState | None:
        snap = self._snapshots.get((security_id, timeframe))
        return snap.ema if snap is not None else None

    def get_rsi(self, security_id: str, timeframe: str) -> RSIState | None:
        snap = self._snapshots.get((security_id, timeframe))
        return snap.rsi if snap is not None else None

    def get_psar(self, security_id: str, timeframe: str) -> ParabolicSARState | None:
        snap = self._snapshots.get((security_id, timeframe))
        return snap.psar if snap is not None else None

    def get_vwap(self, security_id: str, timeframe: str) -> VWAPState | None:
        snap = self._snapshots.get((security_id, timeframe))
        return snap.vwap if snap is not None else None

    def get_vwma(self, security_id: str, timeframe: str) -> VWMAState | None:
        snap = self._snapshots.get((security_id, timeframe))
        return snap.vwma if snap is not None else None

    def get_pivots(self, security_id: str, timeframe: str) -> PivotState | None:
        snap = self._snapshots.get((security_id, timeframe))
        return snap.pivots if snap is not None else None

    def get_fvg(self, security_id: str, timeframe: str) -> FVGState | None:
        snap = self._snapshots.get((security_id, timeframe))
        return snap.fvg if snap is not None else None

    def get_volume_profile(self, security_id: str, timeframe: str) -> VolumeProfileState | None:
        snap = self._snapshots.get((security_id, timeframe))
        return snap.volume_profile if snap is not None else None

    def get_market_profile(self, security_id: str, timeframe: str) -> MarketProfileState | None:
        snap = self._snapshots.get((security_id, timeframe))
        return snap.market_profile if snap is not None else None
