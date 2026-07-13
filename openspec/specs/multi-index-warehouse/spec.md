# multi-index-warehouse Specification

## Purpose
TBD - created by archiving change multi-index-warehouse. Update Purpose after archive.
## Requirements
### Requirement: Configurable warehouse underlyings

`WarehouseService` SHALL accept its list of underlyings as an explicit constructor
argument (`underlyings: list[str]`), not read from a settings/environment value. The
caller SHALL derive that list via `pdp.strategy.registry.strategy_underlyings(strategies_dir)`
— the union of every loaded strategy YAML's `params.underlying`. For each underlying in
the list the service SHALL subscribe to the corresponding index spot feed and the ATM ±
N option band, using the correct security ID and strike step for that underlying. Adding
a new underlying SHALL require only adding or editing a strategy YAML — no code change
and no environment-variable edit.

#### Scenario: Default behaviour is unchanged with only a NIFTY strategy configured

- **WHEN** `strategies/` contains only strategy YAMLs with `params.underlying: NIFTY`
- **THEN** the derived underlyings list is `["NIFTY"]` and the service subscribes only to
  NIFTY (sid 13, step 50)

#### Scenario: BANKNIFTY added via a strategy YAML

- **WHEN** a strategy YAML declaring `params.underlying: BANKNIFTY` is added to `strategies/`
  and the warehouse process (re)starts
- **THEN** the derived underlyings list includes `"BANKNIFTY"` and the service subscribes to
  both NIFTY (sid 13, step 50) and BANKNIFTY (sid 25, step 100) option bands; closed bars for
  each are written to `option_bars` with the correct `underlying` and `security_id` fields

---

### Requirement: Per-underlying static config registry

The warehouse module SHALL maintain a static registry mapping each supported underlying name
to `(security_id, strike_step, expiry_calendar_path)`. Attempting to configure an unsupported
underlying (present in the derived `underlyings` list but absent from the registry) SHALL raise
a clear startup error. The supported set SHALL be at minimum `{"NIFTY", "BANKNIFTY", "SENSEX"}`.

#### Scenario: Unsupported underlying rejected at startup

- **WHEN** the derived underlyings list is `["NIFTY", "MIDCAP"]` and `MIDCAP` is not in the
  registry
- **THEN** the service raises a `ValueError` at startup naming the unsupported symbol, before
  any Dhan connection is opened

---

### Requirement: Multiplexed tick routing

All Dhan WS subscriptions (across all configured underlyings) SHALL be handled by a single `DhanTickerAdapter` connection. Incoming ticks SHALL be routed to the correct `OptionBarWriter` instance by `security_id`. No tick SHALL be silently dropped if its `security_id` belongs to a subscribed underlying.

#### Scenario: Ticks from two underlyings are routed correctly

- **WHEN** NIFTY (sid 13) and BANKNIFTY (sid 25) are both subscribed and ticks arrive interleaved
- **THEN** each tick is delivered to the writer for its own underlying; no cross-contamination of `underlying` or `security_id` fields occurs in `option_bars`

---

### Requirement: Self-healing gap-fill per underlying

The periodic gap-backfill loop inside `WarehouseService` SHALL run for each underlying in its
constructor-provided `underlyings` list independently, passing the correct `underlying`,
`underlying_sid`, and `strike_step` to `gap_backfill.backfill_gaps()`. BANKNIFTY and SENSEX
SHALL be self-healed in the background like NIFTY whenever they are present in that list. An
underlying SHALL only be skipped if its expiry-calendar cache is missing, in which case a
clear warning naming the missing file is logged.

#### Scenario: Gap-heal runs per underlying

- **WHEN** the service was constructed with `underlyings=["NIFTY","BANKNIFTY"]` and the
  gap-heal interval fires
- **THEN** `backfill_gaps()` is called once for NIFTY and once for BANKNIFTY with the correct
  params for each

#### Scenario: A missing expiry cache is skipped with a clear warning

- **WHEN** an underlying is present in the constructor-provided `underlyings` list but its
  expiry-calendar cache file is missing
- **THEN** that underlying's gap-heal is skipped and a warning naming the missing file is logged

### Requirement: Removed module-level INDEX_SID constant

The module-level `INDEX_SID` constant in `src/pdp/warehouse/writer.py` SHALL be removed. Any code that previously imported `INDEX_SID` SHALL be updated to use the per-instance underlying config. This includes `src/pdp/warehouse/service.py` and `tests/test_warehouse_feed.py`.

#### Scenario: No INDEX_SID import exists after this change

- **WHEN** `grep -r "INDEX_SID" src/ tests/` is run after implementation
- **THEN** no matches are found

