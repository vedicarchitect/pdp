"""Background refresher for third-party/scrape-based dashboard data.

Non-negotiable: the tick->WS hot path budget is p99 <= 50ms and third-party libs
(yfinance/nsepython/feedparser/vaderSentiment) are synchronous and slow. This poller runs each
source on its own interval, offloading sync calls to a thread pool (the sources already do this
internally via `asyncio.to_thread`), and writes `{"data": ..., "as_of": ...}` to Redis. Routes
read only from this cache — never call a source inline on a request.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import asdict
from datetime import UTC, datetime

import structlog

from pdp.intel.sources.global_market import GlobalMarketSource
from pdp.intel.sources.news import NewsSource
from pdp.intel.sources.sentiment import SentimentSource
from pdp.options.fii_dii import FIIDIISource

log = structlog.get_logger()

CACHE_KEY_GLOBAL_INDICES = "intel:global_indices"
CACHE_KEY_NEWS = "intel:news"
CACHE_KEY_SENTIMENT = "intel:sentiment"
CACHE_KEY_FII_DII = "intel:fii_dii_history"

# Cache TTL is generous vs. poll interval so a slow/failed poll cycle doesn't blank the section.
_CACHE_TTL_SECONDS = 3600

# Underlying whose option-chain PCR feeds the sentiment internals sub-score (NIFTY is the
# market-wide benchmark chain — same one already polled by `OptionsChainPoller`).
_PCR_UNDERLYING = "NIFTY"


class IntelPoller:
    def __init__(
        self,
        redis,
        global_market_source: GlobalMarketSource,
        news_source: NewsSource,
        sentiment_source: SentimentSource,
        fii_dii_source: FIIDIISource,
        news_feed_urls: list[str],
        vix_security_id: str,
        global_indices_interval: float,
        news_interval: float,
        fii_dii_interval: float,
        mongo_db=None,
    ) -> None:
        self._redis = redis
        self._global_market = global_market_source
        self._news = news_source
        self._sentiment = sentiment_source
        self._fii_dii = fii_dii_source
        self._news_feed_urls = news_feed_urls
        self._vix_security_id = vix_security_id
        self._global_indices_interval = global_indices_interval
        self._news_interval = news_interval
        self._fii_dii_interval = fii_dii_interval
        self._mongo_db = mongo_db
        self._fallback_cache: dict[str, dict] = {}
        self._tasks: list[asyncio.Task] = []

    def start(self) -> None:
        self._tasks = [
            asyncio.create_task(
                self._loop("global_indices", self._refresh_global_indices, self._global_indices_interval)
            ),
            asyncio.create_task(
                self._loop("news_and_sentiment", self._refresh_news_and_sentiment, self._news_interval)
            ),
            asyncio.create_task(self._loop("fii_dii", self._refresh_fii_dii, self._fii_dii_interval)),
        ]
        log.info("intel_poller_started")

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception as exc:
                log.warning("intel_poller_task_stop_error", exc=str(exc))

    async def _loop(self, name: str, refresh, interval: float) -> None:
        while True:
            try:
                await refresh()
            except Exception as exc:
                log.warning("intel_poll_cycle_failed", source=name, exc=str(exc))
            await asyncio.sleep(interval)

    async def _write_cache(self, key: str, data) -> None:
        payload = {"data": data, "as_of": datetime.now(UTC).isoformat()}
        try:
            await self._redis.set(key, json.dumps(payload, default=str), ex=_CACHE_TTL_SECONDS)
        except Exception as exc:
            log.warning("intel_cache_write_failed", key=key, exc=str(exc))
            self._fallback_cache[key] = payload

    async def read_cache(self, key: str) -> dict | None:
        try:
            raw = await self._redis.get(key)
            if raw:
                return json.loads(raw)
        except Exception as exc:
            log.warning("intel_cache_read_failed", key=key, exc=str(exc))
        return self._fallback_cache.get(key)

    async def _refresh_global_indices(self) -> None:
        quotes = await self._global_market.fetch()
        await self._write_cache(CACHE_KEY_GLOBAL_INDICES, [asdict(q) for q in quotes])

    async def _refresh_news_and_sentiment(self) -> None:
        articles = await self._news.fetch(self._news_feed_urls)
        await self._write_cache(CACHE_KEY_NEWS, [asdict(a) for a in articles])

        vix: float | None = None
        try:
            raw_vix = await self._redis.get(f"ltp:{self._vix_security_id}")
            vix = float(raw_vix) if raw_vix is not None else None
        except Exception:
            vix = None

        pcr = await self._fetch_pcr()
        headlines = [a.headline for a in articles]
        sentiment = await self._sentiment.score(headlines, vix, pcr)
        await self._write_cache(CACHE_KEY_SENTIMENT, asdict(sentiment) if sentiment else None)

    async def _fetch_pcr(self) -> float | None:
        """Market-wide PCR from the latest polled option-chain snapshot (already computed
        elsewhere by `OptionsChainPoller` — no new chain fetch here)."""
        if self._mongo_db is None:
            return None
        try:
            from pdp.options.analytics import compute_pcr

            doc = await self._mongo_db["option_chains"].find_one(
                {"underlying": _PCR_UNDERLYING},
                sort=[("snapshot_ts", -1)],
            )
            if not doc:
                return None
            return compute_pcr(doc.get("strikes", []))
        except Exception as exc:
            log.warning("intel_pcr_fetch_failed", exc=str(exc))
            return None

    async def _refresh_fii_dii(self) -> None:
        fetch_range = getattr(self._fii_dii, "fetch_range", None)
        if fetch_range is None:
            await self._write_cache(CACHE_KEY_FII_DII, [])
            return
        rows = await fetch_range(7)
        await self._write_cache(CACHE_KEY_FII_DII, [asdict(r) for r in rows])
