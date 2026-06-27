"""Unit tests for OptionsHub queue overflow (ws_options_client_lagging)."""
from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

from pdp.options.hub import _CLIENT_QUEUE_SIZE, OptionsHub


def _fake_ws(addr: str = "127.0.0.1:9999") -> MagicMock:
    ws = MagicMock()
    ws.client.host, ws.client.port = addr.split(":")
    return ws


def test_broadcast_delivered_to_matching_client():
    hub = OptionsHub()
    ws = _fake_ws()
    client = hub.make_client(ws, "NIFTY", "2026-06-26")
    hub.add(client)

    snapshot = {"underlying": "NIFTY", "expiry": "2026-06-26", "snapshot_ts": datetime(2026, 6, 6, 9, 30, tzinfo=UTC), "strikes": []}
    hub.broadcast("NIFTY", "2026-06-26", snapshot)

    assert client.queue.qsize() == 1


def test_broadcast_not_delivered_to_other_expiry():
    hub = OptionsHub()
    client = hub.make_client(_fake_ws(), "NIFTY", "2026-07-03")
    hub.add(client)

    hub.broadcast("NIFTY", "2026-06-26", {"underlying": "NIFTY", "expiry": "2026-06-26", "strikes": []})
    assert client.queue.qsize() == 0


def test_queue_overflow_drops_oldest_and_logs(caplog):
    hub = OptionsHub()
    client = hub.make_client(_fake_ws(), "NIFTY", "2026-06-26")
    hub.add(client)

    # Fill queue to capacity + 1 extra
    for _ in range(_CLIENT_QUEUE_SIZE + 1):
        hub.broadcast("NIFTY", "2026-06-26", {"underlying": "NIFTY", "expiry": "2026-06-26", "strikes": []})

    # Queue should still be at capacity (oldest dropped)
    assert client.queue.qsize() == _CLIENT_QUEUE_SIZE
