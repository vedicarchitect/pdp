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

When the warmup does fetch intraday history from the provider, it SHALL request the window in
chunks no larger than the provider's per-request intraday limit (90 calendar days), so a lookback
window wider than that limit is fetched in pieces rather than failing as a whole. A single failed
chunk SHALL be logged and skipped without discarding the chunks that did succeed.

#### Scenario: Thin higher-timeframe store is derived from 1m, not the API

- **WHEN** the 30-minute store holds fewer bars than required but the 1-minute series covers the
  window, and provider credentials are set
- **THEN** the warmup derives the 30-minute bars from the 1-minute series, persists and seeds them,
  and does not call the intraday provider API

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
