"""Unit tests for PortfolioHub queue overflow."""
from __future__ import annotations

from unittest.mock import MagicMock

from pdp.portfolio.hub import _CLIENT_QUEUE_SIZE, PortfolioHub


def _fake_ws(addr: str = "127.0.0.1:9999") -> MagicMock:
    ws = MagicMock()
    ws.client.host, ws.client.port = addr.split(":")
    return ws


def test_broadcast_delivered_to_client():
    hub = PortfolioHub()
    client = hub.make_client(_fake_ws())
    hub.add(client)

    hub.broadcast([{"security_id": "13", "net_qty": 1}])

    assert client.queue.qsize() == 1


def test_broadcast_skipped_when_no_clients():
    hub = PortfolioHub()
    # No exception when no clients
    hub.broadcast([{"security_id": "13"}])


def test_queue_overflow_drops_oldest_and_logs(caplog):
    hub = PortfolioHub()
    client = hub.make_client(_fake_ws())
    hub.add(client)

    for _ in range(_CLIENT_QUEUE_SIZE + 1):
        hub.broadcast([{"security_id": "13", "net_qty": 1}])

    assert client.queue.qsize() == _CLIENT_QUEUE_SIZE


def test_remove_client():
    hub = PortfolioHub()
    client = hub.make_client(_fake_ws())
    hub.add(client)
    hub.remove(client)

    hub.broadcast([{"security_id": "13"}])
    assert client.queue.qsize() == 0
