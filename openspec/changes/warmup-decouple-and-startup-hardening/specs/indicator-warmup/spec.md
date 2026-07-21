## ADDED Requirements

### Requirement: Warmup reconcile is decoupled from the trading-process boot path

The write-heavy warmup reconcile SHALL run only in the standalone premarket job, never on
the trading process's startup path. `warm_up_indicator_engine` exposes a `reconcile` mode:

- In **reconcile mode** (the standalone premarket job) the warmup MAY delete and re-insert
  `market_bars` documents to reconcile derivable higher timeframes from the 1-minute series
  (the existing derive-from-1m behavior).
- In **read-only mode** (the trading process boot, `FeedEngineGroup`) the warmup SHALL seed
  the indicator engine without writing to `market_bars` — it MAY derive higher-timeframe
  bars in memory to seed the engine, but SHALL NOT issue `delete_many` or `insert_many` on
  `market_bars`.

In read-only mode the warmup MAY fetch a bounded current-data top-up from the intraday
provider **only** for short intraday timeframes (5-minute, 15-minute) when the stored depth
is short, and SHALL NOT persist that top-up. For a higher timeframe short on depth in
read-only mode, the warmup SHALL leave it seeded from stored bars only (unconverged periods
remain unconverged) rather than pulling its wide history window onto the boot path.

#### Scenario: Trading-process boot seeds read-only without writing market_bars

- **WHEN** the trading process boots and warms a derivable higher timeframe whose stored
  bars are fewer than a 1-minute-derived rollup of the same window
- **THEN** the engine is seeded from the fuller derived series
- **AND** no `delete_many` or `insert_many` is issued against `market_bars`.

#### Scenario: Read-only boot tops up a short intraday timeframe without persisting

- **WHEN** the trading process boots and a 15-minute series is short on depth and the
  intraday provider has credentials
- **THEN** the warmup fetches a bounded top-up from the provider to seed the engine
- **AND** does not persist the fetched bars to `market_bars`.

#### Scenario: Read-only boot does not pull a higher-timeframe history onto the boot path

- **WHEN** the trading process boots and a 1-hour series is short on depth
- **THEN** the warmup does not call the intraday provider for it
- **AND** the timeframe stays seeded from stored bars only (its deep history is the
  premarket job's responsibility).

#### Scenario: Premarket job reconciles and persists

- **WHEN** the standalone premarket job runs warmup in reconcile mode and a stored higher
  timeframe disagrees with its 1-minute-derived rollup
- **THEN** the warmup replaces the stored window with the derived bars (delete-then-insert)
- **AND** records a completion marker for the current IST trading date.
