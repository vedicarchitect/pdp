## MODIFIED Requirements

### Requirement: Sufficient warmup history before the first live bar

The startup warmup SHALL ensure enough historical bars are seeded to establish a stable SuperTrend
direction — at least a full prior trading session — before the first live bar is processed. When the
local store holds too few bars to cover the required depth, the warmup SHALL top up the missing
history, preferring a source that does not depend on a live intraday API call, and persist it; when
no source can supply the history, the tracker MAY cold-start, and this fallback SHALL be logged.

For a **derivable higher timeframe** (15-minute, 30-minute, 1-hour), the warmup SHALL derive the
missing bars from the 1-minute series already in the local store, using the same session-anchored
bucketing the live aggregator uses, and SHALL persist and seed those derived bars **instead of**
calling the intraday provider API. The warmup SHALL fall back to the provider only when the
1-minute coverage is itself insufficient to derive the required depth.

Before seeding a derivable higher timeframe, the warmup SHALL also **reconcile** the stored bars
against a 1-minute-derived rollup of the same window, independent of whether the stored count meets
the required depth: if the stored series holds a duplicate or misaligned bar at any session-anchored
boundary, or is missing a boundary the 1-minute series covers, the warmup SHALL replace the stored
window with the 1-minute-derived bars before seeding, and SHALL log the discrepancy found. When the
stored series already agrees with the 1-minute-derived rollup, the warmup SHALL seed from the
existing stored bars without rewriting them.

When the warmup does fetch intraday history from the provider, it SHALL request the window in
chunks no larger than the provider's per-request intraday limit (90 calendar days), so a lookback
window wider than that limit is fetched in pieces rather than failing as a whole. A single failed
chunk SHALL be logged and skipped without discarding the chunks that did succeed.

#### Scenario: Thin higher-timeframe store is derived from 1m, not the API

- **WHEN** the 30-minute store holds fewer bars than required but the 1-minute series covers the
  window, and provider credentials are set
- **THEN** the warmup derives the 30-minute bars from the 1-minute series, persists and seeds them,
  and does not call the intraday provider API

#### Scenario: Duplicate bars from a feed-restart race are reconciled before seeding

- **WHEN** the 15-minute store holds duplicate bars at one or more session-anchored boundaries (for
  example, a flush/late-tick race produced two closes for the same bucket), and the count of stored
  bars is at or above the required depth
- **THEN** the warmup still compares the stored series against the 1-minute-derived rollup, detects
  the duplication, replaces the stored window with the 1-minute-derived bars, logs the discrepancy,
  and seeds the tracker from the reconciled bars

#### Scenario: A mid-session gap left by a dropped feed is reconciled before seeding

- **WHEN** the 15-minute store is missing one or more session-anchored boundaries that the
  1-minute series covers (for example, the feed died mid-session and an in-flight higher-timeframe
  bucket was never persisted), regardless of whether the overall stored count still meets the
  required depth
- **THEN** the warmup fills the missing boundaries from the 1-minute-derived rollup, persists the
  reconciled window, logs the discrepancy, and seeds the tracker from the reconciled bars

#### Scenario: A healthy, already-consistent store is not rewritten

- **WHEN** the stored higher-timeframe bars already agree with the 1-minute-derived rollup for the
  same window
- **THEN** the warmup seeds from the existing stored bars and does not delete or rewrite them

#### Scenario: Missing 1m coverage falls back to a chunked provider fetch

- **WHEN** the 30-minute store is short and the 1-minute series is also absent for the window
- **THEN** the warmup fetches intraday history from the provider in ≤90-calendar-day chunks and
  seeds the tracker with it

#### Scenario: Provider window wider than the intraday cap is chunked

- **WHEN** the warmup lookback for an intraday timeframe exceeds 90 calendar days
- **THEN** the provider intraday endpoint is called once per ≤90-day sub-window, not once for the
  whole span, and the results are concatenated

#### Scenario: No source falls back to cold start with a log

- **WHEN** the required history is absent locally, cannot be derived from 1m, and no provider is
  available
- **THEN** the tracker cold-starts and the warmup logs that history was unavailable
