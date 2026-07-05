"""Unit tests for dashboard intel sources — each underlying third-party lib is mocked."""
from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from pdp.intel.sources.global_market import (
    TICKERS,
    StubGlobalMarketSource,
    YfinanceGlobalMarketSource,
)
from pdp.intel.sources.news import FeedparserNewsSource, StubNewsSource
from pdp.intel.sources.sentiment import (
    BlendedSentimentSource,
    StubSentimentSource,
    _internals_score,
)
from pdp.options.fii_dii import NseFIIDIISource, StubFIIDIISource

# ── global_market ────────────────────────────────────────────────────────────

def _fake_yf_frame() -> pd.DataFrame:
    tickers = list(TICKERS.keys())
    cols = pd.MultiIndex.from_product([tickers, ["Close"]])
    data = {}
    for i, t in enumerate(tickers):
        data[(t, "Close")] = [100.0 + i, 105.0 + i]
    return pd.DataFrame(data, columns=cols)


@pytest.mark.asyncio
async def test_yfinance_source_returns_quotes_when_lib_succeeds():
    with patch("yfinance.download", return_value=_fake_yf_frame()):
        source = YfinanceGlobalMarketSource()
        quotes = await source.fetch()
    assert len(quotes) == len(TICKERS)
    dow = next(q for q in quotes if q.ticker == "^DJI")
    assert dow.close == pytest.approx(105.0)
    assert dow.prev_close == pytest.approx(100.0)
    assert dow.change == pytest.approx(5.0)


@pytest.mark.asyncio
async def test_yfinance_source_degrades_on_failure():
    with patch("yfinance.download", side_effect=RuntimeError("network down")):
        source = YfinanceGlobalMarketSource()
        with pytest.raises(RuntimeError):
            # download() raising is a hard failure inside _fetch_sync — poller catches this
            # at the poll-cycle level, not inside the source itself.
            await source.fetch()


@pytest.mark.asyncio
async def test_stub_global_market_source_returns_empty():
    assert await StubGlobalMarketSource().fetch() == []


# ── news ──────────────────────────────────────────────────────────────────

def _fake_feed(titles: list[str]) -> MagicMock:
    parsed = MagicMock()
    parsed.feed = {"title": "Test Feed"}
    parsed.entries = [
        {"title": t, "link": f"https://example.com/{i}", "published_parsed": None}
        for i, t in enumerate(titles)
    ]
    return parsed


@pytest.mark.asyncio
async def test_feedparser_source_returns_real_articles():
    with patch("feedparser.parse", return_value=_fake_feed(["Markets rally", "Nifty at record high"])):
        source = FeedparserNewsSource()
        articles = await source.fetch(["https://example.com/rss.xml"])
    assert len(articles) == 2
    assert articles[0].headline in {"Markets rally", "Nifty at record high"}


@pytest.mark.asyncio
async def test_feedparser_source_degrades_per_feed_on_failure():
    with patch("feedparser.parse", side_effect=RuntimeError("feed unreachable")):
        source = FeedparserNewsSource()
        articles = await source.fetch(["https://example.com/broken.xml"])
    assert articles == []


@pytest.mark.asyncio
async def test_stub_news_source_returns_empty():
    assert await StubNewsSource().fetch(["https://example.com/rss.xml"]) == []


# ── sentiment ─────────────────────────────────────────────────────────────

def test_internals_score_calm_vix_and_bullish_pcr():
    score = _internals_score(vix=10.0, pcr=0.5)
    assert score is not None
    assert score > 60


def test_internals_score_none_when_no_inputs():
    assert _internals_score(vix=None, pcr=None) is None


@pytest.mark.asyncio
async def test_blended_sentiment_combines_news_and_internals():
    source = BlendedSentimentSource()
    data = await source.score(
        headlines=["Markets rally as Nifty hits record high on strong earnings"],
        vix=11.0,
        pcr=0.6,
    )
    assert data is not None
    assert data.news_score is not None
    assert data.internals_score is not None
    assert 0 <= data.blended_score <= 100
    assert data.label in {"Bullish", "Neutral", "Bearish"}


@pytest.mark.asyncio
async def test_blended_sentiment_returns_none_when_no_inputs():
    source = BlendedSentimentSource()
    data = await source.score(headlines=[], vix=None, pcr=None)
    assert data is None


@pytest.mark.asyncio
async def test_stub_sentiment_source_returns_none():
    assert await StubSentimentSource().score([], None, None) is None


# ── fii_dii (NseFIIDIISource) ─────────────────────────────────────────────

def _fake_fiidii_df() -> pd.DataFrame:
    return pd.DataFrame([
        {"buyValue": 18676.35, "category": "DII", "date": "03-Jul-2026",
         "netValue": -1953.89, "sellValue": 20630.24},
        {"buyValue": 13337.33, "category": "FII/FPI", "date": "03-Jul-2026",
         "netValue": 1355.33, "sellValue": 11982.0},
    ])


@pytest.mark.asyncio
async def test_nse_fii_dii_source_parses_real_shape():
    with patch("nsepython.nse_fiidii", return_value=_fake_fiidii_df()):
        source = NseFIIDIISource()
        rows = await source.fetch_range(7)
    assert len(rows) == 1
    row = rows[0]
    assert row.date == date(2026, 7, 3)
    assert row.dii_index_futures_net == 0.0  # granularity NSE doesn't publish — left at 0, not guessed
    assert row.dii_stock_futures_net == pytest.approx(-1953.89)
    assert row.fii_stock_futures_net == pytest.approx(1355.33)


@pytest.mark.asyncio
async def test_nse_fii_dii_source_degrades_on_failure():
    with patch("nsepython.nse_fiidii", side_effect=RuntimeError("nse unreachable")):
        source = NseFIIDIISource()
        rows = await source.fetch_range(7)
    assert rows == []


@pytest.mark.asyncio
async def test_stub_fii_dii_source_returns_none():
    assert await StubFIIDIISource().fetch(date(2026, 7, 3)) is None
