## ADDED Requirements

### Requirement: Paper engine SHALL NOT re-arm stale OPEN orders on boot

On startup, the paper engine SHALL only reload `OPEN` orders placed on the current IST trading day
into its tick-watch list. An `OPEN` order whose `placed_at` falls on a prior IST trading day SHALL be
expired (`status = CANCELLED`, `cancelled_at` set) in the same pass instead of being re-armed to fill
against a future tick.

#### Scenario: Stale OPEN order from a prior day is expired, not reloaded

- **WHEN** the paper engine starts and Postgres has an `OPEN` order whose `placed_at` is on an
  earlier IST trading day
- **THEN** that order transitions to `CANCELLED` with `cancelled_at` set
- **AND** it is not added to the paper engine's tick-watch list, so no future tick can fill it

#### Scenario: OPEN order from today's trading day loads normally

- **WHEN** the paper engine starts and Postgres has an `OPEN` order whose `placed_at` is on the
  current IST trading day
- **THEN** it is added to the tick-watch list unchanged and remains eligible to fill on the next
  matching tick
