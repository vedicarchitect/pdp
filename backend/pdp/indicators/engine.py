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

from datetime import date
from typing import TYPE_CHECKING, Any

import structlog

from pdp.indicators.snapshot import Snapshot
from pdp.indicators.supertrend import SuperTrendState, SuperTrendTracker

if TYPE_CHECKING:
    from pdp.indicators.candlestick import CandlestickState
    from pdp.indicators.elder_impulse import ElderImpulseState
    from pdp.indicators.elliott import ElliottWaveState
    from pdp.indicators.ema import EMAState
    from pdp.indicators.fib_levels import FibLevelsState
    from pdp.indicators.fvg import FVGState
    from pdp.indicators.macd import MACDState
    from pdp.indicators.market_profile import MarketProfileState
    from pdp.indicators.period_levels import PeriodLevelsState
    from pdp.indicators.pivots import PivotState
    from pdp.indicators.psar import ParabolicSARState
    from pdp.indicators.rsi import RSIState
    from pdp.indicators.volume_profile import VolumeProfileState
    from pdp.indicators.vwap import VWAPState
    from pdp.indicators.vwma import VWMAState
    from pdp.market.bars import BarClosed

log = structlog.get_logger()

# The three SuperTrend variants the Execution Console matrix overlays alongside the
# chart, per user confirmation (indicator-matrix-kite-parity) — distinct from the
# single engine-wide `st_period`/`st_multiplier` pair used for strategy signals
# (`get()`/`ctx.indicators.supertrend()`), which is intentionally left unchanged.
MATRIX_ST_VARIANTS: tuple[tuple[str, int, float], ...] = (
    ("st_10_2", 10, 2.0),
    ("st_10_3", 10, 3.0),
    ("st_3_1", 3, 1.0),
)

