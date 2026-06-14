## Why

The backtest tooling has accumulated three overlapping entry points (`backtest_multiday.py` at root, `scripts/backtest_sweep.py`, `scripts/backtest_compare.py`) with duplicate simulation logic and no canonical config format. The new `sim.py` engine fully supersedes `backtest_multiday.py`, but the folder structure and task wiring still point to the old script, creating confusion about what to run and where configs live.

## What Changes

- Archive `backtest_multiday.py` (1248-line monolith superseded by `sim.py` + sweep)
- Create top-level `backtest/` folder as the single home for all backtest tooling
- Move `scripts/backtest_sweep.py` → `backtest/run.py` (sweep + single-config detail)
- Move `scripts/backtest_compare.py` → `backtest/compare.py`
- Introduce YAML-driven config system: `backtest/configs/*.yaml` (one file per named strategy, e.g. `st10_15m_otm1.yaml`)
- Add `StrategyConfig.from_yaml(path)` class method to load configs from YAML
- Update `backtest/run.py` to accept `--config-file <path>` in addition to the existing `--config <json>`
- Add `BACKTEST_DEFAULT_CONFIG` setting pointing to the default config file
- Rewire Taskfile: `task backtest -- [--config-file ...] [--days N]` runs single-config detail; `task backtest:sweep -- [grid flags]` runs the grid
- Create `backtest/CLAUDE.md` documenting folder layout and conventions
- Update root `CLAUDE.md` and `RUNBOOK.md` to reflect new structure

## Capabilities

### New Capabilities
- `backtest-config-yaml`: YAML config files for named backtest strategy configurations; `StrategyConfig.from_yaml()` loader; `BACKTEST_DEFAULT_CONFIG` settings entry; `backtest/configs/` directory with at least the promoted `st10_15m_otm1.yaml`

### Modified Capabilities
- `backtest`: Consolidated entry point (`backtest/run.py`), `--config-file` flag, archived legacy script; task wiring updated
- `backtest-compare`: Moved from `scripts/` to `backtest/compare.py`; task wiring updated
- `strategy-config`: `StrategyConfig` gains `from_yaml()` and `to_yaml()` methods

## Impact

- **Files moved**: `scripts/backtest_sweep.py` → `backtest/run.py`; `scripts/backtest_compare.py` → `backtest/compare.py`; `backtest_multiday.py` → `scripts/archive/`
- **Files created**: `backtest/CLAUDE.md`, `backtest/configs/st10_15m_otm1.yaml`, `backtest/configs/st3_1_5m_otm1.yaml` (anchor baseline)
- **Files modified**: `src/pdp/backtest/strategy_config.py` (add `from_yaml`/`to_yaml`), `src/pdp/settings.py` (add `BACKTEST_DEFAULT_CONFIG`), `Taskfile.yml`, `CLAUDE.md`, `RUNBOOK.md`, `src/pdp/backtest/CLAUDE.md`
- **Future seam**: The YAML shape mirrors the future `POST /api/v1/backtest/run` request body — no API changes in this change, but the structure is intentionally frontend-compatible
- **No logic changes**: `sim.py`, `day_loader.py`, `commissions.py` untouched
