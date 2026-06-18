# backtest Specification

## Purpose
TBD - created by archiving change add-backtest-engine. Update Purpose after archive.
## Requirements
### Requirement: Backtest CLI invocation
The system SHALL provide `backtest/run.py` as the canonical multi-day backtest runner, replacing
both `backtest_multiday.py` (archived to `scripts/archive/`) and `scripts/backtest_sweep.py`
(moved). The script SHALL accept: `--days N` (window size), `--start YYYY-MM-DD` (end date),
`--config-file <path>` (load a named YAML config), `--config <json>` (inline JSON config),
`--st`, `--tf`, `--moneyness` (grid axes), `--no-commission`, `--no-heal`. When neither
`--config-file` nor `--config` is given and no grid flags are supplied, the script SHALL load
the config from `settings.BACKTEST_DEFAULT_CONFIG` and run single-config detail mode for the
last 7 days.

#### Scenario: Single-config detail — default config
- **WHEN** user runs `task backtest` with no arguments
- **THEN** script loads `BACKTEST_DEFAULT_CONFIG`, runs last-7-day detail, prints per-trade
  table + leg summary + day summary

#### Scenario: Single-config detail — explicit config file
- **WHEN** user runs `task backtest -- --config-file backtest/configs/st3_1_5m_otm1.yaml --days 30`
- **THEN** script loads that YAML, runs 30-day single-config detail

#### Scenario: Single-config detail — inline JSON
- **WHEN** user runs `task backtest -- --config '{"st_period":10,"st_multiplier":2,"timeframe_min":15,"moneyness":1}'`
- **THEN** script parses JSON, runs single-config detail with the specified params

#### Scenario: Grid sweep
- **WHEN** user runs `task backtest:sweep -- --days 90 --st "3,1;10,2" --tf "5,15" --moneyness "1,0,-1"`
- **THEN** script runs the grid and prints a ranked comparison table

#### Scenario: Legacy script archived
- **WHEN** a developer looks for `backtest_multiday.py` at the repo root
- **THEN** it is not present; `scripts/archive/backtest_multiday.py` exists with a header
  comment noting it is superseded by `backtest/run.py`

---

### Requirement: Taskfile backtest tasks updated
`task backtest` SHALL invoke `backtest/run.py` (default config, 7-day detail). `task backtest:sweep`
SHALL invoke `backtest/run.py` with pass-through CLI args for grid mode. Both SHALL use
`uv run python backtest/run.py`.

#### Scenario: task backtest runs correctly
- **WHEN** user runs `task backtest` from repo root
- **THEN** `uv run python backtest/run.py` executes with default-config, 7-day detail

#### Scenario: task backtest:sweep passes through args
- **WHEN** user runs `task backtest:sweep -- --days 90 --st "10,2"`
- **THEN** `uv run python backtest/run.py --days 90 --st "10,2"` executes

---

### Requirement: Historical bar replay
The system SHALL replay historical market bars in chronological order, feeding them to the
strategy via the same event-driven interface as live trading. Source bars SHALL be fetched from
the MongoDB `market_bars` collection using the `ts` field for time filtering and
`metadata.security_id` / `metadata.timeframe` for instrument identification (matching the schema
written by `BarWriter`). The MongoDB database name SHALL be read from `settings.MONGO_DB_NAME`
and SHALL NOT be hard-coded. Resampling from 1-minute bars to the signal timeframe is specified
separately and remains pre-existing tech debt outside the scope of this change.

#### Scenario: Bars arrive in correct order
- **WHEN** backtest processes historical bars for a security between two dates
- **THEN** bars are processed in ascending `ts` order, one at a time

#### Scenario: MongoDB schema fields are mapped correctly
- **WHEN** the backtest engine loads bars from MongoDB
- **THEN** it queries the `ts` field for date range and reads `metadata.security_id` and
  `metadata.timeframe` for instrument identification (not top-level `bar_time`, `security_id`,
  or `timeframe`)

#### Scenario: Database name from settings
- **WHEN** the backtest engine connects to MongoDB
- **THEN** it uses the database name from `settings.MONGO_DB_NAME` (default `pdp`), not a
  hard-coded string

#### Scenario: On-bar hook is invoked
- **WHEN** a bar is produced during replay
- **THEN** the strategy's `on_bar()` hook is called with that bar

