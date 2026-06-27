## 1. Expiry calendar generalisation (prerequisite)

- [x] 1.1 Check whether `NiftyExpiryCalendar` can be trivially subclassed or if a generic `ExpiryCalendar` base is needed — if BANKNIFTY shares the same OI-reset detection logic, extend; otherwise add a `SymbolExpiryCalendar.load(symbol, path)` factory in `src/pdp/instruments/expiry_calendar.py`
- [x] 1.2 Build BANKNIFTY expiry cache — run OI-reset detection (or derive from Dhan instrument master) and write `data/expiry/banknifty_expiries.json`
- [x] 1.3 Build SENSEX expiry cache — same approach, write `data/expiry/sensex_expiries.json`
- [x] 1.4 Add `BANKNIFTY_EXPIRY_CACHE_PATH` and `SENSEX_EXPIRY_CACHE_PATH` to `src/pdp/settings.py` (defaults: `data/expiry/banknifty_expiries.json`, `data/expiry/sensex_expiries.json`)

## 2. Core library parameterisation

- [x] 2.1 In `src/pdp/options/gap_backfill.py`: add `underlying: str`, `underlying_sid: int`, `strike_step: int` as explicit parameters to `backfill_gaps()` (and thread them through to `_fetch_day`, `_derive_strike`, and any other helper that uses these values)
- [x] 2.2 Remove or convert the module-level `UNDERLYING = "NIFTY"`, `UNDERLYING_SID = 13`, `STEP = 50` constants to function-local defaults so no caller relies on the old module-level values
- [x] 2.3 Update `src/pdp/warehouse/service.py` gap-heal call site to pass `underlying`, `underlying_sid`, `strike_step` explicitly (preserves current NIFTY behaviour)
- [x] 2.4 Update the type hint `NiftyExpiryCalendar` in `gap_backfill.py` to the generalised calendar type from task 1.1

## 3. CLI script

- [x] 3.1 Add `SYMBOL_CONFIG` dict to `scripts/backfill_options_gap.py` mapping each symbol to `(sid, step, expiry_cache_path_setting)`:
  ```python
  SYMBOL_CONFIG = {
      "NIFTY":     {"sid": 13, "step": 50,  "expiry_path": s.EXPIRY_CACHE_PATH},
      "BANKNIFTY": {"sid": 25, "step": 100, "expiry_path": s.BANKNIFTY_EXPIRY_CACHE_PATH},
      "SENSEX":    {"sid": 51, "step": 100, "expiry_path": s.SENSEX_EXPIRY_CACHE_PATH},
  }
  ```
- [x] 3.2 Add `--symbol NIFTY|BANKNIFTY|SENSEX` argparse flag (default `NIFTY`) to `backfill_options_gap.py`
- [x] 3.3 Resolve config from `SYMBOL_CONFIG[a.symbol]` in `main()` and pass to `backfill_gaps()`
- [x] 3.4 Add missing-expiry-cache guard: if the resolved `expiry_path` does not exist on disk, print a clear error and `sys.exit(1)` before opening any Dhan connection
- [x] 3.5 Update module docstring to document all three symbols and the expiry-cache prerequisite

## 4. Taskfile

- [x] 4.1 Add `backfill:options:banknifty` task: `uv run python scripts/backfill_options_gap.py --symbol BANKNIFTY {{.CLI_ARGS}}`
- [x] 4.2 Add `backfill:options:sensex` task: `uv run python scripts/backfill_options_gap.py --symbol SENSEX {{.CLI_ARGS}}`
- [x] 4.3 Update `scripts/CLAUDE.md` table with the two new tasks

## 5. Spot prerequisite check

- [x] 5.1 Verify BANKNIFTY spot is present: run `task backfill:banknifty -- --from 2021-06-01 --only-missing` if not already done
- [x] 5.2 Verify SENSEX spot is present: run `task backfill:sensex -- --from 2021-06-01 --only-missing` if not already done

## 6. Backfill + validation

- [x] 6.1 Dry-run BANKNIFTY options: `task backfill:options:banknifty -- --from 2021-06-01 --dry-run`
- [x] 6.2 Run BANKNIFTY options backfill: `task backfill:options:banknifty -- --from 2021-06-01 --only-missing`
- [x] 6.3 Dry-run SENSEX options and run backfill similarly
- [x] 6.4 Verify coverage: `task audit:coverage` shows BANKNIFTY (sid 25) and SENSEX (sid 51) rows

## 7. Validation & archive

- [x] 7.1 `task test` and `task lint` / `task typecheck` green
- [x] 7.2 `openspec validate multi-index-options-backfill --strict` passes
- [x] 7.3 Archive: `openspec archive multi-index-options-backfill`
