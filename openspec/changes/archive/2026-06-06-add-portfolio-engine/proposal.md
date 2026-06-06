## Why

The `positions` table (migration 0005) already stores fills from both the paper and Dhan brokers, but `unrealized_pnl` is always written as 0 — no mark-to-market computation exists anywhere in the codebase. There is no REST endpoint for position state and no way for a strategy or UI to subscribe to live P&L updates.

## What Changes

- New `PortfolioService` background task that maintains an in-memory position cache, subscribes to Redis `tick.<sid>` pub/sub for held securities, and recomputes unrealised P&L on each tick.
- Periodic flush writes updated `unrealized_pnl` back to the PG `positions` table (no new table needed).
- EOD snapshot persisted to MongoDB `portfolio_snapshots` collection at market close.
- REST: `GET /api/v1/portfolio/positions` and `GET /api/v1/portfolio/summary`.
- WebSocket: `/ws/portfolio` pushes a full position payload on every MTM update.
- `PortfolioHub` wiring into `main.py` lifespan alongside the existing hubs.

## Capabilities

### New Capabilities

- `portfolio`: Real-time MTM P&L across open positions, portfolio summary aggregation, REST + WebSocket exposure, and EOD MongoDB snapshot.

### Modified Capabilities

(none — `positions` table schema is unchanged; only the unrealized_pnl column gets populated at runtime)

## Impact

- **`src/pdp/portfolio/`** — new package (service, hub, routes, ws, snapshot).
- **`src/pdp/main.py`** — wire `PortfolioService` and `PortfolioHub` into lifespan.
- **`src/pdp/settings.py`** — two new settings (`PORTFOLIO_MTM_INTERVAL_SECONDS`, `PORTFOLIO_EOD_SNAPSHOT`).
- **`src/pdp/mongo/collections.py`** — ensure `portfolio_snapshots` collection + TTL index.
- Depends on: `platform-core` (PG, structlog), `market-data` (Redis `tick.*` pub/sub + `ltp:<sid>` keys), `order-execution` (positions table + OrdersHub fill events), `mongo-store` (motor client).
