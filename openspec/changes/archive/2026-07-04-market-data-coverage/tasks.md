## 1. Coverage computation core

- [x] 1.1 Centralize the underlying→SID map (NIFTY 13, BANKNIFTY 25, SENSEX 51, VIX 21) next to `UNDERLYING_REGISTRY` in `pdp/warehouse/service.py`.
- [x] 1.2 Add a coverage module that computes per-(underlying, family) min/max date, covered trade-day count, gap ranges, and coverage % — reusing `gap_backfill.days_missing`/`expected_contracts`/`trading_days` for options, `market_bars` min/max by SID for spot/VIX, and `index_levels` for Camarilla.
- [x] 1.3 Generalize `scripts/audit_options_coverage.py` off its NIFTY-only hardcode to accept `--symbol`.

## 2. Gap radar (input families)

- [x] 2.1 Promote `pdp/backtest/completeness.py`'s spot gate into per-family readiness functions: spot/VWAP, options, VIX, weekly Camarilla (prior-week spot / `index_levels`), futures (presence/hook).
- [x] 2.2 Produce a per-(index, date, family) status with human labels ("VWAP missing", "weekly Camarilla missing", "VIX missing", "futures missing").

## 3. Coverage + radar API

- [x] 3.1 Add `GET /api/v1/coverage` returning per-underlying, per-family coverage + gap ranges + radar statuses for a window.
- [x] 3.2 Ensure all three indices are represented (not NIFTY-only).

## 4. One-click delta-fill

- [x] 4.1 Plumb `symbol` through `pdp/housekeeping/tasks.py` `backfill_spot`/`backfill_options` (pass `--symbol`); default NIFTY when omitted.
- [x] 4.2 Add `backfill_levels`/`backfill_vix` handlers + register in `pdp/main.py`; extend `_VALID_TASKS` + `housekeeping/routes.py`.
- [x] 4.3 Verified against the live dev server: job routing, `symbol`/`dry_run` param capture, and the `_REPO_ROOT` path fix (see 8.2 note) all confirmed correct for `backfill-levels`/`validate-warehouse`. Actual subprocess execution is blocked by a **pre-existing** platform bug independent of this change — Windows' default asyncio `SelectorEventLoop` (used by uvicorn on this machine) does not support `asyncio.create_subprocess_exec` (raises `NotImplementedError`); confirmed identical failure on the unmodified `validate-warehouse` task, so every housekeeping job is affected, not just the new ones. Out of scope to fix here (needs `WindowsProactorEventLoopPolicy` wired into `pdp/main.py` startup, a cross-cutting change) — flagged for a follow-up.

## 5. Multi-index self-heal

- [x] 5.1 Update `pdp/warehouse/service.py:_run_gap_backfill` to loop `WAREHOUSE_UNDERLYINGS`, loading each underlying's expiry calendar and calling `run_gap_backfill(..., underlying=...)`; remove the non-NIFTY skip.
- [x] 5.2 Skip only when an underlying's expiry cache is missing, with a clear warning naming the file.

## 6. OpenSearch coverage feed + dashboard

- [x] 6.1 Add a `data-coverage` family + mapper in `pdp/observability/{mappings,sinks}.py`; emit periodic coverage snapshots (from the self-heal cycle).
- [x] 6.2 Author `infra/opensearch/dashboards/NN_data_coverage.ndjson` (index-pattern `pdp-data-coverage-*` + coverage %/gap visuals); confirm it loads via `task search:init`.

## 7. Skills

- [x] 7.1 `.claude/skills/data-coverage/SKILL.md` (`/data:coverage`) — read-only per-index/family coverage report (complements `/pdp:health`).
- [x] 7.2 `.claude/skills/data-gapfill/SKILL.md` (`/data:gapfill`) — read `GET /coverage`, list gaps, trigger the one-click backfill, watch `/ws/jobs`, re-check until closed.

## 8. Tests + spec sync

- [x] 8.1 Unit tests: per-family coverage math; gap-radar labels; symbol plumbing job→CLI; multi-index self-heal loop (skip only on missing expiry cache). 34 new tests, all passing.
- [x] 8.2 `task lint` clean for touched/new modules (remaining ruff findings are pre-existing, in code not touched by this change). `task typecheck` (strict pyright) noise from new files is the same pre-existing class of error as everywhere else in the codebase — no motor/pymongo type stubs; not a regression. `task test` full suite: 31 pre-existing failures confirmed via git-stash bisection to exist without this change too (portfolio/risk/options/strategy modules, unrelated to any file touched here); 0 new failures. `openspec validate market-data-coverage --strict` passes.
- [x] 8.3 Compose stack already running; `task search:init` applied templates (count=10, was 9) + imported all 9 dashboards including the new one; confirmed `pdp-data-coverage-*` index-pattern and `data-coverage` dashboard both exist via the OpenSearch Dashboards saved-objects API. Also live-verified `GET /api/v1/coverage` against the running dev server (all 3 underlyings, correct spot-OR-levels radar semantics) and found + fixed a real perf bug (unbounded min/max scan over a 95M-row `option_bars` collection) before this checkbox was signed off.
