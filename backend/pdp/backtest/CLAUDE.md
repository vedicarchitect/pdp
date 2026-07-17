# Backtest Module (`src/pdp/backtest/`)

Python package — importable modules only. Runnable scripts and YAML configs live in `backtest/` (repo root).

## Active files

| File | Role |
|------|------|
| `sim.py` | **Active index simulation engine** — config-driven tick-by-tick replay, fill logic, P&L tracking |
| `strangle_sim.py` | **Directional-strangle engine** — bias-driven multi-leg ratio strangle (PE:CE per bucket), protective hedges, rollup/take-profit/tiered-pct-stop/trend-flip exits, every-minute `BarStatus` trace |
| `strangle_config.py` | `StrangleConfig` dataclass — bias weights, ratio table, strike method, hedge band, exits; `from_yaml`/`to_yaml` |
| `strangle_loader.py` | Assembles per-bar multi-timeframe `BiasInputs` (5m/15m/1h EMAs, daily+weekly Camarilla, swing, VWAP, ORB, India VIX) from a cached Mongo window for `strangle_sim.py` |
| `strangle_report.py` | `RunWriter` — archives per-day artifacts (status.log, trades.csv, legs.csv, day.json) + run-level summary.csv/equity.csv/manifest.json with build/sim timing |
| `day_loader.py` | Loads one trading day of index spot + option bars from MongoDB for `sim.py` |
| `strategy_config.py` | `StrategyConfig` dataclass — all strategy knobs; `from_dict` / `to_dict` / `from_yaml` / `to_yaml` |
| `commissions.py` | `CommissionCalculator` — uses `settings.backtest_commission.*` |
| `execution.py` | Fill execution (no look-ahead: fills on next bar open after signal) |
| `resample.py` | OHLCV resampling (1m → 5m/15m etc.) |
| `chain_loader.py` | Loads option chain snapshots for a day |
| `indicators.py` | Backtest-time indicator compute (replays bars to rebuild ST state) |
| `models.py` | `BacktestResult`, `Trade`, `DayResult` dataclasses |
| `engine.py` | Generic strategy-replay framework (`BacktestEngine`) — not used by the index sim directly |
| `output.py` | Result formatting, console table, CSV/JSON export |
| `routes.py` | `/backtest` FastAPI endpoints (legacy options replay) |
| `store.py` | `BacktestStore` — sync pymongo wrapper; document builders (`build_run_doc`, `build_day_docs`, `build_fold_docs`, `build_trade_docs`, `build_sweep_doc`, `build_decision_docs`) + idempotent upsert for all 6 Mongo warehouse collections; centralized verdict thresholds (`WF_PASS_*`, `verdict_breakdown`) |
| `sweep_engine.py` | `run_strangle_sweep` — in-process grid-sweep runner: loads the window once, replays every combo through `simulate_strangle_day`, returns unranked combos for `store.build_sweep_doc` to rank |
| `warehouse_routes.py` | `/api/v1/strangle-backtests` FastAPI router — list/detail/equity/days/folds/trades/sweeps/decisions/promotion/vs-paper + compare + launch (POST /runs, /sweeps, /walkforwards) + promote (POST /runs/{id}/promote) |
| `job_handlers.py` | Async job handlers for `backtest:single`, `backtest:sweep` (real in-process grid sweep), `backtest:walkforward` — registered in app factory |
| `paper_compare.py` | Generic backtest-vs-paper comparison (`backtest-paper-comparison`) — per-strategy paper realized P&L from the PG ledger, per-day alignment, shared decision-event vocabulary + minute-level diff, gap-radar divergence annotation |

## Commission Settings (settings.py → `backtest_commission`)

| Field | Default |
|-------|---------|
| `brokerage_per_order` | ₹20.00 |
| `stt_rate` | 0.0015 (0.15% on sell premium) |
| `txn_charge_rate` | 0.000355299 (0.0355299% NSE options) |
| `sebi_rate` | 0.000001 (0.0001% of turnover) |
| `stamp_duty_rate` | 0.00003 (0.003% on buy turnover) |
| `ipft_rate` | 0.000000001 (negligible) |
| `gst_rate` | 0.18 (18%) |

Rates verified against Dhan charge schedule 2026-06-26.

Override via `.env`: `BACKTEST_COMMISSION__BROKERAGE_PER_ORDER=15`

## Key Constraints

- **No look-ahead**: signals on bar close → fill on **next bar open**. Enforced in `execution.py`.
- **No live indicator recompute**: backtest rebuilds ST bar-by-bar via `indicators.py`, mirrors live `IndicatorEngine` params.
- Data source: MongoDB `option_bars` and `market_bars` collections.
- `strategy_config.py` is the canonical config format; YAML files in `backtest/configs/` are its serialized form.
- **Suite indicators in backtest**: set `suite_indicators` in `StrategyConfig` to replay any live-suite family alongside ST. `sim.py` builds the bundle, warms it from `prior_session_bars`, and updates it per bar — same tracker classes as live, so states are identical. The snapshot lands as `_suite_snap` in the series loop, ready for strategy conditions.

