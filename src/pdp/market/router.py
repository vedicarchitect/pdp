from __future__ import annotations

import asyncio
import json

import structlog
from redis.asyncio import Redis

from pdp.market.models import Tick

log = structlog.get_logger()


class TickRouter:
    """
    Consumes ticks from the adapter queue and fans out to:
      1. Redis hot LTP cache  (SET ltp:<id> EX 5)
      2. Redis pub/sub        (PUBLISH tick.<id>)

    Bar aggregator and WS hub hooks are stubs for the next change (add-market-data-bars).
    """

    def __init__(self) -> None:
        self._running = False

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

        # 3.2 — hot LTP cache (TTL=5s so stale data auto-expires)
        await redis.set(f"ltp:{sid}", ltp_str, ex=5)

        # 3.2 — pub/sub fan-out for downstream consumers (WS hub in next change)
        payload = json.dumps(
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
        await redis.publish(f"tick.{sid}", payload)
