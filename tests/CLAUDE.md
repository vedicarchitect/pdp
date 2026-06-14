# tests/ — pytest Suite

Async-aware tests. Run with `task test` or `uv run pytest`.

## Structure

```
tests/
├── conftest.py              # Shared fixtures (app, DB session, mock broker)
├── backtest/                # BacktestEngine, commissions, fill timing, data integrity
├── cli/                     # Click CLI command tests
├── indicators/              # SuperTrend tracker, warmup logic
├── instruments/             # Snapshot diff, loader
├── journal/                 # Daily stats computation
├── market/                  # Bar builder, bar writer, WS hub, routes
├── options/                 # Analytics, Greeks, chain poller, routes
├── orders/                  # PaperBroker, DhanBroker (unit + integration)
├── portfolio/               # MTM service, snapshot, hub, routes
├── positional/              # Positional routes
├── risk/                    # KillSwitch, loss cap
└── strategy/                # StrategyHost, context, registry, routes, ST smoke
```

## Key fixtures (conftest.py)

- `app` — TestClient wrapping the full FastAPI app
- `session` — async PG session (uses test DB)
- `mock_broker` — PaperBroker with controllable fills
- `mongo_db` — MongoDB test database

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
