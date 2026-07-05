"""Global market indices — Dow/Nasdaq/S&P/Nikkei/Hang Seng/FTSE via yfinance.

yfinance scrapes Yahoo Finance and is synchronous/slow — callers MUST invoke `fetch()` from a
thread-pool executor (see `pdp/intel/poller.py`), never inline on a request path.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Protocol

import structlog

log = structlog.get_logger()

# ticker -> display symbol
TICKERS: dict[str, str] = {
    "^DJI": "DOW",
    "^IXIC": "NASDAQ",
    "^GSPC": "SPX",
    "^N225": "NIKKEI",
    "^HSI": "HANGSENG",
    "^FTSE": "FTSE",
}


@dataclass
class GlobalIndexQuote:
    symbol: str
    ticker: str
    close: float
    prev_close: float
    change: float
    change_pct: float


class GlobalMarketSource(Protocol):
    async def fetch(self) -> list[GlobalIndexQuote]: ...


class StubGlobalMarketSource:
    async def fetch(self) -> list[GlobalIndexQuote]:
        return []


class YfinanceGlobalMarketSource:
    """Fetches the last two daily closes per ticker and derives change vs prior close."""

    async def fetch(self) -> list[GlobalIndexQuote]:
        return await asyncio.to_thread(self._fetch_sync)

    def _fetch_sync(self) -> list[GlobalIndexQuote]:
        import yfinance as yf

        quotes: list[GlobalIndexQuote] = []
        data = yf.download(
            list(TICKERS.keys()), period="5d", interval="1d",
            progress=False, group_by="ticker",
        )
        for ticker, symbol in TICKERS.items():
            try:
                closes = data[ticker]["Close"].dropna()
                if len(closes) < 2:
                    continue
                close = float(closes.iloc[-1])
                prev_close = float(closes.iloc[-2])
                change = close - prev_close
                change_pct = (change / prev_close * 100) if prev_close else 0.0
                quotes.append(GlobalIndexQuote(
                    symbol=symbol, ticker=ticker, close=close, prev_close=prev_close,
                    change=change, change_pct=change_pct,
                ))
            except Exception as exc:
                log.warning("global_index_fetch_failed", ticker=ticker, exc=str(exc))
        return quotes
