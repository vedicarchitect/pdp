"""Order command channel (api-worker-decoupling): roundtrip, idempotency, 503-when-engine-down.

Uses a minimal in-memory fake Redis (strings + streams) rather than a real Redis server —
mirrors the ``_FakeRedis`` pattern already used in tests/strategy/test_context.py.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from pdp.orders.command_channel import CommandConsumer, CommandProducer, OrderCommand
from pdp.orders.models import OrderType, Product, Side
from pdp.orders.schemas import OrderRequest


class _FakeRedis:
    """Just enough Redis (strings + streams) for CommandProducer/CommandConsumer."""

    def __init__(self) -> None:
        self._kv: dict[str, bytes] = {}
        self._streams: dict[str, list[tuple[str, dict[str, str]]]] = {}
        self._group_cursor: dict[tuple[str, str], int] = {}
        self._seq = 0

    async def get(self, key: str):
        return self._kv.get(key)

    async def set(self, key: str, value, ex=None, nx: bool = False):
        if nx and key in self._kv:
            return None
        self._kv[key] = value if isinstance(value, bytes) else str(value).encode()
        return True

    async def delete(self, key: str) -> None:
        self._kv.pop(key, None)

    async def xadd(self, stream: str, fields: dict) -> str:
        self._seq += 1
        msg_id = f"{self._seq}-0"
        self._streams.setdefault(stream, []).append((msg_id, {k: str(v) for k, v in fields.items()}))
        return msg_id

    async def xgroup_create(self, stream: str, group: str, id: str = "0", mkstream: bool = True) -> None:
        self._streams.setdefault(stream, [])
        self._group_cursor.setdefault((stream, group), 0)

    async def xreadgroup(self, group: str, consumer: str, streams: dict, count: int = 10, block: int = 1000):
        ((stream, _marker),) = streams.items()
        entries = self._streams.get(stream, [])
        start = self._group_cursor.get((stream, group), 0)
        pending = entries[start : start + count]
        if not pending:
            await asyncio.sleep(0)
            return []
        self._group_cursor[(stream, group)] = start + len(pending)
        return [(stream, [(mid, {k.encode(): v.encode() for k, v in data.items()}) for mid, data in pending])]

    async def xack(self, stream: str, group: str, msg_id: str) -> None:
        return None

    async def xrevrange(self, stream: str, min: str = "-", max: str = "+", count: int | None = None):
        entries = self._streams.get(stream, [])
        reversed_entries = list(reversed(entries))
        if count is not None:
            reversed_entries = reversed_entries[:count]
        return [(mid, {k.encode(): v.encode() for k, v in data.items()}) for mid, data in reversed_entries]

    async def xread(self, streams: dict, count: int = 100, block: int = 500):
        ((stream, last_id),) = streams.items()
        entries = self._streams.get(stream, [])
        if last_id == "$":
            await asyncio.sleep(0)
            return []
        idx = next((i for i, (mid, _data) in enumerate(entries) if mid == last_id), -1)
        pending = entries[idx + 1 :]
        if not pending:
            await asyncio.sleep(0)
            return []
        return [(stream, [(mid, {k.encode(): v.encode() for k, v in data.items()}) for mid, data in pending])]


class _FakeSession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False


class _FakeRouter:
    def __init__(self, order_id: int = 1) -> None:
        self.calls: list[OrderRequest] = []
        self._order_id = order_id

    async def place_order(self, order: OrderRequest, session) -> int:
        self.calls.append(order)
        return self._order_id


def _order() -> OrderRequest:
    return OrderRequest(
        security_id="1333",
        exchange_segment="NSE_FNO",
        side=Side.BUY,
        qty=25,
        order_type=OrderType.MARKET,
        price=None,
        product=Product.INTRADAY,
    )


def _cmd(cmd_id: str) -> OrderCommand:
    return OrderCommand(
        cmd_id=cmd_id, kind="place", order=_order(), requester="test", ts=datetime.now(tz=UTC)
    )


@pytest.mark.asyncio
async def test_command_roundtrip_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """API enqueues a command; the engine consumes it, places it once; API gets the ack."""
    monkeypatch.setattr("pdp.db.session.get_session_maker", lambda: (lambda: _FakeSession()))

    redis = _FakeRedis()
    await redis.set("engine:status", b"ready")
    router = _FakeRouter(order_id=42)
    consumer = CommandConsumer(redis, router, group_name="engine", consumer_name="engine-1")
    producer = CommandProducer(redis, timeout=2.0)

    await consumer.start()
    try:
        result = await producer.execute(_cmd("cmd-roundtrip"))
    finally:
        await consumer.stop()

    assert result.status == "placed"
    assert result.order_id == 42
    assert len(router.calls) == 1


@pytest.mark.asyncio
async def test_command_idempotent_on_redelivery(monkeypatch: pytest.MonkeyPatch) -> None:
    """A command re-delivered with the same cmd_id (e.g. engine restart before ack) is
    processed at most once — SETNX on cmd:done:<cmd_id> guards it."""
    monkeypatch.setattr("pdp.db.session.get_session_maker", lambda: (lambda: _FakeSession()))

    redis = _FakeRedis()
    router = _FakeRouter(order_id=7)
    consumer = CommandConsumer(redis, router, group_name="engine", consumer_name="engine-1")

    cmd = _cmd("cmd-dup")
    await redis.xadd("orders.commands", {"data": cmd.model_dump_json()})
    await redis.xadd("orders.commands", {"data": cmd.model_dump_json()})  # re-delivered

    await consumer.start()
    try:
        for _ in range(50):
            await asyncio.sleep(0.005)
            if len(router.calls) >= 1:
                break
    finally:
        await consumer.stop()

    assert len(router.calls) == 1, "duplicate cmd_id must not place a second order"


@pytest.mark.asyncio
async def test_order_rejected_when_engine_down() -> None:
    """No engine consuming the stream (engine:status never set to 'ready') → producer
    returns a rejected result rather than hanging or silently dropping the order."""
    redis = _FakeRedis()
    producer = CommandProducer(redis, timeout=1.0)

    result = await producer.execute(_cmd("cmd-no-engine"))

    assert result.status == "rejected"
    assert "engine unavailable" in (result.detail or "")
