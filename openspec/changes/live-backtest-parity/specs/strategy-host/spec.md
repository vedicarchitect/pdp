## MODIFIED Requirements

### Requirement: Indicator access from strategy context
The strategy host SHALL expose universal indicator reads to a running strategy through its
`StrategyContext`, returning the latest computed value for a `(security_id, timeframe)`.

Before dispatching the first live bar to any strategy, the host SHALL seed the `IndicatorEngine`
with historical bars from MongoDB for every `(security_id, timeframe)` pair in all running
strategies' watchlists, using `pdp.indicators.warmup.warm_up_indicator_engine()`. Seeding SHALL
complete before any live bar is dispatched, so the first `ctx.indicators.supertrend()` call within
`on_bar()` returns a non-None state rather than `None`.

#### Scenario: Strategy reads SuperTrend
- **WHEN** a strategy calls `ctx.indicators.supertrend(security_id, timeframe)`
- **THEN** it receives the latest computed SuperTrend state, or `None` if not yet available

#### Scenario: Indicator pre-seeded before first live bar
- **WHEN** the strategy host starts and MongoDB contains prior bars for a watched `(security_id, timeframe)`
- **THEN** `ctx.indicators.supertrend(security_id, timeframe)` returns a non-None state on the very first `on_bar()` call, not after period+1 live bars have accumulated

#### Scenario: Warmup failure does not block startup
- **WHEN** MongoDB is unreachable at startup
- **THEN** the host logs `indicator_warmup_failed` and continues startup in cold-indicator state; no strategy start is blocked

---

### Requirement: Runtime feed subscription from strategy context
The strategy host SHALL allow a running strategy to subscribe and unsubscribe market-data feed
instruments at runtime through its `StrategyContext`, so dynamically-chosen instruments receive
ticks (enabling paper fills).

When a strategy subscribes an instrument, the host SHALL notify the paper broker immediately
(before `place_order` is called) so the paper broker's Redis `tick.{security_id}` subscription
is active before the first MARKET order for that instrument arrives. This ensures the first tick
after order placement fills the order rather than being missed.

#### Scenario: Strategy subscribes a chosen instrument
- **WHEN** a strategy calls `ctx.market.subscribe(security_id, segment)` and a live feed exists
- **THEN** the feed begins delivering ticks for that instrument

#### Scenario: Paper broker pre-registered on subscribe
- **WHEN** `ctx.market.subscribe(security_id, segment)` is called and the paper broker is active
- **THEN** the paper broker registers `security_id` in its watch list before `subscribe()` returns, so the next MARKET order for that `security_id` will be filled on the first arriving tick

#### Scenario: No live feed is a safe no-op
- **WHEN** a strategy calls `ctx.market.subscribe(...)` and no live feed is configured
- **THEN** the call returns without error and places no subscription