#### Scenario: Missing bars in history
- **WHEN** backtest encounters a gap in bar history
- **THEN** the system logs a warning with the gap period and continues processing

---

### Requirement: Simulated time context
The system SHALL provide a time-aware context to strategies during backtest where `datetime.now()` returns the current bar's timestamp, not wall-clock time.

#### Scenario: Strategy sees replayed timestamp
- **WHEN** strategy code calls `datetime.now()` during backtest
- **THEN** the timestamp returned matches the current bar's timestamp

#### Scenario: Time advances with bars
- **WHEN** successive bars are processed during backtest
- **THEN** `datetime.now()` returns monotonically increasing timestamps

---

### Requirement: Input-data completeness gate

The backtest SHALL validate the NIFTU index 1-minute spot series for each trade day before
simulating, and SHALL NOT generate trades or P&L for a day whose series is incomplete. A day is
incomplete when its bar count is below `MIN_BARS_FRAC` of the expected full-session count
(≈375 bars for 09:15–15:30) or when it contains an intraday gap of at least `MAX_GAP_MIN` minutes.
An incomplete day SHALL be reported with a distinct `data_incomplete` status in both the per-day
output and the final summary, carrying the diagnostic reason (bars present, largest gap). The
backtest SHALL NOT perform a hidden mid-run Dhan fetch to fill the index series on the hot path;
backfill is an explicit, separate step.

#### Scenario: Complete day is simulated

- **WHEN** a trade day has ≈375 NIFTU 1m bars spanning 09:15–15:30 with no gap ≥ `MAX_GAP_MIN`
- **THEN** the backtest simulates the day normally and reports trades and P&L

#### Scenario: Day with an intraday hole is skipped

- **WHEN** a trade day's NIFTU 1m series contains a gap ≥ `MAX_GAP_MIN` minutes (e.g. 10:10→11:38)
- **THEN** the backtest skips the day, records no trades, and reports `data_incomplete` with the gap detail

#### Scenario: Day with no spot data is skipped

- **WHEN** a trade day has zero NIFTU 1m bars in `market_bars`
- **THEN** the backtest skips the day, records no trades, and reports `data_incomplete` rather than fabricating results

### Requirement: NIFTU index spot backfill utility

The system SHALL provide a script that backfills NIFTU index 1-minute history from Dhan into the
`market_bars` collection. The script SHALL fetch `security_id="13"` on `IDX_I`/`INDEX`, convert
epoch timestamps to UTC-naive `datetime`, and upsert keyed on
`(ts, metadata.security_id, metadata.timeframe)` so existing complete days are not duplicated. The
script SHALL throttle requests to the Data-API rate limit and back off on rate-limit errors, and
SHALL support a dry-run mode that requires no credentials and a missing-only mode that skips days
already at the expected bar count.

#### Scenario: Backfill fills a missing day

- **WHEN** the script runs for a date whose `market_bars` index series is empty and Dhan has data
- **THEN** the day's 1m bars are inserted into `market_bars` with UTC-naive timestamps

#### Scenario: Re-running does not duplicate

- **WHEN** the script runs again over an already-backfilled range
- **THEN** no duplicate documents are created (idempotent upsert)

#### Scenario: Dry-run needs no credentials

- **WHEN** the script runs with `--dry-run`
- **THEN** it prints the planned trade-day range and performs no Dhan calls or writes

### Requirement: Continuous cross-day SuperTrend warmup

The backtest SHALL warm each trade day's SuperTrend tracker with the most recent prior trading
day's bars (resampled to the signal timeframe) before feeding the day's own bars, so the indicator
line is continuous across the day boundary and inherits the prior day's direction — matching how
charting platforms (TradingView/Kite) compute SuperTrend. Warmup bars SHALL be fed to the tracker
but SHALL NOT be emitted into the day's signal series, so the day's first `flipped` reflects a
genuine carried-over-direction change rather than a fresh cold-start seed. When no prior session is
available (no data within the lookback), the tracker SHALL cold-start as before.

#### Scenario: Day inherits the prior session's direction at the open

- **WHEN** the prior trading day closed in an established uptrend and the new day gaps up
- **THEN** the day opens with SuperTrend UP (carried over), not a cold-start DOWN seed

#### Scenario: Early flip on a morning reversal is detected

