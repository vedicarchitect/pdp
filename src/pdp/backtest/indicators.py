from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

import polars as pl
import structlog

if TYPE_CHECKING:
    from pymongo import MongoClient

log = structlog.get_logger()


class IndicatorCache:
    """Pre-computes and caches indicators for efficient backtest replay."""

    def __init__(self, mongo_client: MongoClient) -> None:
        self.mongo_client = mongo_client
        self._cache: dict[tuple[str, str], dict] = {}

    def pre_compute(
        self,
        security_id: str,
        timeframe: str,
        from_date: datetime,
        to_date: datetime,
        mongo_db_name: str = "pdp",
    ) -> dict:
        """Pre-compute all indicators for (security, timeframe) over date range."""
        cache_key = (security_id, timeframe)

        if cache_key in self._cache:
            log.debug("indicator_cache_hit", security_id=security_id, timeframe=timeframe)
            return self._cache[cache_key]

        db = self.mongo_client.get_database(mongo_db_name)
        collection = db.get_collection("market_bars")

        # Bars use ts + metadata.{security_id, timeframe} schema (written by BarWriter)
        query = {
            "metadata.security_id": security_id,
            "metadata.timeframe": timeframe,
            "ts": {
                "$gte": from_date,
                "$lte": to_date,
            },
        }

        bars = list(collection.find(query).sort("ts", 1))

        if not bars:
            log.warning(
                "no_bars_for_indicator_compute",
                security_id=security_id,
                timeframe=timeframe,
            )
            return {}

        # Convert to Polars DataFrame for vectorized computation
        df = pl.DataFrame(
            {
                "bar_time": [bar["ts"] for bar in bars],
                "open": [Decimal(str(bar["open"])) for bar in bars],
                "high": [Decimal(str(bar["high"])) for bar in bars],
                "low": [Decimal(str(bar["low"])) for bar in bars],
                "close": [Decimal(str(bar["close"])) for bar in bars],
                "volume": [bar.get("volume", 0) for bar in bars],
            }
        )

        indicators = self._compute_indicators(df)

        # Cache by bar_time for fast lookup during replay
        cache_data = {}
        for i, bar_time in enumerate(df["bar_time"]):
            cache_data[bar_time] = {
                "sma_20": indicators["sma_20"][i] if i < len(indicators["sma_20"]) else None,
                "sma_50": indicators["sma_50"][i] if i < len(indicators["sma_50"]) else None,
                "ema_12": indicators["ema_12"][i] if i < len(indicators["ema_12"]) else None,
                "ema_26": indicators["ema_26"][i] if i < len(indicators["ema_26"]) else None,
                "rsi_14": indicators["rsi_14"][i] if i < len(indicators["rsi_14"]) else None,
            }

        self._cache[cache_key] = cache_data
        log.info(
            "indicator_precompute_done",
            security_id=security_id,
            timeframe=timeframe,
            bars_count=len(bars),
        )
        return cache_data

    def _compute_indicators(self, df: pl.DataFrame) -> dict:
        """Compute all indicators using Polars vectorization."""
        close = df["close"].to_list()
        high = df["high"].to_list()
        low = df["low"].to_list()

        # Simple Moving Average (20, 50 periods)
        sma_20 = self._sma(close, 20)
        sma_50 = self._sma(close, 50)

        # Exponential Moving Average (12, 26 periods)
        ema_12 = self._ema(close, 12)
        ema_26 = self._ema(close, 26)

        # RSI (14 periods)
        rsi_14 = self._rsi(close, 14)

        return {
            "sma_20": sma_20,
            "sma_50": sma_50,
            "ema_12": ema_12,
            "ema_26": ema_26,
            "rsi_14": rsi_14,
        }

    @staticmethod
    def _sma(prices: list, period: int) -> list:
        """Simple Moving Average."""
        sma = []
        for i in range(len(prices)):
            if i < period - 1:
                sma.append(None)
            else:
                avg = sum(prices[i - period + 1 : i + 1]) / period
                sma.append(avg)
        return sma

    @staticmethod
    def _ema(prices: list, period: int) -> list:
        """Exponential Moving Average."""
        ema = []
        multiplier = 2 / (period + 1)

        for i in range(len(prices)):
            if i < period - 1:
                ema.append(None)
            elif i == period - 1:
                sma = sum(prices[:period]) / period
                ema.append(sma)
            else:
                ema_val = prices[i] * multiplier + ema[-1] * (1 - multiplier)
                ema.append(ema_val)
        return ema

    @staticmethod
    def _rsi(prices: list, period: int) -> list:
        """Relative Strength Index."""
        if len(prices) < period + 1:
            return [None] * len(prices)

        deltas = [prices[i] - prices[i - 1] for i in range(1, len(prices))]
        gains = [d if d > 0 else 0 for d in deltas]
        losses = [-d if d < 0 else 0 for d in deltas]

        rsi_vals = [None] * len(prices)

        for i in range(period, len(prices)):
            avg_gain = sum(gains[i - period : i]) / period
            avg_loss = sum(losses[i - period : i]) / period

            if avg_loss == 0:
                rsi = 100 if avg_gain > 0 else 50
            else:
                rs = avg_gain / avg_loss
                rsi = 100 - (100 / (1 + rs))

            rsi_vals[i] = rsi

        return rsi_vals

    def get(self, security_id: str, timeframe: str, bar_time: datetime, indicator: str) -> float | None:
        """Get a specific indicator value for a bar timestamp."""
        cache_key = (security_id, timeframe)

        if cache_key not in self._cache:
            return None

        cache_data = self._cache[cache_key]
        if bar_time not in cache_data:
            return None

        return cache_data[bar_time].get(indicator)
