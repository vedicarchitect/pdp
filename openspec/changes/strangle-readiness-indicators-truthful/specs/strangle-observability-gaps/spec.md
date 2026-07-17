## MODIFIED Requirements

### Requirement: The platform SHALL report per-strategy trading readiness

For each strategy, the platform SHALL report a readiness state composed of: indicator seeding
completeness, bias-input satisfiability, option-chain availability per underlying, broker-mirror
freshness, and leg-to-broker reconciliation. Each component SHALL be `ok`, `degraded` or `blocked`
with a human-readable reason. The composite SHALL be exposed over HTTP and logged once at startup.

The indicator-seeding-completeness component SHALL query the indicator engine using the same
**security identifier** the engine keys its suites by (the numeric security_id), not the underlying
display name. Querying by a key the engine does not recognize (returning an empty seeding summary)
and thereby reporting `ok` regardless of actual convergence is non-conforming — the component MUST
reflect the real seeding state of the strategy's configured indicators.

#### Scenario: An unseeded indicator blocks readiness

- **WHEN** EMA(200) on the 1H timeframe is unseeded at startup
- **THEN** the readiness report marks the indicator component `blocked` with a reason naming the timeframe and period

#### Scenario: Indicator seeding is queried by security_id

- **WHEN** the readiness report builds its indicator-seeding component for a strategy whose
  underlying name differs from its security_id
- **THEN** the seeding summary is requested by the security_id, and an indicator unseeded under that
  security_id blocks the component (it is not silently reported `ok`)

#### Scenario: A stale broker mirror degrades readiness

- **WHEN** the broker mirror's last state refresh is older than the poll interval
- **THEN** the broker component is `degraded` with a reason carrying the timestamp

#### Scenario: A fully ready strategy

- **WHEN** every component is satisfied
- **THEN** the composite readiness is `ok` and the startup log records it