- **WHEN** a day opens UP (inherited) and then falls back through the SuperTrend band in the morning
- **THEN** SuperTrend flips UP→DOWN in that morning window (e.g. ~09:55 on 2026-06-12), and the
  wait-for-first-flip gate may enter from that flip

#### Scenario: No prior data falls back to cold start

- **WHEN** no prior trading session is available within the lookback window
- **THEN** the tracker cold-starts on the day's own first bars, preserving prior behavior

### Requirement: Wait-for-first-flip entry discipline

The backtest SHALL suppress all new-position entries (initial open and scale-in) for a trade day
until the first SuperTrend flip occurring after the session start time. The flip is detected via
the indicator's `flipped` signal, which is true only on a genuine trend-direction change. Once the
first flip of the day has occurred, normal entry behavior resumes. Flip handling, stop-loss, and
square-off logic are otherwise unchanged. The first-flip state SHALL reset at the start of each
trade day.

#### Scenario: No entry before the first flip

- **WHEN** the SuperTrend direction has not flipped since the session start
- **THEN** the backtest opens no position and records no scale-in for that day so far

#### Scenario: Entry resumes on the first flip

- **WHEN** the first SuperTrend flip after session start occurs on a given bar
- **THEN** the backtest may open a position from that bar onward according to the signal

#### Scenario: First-flip gate resets each day

- **WHEN** a new trade day begins
- **THEN** the first-flip requirement applies again before any entry on that day

---

### Requirement: Pre-computed indicator access
The system SHALL update the live `IndicatorEngine` on each bar before dispatching the bar to
the strategy, so `ctx.indicators.supertrend()` returns the value computed for the current bar
when `strategy.on_bar()` executes. A fresh `IndicatorEngine(st_period=3, st_multiplier=1)`
SHALL be created per backtest run and attached to both the `BacktestEngine` (for bar-by-bar
updates) and the `StrategyContext` (via `IndicatorReader`) so the strategy's indicator reads
during replay are identical to live trading behaviour.

#### Scenario: IndicatorEngine updated before strategy dispatch
- **WHEN** the backtest engine processes each bar
- **THEN** `indicator_engine.on_bar(bar_closed)` is called before `strategy.on_bar(bar_closed)`

#### Scenario: Strategy accesses indicator during replay
- **WHEN** strategy calls `ctx.indicators.supertrend(security_id, timeframe)` inside `on_bar()`
- **THEN** system returns the SuperTrend state computed for the current bar (not None)

#### Scenario: IndicatorReader is wired into StrategyContext
- **WHEN** `_run_backtest_async` builds the StrategyContext
- **THEN** `ctx.indicators` is an `IndicatorReader` wrapping the same `IndicatorEngine`
  attached to the `BacktestEngine`

---

### Requirement: Order execution simulation
The system SHALL accept orders from the strategy during backtest and execute them at bar close (OHLC)
with no slippage, immediately confirming fills. Fills SHALL be **non-anticipatory**: when an action is
triggered by the signal computed from bar N (which uses bar N's close), the system SHALL fill that
action at a price no earlier than bar N's close — it SHALL NOT fill at bar N's open or any earlier
bar. This prohibition applies uniformly to position entries, scale-ins, flip-driven exits and
re-entries, stop-driven exits, and square-offs, so that no leg is ever priced off a bar that precedes
the bar whose close produced the decision.

#### Scenario: Market order fills at bar close
- **WHEN** strategy places a market order during on_bar() hook
- **THEN** system fills the order at the bar's close price at end of bar processing

#### Scenario: Flip exit is not priced before the triggering bar
- **WHEN** a SuperTrend flip is detected from bar N's close and the open position is closed on that flip
- **THEN** the exit is filled at bar N's close (or a later bar's open), never at bar N's open

#### Scenario: Flip re-entry is not priced before the triggering bar
- **WHEN** a flip on bar N's close opens a new opposite-side leg
- **THEN** the new entry is filled at bar N's close (or a later bar's open), never at bar N's open

#### Scenario: Exit fill does not reach a future bar
- **WHEN** the bar matching the fill timestamp is missing and a nearest-bar tolerance is applied
- **THEN** the tolerance SHALL NOT select a bar later than the decision bar for an exit, so no
  look-ahead price is used

#### Scenario: Position limit enforcement
- **WHEN** strategy tries to exceed configured position limits
- **THEN** system rejects the order and logs rejection reason

