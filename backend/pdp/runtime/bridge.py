import asyncio
import json
import structlog
from redis.asyncio import Redis

from pdp.market.ws import WSHub

log = structlog.get_logger()

class MarketBridge:
    """
    Bridges Redis pub/sub and Streams back to the in-process WSHub.
    Runs in the API process so clients can get realtime data from the Engine.
    """
    def __init__(self, redis: Redis, ws_hub: WSHub):
        self.redis = redis
        self.ws_hub = ws_hub
        self._running = False
        self._pubsub = self.redis.pubsub(ignore_subscribe_messages=True)

    async def start(self):
        self._running = True
        await self._pubsub.psubscribe("tick.*")
        self._pubsub_task = asyncio.create_task(self._run_pubsub())
        self._streams_task = asyncio.create_task(self._run_streams())
        log.info("market_bridge_started")

    async def stop(self):
        self._running = False
        await self._pubsub.punsubscribe("tick.*")
        await self._pubsub.close()
        self._pubsub_task.cancel()
        self._streams_task.cancel()
        try:
            await asyncio.gather(self._pubsub_task, self._streams_task, return_exceptions=True)
        except asyncio.CancelledError:
            pass

    async def _run_pubsub(self):
        while self._running:
            try:
                msg = await self._pubsub.get_message(timeout=1.0)
                if msg and msg["type"] == "pmessage":
                    channel = msg["channel"]
                    if channel.startswith("tick."):
                        sid = channel.split(".")[1]
                        # msg["data"] is string tick_payload from TickRouter
                        self.ws_hub.publish_tick_raw(sid, msg["data"])
            except Exception as exc:
                log.warning("market_bridge_pubsub_error", exc=str(exc))
                await asyncio.sleep(1.0)

    async def _run_streams(self):
        # We need a cursor for each stream.
        cursors = {}
        while self._running:
            try:
                # 1. Compute active streams from WSHub clients
                active_streams = set()
                for client in self.ws_hub._clients:
                    for sid in client.security_ids:
                        for tf in client.timeframes:
                            active_streams.add(f"bars.{sid}.{tf}")
                
                if not active_streams:
                    await asyncio.sleep(1.0)
                    continue

                streams = {s: cursors.get(s, "$") for s in active_streams}
                
                # 2. XREAD from streams
                results = await self.redis.xread(streams, count=100, block=1000)
                if results:
                    for stream_name, messages in results:
                        cursors[stream_name] = messages[-1][0]
                        # stream_name is like 'bars.NIFTY.15m'
                        parts = stream_name.split(".")
                        sid = parts[1]
                        tf = parts[2]
                        for msg_id, data in messages:
                            # Reconstruct bar payload
                            payload = json.dumps({
                                "type": "bar",
                                "security_id": sid,
                                "timeframe": tf,
                                "bar_time": data.get("bar_time"),
                                "open": data.get("open"),
                                "high": data.get("high"),
                                "low": data.get("low"),
                                "close": data.get("close"),
                                "volume": int(data.get("volume", 0)),
                                "oi": int(data.get("oi", 0)),
                                "ts": float(msg_id.split("-")[0]) / 1000.0,
                            })
                            self.ws_hub.publish_bar_raw(sid, tf, payload)
            except Exception as exc:
                if self._running:
                    log.warning("market_bridge_streams_error", exc=str(exc))
                    await asyncio.sleep(1.0)

class GenericPubSubBridge:
    def __init__(self, redis: Redis, channels_to_hubs: dict[str, tuple]):
        self.redis = redis
        self.channels_to_hubs = channels_to_hubs
        self._running = False
        self._pubsub = self.redis.pubsub(ignore_subscribe_messages=True)

    async def start(self):
        self._running = True
        channels = list(self.channels_to_hubs.keys())
        if channels:
            await self._pubsub.psubscribe(*channels)
            self._task = asyncio.create_task(self._run())
            log.info("generic_pubsub_bridge_started", channels=channels)

    async def stop(self):
        self._running = False
        channels = list(self.channels_to_hubs.keys())
        if channels:
            await self._pubsub.punsubscribe(*channels)
        await self._pubsub.close()
        if hasattr(self, "_task"):
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _run(self):
        while self._running:
            try:
                msg = await self._pubsub.get_message(timeout=1.0)
                if msg and msg["type"] == "pmessage":
                    pattern = msg["pattern"].decode("utf-8") if isinstance(msg["pattern"], bytes) else msg["pattern"]
                    if pattern in self.channels_to_hubs:
                        hub, method = self.channels_to_hubs[pattern]
                        data = msg["data"].decode("utf-8") if isinstance(msg["data"], bytes) else msg["data"]
                        getattr(hub, method)(data)
            except Exception as exc:
                if self._running:
                    log.warning("generic_bridge_error", exc=str(exc))
                    await asyncio.sleep(1.0)

class RedisHubProxy:
    """Proxy object used by engine to publish to Redis pub/sub."""
    def __init__(self, redis: Redis, prefix: str):
        self.redis = redis
        self.prefix = prefix

    def _publish(self, suffix: str, payload: str):
        asyncio.create_task(self.redis.publish(f"{self.prefix}.{suffix}", payload))

    def publish_fill(self, fill):
        payload = fill.model_dump_json() if hasattr(fill, "model_dump_json") else json.dumps(fill)
        self._publish("fill", payload)
        
    def publish_order(self, order):
        payload = order.model_dump_json() if hasattr(order, "model_dump_json") else json.dumps(order)
        self._publish("order", payload)

    def publish_event(self, event):
        payload = event.model_dump_json() if hasattr(event, "model_dump_json") else json.dumps(event)
        self._publish("event", payload)
        
    def publish(self, chain):
        payload = chain.model_dump_json() if hasattr(chain, "model_dump_json") else json.dumps(chain)
        self._publish("chain", payload)
        
    def publish_mtm(self, mtm):
        payload = mtm.model_dump_json() if hasattr(mtm, "model_dump_json") else json.dumps(mtm)
        self._publish("mtm", payload)
