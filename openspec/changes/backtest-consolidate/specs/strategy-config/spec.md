## ADDED Requirements

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
