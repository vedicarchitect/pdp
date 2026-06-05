# Market Data WS Load Test

Measures tick-to-WebSocket-out p99 latency under 200 simultaneous subscribers.

## Prerequisites

```bash
pip install locust websocket-client
docker compose up -d          # Timescale + Redis
uv run pdp                    # Start the server (in another terminal)
```

Subscribe at least one instrument so ticks flow:

```bash
curl -X POST "http://localhost:8000/api/v1/subscriptions?security_id=13&exchange_segment=IDX_I"
```

(Requires `DHAN_CLIENT_ID` and `DHAN_ACCESS_TOKEN` in `.env`.)

## Running the test

```bash
locust -f loadtest/locustfile.py \
       --users 200 \
       --spawn-rate 20 \
       --headless \
       --run-time 120s \
       --host ws://localhost:8000 \
       --csv=loadtest/results/run_$(date +%Y%m%d_%H%M%S)
```

Override the target security:

```bash
SECURITY_ID=13 locust -f loadtest/locustfile.py ...
```

## Reading results

After the run, Locust prints a summary table. The relevant row is `WS tick_latency:tick`.

| Metric | Column | Pass criterion |
|--------|--------|----------------|
| p99 latency | `99%ile (ms)` | **≤ 50 ms** |
| p95 latency | `95%ile (ms)` | ≤ 30 ms (informational) |

CSV columns of interest in `*_stats.csv`:
- `Name`: `WS tick_latency:tick`
- `99%`: p99 in milliseconds

## How latency is measured

Each message emitted by the server carries a `"ts"` field (Unix epoch seconds, `time.time()`).
The Locust user records `recv_ts = time.time()` immediately on receiving the raw frame.

```
latency_ms = (recv_ts - msg["ts"]) * 1000
```

This measures the full path: BarAggregator push → WSHub.publish_tick → queue → asyncio pump → TCP send → client recv. Clock skew between server and client process is zero (same host in test environment).

## Pass/fail

The spec requirement (`Requirement: Tick-to-WebSocket latency budget`) passes when:

```
p99(tick_latency:tick) ≤ 50 ms
```

at 200 concurrent users during a 120-second sustained run.
