## ADDED Requirements

### Requirement: Each critical event type SHALL denote exactly one condition

An event type SHALL NOT be emitted for unrelated conditions. `POSITION_SIZE_CAPPED` SHALL denote only
that an open was refused or clipped at the per-security lot cap. A contradiction between a leg's
recorded type and the broker's position sign SHALL use its own event type.

#### Scenario: Cap enforcement

- **WHEN** an open is clipped because the per-security lot cap is reached
- **THEN** `POSITION_SIZE_CAPPED` is emitted and no other critical event is

#### Scenario: Type contradiction

- **WHEN** a close finds the broker's net-quantity sign contradicts the leg's recorded type
- **THEN** `LEG_TYPE_CONTRADICTED` is emitted and `POSITION_SIZE_CAPPED` is not

#### Scenario: Alerting can distinguish the two

- **WHEN** an operator counts risk-limit events for a session
- **THEN** the count excludes every data-corruption event

### Requirement: Strategy events SHALL be persisted to a database

`_emit_event` SHALL write each event to a durable database store in addition to structured logging.
The write SHALL NOT block the tick hot path; it SHALL be batched and dispatched asynchronously. A
local file SHALL NOT be the system of record for strategy events.

#### Scenario: An event survives a restart

- **WHEN** a leg is opened and the process restarts
- **THEN** the `leg_open` event is readable from the database

#### Scenario: The hot path is not blocked

- **WHEN** events are emitted during tick processing
- **THEN** no database round trip is awaited inside the tick handler and tick-to-websocket p99 latency remains within budget

#### Scenario: Reads and writes agree

- **WHEN** a component reads the events collection
- **THEN** the collection has at least one writer and the read returns the events that were emitted

### Requirement: The platform SHALL report per-strategy trading readiness

For each strategy, the platform SHALL report a readiness state composed of: indicator seeding
completeness, bias-input satisfiability, option-chain availability per underlying, broker-mirror
freshness, and leg-to-broker reconciliation. Each component SHALL be `ok`, `degraded` or `blocked`
with a human-readable reason. The composite SHALL be exposed over HTTP and logged once at startup.

#### Scenario: An unseeded indicator blocks readiness

- **WHEN** EMA(200) on the 1H timeframe is unseeded at startup
- **THEN** the readiness report marks the indicator component `blocked` with a reason naming the timeframe and period

#### Scenario: A stale broker mirror degrades readiness

- **WHEN** the broker mirror's last state refresh is older than the poll interval
- **THEN** the broker component is `degraded` with a reason carrying the timestamp

#### Scenario: A fully ready strategy

- **WHEN** every component is satisfied
- **THEN** the composite readiness is `ok` and the startup log records it

### Requirement: A blocked strategy SHALL NOT open new positions but SHALL continue to manage existing ones

While any readiness component is `blocked`, the strategy SHALL refuse to open its first position of
the session, SHALL emit `STRATEGY_NOT_READY` naming the blocking components, and SHALL re-evaluate
readiness on each bar. It SHALL continue to manage, protect and square off positions it already
holds. A `degraded` component SHALL warn and permit trading.

#### Scenario: Entry is refused while blocked

- **WHEN** the strategy would open its first leg and a readiness component is `blocked`
- **THEN** no order is placed and one `STRATEGY_NOT_READY` event names the blocking components

#### Scenario: Existing positions are still protected

- **WHEN** the strategy holds open positions and becomes `blocked`
- **THEN** stop, take-profit and square-off logic continue to execute

#### Scenario: Readiness recovers intra-session

- **WHEN** a blocking component becomes satisfied at 10:00 IST
- **THEN** the strategy resumes opening positions on the next bar

#### Scenario: Degraded permits trading

- **WHEN** the only non-`ok` component is `degraded`
- **THEN** a warning is emitted and entries proceed

### Requirement: The application SHALL surface strategy readiness to the operator

The execution console SHALL display each strategy's readiness state and the reason for any component
that is not `ok`, so that a strategy which is not trading is visibly blocked rather than apparently
idle.

#### Scenario: Blocked strategy is visible before the open

- **WHEN** the operator views the execution console at 09:10 IST with a blocked strategy
- **THEN** the console names the strategy, its blocked components and their reasons

#### Scenario: Ready strategy is unobtrusive

- **WHEN** every strategy is `ok`
- **THEN** the console shows readiness without occupying prominent space
