# strategy-host

## ADDED Requirements

### Requirement: Indicator access from strategy context
The strategy host SHALL expose universal indicator reads to a running strategy through its
`StrategyContext`, returning the latest computed value for a `(security_id, timeframe)`.

#### Scenario: Strategy reads SuperTrend
- **WHEN** a strategy calls `ctx.indicators.supertrend(security_id, timeframe)`
- **THEN** it receives the latest computed SuperTrend state, or `None` if not yet available

### Requirement: Runtime feed subscription from strategy context
The strategy host SHALL allow a running strategy to subscribe and unsubscribe market-data feed
instruments at runtime through its `StrategyContext`, so dynamically-chosen instruments receive
ticks (enabling paper fills).

#### Scenario: Strategy subscribes a chosen instrument
- **WHEN** a strategy calls `ctx.market.subscribe(security_id, segment)` and a live feed exists
- **THEN** the feed begins delivering ticks for that instrument

#### Scenario: No live feed is a safe no-op
- **WHEN** a strategy calls `ctx.market.subscribe(...)` and no live feed is configured
- **THEN** the call returns without error and places no subscription
