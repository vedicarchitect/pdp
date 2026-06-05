## Why

Every other capability — market feed, orders, portfolio, options analytics — needs a canonical, searchable instrument lookup. Without it, hardcoded security IDs leak everywhere and option-chain strike/expiry resolution becomes ad-hoc.

## What Changes

- New `instruments` table keyed by `(security_id, exchange_segment)` with full attributes: `trading_symbol`, `lot_size`, `tick_size`, `instrument_type`, `expiry`, `strike`, `option_type`, `underlying`, `isin`.
- Daily ingest of Dhan's `api-scrip-master-detailed.csv` via `pdp instruments refresh` CLI (idempotent upsert).
- `GET /api/v1/instruments?q=...&segment=...&instrument_type=...` search endpoint (top-20).
- `GET /api/v1/instruments/{security_id}` detail endpoint.

## Capabilities

### New Capabilities

- `instrument-registry`: Canonical security-ID-keyed instrument catalog with daily refresh and search.

### Modified Capabilities

(none)

## Impact

- New Alembic migration for `instruments` table + indices on `trading_symbol`, `underlying`, `expiry`.
- New module `src/pdp/instruments/` (model, loader, search service, routes).
- Adds outbound HTTPS call to Dhan public CDN during `refresh` only.
