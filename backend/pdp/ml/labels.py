"""Label builders for training targets.

- ``directional_labels``: forward-return bucketing → "up" / "flat" / "down".
- ``expiry_labels``: expiry-close-zone bucketing → distance-from-spot buckets.

Labels look forward by exactly the configured horizon and are DROPPED where the
full horizon is unavailable (end of series / end of session boundary).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pdp.market.bars import BarClosed


def directional_labels(
    bars: list[BarClosed],
    horizon: int = 5,
    up_threshold: float = 0.002,
    down_threshold: float = -0.002,
) -> list[str | None]:
    """Compute forward-return labels for each bar, or None where horizon unavailable.

    Parameters
    ----------
    bars:
        Chronologically ordered closed bars for a single (security_id, timeframe).
    horizon:
        Number of bars ahead to measure the return.
    up_threshold:
        Forward return above this fraction → "up".
    down_threshold:
        Forward return below this fraction → "down". Must be negative.
    """
    n = len(bars)
    labels: list[str | None] = []
    for i in range(n):
        if i + horizon >= n:
            labels.append(None)
            continue
        c_now = float(bars[i].close)
        c_fwd = float(bars[i + horizon].close)
        if c_now == 0:
            labels.append(None)
            continue
        ret = (c_fwd - c_now) / c_now
        if ret >= up_threshold:
            labels.append("up")
        elif ret <= down_threshold:
            labels.append("down")
        else:
            labels.append("flat")
    return labels


def expiry_labels(
    bars: list[BarClosed],
    expiry_close: float,
    near_threshold: float = 0.005,
    far_threshold: float = 0.015,
) -> list[str | None]:
    """Classify current price into an expiry-close-zone bucket.

    Produces one label per bar representing how far the current close is from
    the known expiry close (only usable post-expiry during training).

    Buckets (distance = (expiry_close - bar_close) / bar_close):
        far_below:  distance < -far_threshold
        near_below: -far_threshold <= distance < -near_threshold
        at_spot:    -near_threshold <= distance <= near_threshold
        near_above: near_threshold < distance <= far_threshold
        far_above:  distance > far_threshold

    Returns None for bars where bar.close == 0.
    """
    labels: list[str | None] = []
    for bar in bars:
        c = float(bar.close)
        if c == 0:
            labels.append(None)
            continue
        dist = (expiry_close - c) / c
        if dist < -far_threshold:
            labels.append("far_below")
        elif dist < -near_threshold:
            labels.append("near_below")
        elif dist <= near_threshold:
            labels.append("at_spot")
        elif dist <= far_threshold:
            labels.append("near_above")
        else:
            labels.append("far_above")
    return labels
