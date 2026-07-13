## ADDED Requirements

### Requirement: Expiry-cadence gap detection

The coverage system SHALL detect when the distinct set of claimed expiries for an underlying
(as returned by `real_expiries_from_option_bars`) has a gap larger than that underlying's
expected listing cadence (7 days for a weekly-expiry underlying, 28-35 days for a monthly-only
underlying), distinct from the existing per-expiry chain-completeness check. A cadence gap means
an expiry that should have been listed and ingested is entirely absent from the distinct set —
not merely incomplete — so `nearest_real_expiry()` silently forward-fills trade days across it to
a far-side expiry with no logged signal. The detector SHALL report each cadence gap as
`(underlying, gap_start, gap_end, gap_days)` and SHALL distinguish a gap from a legitimate
lower-cadence stretch (e.g. a monthly-only underlying, or a real holiday-shifted listing) using
the underlying's configured expected cadence rather than a single global threshold.

#### Scenario: A missing weekly expiry is flagged as a cadence gap

- **WHEN** expiry-cadence coverage is computed for a weekly-expiry underlying
- **AND** two consecutive claimed expiries are more than 10 days apart
- **THEN** the stretch between them is reported as a cadence gap, separate from per-expiry chain
  completeness

#### Scenario: A monthly-only underlying's normal cadence is not flagged

- **WHEN** expiry-cadence coverage is computed for an underlying configured with a 28-35 day
  expected cadence
- **AND** two consecutive claimed expiries are 30 days apart
- **THEN** no cadence gap is reported for that stretch

#### Scenario: A backtest run surfaces cadence-gap trade days instead of silently forward-filling

- **WHEN** `strangle_run.py` resolves a trade day's expiry via `nearest_real_expiry()`
- **AND** the resolved expiry falls inside a detected cadence gap
- **THEN** the run's per-chunk summary counts that day as "resolved to a cadence-gap expiry"
  rather than reporting it identically to an ordinary valid or skipped day
