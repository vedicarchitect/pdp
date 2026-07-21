## MODIFIED Requirements

### Requirement: The platform SHALL report per-strategy trading readiness

For each strategy, the platform SHALL report a readiness state composed of: indicator seeding
completeness, bias-input satisfiability, option-chain availability per underlying, broker-mirror
freshness, and leg-to-broker reconciliation. Each component SHALL be `ok`, `degraded` or `blocked`
with a human-readable reason. The composite SHALL be exposed over HTTP and logged once at startup.

Indicator seeding completeness is scoped to families the strategy's own watchlist configures. A
watchlist SHALL NOT configure a volume-anchored indicator family (e.g. `vwap`, `vwma`) against a
security_id whose feed carries no volume (e.g. a spot index) — such a family can never converge and
would permanently block readiness for a value the strategy never consumes. Volume-anchored families
belong on a volume-bearing instrument (e.g. the underlying's futures contract) once that
instrument's bar history exists for both live and backtest.

#### Scenario: An unseeded indicator blocks readiness

- **WHEN** EMA(200) on the 1H timeframe is unseeded at startup
- **THEN** the readiness report marks the indicator component `blocked` with a reason naming the timeframe and period

#### Scenario: A volume-anchored family is not configured on a zero-volume instrument

- **WHEN** a strangle watchlist is authored for an index security_id (spot feed, no volume)
- **THEN** it SHALL NOT include `vwap`/`vwma` against that security_id, since the tracker cannot
  converge and the strategy's bias scoring does not consume it — such families are configured
  only where a volume-bearing sid (e.g. futures) is available and their bar history exists for
  backtest parity

#### Scenario: A stale broker mirror degrades readiness

- **WHEN** the broker mirror's last state refresh is older than the poll interval
- **THEN** the broker component is `degraded` with a reason carrying the timestamp

#### Scenario: A fully ready strategy

- **WHEN** every component is satisfied
- **THEN** the composite readiness is `ok` and the startup log records it
