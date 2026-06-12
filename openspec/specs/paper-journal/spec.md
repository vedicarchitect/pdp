# paper-journal Specification

## Purpose
TBD - created by archiving change add-supertrend-options-strategy. Update Purpose after archive.
## Requirements
### Requirement: Fill recording
The system SHALL record every paper fill (security, side, quantity, fill price, charges,
strategy) into the current IST trading day's journal.

#### Scenario: Fill is journaled
- **WHEN** a paper order fills
- **THEN** an entry is appended to the day's journal with side, qty, fill price, and charges

### Requirement: Daily P&L and progress stats
The system SHALL compute, for a given day, the total premium sold and bought, net premium,
total charges, realized P&L (net of charges), round-trip count, wins, losses, and win-rate.

#### Scenario: Realized P&L net of charges
- **WHEN** a day's fills are fully round-tripped (flat by EOD)
- **THEN** realized P&L equals total sell proceeds minus total buy cost minus total charges

#### Scenario: Win-rate over closed round-trips
- **WHEN** stats are computed
- **THEN** win-rate is the fraction of closed round-trips with positive P&L

### Requirement: Journal query API
The system SHALL expose REST endpoints to fetch a day's journal entries and its rollup stats.

#### Scenario: Fetch the day's journal
- **WHEN** a client calls `GET /api/v1/journal`
- **THEN** the system returns the current day's entries and rollup stats

#### Scenario: Fetch a specific day's stats
- **WHEN** a client calls `GET /api/v1/journal/stats?date=YYYY-MM-DD`
- **THEN** the system returns the rollup stats for that day

