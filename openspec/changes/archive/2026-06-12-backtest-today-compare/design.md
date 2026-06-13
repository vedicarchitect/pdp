## Context

The backtest engine (`src/pdp/backtest/engine.py`) was built when the MongoDB schema used
top-level `bar_time`, `security_id`, and `timeframe` fields. The bar writer was later revised to
the TimescaleDB-compatible time-series layout (`ts` + nested `metadata.{security_id, timeframe}`)
and the database name was changed from `trading` to `pdp` (set via `settings.MONGO_DB_NAME`),
but the backtest engine was never updated to match.

A second bug: `BacktestEngine._process_bar()` calls `strategy.on_bar()` directly without first
calling `indicator_engine.on_bar()`. The `SuperTrendShort` strategy reads
`ctx.indicators.supertrend(sid, tf)` at the top of every bar and returns immediately if it is
`None`. Because the backtest wires no `IndicatorEngine` at all, every bar is silently skipped
and the strategy produces zero trades.

A third bug: migration 0009 creates `backtest_runs`, `backtest_trades`, and `backtest_daily` but
was never applied. The DB jumped from 0008 to 0010 before 0009 was inserted into the chain.
`alembic current` shows `0010` (correct for `alembic_version`), but the three tables are absent.
Running `alembic upgrade head` now would skip 0009 because its version hash is already in
`alembic_version`. Tables must be applied via raw DDL.

Finally, to support a live paper-vs-backtest comparison for any trading day without corrupting
the live orders/positions tables, a standalone comparison script is needed that replays the
strategy purely from MongoDB bars and prints the side-by-side result.

## Goals / Non-Goals

**Goals:**
- Fix all three bugs so `pdp backtest run <strategy> --from D --to D+1` produces correct trades.
- Create the three missing PostgreSQL tables so backtest results can be persisted.
- Wire `IndicatorEngine` into the backtest path (attach to engine + pass via `IndicatorReader`
  in `StrategyContext`) so `ctx.indicators.supertrend()` returns live values during replay.
- Correct MongoDB field references in both `engine.py` and `backtest/indicators.py`.
- Add `scripts/backtest_compare.py`: reads today's NIFTY 5m + option bars from MongoDB,
  replays SuperTrend strategy logic in pure Python (no DB writes), and prints a comparison
  table of simulated vs paper results.

**Non-Goals:**
- Isolated order simulation (the full engine still writes to the live paper DB; isolation is a
  separate effort).
- Resampling from 1-minute bars (the spec requires it but is pre-existing tech debt; not
  introduced or fixed here).
- Backfilling bars for days when the server was not running.

## Decisions

### D1 — Pass `mongo_db_name` to engine, not hard-code it

**Decision**: Add `mongo_db_name: str = "pdp"` parameter to `BacktestEngine.__init__()` and
thread it from `backtest_commands.py` via `settings.MONGO_DB_NAME`.

**Rationale**: Hard-coding `"pdp"` in the engine couples it to a single deployment. The settings
value is already authoritative; the engine should consume it like every other component.

**Alternative considered**: Read settings inside the engine. Rejected — engines should not call
`get_settings()` directly; that creates hidden coupling and complicates unit tests.

### D2 — `attach_indicator_engine()` method, not constructor param

**Decision**: Add `engine.attach_indicator_engine(ie)` called in `_run_backtest_async` rather
than adding `indicator_engine` to `BacktestEngine.__init__()`.

**Rationale**: The engine is constructed in the sync `run_backtest` click handler before the
async loop starts. The `IndicatorEngine` does not need to be passed through the constructor
signature; attaching it before `engine.run()` is called is sufficient and keeps the constructor
lean.

### D3 — Apply missing tables via raw DDL, not alembic downgrade/re-upgrade

**Decision**: Create the three tables with `CREATE TABLE IF NOT EXISTS` DDL executed directly
(either via `scripts/apply_0009_tables.py` or as part of `backtest_compare.py` startup).

**Rationale**: The alembic_version record already shows `0010`. Running `alembic downgrade 0008`
to replay 0009 would drop the `alerts` table (migration 0010) which holds live data. Raw DDL is
idempotent (`IF NOT EXISTS`) and safe.

### D4 — Standalone comparison script reads MongoDB only, no live DB writes

**Decision**: `scripts/backtest_compare.py` replays the SuperTrend strategy using only MongoDB
bar data and the instruments table (read-only). It does not create orders, trades, or positions.

**Rationale**: The live paper tables hold today's actual results; writing simulated trades into
them for comparison would corrupt the paper record and confuse the journal.

## Risks / Trade-offs

- **[Risk] Indicator warmup at bar 0** — SuperTrendTracker needs `period=3` bars to seed ATR. On
  the first day of a backtest the first 2 bars will produce `None` and the strategy will skip
  them. This matches live behaviour (warmup.py seeds from prior-day MongoDB bars).
  → Mitigation: `scripts/backtest_compare.py` optionally pre-seeds the tracker with the last few
  bars of the prior day before replaying today's data.

- **[Risk] Option instrument availability** — `resolve_otm_option()` queries the instruments
  table for active contracts. For dates in the past the contracts may have expired and been
  removed. The standalone script uses the security IDs recorded in the paper journal as the
  ground truth for instrument selection.
  → Mitigation: document this in the script's header comment; full historical instrument support
  is tracked separately under the security-master-snapshot change.

- **[Risk] DB contamination if full backtest CLI is run** — `pdp backtest run` still uses the
  live paper DB for order fills. Running it for today's date would add duplicate orders.
  → Mitigation: document in CLI help text that today's date should be run via the standalone
  script, not via the CLI, until an isolated backtest broker is implemented.

## Migration Plan

1. Apply DDL for `backtest_runs`, `backtest_trades`, `backtest_daily` (task T1).
2. Patch engine and CLI (tasks T2–T4) — no schema changes, fully backward-compatible.
3. Add comparison script (task T5) — new file, no impact on existing code.
4. Rollback: the DDL additions are additive; rollback = drop the three tables if needed.
