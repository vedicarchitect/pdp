## MODIFIED Requirements

### Requirement: Backtest CLI invocation
The system SHALL provide `backtest/run.py` as the canonical multi-day backtest runner, replacing
both `backtest_multiday.py` (archived to `scripts/archive/`) and `scripts/backtest_sweep.py`
(moved). The script SHALL accept: `--days N` (window size), `--start YYYY-MM-DD` (end date),
`--config-file <path>` (load a named YAML config), `--config <json>` (inline JSON config),
`--st`, `--tf`, `--moneyness` (grid axes), `--no-commission`, `--no-heal`. When neither
`--config-file` nor `--config` is given and no grid flags are supplied, the script SHALL load
the config from `settings.BACKTEST_DEFAULT_CONFIG` and run single-config detail mode for the
last 7 days.

#### Scenario: Single-config detail — default config
- **WHEN** user runs `task backtest` with no arguments
- **THEN** script loads `BACKTEST_DEFAULT_CONFIG`, runs last-7-day detail, prints per-trade
  table + leg summary + day summary

#### Scenario: Single-config detail — explicit config file
- **WHEN** user runs `task backtest -- --config-file backtest/configs/st3_1_5m_otm1.yaml --days 30`
- **THEN** script loads that YAML, runs 30-day single-config detail

#### Scenario: Single-config detail — inline JSON
- **WHEN** user runs `task backtest -- --config '{"st_period":10,"st_multiplier":2,"timeframe_min":15,"moneyness":1}'`
- **THEN** script parses JSON, runs single-config detail with the specified params

#### Scenario: Grid sweep
- **WHEN** user runs `task backtest:sweep -- --days 90 --st "3,1;10,2" --tf "5,15" --moneyness "1,0,-1"`
- **THEN** script runs the grid and prints a ranked comparison table

#### Scenario: Legacy script archived
- **WHEN** a developer looks for `backtest_multiday.py` at the repo root
- **THEN** it is not present; `scripts/archive/backtest_multiday.py` exists with a header
  comment noting it is superseded by `backtest/run.py`

## ADDED Requirements

### Requirement: Taskfile backtest tasks updated
`task backtest` SHALL invoke `backtest/run.py` (default config, 7-day detail). `task backtest:sweep`
SHALL invoke `backtest/run.py` with pass-through CLI args for grid mode. Both SHALL use
`uv run python backtest/run.py`.

#### Scenario: task backtest runs correctly
- **WHEN** user runs `task backtest` from repo root
- **THEN** `uv run python backtest/run.py` executes with default-config, 7-day detail

#### Scenario: task backtest:sweep passes through args
- **WHEN** user runs `task backtest:sweep -- --days 90 --st "10,2"`
- **THEN** `uv run python backtest/run.py --days 90 --st "10,2"` executes
