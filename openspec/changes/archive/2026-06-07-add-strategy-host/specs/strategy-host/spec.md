## ADDED Requirements

### Requirement: Strategy ABC
Every strategy SHALL be a Python class that inherits from `pdp.strategy.abc.Strategy` and
implements `on_init(ctx: StrategyContext) -> None`. The hooks `on_tick`, `on_bar`, `on_fill`, and
`on_shutdown` SHALL have default no-op implementations so strategies only override what they need.
`on_init` SHALL be called exactly once, before the strategy's first event is delivered.

#### Scenario: Strategy with only on_bar implemented
- **WHEN** a class inherits from `Strategy` and overrides only `on_bar`
- **THEN** the host SHALL load and run it without error; `on_tick`, `on_fill`, and `on_shutdown` are silent no-ops

#### Scenario: Strategy not implementing on_init
- **WHEN** a class inherits from `Strategy` but does not implement `on_init`
- **THEN** the host SHALL raise a `TypeError` at load time (abstract method not implemented)

### Requirement: YAML strategy registry
Each strategy SHALL be described by a YAML file at `strategies/<id>.yaml` containing:
`id` (string), `class` (dotted Python import path), `watchlist` (list of `{security_id, exchange_segment, timeframes}`), `params` (arbitrary dict), and `risk` (`max_open_orders`, `max_daily_loss_inr`).
The host SHALL validate the YAML against a pydantic `StrategyConfig` schema on load and reject
invalid configs with a descriptive error.

#### Scenario: Valid YAML loaded at startup
- **WHEN** `strategies/sma.yaml` exists with all required fields
- **THEN** the host loads `StrategyConfig` without error and makes the strategy available in the list

#### Scenario: YAML with unknown class path
- **WHEN** `class: pdp.strategies.nonexistent.Foo` cannot be imported
- **THEN** `POST /api/v1/strategies/sma/start` returns HTTP 422 with an `ImportError` message

#### Scenario: YAML missing required field
- **WHEN** a YAML file omits the `watchlist` key
- **THEN** validation raises a pydantic `ValidationError`; the strategy is not registered

### Requirement: Per-strategy asyncio isolation
Each running strategy SHALL execute in a dedicated `asyncio.Task` that consumes from a bounded
inbox queue. The queue capacity SHALL default to 1000 events. A strategy task crash SHALL be caught,
logged as `strategy_crashed`, and set the strategy status to `CRASHED` without affecting other
running strategies or the hot path.

#### Scenario: Strategy raises unhandled exception in on_bar
- **WHEN** `on_bar` raises an unhandled exception
- **THEN** the task catches it, logs `strategy_crashed` with the traceback, sets status to CRASHED, and all other strategies continue running

#### Scenario: Inbox overflow (strategy falling behind)
- **WHEN** the strategy inbox queue is full and a new tick arrives
- **THEN** the event is dropped, `strategy_lagging` is logged with `strategy_id` and `dropped_count`, and the hot path returns without blocking

### Requirement: Event dispatch — ticks
The `StrategyHost` SHALL receive every tick from `TickRouter` via a synchronous `on_tick(tick)`
callback. For each running strategy whose watchlist includes the tick's `security_id`, the host
SHALL enqueue a tick event to that strategy's inbox using `put_nowait`.

#### Scenario: Tick for watched security
- **WHEN** a tick arrives for `security_id="1333"` and strategy `s` has `"1333"` in its watchlist
- **THEN** the tick is enqueued in `s`'s inbox and `s.on_tick` is called in its task

#### Scenario: Tick for unwatched security
- **WHEN** a tick arrives for `security_id="9999"` and no strategy watches it
- **THEN** the tick is discarded silently with no queue operations

### Requirement: Event dispatch — bars
The `StrategyHost` SHALL receive `BarClosed` events from `TickRouter` via a synchronous `on_bar(bar)`
callback. For each running strategy whose watchlist includes the bar's `(security_id, timeframe)`
pair, the host SHALL enqueue the bar event to that strategy's inbox.