#### Scenario: Order is rejected
- **WHEN** strategy places an order that violates constraints
- **THEN** order is not executed and a rejection event is sent to strategy

---

### Requirement: Trade record generation
The system SHALL record all executed trades to the `backtest_trades` table with timestamp, symbol, quantity, entry/exit price, P&L, and related strategy metadata.

#### Scenario: Filled order is recorded as trade
- **WHEN** an order is executed during backtest
- **THEN** a record is inserted into `backtest_trades` with execution details

#### Scenario: Trade includes profitability metrics
- **WHEN** a trade is closed (position exits)
- **THEN** `backtest_trades` includes entry_price, exit_price, quantity, and realized_pnl

---

### Requirement: Daily equity snapshot
The system SHALL compute daily equity curves and store them in the `backtest_daily` table with date, cumulative P&L, peak equity, and drawdown metrics.

#### Scenario: Daily snapshot at market close
- **WHEN** last bar of trading day is processed
- **THEN** system records daily summary (date, starting_equity, ending_equity, trades_that_day)

#### Scenario: Drawdown calculation
- **WHEN** daily equity curve is computed
- **THEN** `backtest_daily` includes max_drawdown and current_drawdown_pct

---

### Requirement: Backtest run metadata
The system SHALL create a `backtest_runs` table row for each backtest with strategy_id, date
range, start/end equity, total trades, and configuration snapshot. The table SHALL exist in
PostgreSQL before any backtest is run; if missing it SHALL be created via idempotent DDL
(`CREATE TABLE IF NOT EXISTS`) rather than requiring a full alembic migration replay.

#### Scenario: Backtest run is recorded
- **WHEN** backtest completes
- **THEN** a record is inserted into `backtest_runs` with strategy_id, from_date, to_date,
  start_equity, end_equity

#### Scenario: Configuration snapshot is stored
- **WHEN** backtest run is recorded
- **THEN** `backtest_runs` includes a JSON column with strategy config at backtest time

#### Scenario: Table missing does not crash at startup
- **WHEN** `backtest_runs` does not exist and `pdp backtest list` is called
- **THEN** system returns a clear error rather than an unhandled exception

### Requirement: CSV export
The system SHALL export backtest results to CSV files in the `backtest/results/` directory, one file per backtest_run with trades and daily curves.

#### Scenario: Results exported to CSV
- **WHEN** backtest completes
- **THEN** files are written to `backtest/results/<run_id>/trades.csv` and `backtest/results/<run_id>/daily.csv`

#### Scenario: CSV files are readable
- **WHEN** CSV files are created
- **THEN** they follow standard CSV format with headers and can be opened in spreadsheet software

---

### Requirement: Leg-grouped trade summary
The backtest SHALL, in addition to any per-order detail, produce a leg-grouped summary in which
each open-through-cover leg is a single row. Scale-in orders SHALL be folded into their parent
leg via a running average entry price and a cumulative lot count. Each leg row SHALL report the
entry time (IST), the exit time (IST), the average entry price, the exit price, the lot count,
the realized leg profit and loss, and the close reason (one of flip, leg_stop, day_stop, or
square-off).

#### Scenario: Scale-ins fold into one leg
- **WHEN** a leg is opened and scaled in over several bars, then covered
- **THEN** the summary shows a single row whose average entry reflects all entry fills and whose
  lot count equals the total lots covered

#### Scenario: Close reason is reported
- **WHEN** a leg is closed by a flip, a per-leg stop, the daily loss cap, or end-of-day square-off
- **THEN** the leg row's reason column states which of those caused the close

#### Scenario: Leg P&L reconciles to the day total
- **WHEN** all leg rows for a day are summed
- **THEN** the total realized leg P&L equals the day's realized P&L reported by the per-order view

---

### Requirement: Backtest query interface
The system SHALL expose a REST endpoint to query backtest results by strategy_id, date range, and filtering by backtest_run metadata.

#### Scenario: Query backtests for a strategy
- **WHEN** user calls `GET /api/backtests?strategy_id=<id>`
- **THEN** system returns list of backtest_runs for that strategy

#### Scenario: Filter by date range
- **WHEN** user calls `GET /api/backtests?from=<date>&to=<date>`
- **THEN** system returns backtest_runs within the specified range

