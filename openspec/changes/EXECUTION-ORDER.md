# Execution order — 2026-07-09 incident remediation

Ten changes, written 2026-07-10 from the findings of the 2026-07-09 inflated-P&L incident. Execute
**one at a time, in this order.** Each has a self-contained `README.md` (minimal context),
`proposal.md` (why + what), `tasks.md` (an ordered, checkable list) and `specs/<id>/spec.md`.

**Start every change by reading its own `README.md`. It lists the only files you need.**

## Rules that apply to all ten

1. **Spec-first, one change at a time.** Do not start change N+1 until N is archived.
2. **Paper-only.** Never set `LIVE=1`. `BROKER=dhan` + `LIVE=1` places real orders.
3. **Tests first.** Each `tasks.md` opens with tests that must **fail** on current code. If a test
   passes when the proposal says it should fail, the hypothesis is wrong — stop, investigate, and
   write down what actually happens before changing anything.
4. **Never run `task dev` during market hours or during a paper session.** It kills whatever holds
   port 8000, which is the trading backend. Use `task dev:trade`.
5. **`backend/.env` is not in git and its values override `settings.py`.** `OPTIONS_UNDERLYINGS` is
   set there; `BROKER_SYNC_ENABLED` is not. Check before assuming a code edit takes effect.
6. **Verify, don't assume.** Line numbers in these documents are from commit `f6030a6`. Re-grep
   before editing. If a cited line says something different, the proposal is stale — say so.
7. After backend changes: `task test`. After app changes: `cd app`, then `flutter analyze`, then
   `flutter test` (separate commands — do not chain with `&&`).

## Order and rationale

| # | Change | Why here | Blocks |
|---|--------|----------|--------|
| 0 | `broker-sync-visibility` | **Already implemented, uncommitted.** Tasks 1–8 done; group 9 is deploy-day verification needing market hours. Commit it. | — |
| 1 | `dev-reload-scoping` | Until this lands, editing strategy code restarts the trading backend and re-triggers the very bug you are debugging. | everything |
| 2 | `test-suite-baseline-green` | A red baseline (45 failures) cannot detect a regression. The 11 failing loss-cap tests guard the day-loss cap that misfired on phantom P&L. | 3–8 |
| 3 | `bar-session-anchoring` | 30m and 1H bars are anchored to the Unix epoch, not the 09:15 IST open. Every indicator built on them is computed over the wrong candles. **Rebuilds `market_bars`.** | 4, 5 |
| 4 | `indicator-history-depth` | EMA(200) is not configured anywhere; warmup windows are hand-tuned constants. Pointless before bars are anchored correctly. | 5 |
| 5 | `bias-input-completeness` | Three of the strategy's eight bias inputs are silently dead. Wiring them to mis-anchored or under-seeded bars trades one silent error for another. | 8 |
| 6 | `strangle-close-path-atomicity` | **Highest impact.** `_roll_leg` closes the short *and its hedge* before checking it can reopen. The close path holds no lock while the open path does. | 7 |
| 7 | `strangle-leg-state-durability` | Leg type lives only in memory; rehydration reads a Mongo collection nothing writes. Land after 6 — that change replaces the three leg lists with one structure. **Only PostgreSQL migration in the set.** | 8 |
| 8 | `strangle-observability-gaps` | Aggregates readiness signals produced by 4, 5, 6 and 7. Measuring before fixing yields high-fidelity readings of a system that still miscounts. | — |

## Independent — land any time

| Change | Note |
|--------|------|
| `flutter-execution-tab-layout` | **Code already written and verified.** Only tasks 5.x remain (docs, Android check, audit). Commit separately from `broker-sync-visibility`. |
| `dhan-same-day-data` | Task 1 is an **investigation** that blocks the rest; its scope is unknown until answered. Do not estimate it first. |

## Expect the backtest baselines to move

Changes 3, 4 and 5 all alter the inputs the strategy sees. The archived NIFTY baseline
(+Rs 85.6L, PF 5.72, MaxDD Rs 71k) was produced from mis-anchored 30m/1H bars and a bias engine with
three dead inputs. Re-run the three strangle configs after change 5 and **decide explicitly** whether
the new numbers supersede the archived ones. A different result is expected and is not, by itself, a
regression.

## Findings deliberately not given their own change

- **Three in-flight API proposals** (`api-reliability-hardening`, `api-openapi-schema-completeness`,
  `api-worker-decoupling`) already exist in `openspec/changes/`. Unchanged.
- **`execution-console-daily-parity`** is implemented (23/23 tasks) but unarchived. It already fixed
  `entry_price=0`, the `avg_price` re-base, the DB-first ledger and the intraday broker poll. Archive
  it; do not redo that work. Change 7 fixes the leg-*type* durability its `rehydrate_legs()` task
  left resting on a nonexistent Mongo write.
- **267 ruff items.** Recorded in `test-suite-baseline-green` task 1.6; fixed in a separate pass.
  Mixing a lint sweep into a test rescue makes the diff unreviewable.
- **`stop_half` / `stop_all` missing exit fields** — already fixed in `f045282`. Verified, not re-fixed.

## Unresolved contradictions to settle while working

- `live-supertrend-session-warmup` is **archived with 10/10 tasks checked**, yet memory
  `live_supertrend_warmup_gap` records it as never implemented. Settle it in `dhan-same-day-data`
  task 1.6.
- `backend/pdp/market/CLAUDE.md` documents `market_bars` with a top-level `security_id`. It is a Mongo
  **timeseries** collection keyed on `metadata.security_id` / `metadata.timeframe`. Fix in change 3.
- The root `CLAUDE.md` troubleshooting table says EMA200 = `--` is caused by insufficient warmup and
  advises raising `_TF_WARMUP_CALENDAR_DAYS`. **That is wrong** — the period was never configured.
  Delete the row in change 4.
