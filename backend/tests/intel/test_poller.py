"""Poller tests: confirms sync lib calls are offloaded and results land in the cache."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from pdp.intel.poller import (
    CACHE_KEY_FII_DII,
    CACHE_KEY_GLOBAL_INDICES,
    CACHE_KEY_NEWS,
    CACHE_KEY_SENTIMENT,
    IntelPoller,
)
from pdp.intel.sources.global_market import GlobalIndexQuote
from pdp.intel.sources.news import NewsArticle
from pdp.intel.sources.sentiment import SentimentData
from pdp.options.fii_dii import FIIDIIData


def _make_poller(redis, mongo_db=None) -> IntelPoller:
    global_source = MagicMock()
    global_source.fetch = AsyncMock(
        return_value=[
            GlobalIndexQuote(
                symbol="DOW", ticker="^DJI", close=100.0, prev_close=95.0, change=5.0, change_pct=5.26
            ),
        ]
    )
    news_source = MagicMock()
    news_source.fetch = AsyncMock(
        return_value=[
            NewsArticle(
                headline="Markets rally",
                source="Test",
                url="https://x",
                published_at=__import__("datetime").datetime.now(),
            ),
        ]
    )
    sentiment_source = MagicMock()
    sentiment_source.score = AsyncMock(
        return_value=SentimentData(
            blended_score=65.0,
            label="Bullish",
            news_score=70.0,
            internals_score=60.0,
        )
    )
    fii_dii_source = MagicMock()
    fii_dii_source.fetch_range = AsyncMock(
        return_value=[
            FIIDIIData(
                date=__import__("datetime").date(2026, 7, 3),
                fii_index_futures_net=0.0,
                fii_index_options_net=0.0,
                fii_stock_futures_net=1355.33,
                dii_index_futures_net=0.0,
                dii_index_options_net=0.0,
                dii_stock_futures_net=-1953.89,
            ),
        ]
    )
    return IntelPoller(
        redis=redis,
        global_market_source=global_source,
        news_source=news_source,
        sentiment_source=sentiment_source,
        fii_dii_source=fii_dii_source,
        news_feed_urls=["https://example.com/rss.xml"],
        vix_security_id="21",
        global_indices_interval=300.0,
        news_interval=300.0,
        fii_dii_interval=900.0,
        mongo_db=mongo_db,
    )


@pytest.fixture
def fake_redis():
    store: dict[str, str] = {}

    async def _set(key, value, ex=None):
        store[key] = value

    async def _get(key):
        return store.get(key)

    redis = MagicMock()
    redis.set = AsyncMock(side_effect=_set)
    redis.get = AsyncMock(side_effect=_get)
    return redis


@pytest.mark.asyncio
async def test_refresh_global_indices_writes_cache(fake_redis):
    poller = _make_poller(fake_redis)
    await poller._refresh_global_indices()
    cached = await poller.read_cache(CACHE_KEY_GLOBAL_INDICES)
    assert cached is not None
    assert cached["data"][0]["ticker"] == "^DJI"
    assert "as_of" in cached


@pytest.mark.asyncio
async def test_refresh_news_and_sentiment_writes_both_caches(fake_redis):
    poller = _make_poller(fake_redis)
    await poller._refresh_news_and_sentiment()

    news_cached = await poller.read_cache(CACHE_KEY_NEWS)
    assert news_cached["data"][0]["headline"] == "Markets rally"

    sentiment_cached = await poller.read_cache(CACHE_KEY_SENTIMENT)
    assert sentiment_cached["data"]["blended_score"] == pytest.approx(65.0)


@pytest.mark.asyncio
async def test_refresh_news_and_sentiment_passes_real_pcr_when_mongo_configured(fake_redis):
    chain_doc = {
        "underlying": "NIFTY",
        "strikes": [{"strike": 24700, "ce": {"oi": 100}, "pe": {"oi": 130}}],
    }
    chains_col = MagicMock()
    chains_col.find_one = AsyncMock(return_value=chain_doc)
    mongo_db = {"option_chains": chains_col}

    poller = _make_poller(fake_redis, mongo_db=mongo_db)
    await poller._refresh_news_and_sentiment()

    poller._sentiment.score.assert_awaited_once()
    _headlines, _vix, pcr = poller._sentiment.score.await_args.args
    assert pcr == pytest.approx(1.3)


@pytest.mark.asyncio
async def test_refresh_news_and_sentiment_pcr_none_without_mongo(fake_redis):
    poller = _make_poller(fake_redis, mongo_db=None)
    await poller._refresh_news_and_sentiment()

    poller._sentiment.score.assert_awaited_once()
    _headlines, _vix, pcr = poller._sentiment.score.await_args.args
    assert pcr is None


@pytest.mark.asyncio
async def test_fetch_pcr_returns_none_when_chain_missing(fake_redis):
    chains_col = MagicMock()
    chains_col.find_one = AsyncMock(return_value=None)
    mongo_db = {"option_chains": chains_col}

    poller = _make_poller(fake_redis, mongo_db=mongo_db)
    assert await poller._fetch_pcr() is None


@pytest.mark.asyncio
async def test_refresh_fii_dii_writes_cache(fake_redis):
    poller = _make_poller(fake_redis)
    await poller._refresh_fii_dii()
    cached = await poller.read_cache(CACHE_KEY_FII_DII)
    assert len(cached["data"]) == 1
    assert cached["data"][0]["fii_stock_futures_net"] == pytest.approx(1355.33)


@pytest.mark.asyncio
async def test_redis_failure_falls_back_to_in_process_cache():
    redis = MagicMock()
    redis.set = AsyncMock(side_effect=RuntimeError("redis down"))
    redis.get = AsyncMock(side_effect=RuntimeError("redis down"))
    poller = _make_poller(redis)

    await poller._refresh_global_indices()
    cached = await poller.read_cache(CACHE_KEY_GLOBAL_INDICES)
    assert cached is not None
    assert cached["data"][0]["ticker"] == "^DJI"


@pytest.mark.asyncio
async def test_cache_payload_is_json_serializable(fake_redis):
    poller = _make_poller(fake_redis)
    await poller._refresh_global_indices()
    raw = await fake_redis.get(CACHE_KEY_GLOBAL_INDICES)
    parsed = json.loads(raw)
    assert parsed["data"][0]["symbol"] == "DOW"
