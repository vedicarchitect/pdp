"""Blended sentiment: news-headline scoring (vaderSentiment) + existing market internals.

No new internals computation lives here — the internals sub-score is derived from signals the
codebase already computes elsewhere (India VIX level via the tick feed, option PCR via
`pdp.options.analytics.compute_pcr`). This module only blends what's handed to it.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Protocol

import structlog

log = structlog.get_logger()

# VIX below this = calm (bullish-leaning internals); above this = fearful (bearish-leaning)
_VIX_CALM = 13.0
_VIX_FEARFUL = 20.0
# PCR near 1.0 is neutral; > this is bearish-leaning (put-heavy), < this is bullish-leaning
_PCR_BEARISH = 1.3
_PCR_BULLISH = 0.7


@dataclass
class SentimentData:
    blended_score: float  # 0-100, 50 = neutral
    label: str  # "Bullish" | "Neutral" | "Bearish"
    news_score: float | None  # 0-100, None if no headlines available
    internals_score: float | None  # 0-100, None if neither VIX nor PCR available


class SentimentSource(Protocol):
    async def score(
        self,
        headlines: list[str],
        vix: float | None,
        pcr: float | None,
    ) -> SentimentData | None: ...


class StubSentimentSource:
    async def score(
        self,
        headlines: list[str],
        vix: float | None,
        pcr: float | None,
    ) -> SentimentData | None:
        return None


def _label(score: float) -> str:
    if score >= 60:
        return "Bullish"
    if score <= 40:
        return "Bearish"
    return "Neutral"


def _internals_score(vix: float | None, pcr: float | None) -> float | None:
    parts: list[float] = []
    if vix is not None:
        if vix <= _VIX_CALM:
            parts.append(70.0)
        elif vix >= _VIX_FEARFUL:
            parts.append(30.0)
        else:
            # linear interpolation between calm (70) and fearful (30)
            frac = (vix - _VIX_CALM) / (_VIX_FEARFUL - _VIX_CALM)
            parts.append(70.0 - frac * 40.0)
    if pcr is not None:
        if pcr <= _PCR_BULLISH:
            parts.append(65.0)
        elif pcr >= _PCR_BEARISH:
            parts.append(35.0)
        else:
            frac = (pcr - _PCR_BULLISH) / (_PCR_BEARISH - _PCR_BULLISH)
            parts.append(65.0 - frac * 30.0)
    if not parts:
        return None
    return sum(parts) / len(parts)


class BlendedSentimentSource:
    async def score(
        self,
        headlines: list[str],
        vix: float | None,
        pcr: float | None,
    ) -> SentimentData | None:
        return await asyncio.to_thread(self._score_sync, headlines, vix, pcr)

    def _score_sync(
        self,
        headlines: list[str],
        vix: float | None,
        pcr: float | None,
    ) -> SentimentData | None:
        news_score: float | None = None
        if headlines:
            try:
                from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

                analyzer = SentimentIntensityAnalyzer()
                compounds = [analyzer.polarity_scores(h)["compound"] for h in headlines]
                avg_compound = sum(compounds) / len(compounds)
                news_score = (avg_compound + 1.0) / 2.0 * 100.0
            except Exception as exc:
                log.warning("sentiment_news_score_failed", exc=str(exc))

        internals_score = _internals_score(vix, pcr)

        sub_scores = [s for s in (news_score, internals_score) if s is not None]
        if not sub_scores:
            return None
        blended = sum(sub_scores) / len(sub_scores)
        return SentimentData(
            blended_score=round(blended, 1),
            label=_label(blended),
            news_score=round(news_score, 1) if news_score is not None else None,
            internals_score=round(internals_score, 1) if internals_score is not None else None,
        )
