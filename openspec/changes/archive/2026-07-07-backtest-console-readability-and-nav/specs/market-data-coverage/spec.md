## MODIFIED Requirements

### Requirement: Per-underlying, per-family coverage API
The system SHALL expose `GET /api/v1/coverage` that returns, for each configured underlying
(NIFTY, BANKNIFTY, SENSEX) and each market-data family (spot bars, options chain, India VIX,
`index_levels` daily/weekly Camarilla), the earliest and latest available date, the count of
covered trade-days, the gap-day ranges within a requested window, and a coverage percentage. The
computation SHALL reuse the existing gap-detection helpers (`gap_backfill.days_missing`,
`expected_contracts`, `trading_days`) rather than a parallel implementation. The endpoint SHALL
return in under 2 seconds for a 90-day window across all three indices: the per-underlying and
per-family probes SHALL be executed concurrently (not serially), India VIX SHALL be computed once
per request and reused across underlyings (it is index-independent), and the probes SHALL share a
single pooled Mongo client rather than opening a fresh client per probe.

#### Scenario: Coverage is reported per underlying and family
- **WHEN** the coverage endpoint is requested for a date window
- **THEN** for each underlying and family it returns min/max date, covered trade-day count, gap-day ranges, and coverage %

#### Scenario: Coverage returns within the latency budget

- **WHEN** the coverage endpoint is requested for a 90-day window across NIFTY, BANKNIFTY, and
  SENSEX
- **THEN** it returns in under 2 seconds, having run the probes concurrently, computed VIX once,
  and reused a single pooled Mongo client

#### Scenario: VIX is computed once per request

- **WHEN** coverage is computed for all three underlyings in one request
- **THEN** the India VIX family coverage is computed a single time and reused, not recomputed per
  underlying
