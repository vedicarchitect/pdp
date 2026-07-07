## MODIFIED Requirements

### Requirement: Input-family gap radar
The system SHALL expose a gap radar that assesses, per (underlying, trade-date), the readiness of
each input family the backtest depends on, promoting the spot-completeness gate in
`pdp/backtest/completeness.py` to a per-family check. The radar SHALL cover only input families
that have a real ingested source and are actually consumed by the strategy: `spot`, `options`,
`vix`, and `levels_weekly`. It SHALL NOT report a `futures` family — futures are not warehoused
and, since VWAP is no longer a bias input, nothing consumes them, so the perpetual
"futures missing" flag is removed rather than emitted as noise. A missing or incomplete family
SHALL be reported with a human-readable label — e.g. "spot missing", "weekly Camarilla missing"
(prior-week spot or `index_levels` gap), "VIX missing" — so the console can render one row per
(index, date, family) with a status.

#### Scenario: A missing input family is flagged
- **WHEN** a trade-date lacks the prior-week spot needed for weekly Camarilla
- **THEN** the radar reports that (index, date) as "weekly Camarilla missing"

#### Scenario: A ready date reports all families present
- **WHEN** a trade-date has complete spot, options, VIX, and levels
- **THEN** the radar reports all families ready for that (index, date)

#### Scenario: No futures family is reported

- **WHEN** the gap radar output is produced for any (index, date)
- **THEN** it contains no `futures` family key and never emits a "futures missing" label