#### Scenario: Fetch trade details
- **WHEN** user calls `GET /api/backtests/<run_id>/trades`
- **THEN** system returns list of trades from `backtest_trades` for that run

### Requirement: Backtest output reports gross and net P&L
The system SHALL report both gross P&L (premium collected minus premium paid, no costs) and net P&L (gross minus all commissions) in backtest output. Both values SHALL be present in the per-day result dict and the final summary table. The per-day `Trade` record SHALL carry a `commission_inr` field populated by `CommissionCalculator` at fill time.

#### Scenario: Per-day output shows gross, commission, and net columns
- **WHEN** `backtest_multiday.py` completes simulation for a trading day
- **THEN** the printed day summary line shows `Net premium: <gross>  Charges: -<commission_total>  Realized: <net>` where `net = gross - commission_total`

#### Scenario: Final summary includes net P&L totals
- **WHEN** the multi-day backtest summary is printed
- **THEN** each day row in the summary table includes a `Net` column (= gross - commission), and the footer shows `Total gross`, `Total commission`, `Total net`, and `Avg daily net`

#### Scenario: Commission is calculated per fill not per day
- **WHEN** a `Trade` is recorded (BUY or SELL)
- **THEN** `trade.commission_inr` is set to the result of `CommissionCalculator.calculate(side=trade.side, turnover_inr=trade.qty * trade.price)` at the time of fill

#### Scenario: --no-commission flag suppresses cost deduction
- **WHEN** `backtest_multiday.py --no-commission` is run
- **THEN** all `commission_inr` values are 0.00, gross P&L equals net P&L, and the output notes `[commissions disabled]`

### Requirement: Batch option-chain pre-loading

The backtest SHALL pre-load option bars in batch rather than querying per signal bar. For each
distinct expiry in the backtest range the system SHALL issue at most one `option_bars` query,
filtered by `underlying`, `expiry_date`, `option_type`, `timeframe`, and a `ts` range covering all
that expiry's trade-days, using the `(underlying, expiry_date, option_type, ts)` index. Loaded bars
SHALL be grouped in memory by `(trade_date, option_type, strike)` and resampled once to the signal
timeframe. The total number of option-bar queries for a run SHALL be O(number of expiries), not
O(number of signal bars).

#### Scenario: One query per expiry

- **WHEN** a backtest spans N trading days across M distinct weekly expiries
- **THEN** the system issues at most M option-bar queries (plus one NIFTY spot query for the range)
- **AND** the per-bar inner loop performs no MongoDB reads

#### Scenario: Results are unchanged

- **WHEN** the same backtest window is run with batch pre-loading
- **THEN** the replayed trades, per-leg P&L, and summary totals are identical to the per-bar reader

### Requirement: In-memory nearest-strike fallback

When the exact target strike is absent for a `(trade_date, option_type)`, the backtest SHALL select
the nearest available strike within `WAREHOUSE_STRIKE_BAND` grid steps from the already pre-loaded
chain, without issuing additional MongoDB queries. The live broker API MAY be consulted only when
no strike in the band was pre-loaded.

#### Scenario: Substitute strike served from memory

- **WHEN** the exact strike has no bars but a strike within the band does
- **THEN** the nearest in-band strike is used and the substitution is logged
- **AND** no extra MongoDB query is issued to find it

### Requirement: Backtest performance instrumentation

The backtest SHALL record and log, via `structlog`, the total elapsed wall-clock time, per-day
elapsed time, and the count of option-bar queries issued. These metrics SHALL be emitted at the end
of a run so the O(expiries) query budget and the sub-minute target can be verified.

#### Scenario: Timing emitted

- **WHEN** a multi-day backtest completes
- **THEN** a structured log line reports `elapsed_s`, `days`, and `option_queries`

### Requirement: 1-minute option chain store

The backtest SHALL pre-load option bars at 1-minute resolution alongside the existing
5-minute chain store, in a separate `_chain_store_1m`, using the same `load_expiry_chain`
function with `tf_min=1`. The 1-minute store SHALL cover the same expiries and trade dates
as the 5-minute store and SHALL be populated before the day-loop begins (zero MongoDB
round-trips on the hot path).

The 1-minute store is used exclusively for pricing the ST-touch intra-bar exit. If a
contract's 1-minute bars are unavailable, the exit price SHALL fall back to the 5-minute
bar's close price.

