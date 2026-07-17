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

### Requirement: Persistent expiry calendar as the backfill's labelling source

Because Dhan's `expired_options_data` returns option bars with no expiry date, the backfill SHALL
label each fetched series from a persistent, editable `expiry_calendar` store (MongoDB) rather than
a static JSON cache that shares `option_bars`' own coverage gaps. The store SHALL hold, per
`(underlying, flag, expiry_date)`, the real expiries observed in `option_bars` (WEEK = every real
expiry, MONTH = the last real expiry of each calendar month) plus any explicitly-confirmed dates,
and SHALL be kept current from the daily scrip-master refresh. The backfill SHALL be able to cover
the full expiry ladder from the near weeklies through at least the next-month monthly by fetching
both `WEEK` and `MONTH` `expiry_flag`s (Dhan caps `expiry_code` at 0-3 per flag).

#### Scenario: A previously-missing expiry becomes labellable once seeded

- **WHEN** a confirmed real expiry that is absent from `option_bars` is added to the `expiry_calendar`
  store
- **THEN** the backfill resolves trade days in that expiry's window to it and labels the fetched
  bars with that expiry date, instead of forward-filling them onto a far-side expiry

#### Scenario: The ladder spans weekly and monthly expiries

- **WHEN** the one-shot backfill runs with its default ladder
- **THEN** it fetches the near `WEEK` expiries and the current/next `MONTH` expiries, each stored
  with its own `expiry_flag`, so coverage extends from the nearest weekly through at least the
  next-month monthly

### Requirement: Authoritative expiry seed from exchange bhavcopy archives

The `expiry_calendar` store SHALL be seedable from the authoritative exchange bhavcopy archives
rather than only from `option_bars` (which cannot supply dates it is itself missing). The seeder
SHALL be exchange-aware — routing NSE-listed underlyings (NIFTY, BANKNIFTY) to the NSE F&O archive
and BSE-listed underlyings (SENSEX) to the BSE F&O archive — and SHALL read both the legacy and the
UDiFF bhavcopy formats. Each seeded expiry SHALL be enriched, where the source row provides it, with
its weekday (name and index) and lot size, so downstream strategies can map expiries to existing
`option_bars` by weekday-regime and contract size. Seeding from the archive is a one-time historical
operation; forward contracts SHALL continue to be populated by the daily scrip-master refresh.

#### Scenario: A genuinely-missing expiry date is recoverable from the archive

- **WHEN** an underlying's `option_bars` is missing a real expiry entirely (a cadence gap)
- **AND** the archive seeder is run for that underlying
- **THEN** the missing expiry's real date is read from the exchange bhavcopy and upserted into
  `expiry_calendar`, making the gap labellable without guessing the date from cadence

#### Scenario: A seeded expiry carries weekday and lot metadata

- **WHEN** an expiry is upserted from a bhavcopy row that includes its lot size
- **THEN** the stored calendar document records the expiry's weekday name, weekday index, and lot
  size alongside the date, and re-running the seed does not overwrite the original source/confirm
  provenance
