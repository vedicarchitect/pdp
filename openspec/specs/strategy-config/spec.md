# strategy-config Specification

## Purpose
TBD - created by archiving change configurable-strategy-backtest-sweep. Update Purpose after archive.
## Requirements
### Requirement: Strategy configuration object
The system SHALL provide a serializable `StrategyConfig` (a dataclass in
`src/pdp/backtest/strategy_config.py`) that captures every SuperTrend option-selling knob and is
constructable from a plain dict via `StrategyConfig.from_dict(...)`. The object SHALL hold at least:
SuperTrend `st_period` and `st_multiplier`; signal `timeframe_min`; strike `moneyness` (signed int,
`>0` OTM, `0` ATM, `<0` ITM) and `strike_step`; `base_lots`, `add_lots`, `max_lots`, `lot_size`;
`start_ist` and `squareoff_ist`; risk `leg_stop_per_lot` and `day_stop`; `roll_enabled`,
`roll_trigger_prem`, `roll_target_min_prem`; `scale_in_gate` mode; and `flip_mode`. It SHALL NOT
contain profit-lock or ST-touch settings.

#### Scenario: Build config from a dict
- **WHEN** `StrategyConfig.from_dict({...})` is called with a subset of keys
- **THEN** the returned config has those values set and documented defaults for all unspecified keys

#### Scenario: Defaults reproduce the legacy baseline
- **WHEN** a config is built with the legacy values (st 3/1, timeframe 5m, moneyness +1 OTM, base 2,
  add 1, max 5, legacy scale-in and flip modes)
- **THEN** the backtest engine driven by that config reproduces the current baseline P&L for the
  same window

#### Scenario: Round-trips to a dict
- **WHEN** a `StrategyConfig` is serialized to a dict and rebuilt with `from_dict`
- **THEN** the rebuilt config equals the original (so the frontend can persist and replay configs)

### Requirement: Configuration validation
`StrategyConfig` SHALL reject incoherent values so a sweep never runs a meaningless combo.

#### Scenario: Lot ordering enforced
- **WHEN** a config is built with `base_lots` or `add_lots` such that lots could exceed `max_lots`
  before any add, or with non-positive `base_lots`
- **THEN** construction raises a validation error naming the offending field

#### Scenario: Timeframe restricted to supported values
- **WHEN** a config specifies a `timeframe_min` outside the supported set (3, 5, 15, 30, 60)
- **THEN** construction raises a validation error

