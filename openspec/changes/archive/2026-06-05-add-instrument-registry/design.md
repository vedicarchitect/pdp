# Design — add-instrument-registry

## Source

Dhan publishes two CSVs:
- `api-scrip-master.csv` (compact)
- `api-scrip-master-detailed.csv` (with expiry/strike/option_type, lot size, ISIN)

We pull the detailed one. URL is documented in Dhan API docs and configurable via `DHAN_SCRIPMASTER_URL` env.

## Schema

```sql
CREATE TABLE instruments (
    id                BIGSERIAL PRIMARY KEY,
    security_id       TEXT NOT NULL,
    exchange_segment  TEXT NOT NULL,    -- NSE_EQ, NSE_FNO, BSE_EQ, MCX_COMM, IDX_I
    trading_symbol    TEXT NOT NULL,
    instrument_type   TEXT NOT NULL,    -- EQUITY, FUTIDX, OPTIDX, FUTSTK, OPTSTK, INDEX
    underlying        TEXT,             -- e.g. NIFTY, RELIANCE
    expiry            DATE,
    strike            NUMERIC(12,2),
    option_type       TEXT,             -- CE, PE, NULL
    lot_size          INTEGER NOT NULL DEFAULT 1,
    tick_size         NUMERIC(8,4) NOT NULL DEFAULT 0.05,
    isin              TEXT,
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (security_id, exchange_segment)
);
CREATE INDEX ix_instruments_trading_symbol ON instruments (trading_symbol);
CREATE INDEX ix_instruments_underlying_expiry ON instruments (underlying, expiry);
```

## Ingest

`pdp instruments refresh`:
1. Stream-download CSV via `httpx`.
2. Parse rows with Polars (`pl.read_csv` is fast on the ~200k-row file).
3. Upsert in batches of 5000 via `INSERT … ON CONFLICT (security_id, exchange_segment) DO UPDATE`.
4. Log row counts: added / updated / unchanged.

## Search

`GET /api/v1/instruments?q=NIFTY&segment=NSE_FNO`:
- Full-text-ish: `WHERE trading_symbol ILIKE :q OR underlying ILIKE :q`
- Filterable by `segment`, `instrument_type`, `underlying`, `expiry`
- Returns top-20 ordered by exact-match → prefix-match → contains
