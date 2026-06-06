## Context

PDP already has a MongoDB store (motor client, `market_bars` time-series collection) wired in `app.state.mongo_db` via the `add-mongo-store` and `migrate-bars-to-mongo` phases. The Dhan broker adapter is live-gated; the market feed adapter handles ticks via WebSocket. Options-chain data is a **snapshot** resource (polled, not streamed) — Dhan exposes it via REST (`/v2/optionchain`). Greeks/IV are not provided by Dhan; they must be computed locally.

Current state: no options capability exists. The proposal stub referenced a PostgreSQL JSONB table, which is superseded by this design (Mongo-first per project profile).

## Goals / Non-Goals

**Goals:**
- Poll Dhan option chain REST API on a configurable interval and on-demand.
- Compute IV, delta, gamma, theta, vega with `py_vollib_vectorized` (vectorized, Polars-backed).
- Derive max-pain strike and PCR from OI.
- Persist each snapshot as a single MongoDB document in the `options_chain` collection.
- Expose `GET /api/v1/options/{underlying}/chain`, `/max-pain`, `/pcr`.
- Push snapshots to WebSocket subscribers via `/ws/options`.
- Gate live chain fetches on `LIVE=1` + `DHAN_CLIENT_ID`; paper mode returns empty/mocked snapshots.

**Non-Goals:**
- Backtesting from historical options chain data (querying old snapshots is out of scope for v1).
- Real-time tick-level streaming of options quotes (chain is polled, not streamed).
- Multi-broker options support.
- Frontend chart rendering.

## Decisions

### 1. MongoDB document schema — one document per (underlying, expiry, snapshot_ts)

Each poll produces one document per expiry. This allows `find_one(sort=[("snapshot_ts", -1)])` to fetch the latest snapshot without aggregation.

```json
{
  "underlying": "NIFTY",
  "expiry": "2026-06-26",
  "snapshot_ts": ISODate("2026-06-06T09:30:00Z"),
  "spot_price": 22500.0,
  "max_pain": 22400,
  "pcr": 1.23,
  "strikes": [
    {
      "strike": 22000,
      "ce": {"ltp": 523.0, "oi": 1200000, "volume": 50000, "iv": 0.18, "delta": 0.72, "gamma": 0.003, "theta": -45.2, "vega": 12.1},
      "pe": {"ltp": 47.0,  "oi":  800000, "volume": 20000, "iv": 0.17, "delta": -0.28, "gamma": 0.003, "theta": -40.1, "vega": 11.8}
    }
  ]
}
```

Alternatives considered:
- **One doc per strike per snapshot**: too many small documents, querying a full chain requires an aggregation.
- **Time-series collection**: granularity doesn't match (snapshots every 30s, not per-second ticks); embedding the full strikes array as the "measurement" is awkward.

### 2. Greeks via vollib + Polars

Originally planned to use `py_vollib_vectorized` for fully vectorised IV/Greeks. At implementation time, `py_vollib_vectorized 0.1.1` failed with a Numba JIT compilation error (`TypingError` in `_iv_models.py`) against the installed `llvmlite 0.47 / numba 0.65` versions. The dependency `vollib` (the non-JIT base library, already installed transitively) produces identical results and is used instead.

Build a Polars DataFrame from the strikes list, then iterate with `vollib` per-row functions (`implied_volatility`, `delta`, `gamma`, `theta`, `vega`). For a 200-strike chain this runs in ~10 ms, well within budget.

Risk-free rate: fixed at `0.065` (approx. 6.5% India 91-day T-bill). Configurable via `OPTIONS_RISK_FREE_RATE` env var.

Time-to-expiry: derived from `(expiry_date - utcnow().date()).days / 365.0`. If T ≤ 0 (expiry day post 15:30), skip IV computation (set all Greeks to 0).

### 3. Polling via asyncio background task

A single `OptionsChainPoller` task runs inside the lifespan, iterating over configured underlyings. Poll interval: `OPTIONS_POLL_INTERVAL_SECONDS` (default 30). Pause when outside market hours (before 09:15 or after 15:35 IST). On-demand refresh: `POST /api/v1/options/{underlying}/refresh` enqueues into a `asyncio.Queue` that the poller drains after each interval.

Alternatives considered:
- **APScheduler**: adds a dependency; asyncio task is sufficient for a single-process app.
- **Redis CRON via Celery**: over-engineered for this scale.

### 4. WebSocket fan-out via OptionsHub (mirrors WSHub pattern)

`OptionsHub` keeps per-client `asyncio.Queue` (bounded at 20 messages). On each new snapshot, the poller calls `hub.broadcast(snapshot_dict)`. A `/ws/options` endpoint drains the client queue. Clients subscribe by sending `{"action":"subscribe","underlying":"NIFTY","expiry":"2026-06-26"}`.

### 5. No live fetch in paper mode

If `LIVE=0` or `DHAN_CLIENT_ID` is absent, `GET /api/v1/options/{underlying}/chain` returns an empty `strikes` list with `"mode":"paper"` in the response. The poller does not start.

## Risks / Trade-offs

- **py_vollib_vectorized numerical instability**: IV solver can return NaN for deep ITM/OTM options or at expiry. Mitigation: clip IV to `[0.01, 5.0]`; replace NaN Greeks with 0.
- **Dhan rate limits on options chain API**: undocumented, observed ~10 req/s. Mitigation: poll at 30s; single underlying per request; back off on 429.
- **MongoDB document size**: 200 strikes × 2 sides × ~12 fields ≈ 15 KB per document. Well within 16 MB BSON limit. No risk.
- **WS snapshot lag**: if snapshot is 15 KB JSON, 200 subscribers = 3 MB broadcast per tick. Mitigation: bounded queue drops slow clients.

## Migration Plan

1. `uv add py_vollib_vectorized polars` (polars may already be present per project profile).
2. Add `options_chain` collection init in `src/pdp/mongo/collections.py` (regular collection, TTL index on `snapshot_ts` for 7-day retention, compound index on `(underlying, expiry, snapshot_ts)`).
3. Add `OPTIONS_POLL_INTERVAL_SECONDS`, `OPTIONS_RISK_FREE_RATE`, `OPTIONS_UNDERLYINGS` to settings.
4. Implement `src/pdp/options/` module: `poller.py`, `greeks.py`, `hub.py`, `routes.py`.
5. Wire `OptionsChainPoller` and `OptionsHub` into `main.py` lifespan (gated on `LIVE` + credentials).
6. No Alembic migration needed (Mongo-only).

## Open Questions

- **Which expiries to poll?** Default: nearest 3 weekly expiries for NIFTY/BANKNIFTY. Configurable via `OPTIONS_UNDERLYINGS` env list (JSON).
- **Dhan options chain endpoint authentication**: same `access_token` header as order API. Confirmed same credential.
