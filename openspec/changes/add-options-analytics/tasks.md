## 1. Dependencies and Settings

- [x] 1.1 `uv add py_vollib_vectorized` (polars already present)
- [x] 1.2 Add `OPTIONS_POLL_INTERVAL_SECONDS` (int, default 30), `OPTIONS_RISK_FREE_RATE` (float, default 0.065), and `OPTIONS_UNDERLYINGS` (JSON list str, default `'["NIFTY","BANKNIFTY"]'`) to `src/pdp/settings.py`
- [x] 1.3 Add `options_chain` collection initialisation in `src/pdp/mongo/collections.py`: regular collection, TTL index on `snapshot_ts` (7 days), compound index on `(underlying, expiry, snapshot_ts)`

## 2. Greeks and Analytics Module

- [x] 2.1 Create `src/pdp/options/greeks.py`: function `compute_greeks(strikes_df: pl.DataFrame, spot: float, expiry_date: date, risk_free_rate: float) -> pl.DataFrame` using `py_vollib_vectorized`; NaN IV clipped to `[0.01, 5.0]`, NaN Greeks → 0; returns T ≤ 0 early with all-zero Greeks
- [x] 2.2 Create `src/pdp/options/analytics.py`: `compute_max_pain(strikes: list[dict]) -> int` and `compute_pcr(strikes: list[dict]) -> float`

## 3. Options Chain Poller

- [x] 3.1 Create `src/pdp/options/dhan_client.py`: async `fetch_chain(underlying: str, session: httpx.AsyncClient) -> dict` calling Dhan `/v2/optionchain` with bearer token; returns raw JSON
- [x] 3.2 Create `src/pdp/options/poller.py`: `OptionsChainPoller` class with `start()` / `stop()` methods; asyncio background loop; market-hours guard (09:15–15:35 IST); `refresh_queue: asyncio.Queue` drained per iteration; calls `dhan_client.fetch_chain`, `greeks.compute_greeks`, `analytics.compute_max_pain/pcr`, writes document to `options_chain` MongoDB collection, broadcasts to `OptionsHub`

## 4. WebSocket Hub

- [x] 4.1 Create `src/pdp/options/hub.py`: `OptionsHub` class mirroring `WSHub` pattern; per-client bounded queue (20 msgs); `subscribe(underlying, expiry, queue)` / `unsubscribe` / `broadcast(underlying, expiry, snapshot)`; logs `ws_options_client_lagging` on drop

## 5. REST Routes

- [x] 5.1 Create `src/pdp/options/routes.py` with router prefix `/api/v1/options`:
  - `GET /{underlying}/chain?expiry=` → latest snapshot from MongoDB (404 if none)
  - `GET /{underlying}/max-pain?expiry=` → `{underlying, expiry, max_pain, snapshot_ts}` (404 if none)
  - `GET /{underlying}/pcr?expiry=` → `{underlying, expiry, pcr, snapshot_ts}` (404 if none)
  - `POST /{underlying}/refresh` → enqueue immediate refresh, return 202
- [x] 5.2 Add paper-mode guard: if poller not started, `GET .../chain` returns `{"mode":"paper","strikes":[],"max_pain":null,"pcr":null}`

## 6. WebSocket Endpoint

- [x] 6.1 Create `src/pdp/options/ws.py`: `/ws/options` endpoint; parse subscribe/unsubscribe JSON; drain client queue; log `ws_options_client_lagging` on queue overflow

## 7. Lifespan Wiring

- [x] 7.1 In `src/pdp/main.py` lifespan: instantiate `OptionsHub`; if `LIVE` and `DHAN_CLIENT_ID` instantiate and `await poller.start()`; store `app.state.options_hub`; on shutdown `await poller.stop()`
- [x] 7.2 Register `options_router` and `options_ws_router` in `create_app()`

## 8. Tests

- [x] 8.1 `tests/options/test_greeks.py`: unit tests for `compute_greeks` — ATM strike returns non-zero Greeks, expired expiry returns all-zero, NaN IV clamped to 0.01
- [x] 8.2 `tests/options/test_analytics.py`: unit tests for `compute_max_pain` and `compute_pcr` with known OI distribution
- [x] 8.3 `tests/options/test_routes.py`: integration tests for chain/max-pain/pcr endpoints — returns snapshot, 404 when absent, paper-mode response when poller not started

## 9. Smoke Test (live infra, manual)

- [x] 9.1 `docker compose up -d && alembic upgrade head` — verify `/readyz` still healthy (no Alembic change needed, but sanity check)
- [x] 9.2 With `LIVE=1` + valid Dhan credentials, `POST /api/v1/options/NIFTY/refresh` and confirm document appears in `mongosh db.options_chain.findOne()`
- [x] 9.3 Connect to `/ws/options`, subscribe to NIFTY nearest expiry, confirm snapshot push arrives within 35 s
