## ADDED Requirements

### Requirement: Tick delivery for runtime subscriptions
The system SHALL deliver ticks to a running strategy for any security the strategy subscribes to at
runtime, in addition to the securities listed in its static watchlist.

The host MUST track, per running strategy, the set of securities subscribed via
`MarketControl.subscribe()` and route incoming ticks to `strategy.on_tick()` when the tick's
security is in the static watchlist **or** that dynamic set. The dynamic set MUST be cleared when a
security is unsubscribed and when the strategy stops, so it does not grow without bound.

#### Scenario: Dynamically-subscribed option tick reaches the strategy
- **WHEN** a running strategy calls `ctx.market.subscribe(sid, segment)` for an option not in its
  static watchlist, and a tick for that `sid` subsequently arrives at the host
- **THEN** the host invokes `strategy.on_tick()` for that tick
- **AND** the strategy's LTP cache for that `sid` is populated

#### Scenario: Static watchlist still delivered
- **WHEN** a tick arrives for a security in the strategy's static YAML watchlist
- **THEN** the host invokes `strategy.on_tick()` for that tick as before

#### Scenario: Unsubscribe and stop clear the dynamic set
- **WHEN** a security is unsubscribed, or the strategy is stopped
- **THEN** subsequent ticks for that security are no longer dispatched to that strategy
- **AND** the per-strategy dynamic set holds no entries after stop