## DB-first warehouse (since `backtest-results-warehouse`, archived 2026-07-04)

Results are DB-first, not local files. `strangle_run.py`/`strangle_walkforward.py` persist to Mongo by
default (`--mongo` default True; opt out with `--no-mongo`); local `backtest/runs/<id>/` archival only
happens if `--out-dir` is explicitly passed (legacy/manual inspection). Logs route to OpenSearch, not
`logs/*.log`. 6 Mongo collections: `backtest_runs`, `backtest_days`, `backtest_folds`, `backtest_trades`,
`backtest_sweeps` (leaderboard), `backtest_decisions` (why-entry/why-exit event trace). Every decision
event uses a strategy-agnostic reason-code vocabulary: `st_flip | entry | scale_in | rollup | exit |
reentry`. Operate the machinery via skills, not raw API calls: `/backtest:run`, `/backtest:sweep`,
`/backtest:promote`, `/backtest:ingest`, `/backtest:explain`, `/backtest:vs-paper`
(`.claude/skills/backtest-*/SKILL.md`).
Spec: `openspec/specs/backtest-warehouse/spec.md` + `backtest-sweeps/spec.md` + `backtest-decision-trace/spec.md`
+ `backtest-paper-comparison/spec.md`.

## Known `option_bars` expiry-cadence gaps (as of 2026-07-13)

`day_loader.py::load_window` resolves each trade day's expiry via `nearest_real_expiry()` — the
first *distinct expiry with any ingested rows* on or after that day. When a real weekly/monthly
expiry was simply never ingested, every day in that stretch silently forward-fills to the far-side
expiry instead. `WindowData.cadence_gap_days` (populated from
`pdp.instruments.expiry_calendar.expiry_cadence_gaps`) flags exactly which trade days this
happened to, and `strangle_run.py`'s per-chunk log line reports the count separately from
`valid`/`skipped` — see `option-bars-expiry-gap-backfill`.

Confirmed gaps, NIFTY (`underlying="NIFTY"`):
- **763-day blackout, 2020-12-03 → 2023-01-05** — zero ingested expiry data; any backtest window
  spanning this range silently trades (or phantom-skips) against a badly mismatched far-side
  contract for every day inside it. Backfillability from Dhan's historical option-chain API is
  unconfirmed (blocked on live Dhan creds as of 2026-07-13 — see the change's README).
- **19-25 smaller 12-21 day gaps, 2023-2026** (19 confirmed via `expiry_cadence_gaps()` in the
  2023-01..2026-05 window alone), mostly around monthly-expiry transition weeks — real, listed
  contracts that were simply never ingested, not weeks with no contract. 4 spot-checked against
  NSE's real calendar (2023-02-16, 2023-03-23, the holiday-shifted 2023-04-19, 2024-04-18), all
  confirmed missing-ingestion. The existing per-day contract-completeness audit
  (`audit_options_coverage.py`'s `days_missing()`) reports **zero** gap days over this same
  window — it cannot see this bug, since the days inside a cadence gap still have a full option
  chain, just against the wrong far-side expiry.

BANKNIFTY / SENSEX (audited 2026-07-13): **both clean** — 0 cadence gaps each (BANKNIFTY: 261
stored expiries 2021-08-04..2026-07-29; SENSEX: 167 stored expiries 2023-05-15..2026-07-13; both
uninterrupted ~7-day cadence throughout). Only NIFTY has this bug.

**Separate finding (out of this change's scope)**: BANKNIFTY's real-world forward listing went
monthly-only (regime change), but its `option_bars` historical distinct-expiry set stays
weekly-cadence straight through 2026-07-29 — `pdp.options.gap_backfill.fill_day()` resolves every
backfilled day against the hardcoded `"WEEK"` calendar flag regardless of the underlying's current
real regime, so that's what's actually stored. `expiry_cadence_gaps()`'s BANKNIFTY threshold is
set to match what's actually persisted (weekly), not the real-world regime, since the detector
reads `real_expiries_from_option_bars` (the stored data). Whether BANKNIFTY's `option_bars`
ingestion should itself resolve against the real (monthly) regime is unresolved.

## Common Tasks

**Add a commission field:** Edit `BacktestCommissionSettings` in `settings.py` + update `commissions.py`.

**Change fill timing:** Only touch `execution.py`. Do NOT change `sim.py` fill logic directly — keep look-ahead guard in one place.

**Add a new StrategyConfig knob:** Edit `StrategyConfig` in `strategy_config.py`, update `sim.py` to consume it, add validation in `validate()`.
