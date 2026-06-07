## Context

PDP has shipped:
- **market-data feed** — `TickRouter` fans ticks to Redis pub/sub, `BarAggregator` produces `BarClosed` events, bars persisted to MongoDB.
- **order execution** — `OrderRouter` validates and routes to `PaperBroker` or `DhanBroker`; `orders.strategy_id` column already exists (migration 0005).
- **portfolio** — `PortfolioService` subscribes to fill events via `OrdersHub.subscribe_fill_events`.

The missing layer is a **strategy runtime** — something that sits between market events and order placement, executing user-defined logic with consistent lifecycle hooks, isolation, and risk guardrails.

## Goals / Non-Goals

**Goals:**
- `Strategy` ABC with hooks: `on_init`, `on_tick`, `on_bar`, `on_fill`, `on_shutdown`.
- Per-strategy asyncio task with a bounded inbox queue so a slow strategy cannot block the hot path.
- YAML-based registry (`strategies/<id>.yaml`) — params, watchlist, risk caps.
- `StrategyHost` manages lifecycle (load, start, stop, supervise).
- `StrategyOrderClient` wraps `OrderRouter` with session management and risk-cap enforcement.
- REST API: `GET /api/v1/strategies`, `POST /api/v1/strategies/{id}/start|stop`.
- Fill events forwarded from `OrdersHub` into relevant strategy inboxes.

**Non-Goals:**
- Backtesting (depends on this change; tracked in `add-backtest-engine`).
- Multi-process or multi-host distribution — single-process asyncio only.
- Auto-restart after crash — deliberate: require explicit operator action.
- Built-in indicator computation — strategies receive raw ticks/bars and use Polars directly.
- Strategy persistence across process restarts — strategies reload from YAML on startup.

## Decisions

### D1 — Dispatch model: TickRouter callback, not per-strategy Redis subscription

`TickRouter` accepts an optional `strategy_host` argument (same pattern as `ws_hub`, `bar_writer`).
After processing each tick, it calls `strategy_host.on_tick(tick)` (sync, non-blocking). After each
closed bar it calls `strategy_host.on_bar(bar)` (sync, non-blocking). The host iterates watchlist-
matched strategies and calls `queue.put_nowait()` on each inbox, dropping if full.

**Alternative considered:** each strategy subscribes its own Redis XREAD from `bars.*.*` streams.
**Rejected:** adds N Redis connections, introduces XREAD latency (even minimal), and requires
consumer-group management. The callback approach adds zero latency and is already the TickRouter
fan-out idiom.

### D2 — Strategy discovery: YAML + importlib dynamic import

`strategies/<id>.yaml` files at project root, each with a `class: dotted.module.ClassName` field.
`registry.py` globs `strategies/*.yaml`, validates with pydantic, and imports the class via
`importlib.import_module` at startup.

**Alternative considered:** Python entry-points (packaging-level plugin system).
**Rejected:** requires a `pyproject.toml` entry per strategy, packaging overhead, and a `pip install`
cycle. For a self-hosted platform where strategies live in the same repo, YAML + importlib is
sufficient and far simpler.

### D3 — Order placement: StrategyOrderClient, not raw session injection

`StrategyContext.orders` is a `StrategyOrderClient`. Each `place_order()` call opens and commits
its own `AsyncSession` internally. Strategies write:

```python
await self.ctx.orders.place_order(security_id=..., side=Side.BUY, qty=25, ...)
```

No session, no transaction management in strategy code.

**Why:** strategies are domain-logic; I/O lifecycle is infrastructure. Mixing them makes strategies
harder to test and harder to port to backtesting.

### D4 — Isolation: asyncio tasks + supervised crash loop

Each strategy runs an `asyncio.Task` that pulls from its inbox queue in a tight loop. The task is
wrapped in `try/except Exception` — a crash logs the error, sets status to `CRASHED`, and removes
the task from the active set. Restart is manual via `POST /api/v1/strategies/{id}/start`.

**No automatic restart** — a crash likely means a strategy bug; silently restarting would repeat it.
Operators get an alert via log `strategy_crashed` and can re-read the log before restarting.

### D5 — Inbox overflow: drop + warn, no backpressure

`queue.put_nowait()` is called; `asyncio.QueueFull` is caught, the event is dropped, and
`strategy_lagging` is logged. The hot-path latency budget (p99 ≤ 50ms) must not be affected by any
individual strategy. A strategy that consistently drops events is surfaced via its `dropped_ticks`
counter in the REST list response.

### D6 — Fill routing: reuse OrdersHub subscription

`StrategyHost.subscribe_fill_events(orders_hub)` registers a callback (same pattern as
`PortfolioService`). On fill, the host matches `trade.strategy_id` to the relevant strategy inbox
and enqueues a `FillEvent`. No new pub/sub channel.

## Risks / Trade-offs

- **Dynamic import of arbitrary `class:`** — user-written strategies have full Python access. On a
  self-hosted platform the operator owns the code, so this is acceptable. An allow-list (explicit
  list of permitted module prefixes) can be added later without API changes.
- **Cooperative asyncio** — a CPU-bound `on_bar` will starve the event loop. Documented constraint:
  hooks must be non-blocking; heavy computation (e.g. Polars operations on large frames) should be
  offloaded with `asyncio.to_thread`.
- **YAML validated at `start` time** — bad `class:` path raises `ImportError` returned as HTTP 422.
  Operators discover config errors at start, not at deployment.

## Migration Plan

No DB migration required — `orders.strategy_id` exists since migration 0005.

1. Add `src/pdp/strategy/` module (`abc.py`, `context.py`, `host.py`, `registry.py`, `schemas.py`, `routes.py`).
2. Add optional `strategy_host` parameter to `TickRouter.__init__` and `_handle()`.
3. Wire in `main.py` lifespan: construct `StrategyHost`, pass to `TickRouter`, call `strategy_host.subscribe_fill_events(orders_hub)`.
4. Mount strategy routes in `create_app()`.
5. Add `strategies/` directory with a commented example YAML.
6. Add `strategies/` to `.gitignore` (optional — operators may choose to check in configs).

## Open Questions

- **Risk-cap scope**: should `max_open_orders` count all orders for the strategy (across all securities) or per-security? Current proposal: per-strategy total. Can be refined in implementation.
- **YAML hot-reload**: should `POST .../start` re-read the YAML each time (allowing param changes without restart)? Proposed: yes — load fresh YAML on each start call.
