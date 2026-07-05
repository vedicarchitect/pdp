## MODIFIED Requirements

### Requirement: Self-healing gap-fill per underlying
The periodic gap-backfill loop inside `WarehouseService` SHALL run for each configured underlying
independently, passing the correct `underlying`, `underlying_sid`, and `strike_step` to
`gap_backfill.backfill_gaps()`. Because `multi-index-options-backfill` has landed, BANKNIFTY and
SENSEX SHALL be self-healed in the background like NIFTY — the previous "skip non-NIFTY with a
warning" behavior is removed. An underlying SHALL only be skipped if its expiry-calendar cache is
missing, in which case a clear warning naming the missing file is logged.

#### Scenario: Gap-heal runs per underlying
- **WHEN** `WAREHOUSE_UNDERLYINGS=["NIFTY","BANKNIFTY"]` and the gap-heal interval fires
- **THEN** `backfill_gaps()` is called once for NIFTY and once for BANKNIFTY with the correct params for each

#### Scenario: BANKNIFTY/SENSEX are no longer skipped
- **WHEN** the gap-heal interval fires with SENSEX configured and its expiry cache present
- **THEN** SENSEX missing days are backfilled in the background rather than skipped with a "not implemented" warning

#### Scenario: A missing expiry cache is skipped with a clear warning
- **WHEN** an underlying is configured but its expiry-calendar cache file is missing
- **THEN** that underlying's gap-heal is skipped and a warning naming the missing file is logged
