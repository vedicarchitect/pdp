"""Shared fakes for event-detector unit tests (no DB / no I/O)."""
from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from pdp.events.config import EventConfig
from pdp.events.detectors.base import BarContext


@pytest.fixture
def cfg() -> EventConfig:
    return EventConfig(
        enabled=True,
        timeframes=["15m"],
        ema_pairs=[(9, 20), (9, 50)],
        price_ema_periods=[50],
        watch_levels={"NIFTY": [24000.0]},
        position_ranges={"NIFTY:strangle": (23500.0, 24500.0)},
        proximity_band_pts=30.0,
        confluence_min=2,
        confluence_band_pts=25.0,
        otm_distance_pts=100.0,
        mtm_swing_inr=5000.0,
        trail_giveback_pct=30.0,
        pcr_bands=[0.7, 1.3],
        gex_wall_pts=50.0,
        gap_pct=0.5,
        cooldown_seconds=300,
    )


def make_snapshot(**families) -> SimpleNamespace:
    """Build a snapshot-like object; absent families default to None."""
    defaults = dict(
        ema=None, rsi=None, psar=None, vwap=None, vwma=None, pivots=None,
        period_levels=None, fvg=None, volume_profile=None, market_profile=None,
        macd=None, candlestick=None, elliott=None, fib_levels=None, elder_impulse=None,
    )
    defaults.update(families)
    return SimpleNamespace(**defaults)


def make_ctx(
    cfg: EventConfig,
    *,
    sid: str = "13",
    underlying: str | None = "NIFTY",
    tf: str = "15m",
    o: float = 24000,
    h: float = 24050,
    low: float = 23950,
    c: float = 24000,
    volume: float = 100000,
    snapshot=None,
    supertrend=None,
    ml_signal=None,
    oi_levels=(),
    bar_time: datetime | None = None,
) -> BarContext:
    return BarContext(
        security_id=sid, underlying=underlying, timeframe=tf,
        open=o, high=h, low=low, close=c, volume=volume,
        bar_time=bar_time or datetime(2026, 6, 17, 5, 0, tzinfo=UTC),
        snapshot=snapshot, supertrend=supertrend, ml_signal=ml_signal,
        cfg=cfg, oi_levels=list(oi_levels),
    )


def ema(values: dict[int, float]) -> SimpleNamespace:
    return SimpleNamespace(values=values)
