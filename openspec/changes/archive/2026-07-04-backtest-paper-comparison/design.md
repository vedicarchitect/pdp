## Context

Paper is live since ~2026-06-29 (`directional_strangle_{nifty,banknifty,sensex}`), so both sides of a
comparison have real data. But: `Trade` (`pdp/orders/models.py`) has no `strategy_id` — it's reachable
only via `Trade.order_id → Order.strategy_id`, and `Order.mode` distinguishes PAPER/LIVE.
`orders.strategy_id` is not indexed. `PortfolioService`/`compute_daily_stats` compute realized P&L but
not grouped per strategy over a window. `backtest/compare.py` is a ST-only, single-date CLI reading
Mongo `paper_journal`. Change 1 adds `backtest_decisions` (backtest side); live already emits
`bias_evaluated`/`leg_open`/`leg_close`/`rolled`/`stop_gate_wait`. Change 2 adds the gap radar.

## Goals / Non-Goals

**Goals:**
- A generic per-`strategy_id` paper realized-P&L query over a window from the PG ledger.
- `runs/{id}/vs-paper` aligning backtest vs paper per day.
- Minute-level backtest-vs-live decision diff via a shared event vocabulary.
- Root-cause hooks tying divergence to gap-radar findings / bias votes.
- Retire the ST-only compare CLI.

**Non-Goals:**
- The Flutter comparison view (change 5).
- Changing how paper trades are recorded — we only *read* the ledger.
- Live→live or broker-recon comparison (covered elsewhere).

## Decisions

### 1. Read paper P&L from the PG ledger, not Mongo journal
Aggregate `trades ⨝ orders` (`order_id`), filter `orders.mode='PAPER'`, group by
`orders.strategy_id`, deriving realized P&L with the same buy/sell+charges logic as
`compute_daily_stats`. Rationale: the ledger is ACID source-of-truth for fills; the Mongo journal is a
daily rollup. Add an Alembic index on `orders.strategy_id` (only `positions.strategy_id` is indexed
today).

### 2. vs-paper aligns by date on the same strategy_id
The endpoint resolves the run's `strategy_id` (via the unified registry, change 4, once available;
until then via the run doc's strategy label), pulls the backtest per-day series from `backtest_days`
and the paper per-day series from the PG query over the run's window, and returns both aligned by date
with a divergence column. Missing paper data returns an empty paper series + indicator, not an error.

### 3. Minute-level diff uses a shared event vocabulary
Define one small vocabulary the backtest (`backtest_decisions`, change 1) and live emitters both map
onto (`bias/score/bucket`, `entry`, `scale_in`, `rollup`, `exit`, `reentry`, `stop_gate_wait`). The
diff joins backtest and live events by `(strategy_id, timestamp)` and flags mismatches. Rationale:
the user wants "on this minute, backtest did X, live did Y"; a shared vocabulary makes it a join.

### 4. Root-causing is annotation, not inference
Divergence rows are annotated by cross-referencing the gap radar (change 2) for missing input families
on that date and the `bias_evaluated` votes (which signal was absent). We attribute to a concrete
cause when one exists; we do not guess. Rationale: matches `/strangle:review`'s existing approach.

### 5. Retire compare.py
Remove `backtest/compare.py` + the `backtest:compare` task. Rationale: superseded; keeping a
divergent ST-only path invites confusion.

## Risks / Trade-offs

- [Realized-P&L parity between backtest commissions and paper charges] → reuse the same commission
  model where possible; surface gross vs net separately so a charge-model mismatch is visible rather
  than hidden in a single number.
- [strategy_id mapping backtest↔paper] → depends on change 4's registry for a clean key; interim, map
  the run's family label to the live strategy id explicitly.
- [Minute-level diff requires both sides emit the shared vocabulary] → change 1 provides the backtest
  side; live already emits the events — normalize field names in a thin adapter.
- [Large windows] → per-day aggregation is cheap; the minute-level diff is scoped to a single date on
  demand.

## Migration Plan

1. Add the Alembic index on `orders.strategy_id`.
2. Add the per-strategy paper P&L query/service (reuse `compute_daily_stats` semantics).
3. Add `GET /runs/{id}/vs-paper` (per-day alignment).
4. Add the minute-level diff (shared vocabulary adapter over `backtest_decisions` + live events).
5. Add divergence annotation via gap radar + bias votes.
6. Remove `backtest/compare.py` + `backtest:compare`; author `/backtest:vs-paper`.
Rollback: additions are read-only; the index is additive; only the compare.py removal is destructive
and is a straight deletion of a superseded script.

## Open Questions

- Should vs-paper normalize to net-of-charges on both sides by default, or show gross and net side by
  side? Leaning show both so charge-model differences are explicit. Confirm during tasks.
