## ADDED Requirements

### Requirement: Configurable warehouse underlyings

`WarehouseService` SHALL support a configurable list of underlyings via `settings.WAREHOUSE_UNDERLYINGS` (a `list[str]`, default `["NIFTY"]`). For each underlying in the list it SHALL subscribe to the corresponding index spot feed and the ATM ± N option band, using the correct security ID and strike step for that underlying. Adding `"BANKNIFTY"` or `"SENSEX"` to `WAREHOUSE_UNDERLYINGS` SHALL not require any code changes — only the environment variable.

#### Scenario: Default behaviour is unchanged

- **WHEN** `WAREHOUSE_UNDERLYINGS` is unset or `["NIFTY"]`
- **THEN** the service subscribes only to NIFTY (sid 13, step 50) and behaviour is identical to before this change

#### Scenario: BANKNIFTY added to underlyings

- **WHEN** `WAREHOUSE_UNDERLYINGS=["NIFTY","BANKNIFTY"]`
- **THEN** the service subscribes to both NIFTY (sid 13, step 50) and BANKNIFTY (sid 25, step 100) option bands; closed bars for each are written to `option_bars` with the correct `underlying` and `security_id` fields

---

### Requirement: Per-underlying static config registry

The warehouse module SHALL maintain a static registry mapping each supported underlying name to `(security_id, strike_step, expiry_calendar_path)`. Attempting to configure an unsupported underlying SHALL raise a clear startup error. The supported set SHALL be at minimum `{"NIFTY", "BANKNIFTY", "SENSEX"}`.

#### Scenario: Unsupported underlying rejected at startup

- **WHEN** `WAREHOUSE_UNDERLYINGS=["NIFTY","MIDCAP"]` and `MIDCAP` is not in the registry
- **THEN** the service raises a `ValueError` at startup naming the unsupported symbol, before any Dhan connection is opened

---

### Requirement: Multiplexed tick routing

All Dhan WS subscriptions (across all configured underlyings) SHALL be handled by a single `DhanTickerAdapter` connection. Incoming ticks SHALL be routed to the correct `OptionBarWriter` instance by `security_id`. No tick SHALL be silently dropped if its `security_id` belongs to a subscribed underlying.

#### Scenario: Ticks from two underlyings are routed correctly

- **WHEN** NIFTY (sid 13) and BANKNIFTY (sid 25) are both subscribed and ticks arrive interleaved
- **THEN** each tick is delivered to the writer for its own underlying; no cross-contamination of `underlying` or `security_id` fields occurs in `option_bars`

---

### Requirement: Self-healing gap-fill per underlying

The periodic gap-backfill loop inside `WarehouseService` SHALL run for each configured underlying independently, passing the correct `underlying`, `underlying_sid`, and `strike_step` to `gap_backfill.backfill_gaps()`. This requires `multi-index-options-backfill` to be implemented first; if that change has not landed, gap-heal for BANKNIFTY/SENSEX SHALL be skipped with a warning log.

#### Scenario: Gap-heal runs per underlying

- **WHEN** `WAREHOUSE_UNDERLYINGS=["NIFTY","BANKNIFTY"]` and the gap-heal interval fires
- **THEN** `backfill_gaps()` is called once for NIFTY and once for BANKNIFTY with the correct params for each

---

### Requirement: Removed module-level INDEX_SID constant

The module-level `INDEX_SID` constant in `src/pdp/warehouse/writer.py` SHALL be removed. Any code that previously imported `INDEX_SID` SHALL be updated to use the per-instance underlying config. This includes `src/pdp/warehouse/service.py` and `tests/test_warehouse_feed.py`.

#### Scenario: No INDEX_SID import exists after this change

- **WHEN** `grep -r "INDEX_SID" src/ tests/` is run after implementation
- **THEN** no matches are found
