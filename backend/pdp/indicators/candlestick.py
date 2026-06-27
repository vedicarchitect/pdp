"""Candlestick pattern detector — doji, hammer, engulfing, harami, star, marubozu."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True)
class CandlestickState:
    doji: bool
    hammer: bool
    shooting_star: bool
    bullish_engulfing: bool
    bearish_engulfing: bool
    bullish_harami: bool
    bearish_harami: bool
    morning_star: bool
    evening_star: bool
    bullish_marubozu: bool
    bearish_marubozu: bool
    signal: int  # 1 = bullish, -1 = bearish, 0 = neutral


def _body(o: float, c: float) -> float:
    return abs(c - o)


def _range(h: float, lo: float) -> float:
    return h - lo


class CandlestickTracker:
    """Detects single- and multi-bar candlestick patterns from closed bars.

    Keeps a rolling window of the last 3 OHLC bars. All patterns are computed from
    closed-bar data only — no look-ahead.

    Parameters
    ----------
    doji_threshold:
        Body / range ratio below which a bar is a doji (default 0.1).
    wick_ratio:
        Minimum shadow-to-body ratio for hammer / shooting-star (default 2.0).
    marubozu_threshold:
        Maximum wick / range ratio for a marubozu bar (default 0.05).
    """

    __slots__ = ("_bars", "_doji_threshold", "_marubozu_threshold", "_wick_ratio")

    def __init__(
        self,
        doji_threshold: float = 0.1,
        wick_ratio: float = 2.0,
        marubozu_threshold: float = 0.05,
    ) -> None:
        self._doji_threshold = doji_threshold
        self._wick_ratio = wick_ratio
        self._marubozu_threshold = marubozu_threshold
        # (open, high, low, close) for last 3 bars
        self._bars: list[tuple[float, float, float, float]] = []

    def update(
        self,
        high: float,
        low: float,
        close: float,
        volume: float = 0.0,
        bar_time: datetime | None = None,
        open_price: float | None = None,
    ) -> CandlestickState | None:
        # open_price is an extended param; fall back to close when missing (smoke test compat)
        o = open_price if open_price is not None else close

        self._bars.append((o, high, low, close))
        if len(self._bars) > 3:
            self._bars.pop(0)

        if len(self._bars) < 2:
            return None

        b0_o, b0_h, b0_l, b0_c = self._bars[-1]  # current bar
        b1_o, _b1_h, _b1_l, b1_c = self._bars[-2]  # previous bar
        b2 = self._bars[-3] if len(self._bars) == 3 else None

        bar_range = _range(b0_h, b0_l)
        body = _body(b0_o, b0_c)

        # ── Doji ─────────────────────────────────────────────────────────────
        doji = bar_range > 0 and body / bar_range <= self._doji_threshold

        # ── Hammer (bullish): small body in upper third, long lower shadow ───
        lower_shadow = min(b0_o, b0_c) - b0_l
        upper_shadow = b0_h - max(b0_o, b0_c)
        hammer = (
            bar_range > 0
            and not doji
            and lower_shadow >= self._wick_ratio * body
            and upper_shadow <= body
            and min(b0_o, b0_c) > (b0_l + bar_range * 0.6)
        )

        # ── Shooting Star (bearish): small body in lower third, long upper wick
        shooting_star = (
            bar_range > 0
            and not doji
            and upper_shadow >= self._wick_ratio * body
            and lower_shadow <= body
            and max(b0_o, b0_c) < (b0_l + bar_range * 0.4)
        )

        # ── Engulfing (2-bar) ────────────────────────────────────────────────
        b1_bearish = b1_c < b1_o
        b1_bullish = b1_c > b1_o
        b0_bearish = b0_c < b0_o
        b0_bullish = b0_c > b0_o

        bullish_engulfing = (
            b1_bearish and b0_bullish
            and b0_o < b1_c and b0_c > b1_o
        )
        bearish_engulfing = (
            b1_bullish and b0_bearish
            and b0_o > b1_c and b0_c < b1_o
        )

        # ── Harami (2-bar) — small bar contained inside prior bar ────────────
        b1_body_top = max(b1_o, b1_c)
        b1_body_bot = min(b1_o, b1_c)
        b0_body = _body(b0_o, b0_c)
        b1_body = _body(b1_o, b1_c)
        contained = (
            b1_body > 0 and b0_body > 0
            and max(b0_o, b0_c) <= b1_body_top
            and min(b0_o, b0_c) >= b1_body_bot
            and b0_body < b1_body * 0.6
        )
        bullish_harami = contained and b1_bearish and b0_bullish
        bearish_harami = contained and b1_bullish and b0_bearish

        # ── Morning Star / Evening Star (3-bar) ──────────────────────────────
        morning_star = False
        evening_star = False
        if b2 is not None:
            b2_o, _b2_h, _b2_l, b2_c = b2
            b2_body = _body(b2_o, b2_c)
            b1_body_size = _body(b1_o, b1_c)
            # Morning star: b2 bearish (large), b1 small body (gap or near gap),
            #               b0 bullish closing into b2's body
            if (
                b2_c < b2_o
                and b2_body > 0
                and b1_body_size <= b2_body * 0.3
                and b0_c > b0_o
                and b0_c > (b2_o + b2_c) / 2
            ):
                morning_star = True
            # Evening star: b2 bullish (large), b1 small body,
            #               b0 bearish closing into b2's body
            if (
                b2_c > b2_o
                and b2_body > 0
                and b1_body_size <= b2_body * 0.3
                and b0_c < b0_o
                and b0_c < (b2_o + b2_c) / 2
            ):
                evening_star = True

        # ── Marubozu ─────────────────────────────────────────────────────────
        bullish_marubozu = (
            bar_range > 0
            and b0_bullish
            and upper_shadow / bar_range <= self._marubozu_threshold
            and lower_shadow / bar_range <= self._marubozu_threshold
        )
        bearish_marubozu = (
            bar_range > 0
            and b0_bearish
            and upper_shadow / bar_range <= self._marubozu_threshold
            and lower_shadow / bar_range <= self._marubozu_threshold
        )

        # ── Composite signal ──────────────────────────────────────────────────
        bullish = hammer or bullish_engulfing or bullish_harami or morning_star or bullish_marubozu
        bearish = shooting_star or bearish_engulfing or bearish_harami or evening_star or bearish_marubozu
        signal = 1 if bullish else (-1 if bearish else 0)

        return CandlestickState(
            doji=doji,
            hammer=hammer,
            shooting_star=shooting_star,
            bullish_engulfing=bullish_engulfing,
            bearish_engulfing=bearish_engulfing,
            bullish_harami=bullish_harami,
            bearish_harami=bearish_harami,
            morning_star=morning_star,
            evening_star=evening_star,
            bullish_marubozu=bullish_marubozu,
            bearish_marubozu=bearish_marubozu,
            signal=signal,
        )
