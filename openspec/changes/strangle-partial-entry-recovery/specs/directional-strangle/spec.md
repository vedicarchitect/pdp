## ADDED Requirements

### Requirement: A required leg-side that fails to open SHALL be recovered within the same bucket

The live directional-strangle strategy SHALL track, for the current bias bucket, the intended
short-lot count for each side (PE and CE) and which sides have been *realized* — successfully opened
at least one short leg during the current bucket episode. On every subsequent decision bar for which
the bucket is unchanged, new entries are allowed (past the entry-after time, not gated, not
`neutral_no_trade` in a neutral bucket, lot size not degraded), the strategy SHALL attempt to open
any side that the bucket requires (intended lots > 0) that currently has **no open short leg** and
has **not** been realized this episode. Recovery SHALL reuse the normal short-open path so the per-
security lock, the position-lot cap, and the protective hedge all still apply. The intended-
composition tracking and the realized-side set SHALL reset when the bucket changes.

A side that was opened and then deliberately closed this episode — by take-profit, by a premium
stop (which gates the side), or by a roll — SHALL NOT be recovered: recovery applies only to a side
that never successfully opened. Recovery SHALL be bounded to `entry_recovery_max_attempts` attempts
(default 3) per side per bucket episode; each attempt SHALL be logged, and when the bound is reached
the strategy SHALL emit a terminal `ENTRY_SIDE_UNFILLED` event for that side and stop retrying it
until the next bucket change. Recovery SHALL be enabled by default and disableable via
`entry_recovery_enabled`. This behavior is live-only; the backtest simulator is unaffected.

#### Scenario: Aborted side is retried on the next bar and completes the strangle

- **GIVEN** a confirmed neutral bucket whose ratio requires a PE and a CE short leg
- **AND** the CE short opens successfully but the PE short aborts because its entry price cannot be
  resolved (all fill-price layers cold, `fill_avg_px_zero`)
- **WHEN** the next decision bar is processed with the bucket unchanged and entries allowed
- **THEN** the strategy SHALL attempt to open the PE short again
- **AND** on success the book SHALL hold both the PE and CE shorts (each with its hedge) as the
  bucket intended

#### Scenario: A fully-aborted entry recovers both sides

- **GIVEN** a confirmed bucket requiring PE and CE shorts where **both** sides aborted on entry
  (e.g. every target contract was cold immediately after a feed reconnect) leaving the book flat
- **WHEN** subsequent decision bars are processed with the bucket unchanged and entries allowed
- **THEN** the strategy SHALL attempt each unrealized side and open it once a price resolves

#### Scenario: A side closed by take-profit is not resurrected

- **GIVEN** a bucket whose PE short opened, was realized, and was then closed by take-profit
- **WHEN** later decision bars are processed with the bucket unchanged
- **THEN** the strategy SHALL NOT re-open the PE side, because it was realized and deliberately exited

#### Scenario: A stop-gated side is not recovered

- **GIVEN** a bucket whose CE short opened and then hit a premium stop, placing CE in the stop gate
- **WHEN** later decision bars are processed with the bucket unchanged
- **THEN** recovery SHALL skip the CE side while it is stop-gated (stop-recovery cooldown owns re-entry)

#### Scenario: Recovery is bounded and surfaced

- **GIVEN** a required side that keeps aborting (its contract stays unpriceable)
- **WHEN** recovery has attempted that side `entry_recovery_max_attempts` times in the episode
- **THEN** the strategy SHALL emit `ENTRY_SIDE_UNFILLED` for that side and stop retrying it until the
  next bucket change

#### Scenario: A bucket change resets recovery state

- **GIVEN** a side marked unrecoverable (bound reached) in the current bucket episode
- **WHEN** the bias bucket changes and is confirmed
- **THEN** the intended composition, realized-side set, and per-side attempt counters SHALL reset so
  the new bucket's legs are opened and tracked afresh
