"""Tests for WSHub publish, subscription filtering, and drop-oldest."""
from __future__ import annotations

import time
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from pdp.market.bars import BarClosed
from pdp.market.models import Tick
from pdp.market.ws import _CLIENT_QUEUE_SIZE, WSHub, _Client


class _FakeWS:
    """Minimal stand-in for FastAPI WebSocket used only for _Client construction."""

    class _ClientAddr:
        host = "127.0.0.1"
        port = 9999

    client = _ClientAddr()


def _make_client() -> _Client:
    return _Client(_FakeWS())  # type: ignore[arg-type]


def _tick(sid: str = "13") -> Tick:
    return Tick(
        security_id=sid,
        exchange_segment="NSE_EQ",
        ltp=Decimal("100.0"),
        ltt=datetime.now(UTC),
        volume=10,
        oi=0,
        ts_recv=time.monotonic(),
    )


def _bar(sid: str = "13", tf: str = "5m") -> BarClosed:
    return BarClosed(
        security_id=sid,
        timeframe=tf,
        bar_time=datetime.now(UTC),
        open=Decimal("100"),
        high=Decimal("105"),
        low=Decimal("99"),
        close=Decimal("103"),
        volume=500,
        oi=0,
    )


class TestWSHub:
    def test_publish_tick_delivers_to_subscribed_client(self) -> None:
        hub = WSHub()
        client = _make_client()
        client.security_ids = {"13"}
        hub._clients.add(client)

        hub.publish_tick(_tick("13"))
        assert client.queue.qsize() == 1

    def test_publish_tick_skips_unsubscribed_client(self) -> None:
        hub = WSHub()
        client = _make_client()
        client.security_ids = {"25"}
        hub._clients.add(client)

        hub.publish_tick(_tick("13"))
        assert client.queue.empty()

    def test_publish_bar_delivers_matching_timeframe(self) -> None:
        hub = WSHub()
        client = _make_client()
        client.security_ids = {"13"}
        client.timeframes = {"5m"}
        hub._clients.add(client)

        hub.publish_bar(_bar("13", "5m"))
        assert client.queue.qsize() == 1

    def test_publish_bar_skips_unmatched_timeframe(self) -> None:
        hub = WSHub()
        client = _make_client()
        client.security_ids = {"13"}
        client.timeframes = {"1m"}
        hub._clients.add(client)

        hub.publish_bar(_bar("13", "5m"))
        assert client.queue.empty()

    def test_drop_oldest_when_queue_full(self) -> None:
        hub = WSHub()
        client = _make_client()
        client.security_ids = {"13"}
        hub._clients.add(client)

        # Fill queue to max
        for _ in range(_CLIENT_QUEUE_SIZE):
            hub.publish_tick(_tick("13"))
        assert client.queue.full()

        # One more — should drop oldest, queue stays at max
        hub.publish_tick(_tick("13"))
        assert client.queue.qsize() == _CLIENT_QUEUE_SIZE

    @pytest.mark.asyncio
    async def test_no_clients_publish_is_noop(self) -> None:
        hub = WSHub()
        # Should not raise with no connected clients
        hub.publish_tick(_tick("13"))
        hub.publish_bar(_bar("13", "5m"))
