# tests/ — pytest Suite

Async-aware tests. Run with `task test` or `uv run pytest`.

## Structure

```
tests/
├── conftest.py              # Shared fixtures (app, DB session, mock broker)
├── backtest/                # BacktestEngine, commissions, fill timing, data integrity
├── broker_sync/             # Broker account/report sync; has its own _fresh_engine conftest (see below)
├── cli/                     # Click CLI command tests
├── events/                  # Event publisher, detectors
├── indicators/              # SuperTrend tracker, warmup logic
├── instruments/             # Snapshot diff, loader
├── intel/                   # Dashboard market-intel feeds/routes
├── jobs/                    # Job runner; own _fresh_engine conftest (same pattern as broker_sync/)
├── journal/                 # Daily stats computation
├── market/                  # Bar builder, bar writer, WS hub, routes
├── ml/                      # LightGBM offline train + online inference
├── observability/           # OpenSearch log pipeline, /logs/ingest
├── options/                 # Analytics, Greeks, chain poller, routes
├── orders/                  # PaperBroker, DhanBroker (unit + integration)
├── portfolio/               # MTM service, snapshot, hub, routes
├── positional/              # Positional routes
├── risk/                    # KillSwitch, loss cap
├── scripts/                 # Operational script tests
├── signals/                 # Bias-scoring engine
├── strategies/              # Cross-cutting strategy invariants (leg rehydration, event taxonomy)
├── strategy/                # StrategyHost, context, registry, routes, ST smoke, DirectionalStrangle
├── test_runtime_groups.py   # Every required=True group in GROUPS_BY_ROLE actually starts (real classes)
└── test_lifespan_required_groups.py  # lifespan()'s abort-on-required-failure logic (synthetic fake groups)
```

## Key fixtures (conftest.py)

- `app` — TestClient wrapping the full FastAPI app
- `session` — async PG session (uses test DB)
- `mock_broker` — PaperBroker with controllable fills
- `mongo_db` — MongoDB test database
- `mock_mongo_lifespan` (autouse) — patches `mongo_connect`/`init_collections`/`mongo_disconnect` in
  **both** `pdp.main` and `pdp.runtime.groups` (the latter holds its own `from ... import ... as ...`
  name binding and is what the real lifespan actually calls — patching only `pdp.main`'s copy used to
  leave full-lifespan tests hitting a real Motor database; fixed in `test-suite-baseline-green`,
  2026-07-10).
- `DHAN_CLIENT_ID`/`DHAN_ACCESS_TOKEN` are force-cleared at import time regardless of `.env` —
  without this, any full-lifespan test opens a real Dhan WebSocket feed and hangs indefinitely.
- The global async DB engine (`pdp/db/session.py`) is a singleton bound to whichever event loop first
  used it; pytest-asyncio gives each test its own loop, so a module exercising a real DB across
  multiple tests needs its own autouse `_fresh_engine` fixture disposing the engine before/after each
  test (see `tests/broker_sync/conftest.py`, `tests/jobs/conftest.py`) — otherwise the second test in
  the module fails with "Event loop is closed" on Windows.

## Running subsets

```powershell
uv run pytest tests/backtest/          # just backtest tests
uv run pytest -k "commission"          # pattern match
uv run pytest tests/ -m integration    # integration-marked only
uv run pytest -s -v tests/strategy/test_supertrend_smoke.py
```

## Backtest regression anchor

`tests/backtest/test_data_integrity.py` contains the `-264k INR` baseline.
**Do not change** without explicit approval — it's the regression guard.
