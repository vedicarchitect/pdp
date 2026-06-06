from __future__ import annotations

import asyncio
import asyncio.futures
import concurrent.futures
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any

import structlog
from dhanhq import DhanContext, MarketFeed
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from pdp.market.models import Tick

if TYPE_CHECKING:
    pass

log = structlog.get_logger()

# Maps our canonical segment labels → MarketFeed exchange codes
_SEGMENT_TO_EXCH: dict[str, int] = {
    "NSE_EQ": MarketFeed.NSE,
    "NSE_FNO": MarketFeed.NSE_FNO,
    "NSE_CUR": MarketFeed.NSE_CURR,
    "BSE_EQ": MarketFeed.BSE,
    "BSE_FNO": MarketFeed.BSE_FNO,
    "BSE_CUR": MarketFeed.BSE_CURR,
    "MCX_COMM": MarketFeed.MCX,
    "IDX_I": MarketFeed.IDX,
}

_EXCH_TO_SEGMENT: dict[int, str] = {v: k for k, v in _SEGMENT_TO_EXCH.items()}

# Tick subscription mode — Quote gives us LTP + volume; Full adds OI
_FEED_MODE = MarketFeed.Quote


def _parse_ltp(raw: Any) -> Decimal:
    try:
        return Decimal(str(raw))
    except (InvalidOperation, TypeError):
        return Decimal("0")


def _parse_ltt(raw: Any) -> datetime:
    if isinstance(raw, datetime):
        return raw if raw.tzinfo else raw.replace(tzinfo=UTC)
    try:
        return datetime.fromisoformat(str(raw))
    except ValueError:
        return datetime.now(UTC)


