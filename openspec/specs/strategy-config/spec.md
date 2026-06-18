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

### Requirement: YAML serialization for StrategyConfig
`StrategyConfig` SHALL gain two methods: `from_yaml(path: str | Path) -> StrategyConfig` (class
method, loads YAML and calls `from_dict`) and `to_yaml(path: str | Path) -> None` (instance method,
serializes via `to_dict()` and writes YAML). The YAML schema SHALL be the flat dict produced by
`to_dict()` — no nested sections. `PyYAML` SHALL be used (already a transitive dependency).

#### Scenario: from_yaml loads a valid config file
- **WHEN** a YAML file with valid StrategyConfig fields exists at the given path
- **THEN** `StrategyConfig.from_yaml(path)` returns a config equal to `StrategyConfig.from_dict(yaml.safe_load(file))`

#### Scenario: to_yaml writes a reloadable file
- **WHEN** `cfg.to_yaml("out.yaml")` is called
- **THEN** the file is created and `StrategyConfig.from_yaml("out.yaml") == cfg`

#### Scenario: from_yaml validates same as from_dict
- **WHEN** a YAML file contains an invalid value (e.g. unsupported timeframe_min=7)
- **THEN** `from_yaml` raises the same validation error as `from_dict`

#### Scenario: from_yaml with missing file
- **WHEN** the path does not exist
- **THEN** raises `FileNotFoundError` with the path in the message (not a generic YAML error)

### Requirement: Per-instrument indicator selection
The strategy configuration SHALL allow a watchlist entry to declare an optional `indicators`
list naming which indicator-suite families to compute for that entry's `security_id` and
timeframes, with optional per-family parameters (for example EMA periods or volume-profile
bucket size). When the list is absent or empty, no indicator-suite families SHALL be computed
for that entry. The indicator engine SHALL compute, per `(security_id, timeframe)`, the union
of families requested across all loaded strategies.

#### Scenario: Watchlist declares indicators
- **WHEN** a watchlist entry declares `indicators: [ema, rsi, vwap]` with periods for EMA
- **THEN** the engine computes EMA (for the given periods), RSI, and VWAP for that entry's
  `(security_id, timeframe)` and no other families

#### Scenario: No indicators declared
- **WHEN** a watchlist entry omits the `indicators` list
- **THEN** the engine computes no indicator-suite families for that entry

### Requirement: Opt-in ML signal consumption
The strategy configuration SHALL allow a watchlist entry to opt into the `candlestick-ml-signals`
signal for its `security_id` and timeframes, including which trained model version to serve. When
not opted in, no ML model SHALL be loaded or served for that entry, and the entry's existing
indicator selection SHALL be unaffected.

#### Scenario: Watchlist opts into the ML signal
- **WHEN** a watchlist entry enables the ML signal with a model version for a timeframe
- **THEN** that model version is loaded and `ml_signal(sid, tf)` returns its output for that entry

#### Scenario: ML signal not requested
- **WHEN** a watchlist entry does not enable the ML signal
- **THEN** no ML model is loaded for that entry and `ml_signal(sid, tf)` returns `None`
