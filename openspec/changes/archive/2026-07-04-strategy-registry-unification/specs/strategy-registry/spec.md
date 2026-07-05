## ADDED Requirements

### Requirement: Canonical-id strategy registry
The system SHALL provide a single strategy registry keyed by a canonical strategy id, in the same
style as the live strategy configs (`pdp/strategy/registry.py`), that enumerates the available
strategies across both the live `strategies/*.yaml` configs and the backtest configs
(`backtest/configs/*.yaml`). Each registry entry SHALL expose the canonical id, the engine/kind, the
underlying/index, and the editable parameters with their defaults. A backtest config MAY declare an
explicit canonical `strategy_id`; when absent, the registry SHALL derive a stable id from the config
filename.

#### Scenario: Live and backtest strategies are enumerated under one registry
- **WHEN** the registry is loaded
- **THEN** it returns entries for the live strategies and the backtest configs, each with a canonical id, engine/kind, underlying, and editable params

#### Scenario: A backtest config without an explicit id gets a stable derived id
- **WHEN** a `backtest/configs/*.yaml` file declares no `strategy_id`
- **THEN** the registry assigns it a stable id derived from its filename

### Requirement: Strategy listing API with editable param schema
The system SHALL expose `GET /api/v1/strategies` returning the registered strategies, each with its
canonical id, engine/kind, underlying, and an editable parameter schema (parameter names, types,
defaults, and bounds where known), so a client can render a param editor instead of a raw-JSON box.

#### Scenario: Strategies are listed with a param schema
- **WHEN** `GET /api/v1/strategies` is requested
- **THEN** each strategy is returned with its canonical id, engine/kind, underlying, and an editable param schema with defaults

### Requirement: Add a new strategy and immediately backtest it
The system SHALL allow registering a new strategy configuration (a canonical id + engine/kind +
params) through the registry such that it becomes selectable for a backtest launch without a code
change. A newly registered strategy SHALL be returned by `GET /api/v1/strategies` and be usable as
the target of a backtest launch.

#### Scenario: A newly added strategy is backtestable
- **WHEN** a new strategy config is registered with a canonical id and params
- **THEN** it appears in `GET /api/v1/strategies` and can be selected as the target of a backtest launch

### Requirement: Canonical run identity
The system SHALL map each backtest run's coarse family label to a canonical strategy id from the
registry, so backtest runs, paper trades, and comparisons all key on the same `strategy_id`.

#### Scenario: A run resolves to a canonical strategy id
- **WHEN** a backtest run whose label is a coarse family (e.g. `strangle`) is resolved through the registry
- **THEN** it maps to the canonical strategy id (e.g. `directional_strangle_nifty`) used by the matching live/paper strategy
