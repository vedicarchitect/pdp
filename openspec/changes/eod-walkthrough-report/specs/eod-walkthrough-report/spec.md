## ADDED Requirements

### Requirement: Per-day forensic report

The system SHALL generate one self-contained markdown file per trading day at
`backend/backtest/manual/YYYY-MM-DD.md`, replaying both the directional-strangle and
intraday-directional engines over that day and rendering, for each: a decision timeline, an
orders/fills table with the underlying spot printed beside every fill, a closed-legs table, a
why-no-trade census of block/gate reasons, a per-decision-bar table, and a collapsed per-minute
spot/indicator/leg ribbon. The report SHALL end with a ranked FINDINGS section produced by
automated invariant checks.

The renderer SHALL be a pure function of already-replayed results — no Mongo access, no file I/O —
so it is unit-testable against synthetic days independent of the runner that drives it.

#### Scenario: Report covers a normal trading day

- **WHEN** the runner replays both engines for a date with a complete option chain
- **THEN** `backend/backtest/manual/<date>.md` is written containing a header, a verdict box for
  each strategy, per-strategy timeline/fills/closed-legs/census/bar-table/minute-ribbon sections,
  a cross-strategy contrast, and a FINDINGS section

#### Scenario: Every fill shows underlying spot

- **WHEN** a strategy opens or closes a leg on any day
- **THEN** the corresponding fill row in the report shows the underlying's spot price at that
  timestamp, not just the option's fill price

### Requirement: Arbitrary and ranged date selection

The system SHALL accept a single arbitrary historical date, a `--from`/`--to` range, or a trailing
`--days N [--start D]` window, producing exactly one file per resolved trading day through the
identical code path. Omitting every selector SHALL default to today (IST).

#### Scenario: Single historical date

- **WHEN** the runner is invoked with `--date 2024-03-14`
- **THEN** it replays only that date and writes `backend/backtest/manual/2024-03-14.md`, regardless
  of the current date

#### Scenario: Range produces one file per day

- **WHEN** the runner is invoked with `--from 2026-07-21 --to 2026-07-24`
- **THEN** four files are written, one per trading day in the range, each independently correct

#### Scenario: No selector defaults to today

- **WHEN** the runner is invoked with no date arguments
- **THEN** it resolves the current IST trading date and generates that day's report only

### Requirement: Historical-data honesty

The system SHALL refuse to silently generate a report over data known to be unreliable. A
non-trading day (weekend, holiday, or no bars) SHALL exit without writing a file. A date whose
resolved expiry falls inside a known `cadence_gap_days` stretch SHALL render a loud banner at the
top of the file and emit a corresponding finding rather than reporting the numbers as trustworthy.
A date inside the confirmed NIFTY blackout (2020-12-03 → 2023-01-05) SHALL refuse outright unless
the caller passes `--force`.

#### Scenario: Weekend produces no file

- **WHEN** the runner is invoked with a Saturday or Sunday date
- **THEN** no file is written and the runner exits with a clear message identifying the day as a
  non-trading day

#### Scenario: Cadence gap is surfaced, not hidden

- **WHEN** a requested date's resolved expiry falls inside a known ingestion cadence gap
- **THEN** the report is still generated but carries a top-of-file banner and a `F-DATA-GAP`
  finding naming the gap

#### Scenario: Blackout date refuses without --force

- **WHEN** a requested date falls inside 2020-12-03 → 2023-01-05 and `--force` is not passed
- **THEN** the runner exits without writing a file, naming the blackout as the reason

#### Scenario: Blackout date proceeds with --force

- **WHEN** a requested date falls inside the blackout and `--force` is passed
- **THEN** the report is generated with the blackout banner and `F-DATA-GAP` finding present

### Requirement: Automated findings engine

The system SHALL run a fixed set of invariant checks against each day's replayed trace, trades,
legs, and config, each emitting zero or more `Finding` records with a stable ID, severity, title,
evidence lines, and bar references. Every detector SHALL have both a positive fixture (it fires
when the condition is present) and a negative fixture (it stays silent otherwise), so a detector
cannot silently no-op. Findings SHALL be rendered ranked by severity in the report and summarized
as one line per day in `backend/backtest/manual/INDEX.md`.

#### Scenario: A cost/qty inconsistency is caught generically

- **WHEN** any leg's `total_cost` and `avg_entry * total_qty` diverge by more than a cent on any bar
- **THEN** `F-COST-QTY` fires with the offending bar reference and both values as evidence

#### Scenario: VIX-gate regression guard

- **WHEN** a bar's config has `vix_gate_enabled: false` but the recorded gate reason is not
  `vix_gate_disabled`
- **THEN** `F-VIX-ACTIVE` fires, naming the bar and the recorded reason

#### Scenario: Silent day-loss breach

- **WHEN** `day_pnl` is below `-day_loss_limit` on a bar where the day is not marked done, or any
  fill is recorded after the day was marked done
- **THEN** `F-HALT-BREACH` fires, excluding fills that close a protective hedge rather than open risk

### Requirement: Single-sourced VIX gate

The system SHALL gate strangle entries on India VIX through exactly one configuration field,
`BiasWeights.vix_gate_enabled`, read by `_vix_gate` in the shared bias-scoring core. Every call site
that constructs `BiasWeights` — backtest CLI, walk-forward, sweep, replay, and live — SHALL reach
the gate through that single field rather than each independently faking a disabled state.

#### Scenario: Disabled gate is honored on every call path

- **WHEN** a config sets `vix_gate_enabled: false`
- **THEN** `strangle_run.py`, `strangle_walkforward.py`, `sweep_engine.py`, `replay.py`, and the live
  strategy all record `vix_gate_disabled` as the gate reason for every bar, with no code path
  gating on VIX regardless

#### Scenario: Enabled gate still functions

- **WHEN** a config sets `vix_gate_enabled: true` and VIX data is unavailable for a bar
- **THEN** the bar is gated with reason `vix_unavailable`

### Requirement: Correct partial-close arithmetic

The system SHALL preserve a leg's average entry price across a partial close: reducing
`total_qty` SHALL NOT change `avg_entry`, and `total_cost` SHALL always equal
`avg_entry * total_qty` to within floating-point tolerance. A partial close SHALL be subject to the
same day-loss-cap check as a full close, and a leg reduced by a partial close SHALL be latched
against firing the same partial-stop rule again until a fill re-establishes its position.

#### Scenario: Average entry unchanged by a partial close

- **WHEN** a leg with 5 lots at average entry 100 is partially closed to 3 remaining lots
- **THEN** the remaining leg's `avg_entry` is still 100 and `total_cost == 100 * 3 * lot_size`

#### Scenario: Partial close can trip the day-loss cap

- **WHEN** a partial close's realized loss pushes cumulative day P&L below `-day_loss_limit`
- **THEN** the day is marked done with a `day_loss` reason, exactly as a full close would

#### Scenario: Partial-stop does not re-fire on the same leg

- **WHEN** a leg has already been half-stopped once
- **THEN** the same partial-stop rule does not fire again for that leg until a new fill changes its
  position
