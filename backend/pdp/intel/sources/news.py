"""Market news headlines via feedparser RSS.

feedparser performs blocking network I/O — callers MUST invoke `fetch()` from a thread-pool
executor (see `pdp/intel/poller.py`), never inline on a request path.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from time import mktime
from typing import Protocol

import structlog

log = structlog.get_logger()


@dataclass
class NewsArticle:
    headline: str
    source: str
    url: str
    published_at: datetime


class NewsSource(Protocol):
    async def fetch(self, feed_urls: list[str], limit: int = 20) -> list[NewsArticle]: ...


class StubNewsSource:
    async def fetch(self, feed_urls: list[str], limit: int = 20) -> list[NewsArticle]:
        return []


class FeedparserNewsSource:
    async def fetch(self, feed_urls: list[str], limit: int = 20) -> list[NewsArticle]:
        return await asyncio.to_thread(self._fetch_sync, feed_urls, limit)

    def _fetch_sync(self, feed_urls: list[str], limit: int) -> list[NewsArticle]:
        import feedparser

        articles: list[NewsArticle] = []
        for url in feed_urls:
            try:
                parsed = feedparser.parse(url)
                source = parsed.feed.get("title", url) if parsed.feed else url
                for entry in parsed.entries:
                    published = entry.get("published_parsed") or entry.get("updated_parsed")
                    published_at = (
                        datetime.fromtimestamp(mktime(published))
                        if published else datetime.now()
                    )
                    articles.append(NewsArticle(
                        headline=entry.get("title", ""),
                        source=source,
                        url=entry.get("link", ""),
                        published_at=published_at,
                    ))
            except Exception as exc:
                log.warning("news_feed_fetch_failed", url=url, exc=str(exc))
        articles.sort(key=lambda a: a.published_at, reverse=True)
        return articles[:limit]
