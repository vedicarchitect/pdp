## ADDED Requirements

### Requirement: Per-expiry option-chain coverage

The coverage system SHALL report option-chain completeness per `(underlying, expiry_date)`,
not only per trading day. For each underlying it SHALL group `option_bars` by `expiry_date`
and report, for every expiry, whether a complete chain exists (strikes/contracts present
across the expected range) or a gap, so that a phantom expiry (claimed but with no stored
chain) or a real expiry with a missing chain is surfaced rather than hidden behind a per-day
aggregate.

#### Scenario: A claimed expiry with no chain is flagged

- **WHEN** per-expiry coverage is computed for an underlying
- **AND** an expiry is claimed upstream but no `option_bars` chain exists for it
- **THEN** that expiry is reported as missing/gapped in the per-expiry coverage breakdown

#### Scenario: A real expiry with a partial chain is flagged

- **WHEN** per-expiry coverage is computed for an underlying
- **AND** an expiry has some but not the full expected strike coverage
- **THEN** that expiry is reported as a partial/gap chain, distinct from a complete one

#### Scenario: Per-expiry breakdown is exposed via the coverage API and audit script

- **WHEN** the coverage API (or `scripts/audit_options_coverage.py`) is queried for an
  underlying
- **THEN** the response includes a per-expiry breakdown listing each expiry with its
  complete-vs-gap status