class DhanTickerAdapter:
    """
    Bridges Dhan MarketFeed (blocking/threaded) into an asyncio Queue.

    The SDK's run_forever() runs in a ThreadPoolExecutor; on_message callbacks
    use call_soon_threadsafe to push decoded Tick objects into the async queue.
    """

    QUEUE_SIZE = 1000
    MAX_RECONNECT_DELAY = 30.0

    def __init__(self, client_id: str, access_token: str) -> None:
        self._ctx = DhanContext(client_id, access_token)
        self._queue: asyncio.Queue[Tick] = asyncio.Queue(maxsize=self.QUEUE_SIZE)
        # (security_id, exchange_segment) -> MarketFeed exchange code
        self._subs: dict[tuple[str, str], int] = {}
        self._loop: asyncio.AbstractEventLoop | None = None
        self._feed: MarketFeed | None = None
        self._connected = False
        self._stop_event = asyncio.Event()
        self._ws_task: asyncio.Task[None] | None = None
        self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="dhan-feed")

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    @property
    def queue(self) -> asyncio.Queue[Tick]:
        return self._queue

    async def start(self, session: AsyncSession) -> None:
        """Load persisted subscriptions and start the connection loop."""
        self._loop = asyncio.get_running_loop()
        await self._load_subscriptions(session)
        self._ws_task = asyncio.create_task(self._connection_loop(), name="dhan-ws-loop")
        log.info("dhan_adapter_started", subs=len(self._subs))

    async def stop(self) -> None:
        self._stop_event.set()
        if self._feed is not None:
            try:
                self._feed.close_connection()
            except Exception as exc:
                log.debug("dhan_close_error", exc=str(exc))
        self._executor.shutdown(wait=False)

    async def subscribe(self, security_id: str, segment: str, session: AsyncSession) -> bool:
        """Subscribe to a security and persist to the subscriptions table."""
        exch = _SEGMENT_TO_EXCH.get(segment)
        if exch is None:
            log.warning("dhan_subscribe_unknown_segment", segment=segment)
            return False
        key = (security_id, segment)
        if key in self._subs:
            return True
        self._subs[key] = exch
        await self._persist_subscription(security_id, segment, session)
        if self._feed is not None and self._connected:
            try:
                self._feed.subscribe_symbols([(exch, security_id, _FEED_MODE)])
            except Exception as exc:
                log.warning("dhan_subscribe_live_failed", exc=str(exc))
        log.info("dhan_subscribed", security_id=security_id, segment=segment)
        return True

    async def unsubscribe(self, security_id: str, segment: str, session: AsyncSession) -> None:
        key = (security_id, segment)
        exch = self._subs.pop(key, None)
        if exch is not None and self._feed is not None and self._connected:
            try:
                self._feed.unsubscribe_symbols([(exch, security_id, _FEED_MODE)])
            except Exception as exc:
                log.debug("dhan_unsub_error", exc=str(exc))
        await self._remove_subscription(security_id, segment, session)

    # ------------------------------------------------------------------ #
    # Connection loop (tasks 2.2 — exponential reconnect)                  #
    # ------------------------------------------------------------------ #

    async def _connection_loop(self) -> None:
        delay = 1.0
        while not self._stop_event.is_set():
            try:
                await self._run_feed()
                delay = 1.0  # reset on clean disconnect
            except asyncio.CancelledError:
                break
            except Exception as exc:
                log.warning("dhan_ws_error", exc=str(exc), retry_in=delay)
            if self._stop_event.is_set():
                break
            log.info("dhan_ws_reconnecting", delay=delay)
            await asyncio.sleep(delay)
            delay = min(delay * 2, self.MAX_RECONNECT_DELAY)

    async def _run_feed(self) -> None:
        """Spin up a MarketFeed in the thread pool; resolve when it disconnects."""
        instruments = [(exch, sid, _FEED_MODE) for (sid, _), exch in self._subs.items()]
        if not instruments:
            # No instruments yet — wait until a subscribe call arrives.
            # Use a longer idle sleep so the reconnect loop doesn't busy-spin.
            await asyncio.sleep(30)
            return

        loop = self._loop
        assert loop is not None

        feed = MarketFeed(
            self._ctx,
            instruments,
            version="v2",
            on_connect=lambda inst: loop.call_soon_threadsafe(self._on_connect, inst),
            on_message=lambda inst, msg: loop.call_soon_threadsafe(self._on_message, msg),
            on_close=lambda inst: loop.call_soon_threadsafe(self._on_close, inst),
            on_error=lambda inst, err: loop.call_soon_threadsafe(self._on_error, str(err)),
        )
        self._feed = feed

        fut: asyncio.Future[None] = loop.create_future()

        def _run() -> None:
            try:
                feed.run_forever()
            except Exception as exc:
                loop.call_soon_threadsafe(fut.set_exception, exc)
            else:
                loop.call_soon_threadsafe(lambda: fut.set_result(None) if not fut.done() else None)

        self._executor.submit(_run)
        await fut

    # ------------------------------------------------------------------ #
    # SDK callbacks (called from SDK thread, dispatched via call_soon_threadsafe)
    # ------------------------------------------------------------------ #

    def _on_connect(self, _inst: Any) -> None:
        self._connected = True
        log.info("dhan_ws_connected", instruments=len(self._subs))

    def _on_close(self, _inst: Any) -> None:
        self._connected = False
        log.info("dhan_ws_closed")

    def _on_error(self, err: str) -> None:
        self._connected = False
        log.warning("dhan_ws_error_cb", error=err)

    def _on_message(self, msg: dict[str, Any]) -> None:
        """Decode SDK message dict → Tick, push to queue (task 2.4)."""
        if not isinstance(msg, dict):
            return
        sid = str(msg.get("security_id", ""))
        if not sid:
            return
        exch_code = msg.get("exchange_segment")
        segment = _EXCH_TO_SEGMENT.get(int(exch_code), "") if exch_code is not None else ""
        ltp = _parse_ltp(msg.get("LTP", 0))
        ltt = _parse_ltt(msg.get("LTT"))
        volume = int(msg.get("volume", 0) or 0)
        oi = int(msg.get("OI", 0) or 0)
        tick = Tick(
            security_id=sid,
            exchange_segment=segment,
            ltp=ltp,
            ltt=ltt,
            volume=volume,
            oi=oi,
        )
        # Drop oldest if queue is full (task 2.4 + 3.3 backpressure)
        if self._queue.full():
            try:
                self._queue.get_nowait()
                log.warning("tick_dropped", security_id=sid)
            except asyncio.QueueEmpty:
                pass
        try:
            self._queue.put_nowait(tick)
        except asyncio.QueueFull:
            pass  # still full after one drop — skip

    # ------------------------------------------------------------------ #
    # DB helpers                                                           #
    # ------------------------------------------------------------------ #

    async def _load_subscriptions(self, session: AsyncSession) -> None:
        from pdp.market.subscription_model import Subscription

        result = await session.execute(select(Subscription))
        rows = result.scalars().all()
        for row in rows:
            exch = _SEGMENT_TO_EXCH.get(row.exchange_segment)
            if exch is not None:
                self._subs[(row.security_id, row.exchange_segment)] = exch
        log.info("dhan_subscriptions_loaded", count=len(self._subs))

    async def _persist_subscription(self, security_id: str, segment: str, session: AsyncSession) -> None:
        from pdp.market.subscription_model import Subscription

        stmt = pg_insert(Subscription).values(security_id=security_id, exchange_segment=segment)
        stmt = stmt.on_conflict_do_nothing(constraint="uq_subscriptions_secid_seg")
        await session.execute(stmt)
        await session.commit()

    async def _remove_subscription(self, security_id: str, segment: str, session: AsyncSession) -> None:
        from pdp.market.subscription_model import Subscription

        await session.execute(
            delete(Subscription).where(
                Subscription.security_id == security_id,
                Subscription.exchange_segment == segment,
            )
        )
        await session.commit()
