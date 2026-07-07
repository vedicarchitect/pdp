"""Directional-strangle bias engine (pure, deterministic).

Codifies ``strategies/MultiTimeFrameSelling.txt``: combine many timeframe/level
signals into a single bias *score* in [-1, +1], map it to one of seven bias
*buckets*, and from the bucket derive a PE:CE sell-lot *ratio* for a directional
strangle. VIX is a hard entry **gate**; PCR/EMA/pivots/swing/ORB are votes.

Design goals:
- **Pure**: no I/O, no globals, deterministic. Identical inputs -> identical
  ``BiasResult``. This is what makes the backtest and the live strategy agree.
- **Decoupled**: takes plain floats (via ``BiasInputs``), not indicator-engine
  state objects, so it is trivially unit-testable and reusable.

Sign convention for votes: ``+1`` = bullish, ``-1`` = bearish, ``0`` = neutral
or insufficient data. "Bullish" for a *seller* means lean the strangle toward
selling more PUTs (premium safe to the upside).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

# --------------------------------------------------------------------------- #
# Inputs
# --------------------------------------------------------------------------- #


@dataclass(slots=True)
class TimeframeEMA:
    """Price and the 9/20/50 EMAs for one timeframe (price = bar close)."""

    price: float
    ema9: float
    ema20: float
    ema50: float


@dataclass(slots=True)
class CamLevels:
    """Camarilla resistance/support levels for a period (daily or weekly)."""

    r3: float
    r4: float
    s3: float
    s4: float


@dataclass(slots=True)
class BiasInputs:
    """Everything the bias engine needs at one decision instant.

    Any field may be ``None`` when its data is unavailable; missing signals are
    simply excluded from the (weight-normalised) score rather than counted as
    neutral, so partial data does not silently drag the score toward zero.
    """

    spot: float
    # EMA alignment per timeframe
    ema_1h: TimeframeEMA | None = None
    ema_15m: TimeframeEMA | None = None
    ema_5m: TimeframeEMA | None = None
    # Camarilla daily / weekly
    cam_daily: CamLevels | None = None
    cam_weekly: CamLevels | None = None
    # Swing levels
    pdh: float | None = None
    pdl: float | None = None
    pwh: float | None = None
    pwl: float | None = None
    # 15m opening range
    orb_high: float | None = None
    orb_low: float | None = None
    # Put-call ratio
    pcr: float | None = None
    # VIX gate inputs
    vix_now: float | None = None
    vix_day_open: float | None = None
    vix_day_high: float | None = None
    # Recent VIX closes, OLDEST-first, for the "rising last 3 5m candles" rule.
    vix_recent: list[float] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# Weights / configuration
# --------------------------------------------------------------------------- #


@dataclass(slots=True)
class BiasWeights:
    """Per-signal weights and score thresholds. All tunable (walk-forward)."""

    w_ema_1h: float = 2.0
    w_ema_15m: float = 1.5
    w_ema_5m: float = 1.0
    w_cam_daily: float = 1.5
    w_cam_weekly: float = 1.5
    w_swing: float = 1.0
    w_orb: float = 1.0
    w_pcr: float = 1.0

    # Score bucket thresholds (absolute value of normalised score in [0, 1]).
    th_complete: float = 0.75  # |score| >= -> complete bull/bear
    th_most: float = 0.50  # -> most
    th_more: float = 0.20  # -> more; below this -> neutral

    # VIX gate
    vix_spike_pct: float = 0.05  # >5% intraday rise blocks entries
    vix_day_high_eps: float = 1e-6  # tolerance for "at day high"
    pcr_bull: float = 1.1
    pcr_bear: float = 0.9


class BiasBucket(StrEnum):
    COMPLETE_BULL = "complete_bull"
    MOST_BULL = "most_bull"
    MORE_BULL = "more_bull"
    NEUTRAL = "neutral"
    MORE_BEAR = "more_bear"
    MOST_BEAR = "most_bear"
    COMPLETE_BEAR = "complete_bear"


# Default PE:CE *sell-lot* ratio per bucket.
#
# NOTE: the source playbook's gradient escalates bullishness as "sell more PE"
# (more-bull 3:2, most-bull 4:2) but then writes "complete bullish - sell ATM ce
# - 5ce", which inverts the gradient. We default to the gradient-consistent and
# premium-selling-consistent reading (complete-bull = sell 5 PE, 0 CE) and keep
# this table fully configurable so the literal-doc variant can be swapped in.
DEFAULT_RATIO_TABLE: dict[BiasBucket, tuple[int, int]] = {
    BiasBucket.COMPLETE_BULL: (5, 0),
    BiasBucket.MOST_BULL: (4, 2),
    BiasBucket.MORE_BULL: (3, 2),
    BiasBucket.NEUTRAL: (1, 1),
    BiasBucket.MORE_BEAR: (2, 3),
    BiasBucket.MOST_BEAR: (2, 4),
    BiasBucket.COMPLETE_BEAR: (0, 5),
}


# --------------------------------------------------------------------------- #
# Result
# --------------------------------------------------------------------------- #


@dataclass(slots=True)
class BiasResult:
    score: float  # normalised, [-1, +1]
    bucket: BiasBucket
    pe_lots: int
    ce_lots: int
    gated: bool  # True -> VIX gate blocks new entries
    reason: str
    votes: dict[str, int] = field(default_factory=dict)  # per-signal votes (debug)


# --------------------------------------------------------------------------- #
# Per-signal votes
# --------------------------------------------------------------------------- #


def _ema_vote(e: TimeframeEMA | None) -> int | None:
    """+1 if price above 50EMA with 9>20>50; -1 if below with 9<20<50; else 0."""
    if e is None:
        return None
    if e.price > e.ema50 and e.ema9 > e.ema20 > e.ema50:
        return 1
    if e.price < e.ema50 and e.ema9 < e.ema20 < e.ema50:
        return -1
    return 0


def _ema5_vote(e: TimeframeEMA | None) -> int | None:
    """5m only needs price vs the 50 EMA."""
    if e is None:
        return None
    if e.price > e.ema50:
        return 1
    if e.price < e.ema50:
        return -1
    return 0


def _cam_vote(spot: float, c: CamLevels | None) -> int | None:
    """+1 on a break above R3/R4, -1 on a break below S3/S4."""
    if c is None:
        return None
    if spot > c.r3:
        return 1
    if spot < c.s3:
        return -1
    return 0


def _swing_vote(
    spot: float,
    pdh: float | None,
    pdl: float | None,
    pwh: float | None,
    pwl: float | None,
) -> int | None:
    """+1 above both prior-day & prior-week highs; -1 below both lows."""
    highs = [x for x in (pdh, pwh) if x is not None]
    lows = [x for x in (pdl, pwl) if x is not None]
    if not highs and not lows:
        return None
    if highs and all(spot > h for h in highs):
        return 1
    if lows and all(spot < lo for lo in lows):
        return -1
    return 0


def _orb_vote(spot: float, hi: float | None, lo: float | None) -> int | None:
    if hi is None or lo is None:
        return None
    if spot > hi:
        return 1
    if spot < lo:
        return -1
    return 0


def _pcr_vote(pcr: float | None, w: BiasWeights) -> int | None:
    if pcr is None:
        return None
    if pcr > w.pcr_bull:
        return 1
    if pcr < w.pcr_bear:
        return -1
    return 0


# --------------------------------------------------------------------------- #
# VIX gate
# --------------------------------------------------------------------------- #


def _vix_gate(inp: BiasInputs, w: BiasWeights) -> tuple[bool, str]:
    """Return (gated, reason). Missing VIX data => allow (logged by caller)."""
    if inp.vix_now is None:
        return False, "vix_unavailable"
    # >5% intraday spike
    if inp.vix_day_open:
        if (inp.vix_now - inp.vix_day_open) / inp.vix_day_open > w.vix_spike_pct:
            return True, "vix_spike_gt_5pct"
    # at day high
    if inp.vix_day_high is not None and inp.vix_now >= inp.vix_day_high - w.vix_day_high_eps:
        return True, "vix_at_day_high"
    # rising over the last 3 5m candles (oldest-first); net increase blocks
    rec = inp.vix_recent
    if len(rec) >= 3 and rec[-1] > rec[-3]:
        return True, "vix_rising_last_3_5m"
    return False, "vix_ok"


# --------------------------------------------------------------------------- #
# Main entry point
# --------------------------------------------------------------------------- #


def _bucket_for(score: float, w: BiasWeights) -> BiasBucket:
    if score >= w.th_complete:
        return BiasBucket.COMPLETE_BULL
    if score >= w.th_most:
        return BiasBucket.MOST_BULL
    if score >= w.th_more:
        return BiasBucket.MORE_BULL
    if score <= -w.th_complete:
        return BiasBucket.COMPLETE_BEAR
    if score <= -w.th_most:
        return BiasBucket.MOST_BEAR
    if score <= -w.th_more:
        return BiasBucket.MORE_BEAR
    return BiasBucket.NEUTRAL


def score_bias(
    inp: BiasInputs,
    weights: BiasWeights | None = None,
    ratio_table: dict[BiasBucket, tuple[int, int]] | None = None,
) -> BiasResult:
    """Combine all signals into a normalised bias score, bucket, and PE:CE ratio.

    Score = sum(weight * vote) / sum(weight) over signals with data present, so
    the result is always in [-1, +1] regardless of how many signals are missing.
    """
    w = weights or BiasWeights()
    table = ratio_table or DEFAULT_RATIO_TABLE

    # (vote, weight, name) for every signal that has data.
    candidates: list[tuple[int | None, float, str]] = [
        (_ema_vote(inp.ema_1h), w.w_ema_1h, "ema_1h"),
        (_ema_vote(inp.ema_15m), w.w_ema_15m, "ema_15m"),
        (_ema5_vote(inp.ema_5m), w.w_ema_5m, "ema_5m"),
        (_cam_vote(inp.spot, inp.cam_daily), w.w_cam_daily, "cam_daily"),
        (_cam_vote(inp.spot, inp.cam_weekly), w.w_cam_weekly, "cam_weekly"),
        (_swing_vote(inp.spot, inp.pdh, inp.pdl, inp.pwh, inp.pwl), w.w_swing, "swing"),
        (_orb_vote(inp.spot, inp.orb_high, inp.orb_low), w.w_orb, "orb"),
        (_pcr_vote(inp.pcr, w), w.w_pcr, "pcr"),
    ]

    votes: dict[str, int] = {}
    weighted_sum = 0.0
    weight_total = 0.0
    for vote, weight, name in candidates:
        if vote is None:
            continue
        votes[name] = vote
        weighted_sum += weight * vote
        weight_total += weight

    score = weighted_sum / weight_total if weight_total > 0 else 0.0
    bucket = _bucket_for(score, w)
    pe_lots, ce_lots = table[bucket]

    gated, gate_reason = _vix_gate(inp, w)
    reason = f"score={score:+.3f} bucket={bucket.value} gate={gate_reason}"

    return BiasResult(
        score=score,
        bucket=bucket,
        pe_lots=pe_lots,
        ce_lots=ce_lots,
        gated=gated,
        reason=reason,
        votes=votes,
    )
