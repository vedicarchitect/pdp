## MODIFIED Requirements

### Requirement: The platform SHALL report per-strategy trading readiness

For each strategy, the platform SHALL report a readiness state composed of: indicator seeding
completeness, bias-input satisfiability, option-chain availability per underlying, broker-mirror
freshness, and leg-to-broker reconciliation. Each component SHALL be `ok`, `degraded` or `blocked`
with a human-readable reason. The composite SHALL be exposed over HTTP and logged once at startup.

The leg-to-broker reconciliation pass SHALL run on an independent periodic schedule owned by the
strategy itself, not only when an operator or console happens to request `state()` over HTTP. A
divergence or orphan broker position SHALL be detected and alerted within one reconciliation
interval of occurring, regardless of whether any HTTP request is made during that interval.

#### Scenario: An unseeded indicator blocks readiness

- **WHEN** EMA(200) on the 1H timeframe is unseeded at startup
- **THEN** the readiness report marks the indicator component `blocked` with a reason naming the timeframe and period

#### Scenario: Reconciliation runs without an operator polling the console

- **WHEN** a broker fill lands as an orphan position (no matching in-memory leg) and no HTTP
  request touches the strategy for several minutes afterward
- **THEN** the strategy's own periodic reconciliation pass still detects the orphan within one
  reconciliation interval and emits `LEG_STATE_DIVERGED` without requiring any external request

#### Scenario: A stale broker mirror degrades readiness

- **WHEN** the broker mirror's last state refresh is older than the poll interval
- **THEN** the broker component is `degraded` with a reason carrying the timestamp

#### Scenario: A fully ready strategy

- **WHEN** every component is satisfied
- **THEN** the composite readiness is `ok` and the startup log records it
