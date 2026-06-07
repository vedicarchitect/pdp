## 1. Module scaffold

- [x] 1.1 Create `src/pdp/strategy/` package with `__init__.py`
- [x] 1.2 Create `strategies/` directory at project root with `.gitkeep` and a `strategies/example.yaml.tpl` template file

## 2. Core ABC and context

- [x] 2.1 Implement `src/pdp/strategy/abc.py` — `Strategy` ABC with abstract `on_init(ctx)` and default no-op `on_tick`, `on_bar`, `on_fill`, `on_shutdown`
- [x] 2.2 Implement `src/pdp/strategy/context.py` — `StrategyContext` dataclass (orders, params, watchlist, log) and `StrategyOrderClient` (wraps `OrderRouter`, opens/closes `AsyncSession` per call, enforces risk caps, raises `RiskCapBreached`)
- [x] 2.3 Add `RiskCapBreached` exception class to `src/pdp/strategy/context.py`

## 3. YAML registry

- [x] 3.1 Implement `src/pdp/strategy/registry.py` — pydantic `WatchlistEntry`, `RiskConfig`, `StrategyConfig` models
- [x] 3.2 Implement `registry.load_all(strategies_dir)` that globs `*.yaml`, validates, and returns `list[StrategyConfig]`
- [x] 3.3 Implement `registry.load_one(strategy_id, strategies_dir)` used by the start endpoint (re-reads YAML each call for hot-reload)

## 4. StrategyHost and dispatcher

- [x] 4.1 Implement `src/pdp/strategy/host.py` — `StrategyHost` class with `strategies_dir` and `session_maker` constructor args
- [x] 4.2 Add `StrategyHost.load_registry()` — populates internal `_configs: dict[str, StrategyConfig]` from YAML dir
- [x] 4.3 Add `StrategyHost.start(strategy_id)` — imports class, constructs instance, creates `asyncio.Task`, sets status RUNNING
- [x] 4.4 Add `StrategyHost.stop(strategy_id)` — signals shutdown, awaits `on_shutdown`, cancels task, sets status STOPPED
- [x] 4.5 Implement `StrategyHost.on_tick(tick)` — sync, iterates running strategies whose watchlist contains `tick.security_id`, calls `queue.put_nowait`, increments `dropped_ticks` counter on `QueueFull`
- [x] 4.6 Implement `StrategyHost.on_bar(bar)` — sync, routes `BarClosed` to strategies watching `(bar.security_id, bar.timeframe)`, same overflow policy
- [x] 4.7 Implement `StrategyHost.subscribe_fill_events(orders_hub)` — registers fill callback; routes fills to matching `strategy_id` inbox
- [x] 4.8 Implement per-strategy task loop — pulls events from inbox, dispatches to `on_tick`/`on_bar`/`on_fill`, wraps in `try/except`, sets CRASHED on unhandled exception

## 5. Wire into TickRouter

- [x] 5.1 Add optional `strategy_host` parameter to `TickRouter.__init__`
- [x] 5.2 Call `strategy_host.on_tick(tick)` and `strategy_host.on_bar(bar)` in `TickRouter._handle` after existing fan-out steps (non-blocking, after step 6)

## 6. REST API

- [x] 6.1 Implement `src/pdp/strategy/schemas.py` — `StrategyInfo` msgspec Struct (id, status, dropped_ticks, watchlist)
- [x] 6.2 Implement `src/pdp/strategy/routes.py` — `GET /api/v1/strategies`, `POST /api/v1/strategies/{id}/start`, `POST /api/v1/strategies/{id}/stop`
- [x] 6.3 Return HTTP 409 when starting an already-RUNNING strategy or stopping a non-running one
- [x] 6.4 Return HTTP 422 with error detail on `ImportError` or pydantic `ValidationError` during start

## 7. Wire into app lifespan

- [x] 7.1 Construct `StrategyHost` in `main.py` lifespan, call `load_registry()`, store as `app.state.strategy_host`
- [x] 7.2 Pass `strategy_host` to `TickRouter` constructor in the market feed block
- [x] 7.3 Call `strategy_host.subscribe_fill_events(orders_hub)` after orders hub setup
- [x] 7.4 Mount strategy routes in `create_app()` via `app.include_router(strategy_router)`

## 8. Tests

- [x] 8.1 Unit test `StrategyHost.on_tick` — tick for watched security enqueues; tick for unwatched is dropped silently
- [x] 8.2 Unit test `StrategyHost.on_bar` — routes on `(security_id, timeframe)` match; wrong timeframe is filtered
- [x] 8.3 Unit test inbox overflow — full queue increments `dropped_ticks`, does not raise
- [x] 8.4 Unit test task crash containment — `on_bar` raising `RuntimeError` sets status CRASHED; other strategies unaffected
- [x] 8.5 Unit test `RiskCapBreached` — `place_order` blocked when `max_open_orders` reached
- [x] 8.6 Integration test REST API — start/stop/list lifecycle against a stub strategy; 409 double-start; 409 stop when not running
