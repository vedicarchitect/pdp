## Why

(STUB — to be authored after `add-paper-broker` ships.)

Long-term equity / MF holdings need real-time mark-to-market P&L, corporate-action awareness (splits, bonuses, dividends), and a unified view alongside intraday/positional. The paper-broker `positions` table covers F&O only — equity holdings have different semantics (long-only, T+1 settlement, demat sync).

## What Changes

- New `holdings` table (broker-synced).
- Holdings ingest from broker `/holdings` endpoint + manual override CSV.
- Real-time P&L via LTP from `market-data` Redis cache.
- Corporate-action ledger and auto-adjustment of cost basis.
- `GET /api/v1/holdings` + `/ws/portfolio` event stream.

## Capabilities

### New Capabilities

- `portfolio`: Long-term equity/MF holdings, P&L, corporate-action handling.

### Modified Capabilities

(none)

## Impact

Depends on `platform-core`, `instrument-registry`, `market-data`, `order-execution`. To be designed in detail once dependencies ship.
