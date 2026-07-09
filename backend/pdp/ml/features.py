"""Single leakage-safe feature builder — used identically offline (training) and online (inference).

Given an ordered bar stream and per-bar indicator snapshots, produces a feature row
using only data available at or before the bar's close (closed-bar snapshots, prior
swings, prior-session levels). No future bar, no whole-series transforms that peek ahead.

Offline usage (training):
    rows = build_feature_rows(bars, snapshots, supertrends)

Online usage (inference):
    row = build_feature_row(bar, snapshot, supertrend)
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pdp.indicators.snapshot import Snapshot
    from pdp.indicators.supertrend import SuperTrendState
    from pdp.market.bars import BarClosed


def _f(v: Any) -> float:
    """Safe float cast; returns 0.0 for None."""
    if v is None:
        return 0.0
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def build_feature_row(
    bar: BarClosed,
    snapshot: Snapshot | None,
    supertrend: SuperTrendState | None,
    prev_bar: BarClosed | None = None,
    options_features: dict[str, float] | None = None,
) -> dict[str, float]:
    """Build one feature row from a closed bar + its indicator snapshot.

    All values must be known at or before the bar's close. ``prev_bar`` is the
    immediately preceding bar (for slope / change features).

    Parameters
    ----------
    bar:
        The just-closed bar.
    snapshot:
        Indicator suite snapshot computed from this bar (already updated).
    supertrend:
        SuperTrend state from the universal engine.
    prev_bar:
        The bar that closed immediately before ``bar`` (for change features).
    options_features:
        Optional dict of options-analytics features (max-pain, PCR, etc.) for
        the expiry head. Passed as-is; None → all such features default to 0.
    """
    h = _f(bar.high)
    lo = _f(bar.low)
    c = _f(bar.close)
    o = _f(bar.open)
    bar_range = h - lo
    body = abs(c - o)
    upper_shadow = h - max(o, c)
    lower_shadow = min(o, c) - lo

    # Change features vs prior bar
    prev_c = _f(prev_bar.close) if prev_bar else c
    prev_h = _f(prev_bar.high) if prev_bar else h
    close_pct_change = (c - prev_c) / prev_c if prev_c != 0 else 0.0
    high_pct_change = (h - prev_h) / prev_h if prev_h != 0 else 0.0

    row: dict[str, float] = {
        # price structure
        "close": c,
        "high": h,
        "low": lo,
        "open": o,
        "bar_range": bar_range,
        "body": body,
        "upper_shadow": upper_shadow,
        "lower_shadow": lower_shadow,
        "close_pct_change": close_pct_change,
        "high_pct_change": high_pct_change,
    }

    # EMA features
    ema_state = snapshot.ema if snapshot else None
    ema9 = _f(ema_state.values.get(9)) if ema_state else 0.0
    ema20 = _f(ema_state.values.get(20)) if ema_state else 0.0
    ema50 = _f(ema_state.values.get(50)) if ema_state else 0.0
    row["ema_9"] = ema9
    row["ema_20"] = ema20
    row["ema_50"] = ema50
    row["close_vs_ema9"] = (c - ema9) / ema9 if ema9 != 0 else 0.0
    row["close_vs_ema20"] = (c - ema20) / ema20 if ema20 != 0 else 0.0
    row["close_vs_ema50"] = (c - ema50) / ema50 if ema50 != 0 else 0.0
    # Slope proxied by close_vs_ema (change vs prior period handled offline via shift)
    row["ema9_slope"] = row["close_vs_ema9"] - ((prev_c - ema9) / ema9 if ema9 != 0 else 0.0)
    row["ema20_slope"] = row["close_vs_ema20"] - ((prev_c - ema20) / ema20 if ema20 != 0 else 0.0)

    # RSI
    rsi_state = snapshot.rsi if snapshot else None
    row["rsi"] = _f(rsi_state.rsi) if rsi_state else 50.0
    row["rsi_ma"] = _f(rsi_state.ma) if rsi_state and rsi_state.ma is not None else 50.0

    # VWAP
    vwap_state = snapshot.vwap if snapshot else None
    vwap = _f(vwap_state.vwap) if vwap_state else c
    row["close_vs_vwap"] = (c - vwap) / vwap if vwap != 0 else 0.0

    # SuperTrend
    row["st_direction"] = float(supertrend.direction) if supertrend and supertrend.direction else 0.0

    # MACD
    macd_state = snapshot.macd if snapshot else None
    row["macd"] = _f(macd_state.macd) if macd_state else 0.0
    row["macd_signal"] = _f(macd_state.signal) if macd_state else 0.0
    row["macd_histogram"] = _f(macd_state.histogram) if macd_state else 0.0
    row["macd_histogram_slope"] = 0.0  # placeholder; offline builder fills from prior row

    # Candlestick
    cs = snapshot.candlestick if snapshot else None
    row["cs_signal"] = float(cs.signal) if cs else 0.0
    row["cs_doji"] = float(cs.doji) if cs else 0.0
    row["cs_hammer"] = float(cs.hammer) if cs else 0.0
    row["cs_shooting_star"] = float(cs.shooting_star) if cs else 0.0
    row["cs_bullish_engulfing"] = float(cs.bullish_engulfing) if cs else 0.0
    row["cs_bearish_engulfing"] = float(cs.bearish_engulfing) if cs else 0.0
    row["cs_bullish_harami"] = float(cs.bullish_harami) if cs else 0.0
    row["cs_bearish_harami"] = float(cs.bearish_harami) if cs else 0.0
    row["cs_morning_star"] = float(cs.morning_star) if cs else 0.0
    row["cs_evening_star"] = float(cs.evening_star) if cs else 0.0
    row["cs_bullish_marubozu"] = float(cs.bullish_marubozu) if cs else 0.0
    row["cs_bearish_marubozu"] = float(cs.bearish_marubozu) if cs else 0.0

    # Elliott Wave
    ew = snapshot.elliott if snapshot else None
    row["ew_trend"] = float(ew.trend) if ew else 0.0
    row["ew_confidence"] = _f(ew.confidence) if ew else 0.0

    # Fibonacci levels
    fl = snapshot.fib_levels if snapshot else None
    row["fib_distance"] = _f(fl.distance) / c if fl and c != 0 else 0.0
    row["fib_nearest_level"] = _f(fl.nearest_level) / c if fl and c != 0 else 0.0

    # Elder Impulse
    ei = snapshot.elder_impulse if snapshot else None
    row["elder_regime_green"] = float(ei.regime == "green") if ei else 0.0
    row["elder_regime_red"] = float(ei.regime == "red") if ei else 0.0
    row["elder_ema13_rising"] = float(ei.ema13_rising) if ei else 0.0
    row["elder_macd_hist_rising"] = float(ei.macd_hist_rising) if ei else 0.0

    # Pivot levels
    pv = snapshot.pivots if snapshot else None
    pp = _f(pv.pp) if pv else c
    r1 = _f(pv.r1) if pv else c
    s1 = _f(pv.s1) if pv else c
    row["close_vs_pp"] = (c - pp) / pp if pp != 0 else 0.0
    row["close_vs_r1"] = (c - r1) / r1 if r1 != 0 else 0.0
    row["close_vs_s1"] = (c - s1) / s1 if s1 != 0 else 0.0

    # Options features (phase 2 expiry head — all default to 0 when not provided)
    opts = options_features or {}
    for col in (
        "max_pain",
        "pcr",
        "gex",
        "iv_atm",
        "india_vix",
        "oi_wall_above",
        "oi_wall_below",
        "max_pain_distance",
    ):
        row[col] = opts.get(col, 0.0)

    return row


def build_feature_rows(
    bars: list[BarClosed],
    snapshots: list[Snapshot | None],
    supertrends: list[SuperTrendState | None],
    options_features_list: list[dict[str, float] | None] | None = None,
) -> list[dict[str, float]]:
    """Build feature rows for a chronologically-ordered bar sequence.

    ``bars``, ``snapshots``, and ``supertrends`` must be aligned 1:1 (index *i*
    in all three refers to the same bar close).  Uses bar[i-1] as ``prev_bar``
    so close_pct_change and slope features use only data known at bar i's close.
    """
    opts_list = options_features_list or [None] * len(bars)
    rows: list[dict[str, float]] = []
    for i, (bar, snap, st, opts) in enumerate(zip(bars, snapshots, supertrends, opts_list, strict=False)):
        prev = bars[i - 1] if i > 0 else None
        row = build_feature_row(bar, snap, st, prev_bar=prev, options_features=opts)
        # Fill macd_histogram_slope from prior row (no look-ahead — prior row is already built)
        if rows:
            row["macd_histogram_slope"] = row["macd_histogram"] - rows[-1]["macd_histogram"]
        rows.append(row)
    return rows


def feature_names() -> list[str]:
    """Return the canonical feature column order (mirrors FEATURE_SCHEMA in registry)."""
    from pdp.ml.registry import FEATURE_SCHEMA

    return list(FEATURE_SCHEMA)
