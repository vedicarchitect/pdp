## MODIFIED Requirements

### Requirement: Next-expiry endpoint
`GET /api/v1/intel/next-expiry` SHALL return the upcoming expiry date per configured index
(NIFTY/BANKNIFTY/SENSEX), resolved from the **instruments table** (the Dhan scrip master) as
the smallest option expiry on or after today for that underlying — not from a
forward-projected weekday JSON calendar. Each index SHALL degrade to `available: false` (never
a fabricated date) when the instruments table has no matching expiry.

#### Scenario: Next expiry is resolved per index from real instruments
- **WHEN** `GET /api/v1/intel/next-expiry` is called
- **THEN** each configured index's next expiry date is the real next tradeable expiry from the
  instruments table (BANKNIFTY monthly, SENSEX Tuesday-weekly, NIFTY weekly), not a synthetic
  weekly date

#### Scenario: A missing expiry degrades honestly
- **WHEN** the instruments table has no upcoming expiry for an index (e.g. not yet loaded)
- **THEN** that index returns `available: false` rather than a projected weekday date

### Requirement: India VIX endpoint
`GET /api/v1/intel/vix` SHALL return the current India VIX level and change, sourced from the
existing tick feed's LTP cache for the configured VIX security id. The configured VIX security
id SHALL be included in the live feed subscription/warmup set so that its `ltp:<sid>` cache is
populated during market hours.

#### Scenario: VIX is returned from the live feed
- **WHEN** the VIX security id has a fresh cached tick
- **THEN** `GET /api/v1/intel/vix` returns `available: true` with the current level and change

#### Scenario: VIX is subscribed so the gate has data
- **WHEN** the live feed is running during market hours
- **THEN** the configured VIX security id is subscribed and its `ltp:<sid>` cache is populated,
  so the dashboard VIX section and the bias `vix_gate` see a real value rather than
  "Unavailable"
