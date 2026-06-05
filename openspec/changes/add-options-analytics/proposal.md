## Why

(STUB.) Option-chain analytics (IV, Greeks, max-pain, PCR, OI build-up) are universal — computed once and consumed by intraday/positional dashboards and strategies.

## What Changes

- Option chain ingest per index (live OI from Dhan WS).
- IV solver + Greeks via `py_vollib_vectorized` per chain snapshot.
- `option_chain_snapshots` table (security_id, expiry, snapshot_ts) + JSONB chain payload.
- Endpoints: `GET /api/v1/options/{underlying}/chain`, `/max-pain`, `/pcr`.

## Capabilities

### New Capabilities

- `options-analytics`: Live option-chain Greeks, IV, max-pain, PCR.

### Modified Capabilities

(none)

## Impact

Depends on `market-data`, `instrument-registry`.
