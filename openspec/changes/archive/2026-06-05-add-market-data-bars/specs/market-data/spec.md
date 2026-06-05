## MODIFIED Requirements

### Requirement: Bar aggregator

The system SHALL aggregate ticks into 1m, 5m, 15m, 30m, and 1H OHLCV bars per `(security_id, timeframe)` and emit a `BarClosed` event when each bar's boundary passes. Boundary SHALL be determined by wall-clock UTC truncation of `tick.ltt`; when `ltt` exceeds `ts_recv` by more than 2 seconds, `ts_recv` SHALL be used instead. Bar aggregation SHALL be performed synchronously in the asyncio event loop (no task spawning per tick).

#### Scenario: 5-minute bar closes

- **WHEN** ticks arrive for security 13 across the 09:15–09:20 IST window and a tick at 09:20:00 marks the close
- **THEN** a `BarClosed` event is emitted with `timeframe="5m"`, `bar_time="09:15:00"`, and OHLCV computed from the window's ticks

#### Scenario: Stale ltt fallback

- **WHEN** a tick arrives with `ltt` more than 2 seconds ahead of `ts_recv`
- **THEN** `ts_recv` is used for bar boundary determination

### Requirement: WebSocket fan-out

The system SHALL expose a `/ws/market` WebSocket endpoint accepting JSON messages `{"action":"subscribe"|"unsubscribe","security_ids":int[],"timeframes":string[]}` and pushing matching tick and bar-close events to the connecting client. Each client SHALL have a dedicated asyncio queue bounded at 50 messages; when full the oldest message SHALL be dropped and a `ws_client_lagging` log entry emitted with the client's remote address.

#### Scenario: Subscribe receives ticks

- **WHEN** a client connects and sends `{"action":"subscribe","security_ids":[13],"timeframes":["5m"]}`
- **THEN** the client receives every subsequent tick for security 13 as `{"type":"tick","security_id":13,"ltp":...,"ltt":...}` and every 5m bar close as `{"type":"bar","security_id":13,"timeframe":"5m","ohlcv":{...}}`

#### Scenario: Slow client gets dropped messages

- **WHEN** a subscribed client's pending queue exceeds 50 messages
- **THEN** the oldest message is dropped and a `ws_client_lagging` log entry is recorded with the client id
