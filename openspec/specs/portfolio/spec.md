## Requirement: Real-time mark-to-market P&L

The system SHALL maintain an in-memory position cache loaded from the PG `positions` table on startup. For each open position (net_qty ≠ 0) the system SHALL subscribe to the Redis `tick.<security_id>` pub/sub channel and recompute `unrealized_pnl = net_qty × (ltp − avg_price)` on every tick. The system SHALL flush updated `unrealized_pnl` values back to the PG `positions` table at most every `PORTFOLIO_MTM_INTERVAL_SECONDS` seconds (default 5) via a batched UPDATE. When a Redis `ltp:<security_id>` key is absent (no recent tick) the system SHALL retain the last known `unrealized_pnl` and mark the position as `ltp_stale: true` in WebSocket pushes.

#### Scenario: MTM updates on tick arrival

- **WHEN** the system holds an open position in security `13` and a `tick.13` Redis message arrives with `ltp=22500`
- **THEN** `unrealized_pnl` is recomputed in-memory within 50 ms and pushed to all connected `/ws/portfolio` clients

#### Scenario: Flush writes to PG

- **WHEN** `PORTFOLIO_MTM_INTERVAL_SECONDS` seconds have elapsed since the last flush and at least one position is dirty
- **THEN** a single batched UPDATE writes the current `unrealized_pnl` for all dirty positions to the `positions` table

#### Scenario: Fill-driven cache refresh

- **WHEN** the `OrdersHub` publishes a `position` event (new fill processed by paper or Dhan broker)
- **THEN** the in-memory cache entry for that `(security_id, exchange_segment, product)` is refreshed from PG and the service subscribes to the tick channel for that security if not already subscribed

#### Scenario: LTP stale flag on missing key

- **WHEN** the Redis `ltp:<security_id>` key has expired (no tick for > 5 seconds)
- **THEN** WebSocket push for that position includes `"ltp_stale": true` and REST response includes the last known `unrealized_pnl`

## Requirement: Portfolio REST endpoints

The system SHALL expose:
- `GET /api/v1/portfolio/positions` — returns all positions from PG (with the latest `unrealized_pnl`).
- `GET /api/v1/portfolio/summary` — returns `{"total_unrealized_pnl": float, "total_realized_pnl": float, "day_pnl": float, "open_positions": int, "mode": "paper|live"}`.

Both endpoints SHALL return HTTP 200 with an empty positions array if no positions exist. Both endpoints SHALL read from the PG `positions` table (not the in-memory cache) for consistency. Mode filtering is not supported as the `positions` table has no `mode` column; the `mode` field in the summary response is derived from the `LIVE` setting.

`realized_pnl` values returned by these endpoints SHALL reflect the corrected short-position accounting: for any position closed from a multi-leg short, `realized_pnl` SHALL equal `(correct_weighted_avg - close_price) * closed_qty` with no sign inversion.

#### Scenario: Positions endpoint returns open positions

- **WHEN** `GET /api/v1/portfolio/positions` is called and two open positions exist
- **THEN** HTTP 200 is returned with a JSON array containing both positions including `unrealized_pnl`, `realized_pnl`, `avg_price`, `net_qty`, and `updated_at`

#### Scenario: Summary endpoint

- **WHEN** `GET /api/v1/portfolio/summary` is called and positions have total unrealized P&L of ₹5000 and realized P&L of ₹1200
- **THEN** HTTP 200 is returned with `{"total_unrealized_pnl": 5000.0, "total_realized_pnl": 1200.0, "day_pnl": 6200.0, "open_positions": 2, "mode": "paper"}`

#### Scenario: Empty portfolio

- **WHEN** `GET /api/v1/portfolio/positions` is called and no positions exist
- **THEN** HTTP 200 is returned with `{"positions": [], "count": 0}`

#### Scenario: Short close realized P&L is correct

- **WHEN** a 4-leg short (total 325 units, weighted avg ≈ 85.30) is closed by BUY 325 @ 96.52
- **THEN** `GET /api/v1/portfolio/summary` returns `total_realized_pnl ≈ -3645` (not +37256 or any sign-inverted value)

## Requirement: Portfolio WebSocket endpoint

The system SHALL expose `/ws/portfolio`. After connecting, the server SHALL immediately push a full snapshot of all open positions. On each MTM update (tick-driven unrealized_pnl change) the server SHALL push the updated positions payload. Each client SHALL have a bounded asyncio queue of 20 messages; when full the oldest message SHALL be dropped and `portfolio_client_lagging` SHALL be logged.

#### Scenario: Client receives initial snapshot on connect

- **WHEN** a client connects to `/ws/portfolio`
- **THEN** within 1 second the client receives a full positions snapshot matching the current state of the `positions` table

#### Scenario: Client receives MTM update on tick

- **WHEN** a tick arrives for a held security and `unrealized_pnl` changes
- **THEN** all connected `/ws/portfolio` clients receive the updated positions payload within 50 ms

#### Scenario: Slow client drop-oldest

- **WHEN** a client's pending queue reaches 20 messages before they are consumed
- **THEN** the oldest queued message is dropped and `portfolio_client_lagging` is logged

## Requirement: EOD portfolio snapshot to MongoDB

If `PORTFOLIO_EOD_SNAPSHOT=true` (default), the system SHALL write one document to the MongoDB `portfolio_snapshots` collection at 15:36 IST each trading day containing: `snapshot_date` (ISO date str), `snapshot_ts` (UTC datetime), `mode` (str), `positions` (array), and `summary` object. The collection SHALL have a TTL index on `snapshot_ts` of 90 days and a unique index on `snapshot_date`.

#### Scenario: EOD snapshot written at market close

- **WHEN** the system is running and IST time reaches 15:36
- **THEN** a `portfolio_snapshots` document is written for the current date with all position fields

#### Scenario: EOD snapshot skipped when disabled

- **WHEN** `PORTFOLIO_EOD_SNAPSHOT=false`
- **THEN** no document is written to `portfolio_snapshots` at market close
