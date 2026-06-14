## 1. Folder skeleton + YAML configs

- [ ] 1.1 Create `backtest/` folder at repo root and `backtest/configs/` subfolder
- [ ] 1.2 Write `backtest/configs/st10_15m_otm1.yaml` — promoted config (ST(10,2)/15m/OTM1, stops 3000/20000)
- [ ] 1.3 Write `backtest/configs/st3_1_5m_otm1.yaml` — legacy anchor baseline (ST(3,1)/5m/OTM1, stops 3000/20000)
- [ ] 1.4 Create `backtest/CLAUDE.md` documenting folder layout, how to run, how to add a config, frontend-seam note

## 2. StrategyConfig YAML I/O

- [ ] 2.1 Add `from_yaml(path: str | Path) -> StrategyConfig` classmethod to `src/pdp/backtest/strategy_config.py` — reads YAML, calls `from_dict`; raises `FileNotFoundError` with path on missing file
- [ ] 2.2 Add `to_yaml(path: str | Path) -> None` instance method — calls `to_dict()`, writes with `yaml.safe_dump`
- [ ] 2.3 Add unit tests in `tests/backtest/test_strategy_sweep.py`: round-trip YAML, missing file error, invalid-value propagation

## 3. Settings

- [ ] 3.1 Add `BACKTEST_DEFAULT_CONFIG: str = "backtest/configs/st10_15m_otm1.yaml"` to `src/pdp/settings.py` (BacktestSettings or top-level Settings — wherever backtest commission settings live)
- [ ] 3.2 Add the env var to `.env.example` with a comment

## 4. backtest/run.py (move + extend backtest_sweep.py)

- [ ] 4.1 Copy `scripts/backtest_sweep.py` to `backtest/run.py`
- [ ] 4.2 Fix `sys.path.insert` — change `"src"` to `os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src")` (already correct in sweep; verify path is `../../src` from new location)
- [ ] 4.3 Add `--config-file <path>` argument to `argparse` in `backtest/run.py`
- [ ] 4.4 In the single-config branch: if `--config-file` is given, load via `StrategyConfig.from_yaml(path)`; if `--config` JSON is given, use existing path; if neither, load `settings.BACKTEST_DEFAULT_CONFIG`
- [ ] 4.5 Add `--days` default of 7 when running in auto-default mode (no explicit config/grid flags)
- [ ] 4.6 Smoke-test: `uv run python backtest/run.py --days 3 --no-heal` (should print grid table)
- [ ] 4.7 Smoke-test: `uv run python backtest/run.py --config-file backtest/configs/st10_15m_otm1.yaml --days 3 --no-heal` (should print per-trade detail)

## 5. backtest/compare.py (move backtest_compare.py)

- [ ] 5.1 Copy `scripts/backtest_compare.py` to `backtest/compare.py`
- [ ] 5.2 Fix `sys.path.insert` path relative to new location (`../src`)
- [ ] 5.3 Smoke-test: `uv run python backtest/compare.py --date 2026-06-12`

## 6. Taskfile wiring

- [ ] 6.1 Change `backtest` task: desc = "7-day per-trade detail for the default config (BACKTEST_DEFAULT_CONFIG)"; cmd = `uv run python backtest/run.py {{.CLI_ARGS}}`
- [ ] 6.2 Change `backtest:sweep` task: desc = "Multi-config parameter sweep — pass grid flags after --"; cmd = `uv run python backtest/run.py {{.CLI_ARGS}}`
- [ ] 6.3 Change `backtest:compare` task: cmd = `uv run python backtest/compare.py {{.CLI_ARGS}}`

## 7. Archive old scripts

- [ ] 7.1 Move `backtest_multiday.py` → `scripts/archive/backtest_multiday.py`; add header comment: `# ARCHIVED 2026-06-14 — superseded by backtest/run.py (sim.py + StrategyConfig). Kept for reference only.`
- [ ] 7.2 Remove `scripts/backtest_sweep.py` (content moved to `backtest/run.py`)
- [ ] 7.3 Remove `scripts/backtest_compare.py` (content moved to `backtest/compare.py`)

## 8. Docs update

- [ ] 8.1 Update root `CLAUDE.md`: remove `backtest_multiday.py` row from module index; add `backtest/` row; update Key Commands to show `task backtest -- [--config-file ...]`
- [ ] 8.2 Overhaul `RUNBOOK.md` §8: replace "Main multi-day backtest runner" section with `task backtest` / `task backtest:sweep` / `task backtest:compare` referencing `backtest/run.py` and config files; remove references to editing module-level constants
- [ ] 8.3 Update `src/pdp/backtest/CLAUDE.md`: mark `sim.py` as the active NIFTY simulation engine; note `engine.py` is the generic strategy-replay framework; add `strategy_config.py` + `day_loader.py` to active files; remove stale references to `backtest_full_day.py` / `backtest_today.py` as top-level scripts

## 9. Verify

- [ ] 9.1 Run `task test` — all existing tests pass
- [ ] 9.2 Run `task backtest -- --days 3 --no-heal` — prints 3-day per-trade detail for promoted config
- [ ] 9.3 Run `task backtest:sweep -- --days 3 --st "3,1;10,2" --tf "5,15" --moneyness "1" --no-heal` — prints 6-row comparison table
- [ ] 9.4 Run `task backtest:compare -- --date 2026-06-12` — runs without error