# Snapshot field names that correspond to indicator family names
_SUITE_FAMILIES = frozenset(
    {
        "ema",
        "rsi",
        "psar",
        "vwap",
        "vwma",
        "pivots",
        "period_levels",
        "fvg",
        "volume_profile",
        "market_profile",
        "macd",
        "candlestick",
        "elliott",
        "fib_levels",
        "elder_impulse",
    }
)


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
        # SuperTrend matrix variants: (sid, tf, variant_label) -> tracker/state.
        # Parallel to _trackers/_latest above; never read by strategies.
        self._variant_trackers: dict[tuple[str, str, str], SuperTrendTracker] = {}
        self._variant_latest: dict[tuple[str, str, str], SuperTrendState] = {}
        # Suite: per-(sid, tf) bundle of family trackers
        self._suite_trackers: dict[tuple[str, str], dict[str, Any]] = {}
        self._snapshots: dict[tuple[str, str], Snapshot] = {}
        self._bar_counts: dict[tuple[str, str], int] = {}
        # ML signal cache: populated by the ML inference layer after on_bar
        self._ml_signals: dict[tuple[str, str], Any] = {}

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

        # SuperTrend matrix variants — only computed for pairs with a suite configured
        # (the matrix's index/strike/ATM rows), so non-matrix (sid, tf) pairs (e.g. a
        # strategy-only timeframe) incur no extra per-bar cost.
        if key in self._suite_trackers:
            for label, period, multiplier in MATRIX_ST_VARIANTS:
                vkey = (bar.security_id, bar.timeframe, label)
                vtracker = self._variant_trackers.get(vkey)
                if vtracker is None:
                    vtracker = SuperTrendTracker(period, multiplier)
                    self._variant_trackers[vkey] = vtracker
                vstate = vtracker.update(bar.high, bar.low, bar.close, bar.bar_time)
                if vstate is not None:
                    self._variant_latest[vkey] = vstate

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

        self._bar_counts[key] = self._bar_counts.get(key, 0) + 1
        return state

    def get(self, security_id: str, timeframe: str) -> SuperTrendState | None:
        """Latest computed SuperTrend for the pair, or None if not yet seeded."""
        return self._latest.get((security_id, timeframe))

    def get_supertrend_variants(
        self, security_id: str, timeframe: str
    ) -> dict[str, SuperTrendState]:
        """Latest state for each of the three matrix SuperTrend variants
        (``MATRIX_ST_VARIANTS``) for this pair. Only populated for (sid, tf) pairs with a
        suite configured (see ``on_bar``) — returns an empty dict otherwise, never a
        partial/fabricated entry for an unseeded variant."""
        return {
            label: state
            for label, _period, _mult in MATRIX_ST_VARIANTS
            if (state := self._variant_latest.get((security_id, timeframe, label))) is not None
        }

    def is_warm(self, security_id: str, timeframe: str, min_bars: int = 200) -> bool:
        """Return True if the tracker for this pair has consumed at least min_bars."""
        return self._bar_counts.get((security_id, timeframe), 0) >= min_bars

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

    def seed_prior_session_pivots(
        self,
        security_id: str,
        timeframe: str,
        prior_high: float,
        prior_low: float,
        prior_close: float,
        prior_day: date | None = None,
    ) -> None:
        """Seed the PivotTracker with the prior session's HLC at warmup time.

        Also refreshes the cached ``Snapshot`` for this ``(sid, tf)`` -- this runs
        *after* ``seed_from_bars`` already cached a snapshot from the historical
        bars, so without this, ``get_pivots``/``get_snapshot`` would keep serving
        that stale pre-correction state until the next live bar closes.
        """
        key = (security_id, timeframe)
        bundle = self._suite_trackers.get(key)
        if bundle and "pivots" in bundle:
            new_state = bundle["pivots"].seed_prior_hlc(prior_high, prior_low, prior_close, prior_day)
            existing = self._snapshots.get(key)
            if existing is not None:
                from dataclasses import replace

                self._snapshots[key] = replace(existing, pivots=new_state)
            else:
                self._snapshots[key] = Snapshot(pivots=new_state)

    def seed_period_levels_history(
        self,
        security_id: str,
        timeframe: str,
        bars: list[BarClosed],
    ) -> None:
        """Replay older bars (strictly before the warmup session) through the
        ``period_levels`` tracker only, so PWH/PWL/PMH/PML are seeded from the
        trailing week/month before the live session starts.

        Bars MUST be chronologically ordered and predate the prior-session bars
        fed via ``seed_from_bars`` to keep boundary detection monotonic.
        """
        bundle = self._suite_trackers.get((security_id, timeframe))
        if not bundle or "period_levels" not in bundle:
            return
        tracker = bundle["period_levels"]
        for bar in bars:
            tracker.update(float(bar.high), float(bar.low), float(bar.close), 0.0, bar.bar_time)

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

    def get_period_levels(self, security_id: str, timeframe: str) -> PeriodLevelsState | None:
        snap = self._snapshots.get((security_id, timeframe))
        return snap.period_levels if snap is not None else None

    def get_fvg(self, security_id: str, timeframe: str) -> FVGState | None:
        snap = self._snapshots.get((security_id, timeframe))
        return snap.fvg if snap is not None else None

    def get_volume_profile(self, security_id: str, timeframe: str) -> VolumeProfileState | None:
        snap = self._snapshots.get((security_id, timeframe))
        return snap.volume_profile if snap is not None else None

    def get_market_profile(self, security_id: str, timeframe: str) -> MarketProfileState | None:
        snap = self._snapshots.get((security_id, timeframe))
        return snap.market_profile if snap is not None else None

    def get_macd(self, security_id: str, timeframe: str) -> MACDState | None:
        snap = self._snapshots.get((security_id, timeframe))
        return snap.macd if snap is not None else None

    def get_candlestick(self, security_id: str, timeframe: str) -> CandlestickState | None:
        snap = self._snapshots.get((security_id, timeframe))
        return snap.candlestick if snap is not None else None

    def get_elliott(self, security_id: str, timeframe: str) -> ElliottWaveState | None:
        snap = self._snapshots.get((security_id, timeframe))
        return snap.elliott if snap is not None else None

    def get_fib_levels(self, security_id: str, timeframe: str) -> FibLevelsState | None:
        snap = self._snapshots.get((security_id, timeframe))
        return snap.fib_levels if snap is not None else None

    def get_elder_impulse(self, security_id: str, timeframe: str) -> ElderImpulseState | None:
        snap = self._snapshots.get((security_id, timeframe))
        return snap.elder_impulse if snap is not None else None

    def get_ml_signal(self, security_id: str, timeframe: str) -> Any:
        """Return the cached MLSignalState for (sid, tf), or None if no model is loaded."""
        return self._ml_signals.get((security_id, timeframe))

    def set_ml_signal(self, security_id: str, timeframe: str, signal: Any) -> None:
        """Cache an MLSignalState produced by the ML inference layer."""
        self._ml_signals[(security_id, timeframe)] = signal

    # ── Startup depth summary (indicator-history-depth) ─────────────────────────

    def seeding_summary(self, security_id: str, timeframe: str) -> dict[tuple[str, int | None], bool]:
        """Which ``(family, period)`` combinations are fully seeded for ``(sid, tf)``.

        ``ema`` reports one entry per configured period (the concrete "EMA(200)
        unseeded on 1H" case a startup summary needs to name); every other suite
        family reports a single ``(family, None)`` entry, seeded once its tracker
        has produced any state.
        """
        key = (security_id, timeframe)
        bundle = self._suite_trackers.get(key, {})
        snap = self._snapshots.get(key)
        result: dict[tuple[str, int | None], bool] = {}
        for family, tracker in bundle.items():
            if family == "ema":
                periods = getattr(tracker, "periods", [])
                seeded_values = snap.ema.values if snap and snap.ema is not None else {}
                for p in periods:
                    result[(family, p)] = p in seeded_values
            else:
                state = getattr(snap, family, None) if snap is not None else None
                result[(family, None)] = state is not None
        return result