#### Scenario: Bar for watched (security, timeframe)
- **WHEN** a `BarClosed` with `security_id="1333"` and `timeframe="5m"` arrives and strategy `s` watches `("1333", "5m")`
- **THEN** the bar is enqueued in `s`'s inbox and `s.on_bar` is called in its task

#### Scenario: Bar for watched security but unwatched timeframe
- **WHEN** strategy `s` watches `("1333", "1m")` only and a `5m` bar arrives for `"1333"`
- **THEN** the bar is NOT enqueued in `s`'s inbox

### Requirement: Event dispatch — fills
The `StrategyHost` SHALL subscribe to `OrdersHub` fill events. When a fill arrives with a
`strategy_id` matching a running strategy, the fill SHALL be enqueued in that strategy's inbox and
delivered to `on_fill`.

#### Scenario: Fill tagged with matching strategy_id
- **WHEN** an order fills and `order.strategy_id == "sma_crossover"` and that strategy is running
- **THEN** the fill is enqueued in the strategy's inbox and `on_fill(trade)` is called

#### Scenario: Fill with no strategy_id
- **WHEN** an order fills with `order.strategy_id == None`
- **THEN** no strategy inbox receives the event

### Requirement: StrategyContext and order placement
Each strategy SHALL receive a `StrategyContext` on `on_init` containing: `orders` (a
`StrategyOrderClient`), `params` (dict from YAML), `watchlist`, and a bound structlog logger.
`StrategyOrderClient.place_order(...)` SHALL open its own `AsyncSession`, call `OrderRouter.place_order`,
commit, and close the session — the strategy SHALL NOT manage sessions.

#### Scenario: Strategy places a market order
- **WHEN** `await ctx.orders.place_order(security_id="1333", exchange_segment="NSE_FO", side=Side.BUY, qty=25, order_type=OrderType.MARKET, product=Product.MIS)`
- **THEN** an `Order` row is created in PostgreSQL with `strategy_id` set to the strategy's id and the order is forwarded to the configured broker

#### Scenario: Risk cap — max open orders exceeded
- **WHEN** a strategy has `max_open_orders: 2` and already has 2 OPEN orders
- **THEN** `place_order` raises `RiskCapBreached` before touching the DB

### Requirement: Strategy lifecycle REST API
The system SHALL expose:
- `GET /api/v1/strategies` — returns all registered strategies with `id`, `status` (STOPPED / RUNNING / CRASHED), `dropped_ticks`, `watchlist`.
- `POST /api/v1/strategies/{id}/start` — loads YAML, imports class, starts asyncio task; returns 200 with strategy status or 422 on config error.
- `POST /api/v1/strategies/{id}/stop` — sends shutdown signal, awaits `on_shutdown`, cancels task; returns 200.

#### Scenario: Start a registered strategy
- **WHEN** `POST /api/v1/strategies/sma_crossover/start` is called and the YAML is valid
- **THEN** response is HTTP 200, status is RUNNING, and the strategy begins receiving events

#### Scenario: Start an already-running strategy
- **WHEN** `POST /api/v1/strategies/sma_crossover/start` is called while it is already RUNNING
- **THEN** response is HTTP 409 with message "strategy already running"

#### Scenario: Stop a running strategy
- **WHEN** `POST /api/v1/strategies/sma_crossover/stop` is called
- **THEN** `on_shutdown` is awaited, the task is cancelled, and status transitions to STOPPED

#### Scenario: Stop a strategy that is not running
- **WHEN** `POST /api/v1/strategies/sma_crossover/stop` is called while STOPPED
- **THEN** response is HTTP 409 with message "strategy not running"

#### Scenario: List all strategies
- **WHEN** `GET /api/v1/strategies` is called
- **THEN** response is HTTP 200 with a JSON array including all registered strategy IDs, their current status, and dropped_ticks count
