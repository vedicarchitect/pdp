# Tasks — dev-reload-scoping

## 1. Tests first
- [x] 1.1 `tests/scripts/test_ensure_port_free.py`: holder is `uvicorn` without `--reload` → exit
      non-zero, no `terminate()` call, PID in stderr
- [x] 1.2 Same, with `--force` → `terminate()` called
- [x] 1.3 Holder is `uvicorn --reload` → `terminate()` called without `--force`
- [x] 1.4 No holder → exit 0, process inspection never invoked
- [x] 1.5 `tests/test_market_hours_guard.py`: 11:00 IST trading day → guard raises;
      20:00 IST → passes; 11:00 IST with `PDP_ALLOW_RELOAD_IN_MARKET=1` → passes with warning

## 2. `ensure_port_free.py`
- [x] 2.1 Resolve the holding PID and read its command line — kept the existing
      `_command_line_windows`/`_command_line_posix` (`wmic`/`ps`) helpers rather than adding a
      `psutil` dependency; `psutil` is not in `backend/pyproject.toml` and the script was already
      dependency-free by design
- [x] 2.2 Classify: `uvicorn` present and `--reload` absent ⇒ trading server ⇒ refuse
- [x] 2.3 Add `--force` to bypass the refusal; keep the existing behaviour behind it
- [x] 2.4 Refusal message names PID + full command line + `task dev:trade` remedy

## 3. Market-hours guard
- [x] 3.1 Added `scripts/guard_market_hours.py`; exits non-zero between 09:15–15:30 IST on a
      trading day unless `PDP_ALLOW_RELOAD_IN_MARKET=1`
- [x] 3.2 Uses `pdp.options.gap_backfill.holidays()` (the existing trading-calendar helper) rather
      than a bare weekday check, so holidays pass
- [x] 3.3 When overridden, prints a `WARNING:` line to stderr that reload is active during market
      hours

## 4. Taskfile
- [x] 4.1 `dev`: add the market-hours guard as the first command
- [x] 4.2 `dev`: `uvicorn pdp.main:app --reload --reload-dir pdp --host 0.0.0.0 --port 8000`
- [x] 4.3 `dev:trade`: unchanged apart from inheriting the `ensure_port_free` refusal (no Taskfile
      edit needed — the refusal lives entirely in `ensure_port_free.py`)
- [x] 4.4 Confirmed: `Taskfile.yml` sets `dir: backend` for the `dev` task, so a relative
      `--reload-dir pdp` resolves to `backend/pdp`

## 5. Startup attribution
- [ ] 5.1 `pdp/main.py` lifespan: log `app_start` with `started_at` (IST) and `reload` derived from
      `sys.argv`
- [ ] 5.2 Unit: the event is emitted once per process start with both fields

## 6. Docs + validation
- [ ] 6.1 `docs/RUNBOOK.md`: "never run `task dev` during a paper session" + the override env var
- [ ] 6.2 Manual: start `dev:trade`, then run `task dev` in a second terminal → the trading server survives
- [ ] 6.3 Manual: edit a file under `openspec/` while `task dev` runs → no restart
- [ ] 6.4 `openspec validate --strict dev-reload-scoping` passes
