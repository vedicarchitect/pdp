### Requirement: OHLCV bar aggregation

The system SHALL aggregate incoming ticks per `(security_id, timeframe)` into OHLCV bars where `timeframe` is one of `1m`, `5m`, `15m`, `30m`, or `1H`. Each bar's boundary SHALL be determined by wall-clock UTC truncation of the tick's `ltt` field. A `BarClosed` event SHALL be emitted synchronously on boundary crossing so downstream consumers (MongoDB writer, Redis stream, WS hub) receive it within the same event-loop iteration.

#### Scenario: Bar opens on first tick

- **WHEN** the first tick for `(security_id="13", timeframe="5m")` arrives at `ltt=09:15:03`
- **THEN** a new bar is opened with `open=ltp`, `high=ltp`, `low=ltp`, `close=ltp`, `volume=tick.volume`, `bar_time=09:15:00`

#### Scenario: Bar accumulates ticks

- **WHEN** subsequent ticks arrive within the same 5-minute window
- **THEN** `high` is updated to `max(high, ltp)`, `low` to `min(low, ltp)`, `close` to `ltp`, `volume` incremented by each tick's `volume`

#### Scenario: Bar closes on boundary crossing

- **WHEN** a tick arrives at `ltt=09:20:00` for a bar that opened at `09:15:00` (5m timeframe)
- **THEN** a `BarClosed` event is emitted for the completed bar and a new bar opens for `09:20:00`

#### Scenario: Stale ltt protection

- **WHEN** a tick's `ltt` is more than 2 seconds ahead of `ts_recv`
- **THEN** `ts_recv` is used for boundary determination instead of `ltt`

### Requirement: Batched MongoDB bar persistence

The system SHALL persist closed bars to the `market_bars` MongoDB time-series collection via batched motor `insert_many` writes. The flush trigger SHALL be whichever occurs first: 1 second elapsed since last flush, or 500 documents accumulated. Each document SHALL have `ts` set to the bar's `bar_time` (UTC datetime), `metadata` set to `{"security_id": <str>, "timeframe": <str>}`, and OHLCV/OI fields at the top level. `insert_many` SHALL use `ordered=False` so duplicate bars are skipped without aborting the batch; any write errors SHALL be logged as warnings with the error count.

#### Scenario: Bar document written within 2 seconds

- **WHEN** a 5m bar closes for security 13 at 09:20:00 UTC
- **THEN** within 2 seconds a document with `ts=09:20:00`, `metadata.security_id="13"`, `metadata.timeframe="5m"` and matching OHLCV values exists in the `market_bars` collection

#### Scenario: Buffer overflow protection

- **WHEN** the unwritten bar buffer exceeds 10,000 documents (MongoDB unavailable)
- **THEN** the oldest documents are dropped and a `bar_writer_overflow` structured log is emitted

#### Scenario: Duplicate bar silently skipped

- **WHEN** `insert_many` is called with a batch containing a document whose `(ts, metadata)` already exists
- **THEN** the duplicate is skipped, the rest of the batch is written, and a warning is logged with the error count

### Requirement: Redis stream bar fan-out

The system SHALL push each closed bar to a Redis stream at key `bars.<security_id>.<tf>` using `XADD` with `MAXLEN ~= 1000`. Downstream consumers (strategy engine, backtest replayer) SHALL be able to read from any offset without missing bars that arrived while they were offline.

#### Scenario: Bar appears in Redis stream

- **WHEN** a 1m bar closes for security 25
- **THEN** a new entry exists in stream key `bars.25.1m` with fields `open`, `high`, `low`, `close`, `volume`, `oi`, `bar_time`

### Requirement: WebSocket market data endpoint

The system SHALL expose a `/ws/market` WebSocket endpoint. After connecting, a client SHALL send a JSON subscription message `{"action":"subscribe","security_ids":[...],"timeframes":["5m",...]}` to receive tick and bar events. Each client SHALL have a dedicated queue bounded at 50 messages; when full the oldest message SHALL be dropped and a `ws_client_lagging` log entry emitted.

#### Scenario: Client receives tick after subscribe

- **WHEN** a client connects and sends `{"action":"subscribe","security_ids":[13],"timeframes":["1m","5m"]}`
- **THEN** every subsequent tick for security 13 is delivered as `{"type":"tick","security_id":13,"ltp":...,"ltt":...}`

#### Scenario: Client receives bar close after subscribe

- **WHEN** a 5m bar closes for security 13 and a client is subscribed with `timeframes:["5m"]`
- **THEN** the client receives `{"type":"bar","security_id":13,"timeframe":"5m","bar_time":...,"open":...,"high":...,"low":...,"close":...,"volume":...}`

#### Scenario: Slow client drop-oldest

- **WHEN** a client's pending queue reaches 50 messages before they are consumed
- **THEN** the oldest queued message is discarded and `ws_client_lagging` is logged with the client's remote address

#### Scenario: Unsubscribe stops delivery

- **WHEN** a client sends `{"action":"unsubscribe","security_ids":[13],"timeframes":["5m"]}`
- **THEN** no further 5m bar events for security 13 are delivered to that client

### Requirement: Historical bars REST endpoint

The system SHALL expose `GET /api/v1/bars/{security_id}?tf=<timeframe>&limit=<n>` returning the `n` most-recent closed bars for the given security and timeframe from the `market_bars` MongoDB collection, ordered by `ts` descending. `limit` SHALL default to 375 and be capped at 2000. The response shape SHALL be identical across storage backends.

#### Scenario: Returns recent bars in order

- **WHEN** `GET /api/v1/bars/13?tf=5m&limit=10` is called and at least 10 documents exist in MongoDB
- **THEN** the response is HTTP 200 with a JSON array of exactly 10 bars ordered newest-first

#### Scenario: Returns empty array when no data

- **WHEN** `GET /api/v1/bars/99999?tf=5m` is called and no bars exist for that security
- **THEN** the response is HTTP 200 with an empty JSON array `[]`

#### Scenario: Invalid timeframe rejected

- **WHEN** `GET /api/v1/bars/13?tf=7m` is called
- **THEN** the response is HTTP 422 with a validation error listing valid timeframes

### Requirement: Tick-to-WebSocket latency budget

The system SHALL achieve a tick-to-WebSocket-out p99 latency of 50ms or less when serving up to 200 simultaneous WebSocket subscribers on a single instrument at full Dhan tick rate.

#### Scenario: Locust load test passes

- **WHEN** `locust -f loadtest/locustfile.py --users 200 --spawn-rate 20` is run against a running instance
- **THEN** the p99 of `(client_receive_ts - tick_server_ts)` across all clients is ≤ 50ms
