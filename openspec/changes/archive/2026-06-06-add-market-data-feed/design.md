# Design — add-market-data-feed

## Hot-path Architecture

```
                       Dhan WS (binary frames)
                              │
                              ▼
              ┌──────────────────────────────┐
              │ DhanTickerAdapter (asyncio)  │
              │  • msgspec.Struct decode     │
              │  • emits Tick(security_id,   │
              │     ltp, ts, vol, oi)        │
              └─────────────┬────────────────┘
                            │  (in-process asyncio.Queue, bounded=1000)
                            ▼
              ┌─────────────────────────────┐
              │ TickRouter                  │
              ├─────────────────────────────┤
              │  fan-out tasks (parallel):   │
              │  1) Redis SET ltp:<id> EX 5  │
              │  2) Redis PUBLISH tick.<id>  │
              │  3) BarAggregator.on_tick    │
              └─────────────┬────────────────┘
                            │
                  ┌─────────┴─────────┐
                  ▼                   ▼
         BarAggregator           WS Hub (per-client)
         (per timeframe)         drop-oldest if queue > 50
                  │
        on_bar_close emit
                  ├──► Redis XADD bars.<id>.<tf>
                  └──► Timescale COPY (batched)
```

## Backpressure

- Tick queue bounded at 1000; if full, drop oldest tick and log a `tick_dropped` warning (better stale than crash).
- WS per-client queue bounded at 50; drop-oldest. Frontend reconciles on next snapshot fetch.

## TimescaleDB

```sql
CREATE TABLE market_bars (
    security_id   TEXT NOT NULL,
    timeframe     TEXT NOT NULL,    -- 1m, 5m, 15m, 30m, 1H
    bar_time      TIMESTAMPTZ NOT NULL,
    open          NUMERIC(14,4) NOT NULL,
    high          NUMERIC(14,4) NOT NULL,
    low           NUMERIC(14,4) NOT NULL,
    close         NUMERIC(14,4) NOT NULL,
    volume        BIGINT NOT NULL DEFAULT 0,
    oi            BIGINT,
    vwap          NUMERIC(14,4),
    PRIMARY KEY (security_id, timeframe, bar_time)
);
SELECT create_hypertable('market_bars', 'bar_time', chunk_time_interval => INTERVAL '7 days');
ALTER TABLE market_bars SET (
  timescaledb.compress,
  timescaledb.compress_segmentby = 'security_id, timeframe'
);
SELECT add_compression_policy('market_bars', INTERVAL '7 days');
SELECT add_retention_policy('market_bars', INTERVAL '2 years');
```

## Latency Budget

| Stage                         | Target |
|-------------------------------|--------|
| Dhan WS → adapter decode      | < 1 ms |
| Adapter → Redis PUBLISH       | < 2 ms |
| Redis PUBLISH → WS Hub recv   | < 5 ms |
| WS Hub → client socket write  | < 5 ms |
| **End-to-end p99**            | **≤ 50 ms** |

Measure via Locust scenario: 1 simulated subscriber per instrument × 200 instruments; record `now() - tick.ts` on receive.

## Open Question

How to bridge Dhan's instrument-list subscription with our `instruments` table when the user adds a new symbol mid-session? → Adapter exposes `subscribe(security_id, segment)` async method; subscription registry persisted in `subscriptions` table so reconnect restores state.
