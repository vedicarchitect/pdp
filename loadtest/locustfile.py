"""
Locust load test: 200 WS subscribers, measure tick-to-client p99 latency.

Usage:
    pip install locust websocket-client
    locust -f loadtest/locustfile.py --users 200 --spawn-rate 20 --headless \
           --run-time 120s --host ws://localhost:8000

Each user:
  1. Connects to /ws/market
  2. Subscribes to NIFTY index (security_id configurable via SECURITY_ID env var)
  3. Receives messages and records round-trip latency (server_ts → client recv_ts)
  4. Reports p99 via Locust's response_time metric
"""
from __future__ import annotations

import json
import os
import time

import websocket
from locust import User, between, events, task
from locust.exception import StopUser

_HOST = os.getenv("WS_HOST", "ws://localhost:8000")
_SECURITY_ID = os.getenv("SECURITY_ID", "13")  # Override with your NIFTY security_id
_SUBSCRIBE_MSG = json.dumps(
    {
        "action": "subscribe",
        "security_ids": [_SECURITY_ID],
        "timeframes": ["1m", "5m"],
    }
)


class MarketWSUser(User):
    """
    Simulates a single WebSocket subscriber to /ws/market.

    Records the latency from server timestamp (embedded in the message)
    to client receive time using Locust's request_success / request_failure hooks.
    """

    wait_time = between(0, 0)  # no pause between receives — keep reading

    def on_start(self) -> None:
        url = f"{_HOST}/ws/market"
        try:
            self.ws = websocket.create_connection(url, timeout=10)
            self.ws.send(_SUBSCRIBE_MSG)
        except Exception as exc:
            events.request.fire(
                request_type="WS",
                name="connect",
                response_time=0,
                response_length=0,
                exception=exc,
                context=self.context(),
            )
            raise StopUser from exc

    def on_stop(self) -> None:
        try:
            self.ws.close()
        except Exception:
            pass

    @task
    def receive_message(self) -> None:
        recv_ts = time.time()
        try:
            raw = self.ws.recv()
        except Exception as exc:
            events.request.fire(
                request_type="WS",
                name="recv",
                response_time=0,
                response_length=0,
                exception=exc,
                context=self.context(),
            )
            raise StopUser from exc

        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            return

        server_ts = msg.get("ts")
        if server_ts is not None:
            latency_ms = (recv_ts - float(server_ts)) * 1000
            events.request.fire(
                request_type="WS",
                name=f"tick_latency:{msg.get('type','?')}",
                response_time=latency_ms,
                response_length=len(raw),
                exception=None,
                context=self.context(),
            )
