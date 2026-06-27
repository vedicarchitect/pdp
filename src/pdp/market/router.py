from __future__ import annotations

import asyncio
import json
import time as _time
from typing import TYPE_CHECKING

import structlog
from redis.asyncio import Redis

from pdp.market.models import Tick

if TYPE_CHECKING:
    from pdp.alerts.evaluator import AlertEvaluator
    from pdp.events.service import EventService
    from pdp.indicators.engine import IndicatorEngine
    from pdp.market.bar_writer import BarWriter
    from pdp.market.bars import BarAggregator
    from pdp.market.ws import WSHub
    from pdp.strategy.host import StrategyHost

log = structlog.get_logger()

_BAR_STREAM_MAXLEN = 1000


class TickRouter:
    """
    Consumes ticks from the adapter queue and fans out to:
      1. Redis hot LTP cache  (SET ltp:<id> EX 5)
      2. Redis pub/sub        (PUBLISH tick.<id>)
      3. BarAggregator        (emits BarClosed events)
      4. BarWriter            (batched MongoDB persistence)
      5. WSHub                (WebSocket fan-out for ticks and bars)
      6. Redis streams        (XADD bars.<id>.<tf>)
    """

    def __init__(
        self,
        bar_aggregator: BarAggregator | None = None,
        bar_writer: BarWriter | None = None,
        ws_hub: WSHub | None = None,
        strategy_host: StrategyHost | None = None,
        alert_evaluator: AlertEvaluator | None = None,
        indicator_engine: IndicatorEngine | None = None,
        event_service: EventService | None = None,
    ) -> None:
        self._running = False
        self._bar_aggregator = bar_aggregator
        self._bar_writer = bar_writer
        self._ws_hub = ws_hub
        self._strategy_host = strategy_host
        self._alert_evaluator = alert_evaluator
        self._indicator_engine = indicator_engine
        # Set post-construction in main.py lifespan once positions/portfolio exist.
        self.event_service = event_service

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

        # 1 & 2 — hot LTP cache + timestamp + pub/sub fan-out
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

        # Batch non-dependent operations in a pipeline to reduce network roundtrips
        async with redis.pipeline(transaction=False) as pipe:
            pipe.set(f"ltp:{sid}", ltp_str, ex=5)
            pipe.set(f"ltp_ts:{sid}", str(_time.time()), ex=5)
            pipe.publish(f"tick.{sid}", tick_payload)
            await pipe.execute()

        # 2.5 — alert evaluator (evaluate price conditions on new tick)
        if self._alert_evaluator is not None:
            from decimal import Decimal
            self._alert_evaluator.evaluate_price(sid, Decimal(str(tick.ltp)))

        # 2.6 — event publisher LTP cache (O(1); position detectors run on a timer)
        if self.event_service is not None:
            self.event_service.on_tick(sid, float(tick.ltp))

        # 3+4+5+6 — bar aggregation, persistence, WS, and Redis streams
        if self._bar_aggregator is not None:
            closed_bars = self._bar_aggregator.push(tick)
            for bar in closed_bars:
                # 4 — enqueue for MongoDB write
                if self._bar_writer is not None:
                    self._bar_writer.enqueue(bar)

                # 5 — WS fan-out for bars
                if self._ws_hub is not None:
                    self._ws_hub.publish_bar(bar)

                # 6b — universal indicators (computed once, before strategy dispatch)
                if self._indicator_engine is not None:
                    state = self._indicator_engine.on_bar(bar)
                    if state is not None and state.direction is not None:
                        await redis.set(
                            f"st:{bar.security_id}:{bar.timeframe}",
                            json.dumps(
                                {
                                    "direction": state.direction,
                                    "value": str(state.value),
                                    "flipped": state.flipped,
                                    "bar_time": bar.bar_time.isoformat(),
                                }
                            ),
                            ex=900,
                        )
                    # Publish suite snapshot (non-blocking; only when suite is configured)
                    _snap = self._indicator_engine.get_snapshot(bar.security_id, bar.timeframe)
                    if _snap is not None:
                        _snap_d = _snap.to_dict()
                        if _snap_d:
                            await redis.set(
                                f"ind:{bar.security_id}:{bar.timeframe}",
                                json.dumps(_snap_d),
                                ex=900,
                            )

                # 6c — ML inference (after on_bar caching; reuses computed snapshot; non-blocking)
                if self._indicator_engine is not None:
                    try:
                        from pdp.ml.infer import infer_all
                        _prev_bar = getattr(self, "_prev_bars", {}).get((bar.security_id, bar.timeframe))
                        ml_results = infer_all(
                            bar.security_id,
                            bar.timeframe,
                            bar,
                            self._indicator_engine.get_snapshot(bar.security_id, bar.timeframe),
                            self._indicator_engine.get(bar.security_id, bar.timeframe),
                            prev_bar=_prev_bar,
                        )
                        if ml_results:
                            import json as _json
                            for head, ml_state in ml_results.items():
                                await redis.set(
                                    f"ml:{bar.security_id}:{bar.timeframe}:{head}",
                                    _json.dumps({
                                        "argmax": ml_state.argmax,
                                        "probs": ml_state.probs,
                                        "version": ml_state.version,
                                        "bar_time": bar.bar_time.isoformat(),
                                    }),
                                    ex=900,
                                )
                            # Store the primary directional signal in the engine for strategy access
                            primary = ml_results.get("directional")
                            if primary is not None:
                                self._indicator_engine.set_ml_signal(bar.security_id, bar.timeframe, primary)
                        # Keep the previous bar for slope features
                        if not hasattr(self, "_prev_bars"):
                            self._prev_bars: dict = {}
                        self._prev_bars[(bar.security_id, bar.timeframe)] = bar
                    except Exception as _ml_exc:
                        log.debug("ml_infer_skipped", exc=str(_ml_exc))

                # 6d — event publisher detectors (uses engine snapshot + ml cached above)
                if self.event_service is not None:
                    self.event_service.on_bar(bar)

                # 7b — strategy host bar dispatch
                if self._strategy_host is not None:
                    self._strategy_host.on_bar(bar)

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

        # 7 — strategy host dispatch (non-blocking; drops on full inbox)
        if self._strategy_host is not None:
            self._strategy_host.on_tick(tick)
