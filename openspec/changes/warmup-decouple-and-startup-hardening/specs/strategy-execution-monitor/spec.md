## ADDED Requirements

### Requirement: Premarket-warmup readiness signal

The strangle monitor payload SHALL expose whether the standalone premarket warmup job has
run for the current IST trading date, so the execution panel can flag a session that started
without one. The premarket job SHALL record a completion marker keyed by IST date (a Redis
key with a 24-hour expiry); `GET /api/v1/strangle/monitor` SHALL read that marker and include
a global `status.premarket` object reporting `ran_today` (and, when it ran, the run time and
the unseeded-family count).

A missing premarket run SHALL NOT block intraday trading — it is surfaced as an advisory, not
a gate. When the marker is absent (older backend, no `premarket` key on the payload), the
client SHALL treat the state as "ran" so no false warning is shown.

#### Scenario: Monitor reports premarket not run

- **WHEN** no premarket completion marker exists for today's IST date
- **THEN** `GET /api/v1/strangle/monitor` returns `status.premarket.ran_today = false`.

#### Scenario: Monitor reports premarket ran

- **WHEN** the premarket job has recorded today's marker
- **THEN** `GET /api/v1/strangle/monitor` returns `status.premarket.ran_today = true` with
  the recorded run time.

#### Scenario: Execution panel banner reflects the signal

- **WHEN** the payload reports `status.premarket.ran_today = false`
- **THEN** the execution panel renders a prominent banner recommending the premarket job
- **AND** the banner is hidden when `ran_today` is true or the `premarket` field is absent.
