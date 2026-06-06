## Context

The PG `positions` table (migration 0005) has `net_qty`, `avg_price`, `realized_pnl`, `unrealized_pnl`, `updated_at`. The paper and Dhan brokers both write to this table via `upsert_position()` in `src/pdp/orders/paper.py`, but always store `unrealized_pnl = 0`.

Redis is already running and the market router (`src/pdp/market/router.py:67`) writes `ltp:<security_id>` string keys with a 5-second TTL, and publishes `PUBLISH tick.<security_id>` JSON payloads on every tick. The `OrdersHub` publishes `position` events on fills.

MongoDB `motor` client is available on `app.state.mongo_db` from Phase 2.

## Goals / Non-Goals

**Goals:**
- Compute and maintain accurate `unrealized_pnl` for all open positions in real time.
- Expose portfolio state via REST and WebSocket without blocking the tick hot path.
- Persist an EOD snapshot to MongoDB for historical review.
- Work in both paper and live modes (paper fills write to PG too).

**Non-Goals:**
- Holdings (equity demat) — out of scope; positions table covers F&O only.
- Margin/risk computation — that is `add-intraday-monitor`.
- Strategy signal generation — that is `add-strategy-host`.
- Historical P&L charting — snapshots are a starting point, UI is out of scope.

## Decisions

### Decision 1: In-memory position cache driven by Redis pub/sub

**Choice:** `PortfolioService` loads all open positions (net_qty ≠ 0) from PG on startup into an in-memory `dict[str, PositionState]` keyed by `(security_id, exchange_segment, product)`. It then subscribes to Redis `tick.<security_id>` channels only for the securities it holds. On each tick it recomputes `unrealized_pnl = Decimal(net_qty) * (ltp - avg_price)` in-process and pushes the update to `PortfolioHub` clients.

**Why:** Writing `unrealized_pnl` back to PG on every tick (potentially 100+ ticks/s across many instruments) would saturate the PG write path. In-memory computation keeps the hot path in Python and avoids DB round-trips per tick.

**Alternative considered:** Poll PG positions + Redis GET on each REST call. Rejected: too slow for WebSocket clients who need sub-second updates.

### Decision 2: Periodic flush to PG (not per-tick writes)

**Choice:** A configurable `PORTFOLIO_MTM_INTERVAL_SECONDS` (default 5) timer writes the current in-memory `unrealized_pnl` for all dirty positions back to PG in a single batched `UPDATE`. Positions are marked dirty on each MTM change.

**Why:** REST reads of `/api/v1/portfolio/positions` hit PG (consistent with the existing pattern used by `/api/v1/orders`). Writing only on the flush interval keeps PG writes to at most 1 batch per 5 seconds regardless of tick rate. WebSocket clients see every tick-level update via the hub.

**Alternative considered:** REST reads directly from in-memory cache. Rejected: introduces a second code path that diverges from PG truth; makes debugging harder.

### Decision 3: Fill-driven cache refresh via OrdersHub

**Choice:** `PortfolioService` subscribes to `position` events from `OrdersHub` (already published on every fill). On a position event the in-memory cache entry is replaced with the fresh PG values and the service re-subscribes to the new security's tick channel if not already subscribed.

**Why:** Avoids polling PG for position changes. The OrdersHub already broadcasts position dicts on fills.

### Decision 4: EOD snapshot to MongoDB

**Choice:** At 15:36 IST (one minute after market close) the service writes one document to `portfolio_snapshots`:
```json
{
  "snapshot_date": "2026-06-06",
  "snapshot_ts": "<UTC datetime>",
  "mode": "paper|live",
  "positions": [ ... ],
  "summary": { "total_unrealized_pnl": ..., "total_realized_pnl": ..., "day_pnl": ... }
}
```
Controlled by `PORTFOLIO_EOD_SNAPSHOT` (bool, default `true`).

**Why:** Provides a historical record for backtesting and performance review without requiring PG queries across many rows.

### Decision 5: PortfolioHub mirrors OptionsHub pattern

**Choice:** `PortfolioHub` holds a set of `_PortfolioClient` objects each with a bounded asyncio queue (size 20). `broadcast()` serialises the positions payload and enqueues to all connected clients. Drop-oldest on overflow with `portfolio_client_lagging` log.

**Why:** Proven pattern from `OptionsHub`. Keeps WebSocket push off the tick path.

## Risks / Trade-offs

- **In-memory cache diverges from PG if service restarts mid-session** → On restart, reload from PG. Any ticks during downtime are missed but PG `avg_price`/`net_qty` are correct from fills; only `unrealized_pnl` needs refresh from LTP.
- **Redis `ltp:<sid>` key expires after 5s** → If the key is missing (market closed, no ticks), `unrealized_pnl` is not updated but the stale in-memory value is retained and labelled with `ltp_stale: true` in the WS push. REST reads return the last known value.
- **Position subscription drift** → If a position goes flat (net_qty = 0) the service unsubscribes from that tick channel to avoid processing irrelevant ticks.
- **Paper + live positions coexist** → The `positions` table has no `mode` column; mode is derived from the `LIVE` setting for the summary response. Per-position mode tracking would require a schema change deferred to a future change.

## Migration Plan

No schema changes required. The flush writes via SQLAlchemy `UPDATE` on existing `positions` rows. The `portfolio_snapshots` MongoDB collection is created in `init_collections()` with a 90-day TTL on `snapshot_ts`.

Rollback: remove the `portfolio` package and its wiring in `main.py` — no data is deleted.

## Open Questions

- Lot-size for margin computation (future `add-intraday-monitor` concern — not solved here).
- Multi-account support — current schema has no `account_id` column; single-account assumed.