#### Scenario: 1-minute option bar found at touch time
- **WHEN** an ST touch is detected at 1-minute timestamp 10:12 for a CE 23,400 leg
- **THEN** the exit price is the CE 23,400 bar's 1-minute close at 10:12 from `_chain_store_1m`

#### Scenario: 1-minute option bar unavailable at touch time
- **WHEN** no 1-minute bar is within tolerance of the touch timestamp
- **THEN** the exit price falls back to the 5-minute bar's close price from `_chain_store`

### Requirement: Config-driven multi-day simulation engine
The system SHALL provide an importable `simulate_day(config, trade_date, data)` engine (in
`src/pdp/backtest/sim.py`) that runs the SuperTrend option-selling logic for one trade day driven
entirely by a `StrategyConfig`. The engine SHALL read no module-level strategy constants; all knobs
(SuperTrend period/multiplier, timeframe, moneyness, lots, session times, stops, roll) SHALL come
from the config. `backtest_multiday.py` SHALL build a config from its values and call this engine.

#### Scenario: Engine consumes config
- **WHEN** `simulate_day` is called with two configs differing only in `st_period`
- **THEN** each run uses its own SuperTrend period and produces independent results

#### Scenario: Legacy config preserves baseline
- **WHEN** the engine runs the full historical window with the legacy config
- **THEN** the window net P&L equals the pre-refactor `backtest_multiday.py` baseline

### Requirement: Signed moneyness strike selection
The engine SHALL select the option strike from spot using a signed `moneyness` offset:
`atm = round(spot/step)*step`; for CE the strike SHALL be `atm + moneyness*step` and for PE
`atm - moneyness*step`, so `moneyness > 0` is OTM, `0` is ATM, and `< 0` is ITM. The result SHALL
feed the existing nearest-strike warehouse fallback unchanged.

#### Scenario: OTM selection
- **WHEN** `select_strike(spot, "CE", moneyness=2, step=50)` is called
- **THEN** it returns the strike two steps above ATM

#### Scenario: ITM selection
- **WHEN** `select_strike(spot, "PE", moneyness=-1, step=50)` is called
- **THEN** it returns the strike one step above ATM (in-the-money for a put)

#### Scenario: ATM selection
- **WHEN** `select_strike(spot, "CE", moneyness=0, step=50)` is called
- **THEN** it returns the ATM strike

### Requirement: First-flip base-lot entry
The engine SHALL open the first position of the day only on the first genuine SuperTrend flip after
session start, sizing the entry at `config.base_lots`.

#### Scenario: No entry before first flip
- **WHEN** the session has started but no SuperTrend flip has occurred yet
- **THEN** the engine opens no position

#### Scenario: Base-lot entry on first flip
- **WHEN** the first genuine flip occurs after session start
- **THEN** the engine opens a `base_lots` short position on the trend-aligned option side

### Requirement: Option-premium scale-in gate
The engine SHALL add `config.add_lots` to the active leg only when the current option bar's low
breaks below the prior option bar's low (premium decay continuing in our favour), never exceeding
`config.max_lots`.

#### Scenario: Add when premium makes a new low
- **WHEN** the active leg's current option bar low is below the prior bar's low and lots < max
- **THEN** the engine adds `add_lots`

#### Scenario: Defer when premium does not make a new low
- **WHEN** the current option bar's low is at or above the prior bar's low
- **THEN** the engine adds nothing this bar and re-evaluates on the next bar

#### Scenario: Respect max lots
- **WHEN** the active leg is already at `max_lots`
- **THEN** the engine adds nothing regardless of the premium break

### Requirement: Partial-flip strangle with flip-candle-break resolution
On a SuperTrend direction flip the engine SHALL close all additional legs of the old side, keep the
old side's base leg, open the opposite side's base leg, and record the flip candle's high and low.
The engine SHALL then resolve the resulting two-base-leg strangle by flip-candle extreme break:
close the old-side base leg when NIFTY breaks above the flip candle's high, and close the new-side
base leg when NIFTY breaks below the flip candle's low. End-of-day square-off SHALL flatten all legs.

#### Scenario: Flip keeps old base and opens opposite base
- **WHEN** direction flips while the active leg holds base + additional lots
- **THEN** the additional lots are closed, the base leg is retained, and an opposite-side base leg is
  opened, leaving a two-leg strangle

