## ADDED Requirements

### Requirement: YAML config files for named backtest strategies
The system SHALL support named backtest strategy configurations stored as YAML files under
`backtest/configs/*.yaml`. Each file SHALL serialize the complete `StrategyConfig` field set
(same keys as `StrategyConfig.to_dict()`). At minimum, two configs SHALL ship with the repo:
`st10_15m_otm1.yaml` (the promoted config, ST(10,2)/15m/OTM1) and `st3_1_5m_otm1.yaml`
(the legacy anchor baseline, ST(3,1)/5m/OTM1).

#### Scenario: Load promoted config from YAML
- **WHEN** `StrategyConfig.from_yaml("backtest/configs/st10_15m_otm1.yaml")` is called
- **THEN** returns a `StrategyConfig` with st_period=10, st_multiplier=2.0, timeframe_min=15, moneyness=1

#### Scenario: Load baseline anchor from YAML
- **WHEN** `StrategyConfig.from_yaml("backtest/configs/st3_1_5m_otm1.yaml")` is called
- **THEN** returns a `StrategyConfig` with st_period=3, st_multiplier=1.0, timeframe_min=5, moneyness=1

#### Scenario: YAML round-trip
- **WHEN** a `StrategyConfig` is serialized with `to_yaml(path)` and reloaded with `from_yaml(path)`
- **THEN** the reloaded config is equal to the original

#### Scenario: Missing file raises clear error
- **WHEN** `StrategyConfig.from_yaml("backtest/configs/nonexistent.yaml")` is called
- **THEN** raises `FileNotFoundError` with the missing path in the message

### Requirement: Default config settings entry
The system SHALL provide a `BACKTEST_DEFAULT_CONFIG` environment variable (pydantic-settings field,
default `"backtest/configs/st10_15m_otm1.yaml"`) that `backtest/run.py` and `task backtest` use
when no `--config-file` or `--config` flag is given.

#### Scenario: Default config used when no flag given
- **WHEN** `task backtest` is run with no arguments
- **THEN** `backtest/run.py` loads the config from `BACKTEST_DEFAULT_CONFIG` and prints
  7-day per-trade detail for that config

#### Scenario: Override via --config-file
- **WHEN** `task backtest -- --config-file backtest/configs/st3_1_5m_otm1.yaml`
- **THEN** the anchor baseline config is used regardless of `BACKTEST_DEFAULT_CONFIG`

### Requirement: backtest/ folder layout documented
The system SHALL include `backtest/CLAUDE.md` documenting: folder purpose, list of files
(`run.py`, `compare.py`, `configs/`), how to add a new config YAML, how to run single-config
detail vs grid sweep, and the frontend-seam note (YAML shape = future API request body).

#### Scenario: CLAUDE.md exists and is accurate
- **WHEN** a developer opens `backtest/CLAUDE.md`
- **THEN** they can determine within 30 seconds how to run a backtest for a named config
  and how to add a new config file
