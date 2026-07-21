## MODIFIED Requirements

### Requirement: The platform SHALL report per-strategy trading readiness

For each strategy, the platform SHALL report a readiness state composed of: indicator seeding
completeness, bias-input satisfiability, option-chain availability per underlying, broker-mirror
freshness, and leg-to-broker reconciliation. Each component SHALL be `ok`, `degraded` or `blocked`
with a human-readable reason. The composite SHALL be exposed over HTTP and logged once at startup.

The leg-to-broker reconciliation component SHALL reflect the *current* memory-vs-broker state on
each evaluation. A leg-lot divergence that has since healed (in-memory lots and broker net_qty
agree again) SHALL clear from the reconciliation state on the next reconcile pass and return the
component to `ok`; a divergence SHALL NOT latch for the remainder of the session after the
underlying mismatch is gone. Alert emission for a divergence SHALL remain rate-limited to once per
distinct `(security_id, memory_lots, broker_lots)` shape per session, independent of the readiness
state clearing.

#### Scenario: An unseeded indicator blocks readiness

- **WHEN** EMA(200) on the 1H timeframe is unseeded at startup
- **THEN** the readiness report marks the indicator component `blocked` with a reason naming the timeframe and period

#### Scenario: A transient leg divergence clears when the mismatch heals

- **WHEN** an in-memory leg's lots briefly disagree with the broker's net_qty (e.g. a fill-timing
  race right after entry) and the reconcile pass flags a divergence, blocking the Reconciliation
  component
- **AND** a later reconcile pass finds the in-memory lots and broker net_qty agree again
- **THEN** the divergence is removed from the reconciliation state and the Reconciliation component
  returns to `ok`, without requiring a process restart
- **AND** no additional `LEG_STATE_DIVERGED` alert is emitted for a shape already alerted this session

#### Scenario: A persistent leg divergence stays blocked and alerts once

- **WHEN** an in-memory leg's lots disagree with the broker's net_qty and remain diverged across
  multiple reconcile passes
- **THEN** the Reconciliation component stays `blocked` and `LEG_STATE_DIVERGED` is emitted exactly
  once for that `(security_id, memory_lots, broker_lots)` shape for the session

#### Scenario: A stale broker mirror degrades readiness

- **WHEN** the broker mirror's last state refresh is older than the poll interval
- **THEN** the broker component is `degraded` with a reason carrying the timestamp

#### Scenario: A fully ready strategy

- **WHEN** every component is satisfied
- **THEN** the composite readiness is `ok` and the startup log records it
