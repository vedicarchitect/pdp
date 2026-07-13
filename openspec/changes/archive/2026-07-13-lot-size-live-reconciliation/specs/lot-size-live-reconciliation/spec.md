## ADDED Requirements

### Requirement: Live/paper strategies SHALL size orders from the current scrip-master lot size

`DirectionalStrangle` (and any future live strategy sizing options) SHALL resolve the exchange
lot size for its underlying from the `instruments` table (the Dhan scrip master) rather than from
a static value in its YAML config. The resolution SHALL happen once per IST trading day, at
session start, and the resulting value SHALL be used for all sizing, MTM, and position-qty
interpretation for that day.

#### Scenario: Lot size resolves from the instruments table at session start

- **WHEN** the strategy starts a new IST trading day and the `instruments` table has option rows
  for its underlying
- **THEN** `self._lot_size` is set to the `lot_size` value carried by those rows, not to any value
  read from YAML

#### Scenario: Lot size persists for the day without per-bar lookups

- **WHEN** the strategy processes bars throughout a trading day after resolving lot size at
  session start
- **THEN** no further `instruments` table query for lot size occurs until the next trading day's
  session start

#### Scenario: A lot-size change between trading days is picked up without a restart

- **WHEN** the scrip master's lot size for an underlying differs between two consecutive trading
  days (e.g. after an NSE/BSE circular takes effect) and the strategy process has stayed running
  across both days
- **THEN** the second day's session-start resolution uses the new lot size, with no code deploy or
  process restart required

### Requirement: YAML-configured lot size SHALL be advisory only, never authoritative

If a strategy's YAML config specifies a `lot_size`, it SHALL be used only as a startup sanity
check compared against the resolved scrip-master value. It SHALL NOT be used for sizing, and a
mismatch SHALL NOT block trading.

#### Scenario: YAML value present and matches — no-op

- **WHEN** the YAML config specifies a `lot_size` equal to the resolved scrip-master value
- **THEN** no warning is logged and trading proceeds normally using the resolved value

#### Scenario: YAML value present and disagrees with the scrip master

- **WHEN** the YAML config specifies a `lot_size` different from the resolved scrip-master value
- **THEN** a `WARNING` is logged, an event is emitted for visibility, and the strategy still sizes
  orders using the resolved scrip-master value, not the YAML value

#### Scenario: YAML value absent

- **WHEN** the YAML config has no `lot_size` key
- **THEN** the strategy resolves and uses the scrip-master value with no warning

### Requirement: An unresolvable lot size SHALL block new entries, not silently size orders wrong

The strategy SHALL NOT fall back to any hardcoded default lot size and SHALL NOT place new entry
orders for an underlying whose lot size is unresolved. If the `instruments` table has no option
row for the underlying at session start, the value is unresolved until a later resolution
succeeds.

#### Scenario: Empty instruments table blocks new entries

- **WHEN** session start resolution finds zero option rows for the underlying in the `instruments`
  table
- **THEN** the strategy marks new-entry trading for that underlying as degraded, emits an alert,
  and does not place any new entry order until a subsequent resolution succeeds

#### Scenario: Existing open legs are still manageable during a degraded period

- **WHEN** new-entry trading is degraded for an underlying due to unresolved lot size
- **THEN** exit/close logic for already-open legs continues to use the last successfully resolved
  lot size, so open positions are not stranded

#### Scenario: Recovery is automatic once resolution succeeds

- **WHEN** the `instruments` table is populated (e.g. `InstrumentLoader` runs) after a period of
  degraded new-entry trading
- **THEN** the next session-start resolution succeeds and new-entry trading resumes without manual
  intervention
