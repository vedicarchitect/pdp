## 1. Schema

- [x] 1.1 Alembic migration `0003_market_bars.py` — `market_bars(security_id, timeframe, bar_time, open, high, low, close, volume, oi)` hypertable on `bar_time`, compress after 7 days, drop chunks after 2 years

## 2. Bar Aggregator

- [x] 2.1 `src/pdp/market/bars.py` — `BarBuilder(security_id, timeframe)` with `push(tick) -> BarClosed | None`; stale-ltt protection (`ts_recv` fallback when `ltt > ts_recv + 2s`)
- [x] 2.2 `BarAggregator` class holding `dict[(security_id, timeframe), BarBuilder]`; creates builders on first tick; returns list of `BarClosed` events per `push(tick)` call
- [x] 2.3 `BarClosed` dataclass with `security_id`, `timeframe`, `bar_time`, `open`, `high`, `low`, `close`, `volume`, `oi`

## 3. TimescaleDB Bar Writer

- [x] 3.1 `src/pdp/market/bar_writer.py` — `BarWriter` class with `enqueue(bar_closed)` and background `_flush_loop` task
- [x] 3.2 Flush trigger: 1-second timer OR 500-row buffer (whichever first) via `asyncpg.copy_records_to_table`
- [x] 3.3 Buffer overflow guard: drop oldest when buffer exceeds 10,000 rows; emit `bar_writer_overflow` structured log
- [x] 3.4 SQLAlchemy ORM model `MarketBar` mapped to `market_bars`; add import to `alembic/env.py`

## 4. Redis Stream Fan-out

- [x] 4.1 In `TickRouter._handle`: after `BarAggregator.push(tick)` collect closed bars; for each, `XADD bars.<security_id>.<tf> MAXLEN ~ 1000 * <fields>`
- [x] 4.2 Wire `BarAggregator` and `BarWriter` instances into `TickRouter` (constructor injection)

## 5. WebSocket Hub

- [x] 5.1 `src/pdp/market/ws.py` — `WSHub` class managing connected clients; per-client `asyncio.Queue(maxsize=50)` with drop-oldest on overflow + `ws_client_lagging` log
- [x] 5.2 `/ws/market` FastAPI WebSocket endpoint; handle `subscribe`/`unsubscribe` JSON messages; pump client queue to WebSocket
- [x] 5.3 `WSHub.publish_tick(tick)` and `WSHub.publish_bar(bar_closed)` called from `TickRouter._handle`
- [x] 5.4 Register `/ws/market` route in `src/pdp/main.py` lifespan; pass `WSHub` instance to `TickRouter`

## 6. REST Endpoint

- [x] 6.1 `GET /api/v1/bars/{security_id}` with query params `tf` (enum: 1m/5m/15m/30m/1H, required) and `limit` (int, default=375, max=2000)
- [x] 6.2 Query `market_bars` via SQLAlchemy async; return JSON array ordered by `bar_time` DESC

## 7. Tests

- [x] 7.1 `tests/market/test_bar_builder.py` — unit tests: first tick opens bar; accumulation updates OHLCV; boundary crossing emits `BarClosed` and opens new bar; stale-ltt fallback uses `ts_recv`
- [x] 7.2 `tests/market/test_bar_integration.py` — integration: inject fake tick sequence into `BarAggregator`; verify `BarClosed` events emitted correctly
- [x] 7.3 `tests/market/test_ws.py` — `WSHub.publish_tick` delivers to subscribed client queue; drop-oldest fires when queue full

## 8. Load Test

- [x] 8.1 `loadtest/locustfile.py` — `MarketUser` task connecting to `/ws/market`, subscribing to one security, recording `(recv_ts - server_ts)` per message
- [x] 8.2 `loadtest/README.md` — how to run, how to read p99, pass/fail criterion (≤ 50ms)

## 9. Validation

- [x] 9.1 `openspec validate --strict add-market-data-bars`
- [x] 9.2 Run full test suite: `uv run pytest -x`
- [x] 9.3 Manual smoke: start server, connect to `/ws/market`, subscribe to NIFTY index, observe ticks and bar events (market hours only)
