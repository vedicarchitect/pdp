## 1. Per-strategy paper P&L

- [x] 1.1 Add an Alembic migration indexing `orders.strategy_id`.
- [x] 1.2 Add a query/service that aggregates realized P&L per `strategy_id` over a date window (`trades ⨝ orders` on `order_id`, `orders.mode='PAPER'`, group by `strategy_id`), reusing `pdp/journal/stats.py:compute_daily_stats` realized-P&L semantics; return gross and net.

## 2. vs-paper alignment API

- [x] 2.1 Add `GET /api/v1/strangle-backtests/runs/{id}/vs-paper` in `warehouse_routes.py`: resolve the run's `strategy_id`, pull backtest per-day series (`backtest_days`) and paper per-day series (task 1.2) over the window, return aligned by date with a divergence column.
- [x] 2.2 Handle no-paper-data: return the backtest series with an empty paper series + indicator, not an error.

## 3. Minute-level decision diff

- [x] 3.1 Define the shared decision-event vocabulary and a thin adapter normalizing backtest (`backtest_decisions`, change 1) and live (`bias_evaluated`/`leg_open`/`leg_close`/`rolled`/`stop_gate_wait`/…) events onto it.
- [x] 3.2 Add a minute-level diff for a run+date joining backtest and live events by `(strategy_id, timestamp)`, flagging mismatches; expose via API (e.g. `runs/{id}/vs-paper?date=&granularity=minute`).

## 4. Divergence root-causing

- [x] 4.1 Annotate divergence rows by cross-referencing the change-2 gap radar (missing input families for the date) and the `bias_evaluated` votes; attribute a concrete cause when one exists.

## 5. Retire the ST-only CLI

- [x] 5.1 Remove `backtest/compare.py` and the `backtest:compare` Taskfile task; update any references/docs.

## 6. Skill

- [x] 6.1 `.claude/skills/backtest-vs-paper/SKILL.md` (`/backtest:vs-paper`) — run the comparison for a strategy_id + window, flag divergence, and root-cause it via the gap radar + bias votes.

## 7. Tests + spec sync

- [x] 7.1 Unit tests: per-strategy P&L join (PAPER-only, grouped); vs-paper alignment incl. no-paper-data; minute-level diff mismatch flagging; divergence annotation.
- [x] 7.2 `task test` / `task lint` / `task typecheck` clean for touched modules; `openspec validate backtest-paper-comparison --strict` passes.
- [x] 7.3 End-to-end: compare the live paper `directional_strangle_nifty` window against the ingested NIFTY backtest run; confirm divergence within tolerance and any gap attributed to a concrete cause. (Ran against the real DB — see tasks.md note below; the promoted run's window predates paper go-live, so the exercised path is the "no paper data in window" scenario, not a numeric divergence.)