#### Scenario: Old base closes on flip-high break
- **WHEN** in a strangle and NIFTY trades above the recorded flip-candle high
- **THEN** the old-side base leg is closed and the new-side base leg continues

#### Scenario: New base closes on flip-low break
- **WHEN** in a strangle and NIFTY trades below the recorded flip-candle low
- **THEN** the new-side base leg is closed and the old-side base leg continues

#### Scenario: Square-off flattens the strangle
- **WHEN** the square-off time is reached while a strangle is open
- **THEN** all open legs are closed

### Requirement: Configurable exit toggles
Roll-up on premium decay, the per-leg MTM stop, and the daily loss cap SHALL be configurable via
`StrategyConfig` (`roll_enabled`/`roll_trigger_prem`/`roll_target_min_prem`, `leg_stop_per_lot`,
`day_stop`).

#### Scenario: Roll-up disabled
- **WHEN** `roll_enabled` is false and a leg's premium falls below `roll_trigger_prem`
- **THEN** the engine does not roll the leg

#### Scenario: Day stop honoured
- **WHEN** cumulative realized day loss reaches `day_stop`
- **THEN** the engine flattens open legs and makes no further entries that day

### Requirement: New engine excludes profit-lock and ST-touch exits
The config-driven `simulate_day` engine SHALL NOT implement the trailing profit-lock or ST-touch
intra-bar exit. These remain defined only for the live strategy (`supertrend-strategy` spec) and are
out of scope for the swept backtest strategy, which acts on completed bars plus the
flip-candle-break rule. `StrategyConfig` SHALL expose no fields for them.

#### Scenario: No profit-lock in the engine
- **WHEN** a leg's MTM peaks and then retraces during a `simulate_day` run
- **THEN** the engine does not close the leg for a profit-lock reason (only stops, flip, roll,
  strangle break, or square-off can close it)

#### Scenario: No intra-bar ST-touch in the engine
- **WHEN** intra-bar NIFTY prices touch the SuperTrend line during a bar
- **THEN** the engine takes no intra-bar exit; exits are evaluated on completed bars and the
  flip-candle-break rule

### Requirement: Fixed actual-strike option pricing

The backtest SHALL price option legs from the `option_bars` warehouse by the **fixed actual
contract** — `(underlying, expiry_date, strike, option_type, timeframe)` — rather than an
ATM-relative rolling label. The target strike SHALL be derived from spot (ATM rounded to the strike
grid, plus the strategy's OTM offset) and the `expiry_date` from the NIFTY expiry calendar. When the
exact target strike is unavailable for a day, the backtest SHALL fall back to the **nearest
available strike** within the warehoused band before any live API call. A held position SHALL be
priced as one stable fixed-strike series across the days it is held.

#### Scenario: Leg priced from the fixed contract

- **WHEN** the backtest needs an option price for a given trade day and side
- **THEN** it computes the target strike from spot and resolves `expiry_date` from the calendar
- **AND** reads that exact `(expiry_date, strike, option_type)` series from `option_bars`, resampled
  to the signal timeframe

#### Scenario: Nearest-strike fallback

- **WHEN** the exact target strike has no bars for the day but other band strikes do
- **THEN** the backtest prices from the nearest available strike and logs the substitution

#### Scenario: Positional hold reads one series

- **WHEN** a position is held across multiple days
- **THEN** the same fixed `(expiry_date, strike, option_type)` contract is read for every day of the
  hold, without strike drift

### Requirement: Backtest routes registered in main.py

The existing `src/pdp/backtest/routes.py` router SHALL be registered in `src/pdp/main.py` so that read-only backtest result endpoints are accessible via the API. This includes any existing `GET` endpoints for listing and viewing past backtest results.

#### Scenario: Backtest routes are accessible
- **WHEN** the API starts
- **THEN** `GET /api/v1/backtests` (if defined) is accessible and returns HTTP 200

---

### Requirement: Backtest run endpoint

The backtest router SHALL include a `POST /api/v1/backtests/run` endpoint that accepts an options strategy configuration and executes the backtest. When the job runner (proposal #5) is available, this endpoint SHALL submit the backtest as an async job instead of running synchronously.

#### Scenario: Synchronous execution before job runner
- **WHEN** `POST /api/v1/backtests/run` is called and the job runner is not yet available
- **THEN** the backtest runs synchronously and results are returned in the response body

