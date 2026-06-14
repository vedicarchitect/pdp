## ADDED Requirements

### Requirement: Prior-session continuity on startup

The live indicator engine SHALL be seeded on startup such that each `SuperTrendTracker` carries the
direction established by the most recent prior trading session, so SuperTrend is continuous with the
chart (and the backtest) regardless of the time at which the process starts. The startup seed
lookback SHALL be **session-aware** — derived by walking back to the most recent prior trading day
over weekend and holiday (non-trading) gaps — rather than a fixed wall-clock window that the
overnight session gap can exceed. A continuously-running process SHALL NOT reset its trackers at the
day boundary.

#### Scenario: Mid-day restart inherits the prior-session direction

- **WHEN** the process starts during the trading session and the prior trading session closed in an
  established uptrend
- **THEN** the seeded SuperTrend direction is up (carried over), not a fresh cold-start seed

#### Scenario: Lookback walks back over a weekend or holiday

- **WHEN** the most recent prior trading day is separated from today by a weekend or holiday cluster
- **THEN** the warmup seeds from that prior trading session's bars, not from an empty or same-day-only
  window

#### Scenario: Continuously-running process stays continuous

- **WHEN** the process runs uninterrupted across a day boundary
- **THEN** the SuperTrend tracker is not reset and remains continuous, unaffected by the startup
  warmup path

### Requirement: Sufficient warmup history before the first live bar

The startup warmup SHALL ensure enough historical bars are seeded to establish a stable SuperTrend
direction — at least a full prior trading session — before the first live bar is processed. When the
local store holds too few bars to cover the prior session and a data provider is configured, the
warmup SHALL fetch the missing prior-session history from the provider and persist it; when no
provider is available, the tracker MAY cold-start, and this fallback SHALL be logged.

#### Scenario: Thin local store triggers a provider fetch

- **WHEN** the local store holds fewer bars than a full prior session and provider credentials are set
- **THEN** the warmup fetches the prior-session history from the provider, persists it, and seeds the
  tracker with it

#### Scenario: No provider falls back to cold start with a log

- **WHEN** the prior session is absent locally and no provider is available
- **THEN** the tracker cold-starts and the warmup logs that prior-session history was unavailable
