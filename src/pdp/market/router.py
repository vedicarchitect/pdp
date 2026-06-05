from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING

import structlog
from redis.asyncio import Redis

from pdp.market.models import Tick

if TYPE_CHECKING:
    from pdp.market.bar_writer import BarWriter
    from pdp.market.bars import BarAggregator
    from pdp.market.ws import WSHub

log = structlog.get_logger()

_BAR_STREAM_MAXLEN = 1000


class TickRouter:
    """
    Consumes ticks from the adapter queue and fans out to:
      1. Redis hot LTP cache  (SET ltp:<id> EX 5)
      2. Redis pub/sub        (PUBLISH tick.<id>)
      3. BarAggregator        (emits BarClosed events)
      4. BarWriter            (batched Timescale persistence)
      5. WSHub                (WebSocket fan-out for ticks and bars)
      6. Redis streams        (XADD bars.<id>.<tf>)
    """

    def __init__(
        self,
        bar_aggregator: BarAggregator | None = None,
        bar_writer: BarWriter | None = None,
        ws_hub: WSHub | None = None,
    ) -> None:
        self._running = False
        self._bar_aggregator = bar_aggregator
        self._bar_writer = bar_writer
        self._ws_hub = ws_hub

    async def run(self, queue: asyncio.Queue[Tick], redis: Redis) -> None:
        self._running = True
        log.info("tick_router_started")
        while self._running:
            try:
                tick = await asyncio.wait_for(queue.get(), timeout=1.0)
            except TimeoutError:
                continue
            try:
                await self._handle(tick, redis)
            except Exception as exc:
                log.warning("tick_router_handle_error", exc=str(exc), security_id=tick.security_id)
            finally:
                queue.task_done()

    async def stop(self) -> None:
        self._running = False

    async def _handle(self, tick: Tick, redis: Redis) -> None:
        ltp_str = str(tick.ltp)
        sid = tick.security_id

        # 1 — hot LTP cache (TTL=5s so stale data auto-expires)
        await redis.set(f"ltp:{sid}", ltp_str, ex=5)

        # 2 — pub/sub fan-out for downstream consumers
        tick_payload = json.dumps(
            {
                "type": "tick",
                "security_id": sid,
                "exchange_segment": tick.exchange_segment,
                "ltp": ltp_str,
                "volume": tick.volume,
                "oi": tick.oi,
                "ltt": tick.ltt.isoformat(),
            }
        )
        await redis.publish(f"tick.{sid}", tick_payload)

        # 3+4+5+6 — bar aggregation, persistence, WS, and Redis streams
        if self._bar_aggregator is not None:
            closed_bars = self._bar_aggregator.push(tick)
            for bar in closed_bars:
                # 4 — enqueue for Timescale write
                if self._bar_writer is not None:
                    self._bar_writer.enqueue(bar)

                # 5 — WS fan-out for bars
                if self._ws_hub is not None:
                    self._ws_hub.publish_bar(bar)

                # 6 — Redis stream XADD bars.<sid>.<tf>
                await redis.xadd(
                    f"bars.{bar.security_id}.{bar.timeframe}",
                    {
                        "open": str(bar.open),
                        "high": str(bar.high),
                        "low": str(bar.low),
                        "close": str(bar.close),
                        "volume": str(bar.volume),
                        "oi": str(bar.oi),
                        "bar_time": bar.bar_time.isoformat(),
                    },
                    maxlen=_BAR_STREAM_MAXLEN,
                    approximate=True,
                )

        # 5 — WS fan-out for raw ticks
        if self._ws_hub is not None:
            self._ws_hub.publish_tick(tick)
