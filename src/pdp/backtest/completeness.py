"""Input-data completeness gate for the multi-day backtest.

A trade day is only simulated when its index 1m spot series is materially complete:
≥ ``MIN_BARS_FRAC`` of the expected full-session count AND no intraday hole ≥ ``MAX_GAP_MIN``.
SuperTrend on a gapped series freezes and cannot flip when it should, so trading such a day
would fabricate P&L. Incomplete days are reported as ``data_incomplete`` (no trades) rather than
silently traded; backfill is an explicit step (``scripts/backfill_spot.py``), never a hidden
hot-path fetch.

This lives in a small importable module (separate from ``backtest_multiday.py``, which executes on
import) so the gate can be unit-tested in isolation.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

EXPECTED_SESSION_BARS = 375   # 09:15–15:30 inclusive at 1m
MIN_BARS_FRAC = 0.95          # need ≥ 95% of the session present
MAX_GAP_MIN = 5               # largest tolerated intraday gap, minutes


def spot_completeness(
    raw1: list[dict[str, Any]],
    *,
    expected_bars: int = EXPECTED_SESSION_BARS,
    min_bars_frac: float = MIN_BARS_FRAC,
    max_gap_min: float = MAX_GAP_MIN,
) -> dict[str, Any]:
    """Assess a day's NIFTY 1m series for the completeness gate.

    ``raw1`` is the day's raw 1-minute bar dicts (each with a ``ts`` datetime). Returns a dict:
    ``ok`` (bool), ``bars`` (count), ``max_gap_min`` (largest minute gap between consecutive
    bars), and ``reason`` (failure detail, or "" when ok). Assessed on the raw 1m source — the
    gate is about source integrity, independent of any signal-timeframe resample.
    """
    bars = len(raw1)
    min_bars = int(expected_bars * min_bars_frac)
    if bars == 0:
        return {"ok": False, "bars": 0, "max_gap_min": 0.0, "reason": "no spot bars"}

    times: list[datetime] = []
    for b in raw1:
        ts: datetime = b["ts"] if b["ts"].tzinfo else b["ts"].replace(tzinfo=timezone.utc)
        times.append(ts)
    times.sort()
    max_gap = 0.0
    for i in range(len(times) - 1):
        gap = (times[i + 1] - times[i]).total_seconds() / 60.0
        if gap > max_gap:
            max_gap = gap

    reasons: list[str] = []
    if bars < min_bars:
        reasons.append(f"{bars}/{expected_bars} bars (<{min_bars})")
    if max_gap >= max_gap_min:
        reasons.append(f"gap {max_gap:.0f}min (>={max_gap_min})")
    return {
        "ok": not reasons,
        "bars": bars,
        "max_gap_min": max_gap,
        "reason": "; ".join(reasons),
    }
