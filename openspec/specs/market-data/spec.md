### Requirement: Dhan ticker WebSocket adapter

The system SHALL maintain a single persistent WebSocket connection to Dhan's market-feed service, decoding binary tick frames into typed `Tick` records and pushing them into an internal asyncio queue.

#### Scenario: Connection establishes

- **WHEN** the app starts with valid `DHAN_CLIENT_ID` and `DHAN_ACCESS_TOKEN` env vars
- **THEN** the adapter establishes a WS connection and emits a `dhan_ws_connected` structured log
- **AND** subscribes to any instruments listed in the `subscriptions` table

#### Scenario: Reconnect on disconnect

- **WHEN** the Dhan WS connection drops
- **THEN** the adapter retries with exponential backoff (1s, 2s, 4s, … capped at 30s) and re-subscribes to all persisted instruments on success

### Requirement: Redis hot LTP cache

The system SHALL store the latest LTP per security in Redis at key `ltp:<security_id>` with a 5-second TTL, refreshed on every tick.

#### Scenario: LTP key set on tick

- **WHEN** a tick arrives for security 13 with LTP 24500.50
- **THEN** Redis key `ltp:13` equals `24500.50` with TTL ≤ 5s

### Requirement: Bar aggregator

The system SHALL aggregate ticks into 1m, 5m, 15m, 30m, and 1H OHLCV bars per `(security_id, timeframe)` and emit a `BarClosed` event when each bar's boundary passes. Boundary SHALL be determined by wall-clock UTC truncation of `tick.ltt`; when `ltt` exceeds `ts_recv` by more than 2 seconds, `ts_recv` SHALL be used instead. Bar aggregation SHALL be performed synchronously in the asyncio event loop (no task spawning per tick).

#### Scenario: 5-minute bar closes

- **WHEN** ticks arrive for security 13 across the 09:15–09:20 IST window and a tick at 09:20:00 marks the close
- **THEN** a `BarClosed` event is emitted with `timeframe="5m"`, `bar_time="09:15:00"`, and OHLCV computed from the window's ticks

#### Scenario: Stale ltt fallback

- **WHEN** a tick arrives with `ltt` more than 2 seconds ahead of `ts_recv`
- **THEN** `ts_recv` is used for bar boundary determination

### Requirement: Bar persistence to TimescaleDB

The system SHALL persist closed bars to the `market_bars` hypertable via batched writes (flush every 1 second or 500-row buffer, whichever first).

#### Scenario: Closed bar persisted

- **WHEN** a 5m bar closes for security 13
- **THEN** within 2 seconds a row exists in `market_bars` with matching `(security_id, timeframe, bar_time)` and OHLCV values

### Requirement: WebSocket fan-out

The system SHALL expose a `/ws/market` WebSocket endpoint accepting JSON messages `{"action":"subscribe"|"unsubscribe","security_ids":int[],"timeframes":string[]}` and pushing matching tick and bar-close events to the connecting client. Each client SHALL have a dedicated asyncio queue bounded at 50 messages; when full the oldest message SHALL be dropped and a `ws_client_lagging` log entry emitted with the client's remote address.

#### Scenario: Subscribe receives ticks

- **WHEN** a client connects and sends `{"action":"subscribe","security_ids":[13],"timeframes":["5m"]}`
- **THEN** the client receives every subsequent tick for security 13 as `{"type":"tick","security_id":13,"ltp":...,"ltt":...}` and every 5m bar close as `{"type":"bar","security_id":13,"timeframe":"5m","ohlcv":{...}}`

#### Scenario: Slow client gets dropped messages

- **WHEN** a subscribed client's pending queue exceeds 50 messages
- **THEN** the oldest message is dropped and a `ws_client_lagging` log entry is recorded with the client id

### Requirement: REST snapshot endpoints

The system SHALL expose `GET /api/v1/ltp?ids=<csv>` returning current LTPs from Redis, and `GET /api/v1/bars/{security_id}?tf=<timeframe>&limit=<n>` returning the most recent N bars from TimescaleDB.

#### Scenario: LTP returns latest

- **WHEN** `GET /api/v1/ltp?ids=13,25` is called with both IDs cached
- **THEN** the response is HTTP 200 with `{"13": 24500.5, "25": 51200.0}`

#### Scenario: Bars returns ordered history

- **WHEN** `GET /api/v1/bars/13?tf=5m&limit=10` is called
- **THEN** the response is HTTP 200 with a JSON array of 10 most-recent 5m bars ordered by `bar_time` descending

### Requirement: Latency budget

The system SHALL achieve a tick-to-WebSocket-out p99 latency of 50ms or less when serving up to 200 simultaneous subscribers under a single instrument's tick rate.

#### Scenario: Load test passes budget

- **WHEN** the `locust` load script is run with 200 simulated subscribers
- **THEN** the recorded p99 of `(client_receive_ts - tick.publish_ts)` is ≤ 50ms
