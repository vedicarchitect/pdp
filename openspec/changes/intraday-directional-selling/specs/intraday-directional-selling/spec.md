## ADDED Requirements

### Requirement: Shared pure decision core

The system SHALL implement all entry, scale-in, and exit decision logic for the intraday directional
option-selling strategy in a single pure module, `pdp/signals/intraday_directional.py`, which both
the live strategy and the backtest engine call. The module MUST NOT perform I/O and MUST NOT import
from `pdp.orders`, `pdp.db`, `pdp.mongo`, or `pdp.market`. Given identical `IntradayInputs`,
`IntradayParams`, and `IntradayState`, it SHALL return identical decisions on both paths.

Any input required by a condition that is absent (`None`) SHALL cause that condition to evaluate as
**not satisfied** — the strategy fails closed rather than guessing, because every entry opens a
short option position.

#### Scenario: Same inputs produce same decision on both paths

- **WHEN** the live strategy and the backtest engine construct the same `IntradayInputs` for a bar
- **THEN** `evaluate_entry`, `evaluate_scale_in`, and `evaluate_exit` return equal results

#### Scenario: Missing indicator blocks entry

- **WHEN** any of `ema9_5m`, `ema20_5m`, `st_5m_dir`, `session_vwap`, `orb_high`, or `orb_low` is `None`
- **THEN** `evaluate_entry` returns `None` and no position is opened

### Requirement: Session and opening-range gating

The system SHALL capture the opening range from the 15-minute candle stamped 09:15 IST (covering
09:15:00–09:29:59), recording `orb_high` and `orb_low`, and SHALL reject every entry until that
candle has closed. Trading decisions SHALL be evaluated on the 5-minute timeframe, with the
15-minute timeframe used for confirmation and scale-in.

The opening range SHALL be reset at each IST day rollover, and a session whose 09:15 candle is
missing SHALL be treated as un-seeded — entries blocked for that day, with an observable event
emitted rather than a silent skip.

#### Scenario: No entry before the ORB candle closes

- **WHEN** the decision bar's IST time is earlier than `entry_after_ist` (09:30 by default)
- **THEN** no entry is evaluated and the strategy logs a heartbeat only

#### Scenario: ORB captured from the 09:15 candle

- **WHEN** the 15m bar stamped 09:15 IST closes
- **THEN** `orb_high`/`orb_low` are set to that bar's high/low and persist for the rest of the session

#### Scenario: Missing ORB blocks the day

- **WHEN** no 15m bar stamped 09:15 IST is observed for the session
- **THEN** the opening range stays un-seeded, entries are blocked for that day, and an unseeded-indicator event is emitted

### Requirement: Expiry selection constrained by DTE

The system SHALL only trade contracts whose calendar days-to-expiry is at most `dte_max` (default 6,
i.e. strictly less than 7 as specified), resolving the expiry from real listed contracts rather than
a hardcoded weekday. Days whose nearest resolved expiry exceeds `dte_max` SHALL be skipped and
counted as skipped, not traded against a farther contract.

#### Scenario: Day beyond the DTE window is skipped

- **WHEN** the nearest real expiry for a trade date is more than `dte_max` calendar days away
- **THEN** that day is skipped with reason `dte_window` and no orders are placed

### Requirement: Bullish entry sells a put

The system SHALL open a short PE position when, on a closed 5-minute decision bar, all four
conditions hold simultaneously: spot is above `orb_low`; spot is above the session VWAP; the
SuperTrend(10,2) direction on the underlying is bullish; and EMA9 is above EMA20 (satisfied either
by a fresh cross-up on this bar or by EMA9 already above EMA20 and rising).

The initial size SHALL be `initial_lots` (default 3).

#### Scenario: All four bullish conditions hold

- **WHEN** spot > `orb_low`, spot > session VWAP, SuperTrend(10,2) is bullish, and EMA9 > EMA20 with positive slope
- **THEN** a short PE leg is opened with `initial_lots` lots

#### Scenario: One bullish condition fails

- **WHEN** three of the four bullish conditions hold but spot is at or below the session VWAP
- **THEN** no position is opened and the failing condition is recorded in the decision trace

### Requirement: Bearish entry sells a call

The system SHALL open a short CE position when, on a closed 5-minute decision bar, all four
conditions hold simultaneously: spot is below `orb_high`; spot is below the session VWAP; the
SuperTrend(10,2) direction on the underlying is bearish; and EMA9 is below EMA20 (satisfied either
by a fresh cross-down on this bar or by EMA9 already below EMA20 and falling).

The initial size SHALL be `initial_lots` (default 3).

#### Scenario: All four bearish conditions hold

- **WHEN** spot < `orb_high`, spot < session VWAP, SuperTrend(10,2) is bearish, and EMA9 < EMA20 with negative slope
- **THEN** a short CE leg is opened with `initial_lots` lots

### Requirement: Only one directional position at a time

The system SHALL hold at most one directional short leg (PE or CE, never both) at any moment. A new
entry SHALL be rejected while a directional position is open, and an opposing signal SHALL NOT flip
the position directly — the existing position must exit through an exit rule first.

Protective hedge legs bought under `hedge_enabled` are not directional positions and do not count
against this limit. A rollup replaces the open leg in place and is likewise not a second position.

After a position exits, the system SHALL permit a new entry the same session once
`reentry_cooloff_minutes` (default 15) has elapsed since that exit, and SHALL block entries during
the cooloff. The cooloff SHALL apply to every exit reason except `day_loss_cap` and `square_off`,
both of which end the session's trading outright.

#### Scenario: Opposing signal while positioned

- **WHEN** a short PE is open and the bearish entry conditions become true
- **THEN** no short CE is opened while the PE leg remains open

#### Scenario: Re-entry blocked during cooloff

- **WHEN** a position exited 5 minutes ago and all entry conditions hold again, with `reentry_cooloff_minutes` 15
- **THEN** no new position is opened and the block is recorded in the decision trace

#### Scenario: Re-entry allowed after cooloff

- **WHEN** a position exited 20 minutes ago and all entry conditions hold again
- **THEN** a new position is opened and the decision event is recorded as `reentry`

#### Scenario: Day-ending exits are not subject to cooloff

- **WHEN** the position exited via `day_loss_cap` or `square_off`
- **THEN** no further entry occurs that session regardless of elapsed time

### Requirement: Strike selection supports ATM and ITM depth

The system SHALL select the sold strike by a configurable `moneyness` offset from the at-the-money
strike, where `0` selects ATM and negative values select in-the-money strikes (`-1` and `-2` giving
the 1–2 strikes ITM the source spec prefers). When the exact strike is unavailable in the chain, the
system SHALL resolve to the nearest available strike within a bounded band, or decline to trade
rather than substituting an arbitrary strike.

#### Scenario: ATM selection

- **WHEN** `moneyness` is 0 and spot is 24,517 with `strike_step` 50
- **THEN** the 24,500 strike is selected

#### Scenario: ITM selection for a put

- **WHEN** `moneyness` is -2 for a PE and the ATM strike is 24,500 with `strike_step` 50
- **THEN** the 24,600 strike is selected

#### Scenario: Strike unavailable

- **WHEN** neither the target strike nor any strike within the resolution band exists in the chain
- **THEN** no order is placed and the attempt is recorded as an aborted entry

### Requirement: Time-based scale-in ladder

The system SHALL add `scale_lots_step` lots (default 3) to the open directional leg every
`scale_in_minutes` (default 15) measured from the entry, for as long as every entry condition for
that side still holds, until cumulative size reaches `max_lots` (default 9) — giving the 3 → 6 → 9
ladder in the source spec.

Scale-in lots SHALL be added to **the same strike as the existing leg**, updating the leg's average
entry price, so the position remains a single leg with a single exit. A scale-in SHALL be skipped,
not deferred, when the entry conditions no longer hold at the scale-in instant, and SHALL never take
cumulative size above `max_lots`. After a rollup the ladder SHALL continue at the new strike,
carrying its cumulative lot count forward.

#### Scenario: Ladder progresses while trend holds

- **WHEN** a 3-lot leg has been open for 15 minutes and all entry conditions still hold
- **THEN** 3 more lots are added at the same strike, taking the leg to 6 lots, and the average entry price is updated

#### Scenario: Ladder stops at the cap

- **WHEN** the leg holds `max_lots` lots and another scale-in interval elapses with conditions holding
- **THEN** no further lots are added

#### Scenario: Conditions broken at the scale-in instant

- **WHEN** the scale-in interval elapses but SuperTrend has flipped against the position
- **THEN** no lots are added

### Requirement: Exit rules evaluated in a fixed priority order

The system SHALL evaluate the eight exit conditions in a fixed, deterministic priority order and act
on the first that matches, exiting the entire directional position (and any matching hedge) in one
decision. The order SHALL be: daily loss cap; time-based square-off; unrealised-loss stop;
premium-rise stop; underlying SuperTrend flip; option-chart SuperTrend flip; sustained EMA20 break;
sustained Camarilla rejection.

Each exit SHALL record its reason code so the decision trace attributes the exit unambiguously.

#### Scenario: Highest-priority rule wins

- **WHEN** both the daily loss cap and the underlying SuperTrend flip trigger on the same bar
- **THEN** the position exits once with reason `day_loss_cap`

### Requirement: Sustained EMA20 break exit

The system SHALL exit the position when the underlying closes on the wrong side of the 20-EMA for
`ema_break_bars` consecutive 5-minute bars (default 3, i.e. the 15 minutes the source spec
requires). The counter SHALL reset to zero on any bar that closes back on the correct side, so only
a sustained break exits.

For a short PE the wrong side is below EMA20; for a short CE it is above EMA20.

#### Scenario: Three consecutive wrong-side closes exit

- **WHEN** a short PE is open and three consecutive 5m bars close below EMA20
- **THEN** the position exits with reason `ema20_break_sustained`

#### Scenario: Interrupted break does not exit

- **WHEN** two bars close below EMA20 and the third closes above it
- **THEN** the counter resets and the position stays open

### Requirement: SuperTrend flip exits on both underlying and option charts

The system SHALL exit the position when the SuperTrend(10,2) direction on the underlying flips
against the position, and separately when the SuperTrend(10,2) computed on the sold option's own
5-minute chart flips against the position.

The option-chart SuperTrend SHALL be computed from that contract's own stored 1-minute bars rolled
up to 5 minutes using the same session-anchored bucketing and the same tracker class the live feed
uses, so the live and backtest reads are identical given the same bars. When the option's bars are
unavailable the read SHALL abstain (contribute no exit) rather than fabricate a direction.

#### Scenario: Underlying SuperTrend flips against a short PE

- **WHEN** a short PE is open and the underlying SuperTrend(10,2) turns bearish
- **THEN** the position exits with reason `underlying_st_flip`

#### Scenario: Option-chart SuperTrend flips

- **WHEN** the sold option's own 5m SuperTrend(10,2) turns against the short position
- **THEN** the position exits with reason `option_st_flip`

#### Scenario: Option bars unavailable

- **WHEN** the sold contract has no stored 1m bars for the session
- **THEN** the option-chart SuperTrend abstains and does not trigger an exit

### Requirement: Sustained Camarilla rejection exit

The system SHALL exit the position when price is rejected from a Camarilla S3, S4, R3, or R4 level
computed from the previous day's high/low/close, and that rejection persists for
`cam_reject_minutes` (default 30, i.e. six consecutive 5-minute bars).

A rejection SHALL be recorded when price touches within `cam_touch_eps` of the level and then closes
back away from it in the direction adverse to the open position; the sustain counter SHALL reset
when price closes back through the level.

#### Scenario: Rejection sustained for 30 minutes

- **WHEN** a short PE is open, price is rejected from R3, and six consecutive 5m bars close below R3 after the touch
- **THEN** the position exits with reason `cam_rejection_sustained`

#### Scenario: Rejection not sustained

- **WHEN** price is rejected from R3 but closes back above R3 three bars later
- **THEN** the counter resets and the position stays open

### Requirement: Premium-based stops

The system SHALL exit the entire position when the sold option's premium reaches
`avg_entry * (1 + premium_rise_stop_pct)` (default `premium_rise_stop_pct` 1.0, i.e. the premium
doubles), and separately when unrealised loss reaches `unreal_loss_pct` (default 0.20) of the
position's credit value, where credit value is `avg_entry * lots * lot_size`.

Both stops SHALL be driven from the sold contract's traded price. The system MUST NOT compute
unrealised P&L from an entry price of zero — an unpriced leg SHALL report zero, never a phantom
value.

#### Scenario: Premium doubles

- **WHEN** the average entry premium is 100 and the option trades at 200 with `premium_rise_stop_pct` 1.0
- **THEN** the position exits with reason `premium_rise_stop`

#### Scenario: Unrealised loss cap

- **WHEN** the average entry premium is 100 and the option trades at 120 with `unreal_loss_pct` 0.20
- **THEN** the position exits with reason `unreal_loss_stop`

#### Scenario: Unpriced leg reports no phantom loss

- **WHEN** a leg's recorded entry price is zero or negative
- **THEN** its unrealised P&L is reported as zero and no premium-based stop fires from it

### Requirement: Daily loss cap halts the day

The system SHALL flatten every position and stop trading for the remainder of the session when the
day's total profit-and-loss reaches `-day_loss_limit` (default ₹10,000). The halt SHALL persist
across a same-day restart so a process restart cannot resume trading after the cap was hit.

Total profit-and-loss for this rule SHALL be realised P&L **plus the open position's
mark-to-market**. Evaluating realised P&L alone would make the rule unreachable while positioned —
the only way to realise a loss is to close, and closing is precisely what this rule exists to
trigger — which would leave the specified hard stop dead in exactly the situation it guards.

#### Scenario: Cap reached on realised loss

- **WHEN** the day's realised P&L reaches -₹10,000
- **THEN** all positions are closed with reason `day_loss_cap` and no further entries occur that day

#### Scenario: Cap reached on an open position's mark-to-market

- **WHEN** the strategy is flat on realised P&L but the open position is down ₹10,000 on mark-to-market
- **THEN** the position is closed with reason `day_loss_cap` and no further entries occur that day

#### Scenario: Restart after cap

- **WHEN** the strategy restarts on the same IST trading day after the cap was hit
- **THEN** it resumes in the halted state and opens no new positions

### Requirement: No overnight positions

The system SHALL close every open position at `squareoff_ist` (default 15:15 IST) and SHALL NOT
carry any position across sessions. Session timing decisions SHALL be derived from bar timestamps
rather than wall-clock time so backtest and live behave identically.

#### Scenario: Square-off time reached

- **WHEN** the decision bar's IST time reaches `squareoff_ist`
- **THEN** every open leg is closed with reason `square_off` and no further entries occur that day

### Requirement: Optional protective hedge

The system SHALL, when `hedge_enabled` is true, buy a far-OTM option of the same expiry and same
option type as the short leg, selecting the furthest-OTM strike whose premium falls within
`[hedge_prem_min, hedge_prem_max]` (default ₹2–₹5). The hedge SHALL be closed whenever its
corresponding short leg closes.

When no strike prices within the band, the system SHALL either select the cheapest available strike
or skip the hedge according to configuration, and MUST NOT leave the hedge silently unopened without
an observable event.

#### Scenario: Hedge bought within the premium band

- **WHEN** `hedge_enabled` is true and a strike in the same expiry prices at ₹3
- **THEN** that strike is bought as a hedge alongside the short leg

#### Scenario: Hedge closed with its short

- **WHEN** the short leg exits for any reason
- **THEN** its matching hedge leg is closed in the same exit

### Requirement: Session VWAP source is explicit and identical across paths

The system SHALL compute the session VWAP input from a configurable `vwap_source`, defaulting to
`session_twap`: a session-anchored cumulative mean of typical price `(high + low + close) / 3` over
the underlying's 1-minute bars from the session open. The same definition and the same source bars
SHALL be used on the live and backtest paths.

A true volume-weighted VWAP on the spot index SHALL NOT be used, because the index carries no
traded volume and the tracker can never converge; this constraint SHALL be documented in the
configuration rather than failing silently at runtime.

#### Scenario: TWAP proxy computed identically

- **WHEN** the same 1m bar series is fed to the live accumulator and the backtest loader
- **THEN** both produce the same session VWAP value at every 5m decision bar

#### Scenario: Session boundary resets the accumulator

- **WHEN** an IST day rollover occurs
- **THEN** the session VWAP accumulator resets and re-anchors at the new session open

### Requirement: Backtest engine reuses the existing warehouse pipeline

The system SHALL provide a backtest engine for this strategy that emits the existing `DayResult`,
`Trade`, and `LegRecord` structures so the established run/day/trade/decision persistence,
aggregation, and verdict machinery apply without modification. Decision events SHALL use the
existing reason-code vocabulary (`entry`, `scale_in`, `exit`, `st_flip`, `reentry`) so the
backtest-explain and backtest-vs-paper tooling continues to work.

Fills SHALL contain no look-ahead: a decision taken on a bar SHALL be priced from data at or before
that bar, and commissions SHALL be applied through the existing commission calculator.

#### Scenario: Run persists through the existing warehouse

- **WHEN** a backtest run completes
- **THEN** its documents appear in `backtest_runs`, `backtest_days`, `backtest_trades`, and `backtest_decisions` with the standard fields

#### Scenario: No look-ahead pricing

- **WHEN** an entry is decided on the bar closing at 10:05
- **THEN** the fill price is drawn from data at or before 10:05

### Requirement: Rollup to ATM on premium decay

The system SHALL roll the open directional short leg back to the at-the-money strike when its
premium decays below `roll_trigger_prem` (default ₹20), closing the decayed leg and re-opening the
same side, same lot count at the current ATM strike. Rolling SHALL preserve the position's side and
size; it is a strike change, not an exit and not a re-entry, and MUST NOT count against the
one-position-at-a-time limit.

The roll SHALL be all-or-nothing: every precondition — a usable spot, a resolvable ATM instrument,
and that instrument pricing at or above `roll_target_min_prem` — SHALL be verified **before** the
existing leg is closed. A roll that cannot complete SHALL leave the existing position exactly as it
was rather than closing it and leaving the strategy flat. After the re-open the system SHALL verify
a leg is actually tracked again, and SHALL raise a naked-position alarm when the close succeeded but
the re-open did not.

The roll SHALL be idempotent under concurrency: two events arriving for the same contract MUST NOT
both roll it. Any matching hedge SHALL be rolled with its short. Rolling SHALL reset the scale-in
clock but preserve the ladder's cumulative lot count.

Three guardrails SHALL bound rolling: the re-opened leg SHALL carry **the same lot count** the
decayed leg held (not `initial_lots`); the ATM strike SHALL price at or above `roll_target_min_prem`
(default ₹50) or the roll is skipped; the session SHALL perform at most `max_rolls_per_day`
(default 2) rolls; and no roll SHALL occur at or after `roll_cutoff_ist` (default 14:45), since a
freshly-opened short has no time to work before square-off.

#### Scenario: Premium decays below the trigger

- **WHEN** the sold option's premium falls below `roll_trigger_prem` and the current ATM strike prices at or above `roll_target_min_prem`
- **THEN** the decayed leg is closed and the same side is re-opened at the ATM strike with the same lot count, emitting a `rollup` decision event

#### Scenario: Roll target too cheap

- **WHEN** the premium decays below the trigger but the ATM strike prices below `roll_target_min_prem`
- **THEN** no roll occurs, the existing leg stays open unchanged, and the skip is recorded with its reason

#### Scenario: Lot count preserved across a roll

- **WHEN** a leg holding 6 lots rolls to ATM
- **THEN** the re-opened leg holds 6 lots, not `initial_lots`

#### Scenario: Daily roll cap reached

- **WHEN** `max_rolls_per_day` rolls have already occurred and another leg decays below the trigger
- **THEN** no further roll occurs and the leg is left to its normal exit rules

#### Scenario: Roll blocked near square-off

- **WHEN** the premium decays below the trigger at or after `roll_cutoff_ist`
- **THEN** no roll occurs

#### Scenario: Roll cannot reopen

- **WHEN** the decayed leg is closed but the re-open fails to land a leg
- **THEN** a naked-position critical event is emitted rather than reporting the roll as successful

#### Scenario: Concurrent roll attempts

- **WHEN** two price updates below the trigger arrive for the same contract concurrently
- **THEN** exactly one roll is performed

### Requirement: Leg lifecycle invariants inherited from the production strategy

The system SHALL enforce, on the live path, the same leg-lifecycle invariants the production
`DirectionalStrangle` established through live-incident remediation, because this strategy places
real option orders through the same order router and is exposed to the same failure modes.

The invariants are:

1. **One leg per security.** Open legs SHALL live in a single `security_id`-keyed map that is the
   sole source of truth; registering a duplicate `security_id` SHALL raise and emit a
   leg-state-diverged alarm rather than tracking one broker position with two leg records.
2. **Lock discipline.** Every broker read-modify-write sequence (`cancel open orders` → read
   `net_qty` → place) on a security SHALL run under that security's own lock, held by both the open
   and the close path, so a concurrent open and close cannot interleave. Because the lock is not
   re-entrant, a roll SHALL release its claim before invoking the close and re-open paths.
3. **Close side derives from the broker sign, never from the leg's recorded kind.** A position with
   `net_qty > 0` SHALL be flattened with a SELL and `net_qty < 0` with a BUY. A sign that
   contradicts the leg's recorded kind SHALL raise a leg-type-contradicted alarm and, in live mode,
   halt the day.
4. **Never close more than the broker holds.** Closing SHALL place `min(leg_lots, broker_lots)`. A
   residual that rounds to less than one lot SHALL flag divergence and leave the leg tracked rather
   than emitting a terminal close that orphans the residual.
5. **Leg identity is durable.** A leg's kind, option type, strike, and expiry SHALL be persisted on
   open and read back on restart; closing SHALL mark the row closed rather than deleting it.
6. **An unresolved entry price MUST NOT silently discard a real fill.** When the fill price cannot
   be read within budget, the system SHALL cancel the entry order and — only if the cancel did not
   take effect, meaning the order had already filled — adopt the broker's own average price. It MUST
   NOT substitute a last-traded-price estimate, which would be available whether or not this
   specific order filled.
7. **Position size is capped per security.** A per-security lot cap SHALL be enforced inside the
   same lock as order placement, so two concurrent opens cannot jointly exceed it.
8. **Divergence is surfaced, not silently corrected**, and reconciliation SHALL run unattended on a
   timer rather than only when a console polls.

Invariant 6 SHALL be implemented **once**, in a shared module used by both this strategy and
`DirectionalStrangle`. Duplicating it is what left two of the strangle's three entry paths exposed
until the 2026-07-25 review, and this change MUST NOT recreate that hazard.

#### Scenario: Duplicate leg registration refused

- **WHEN** a leg is registered for a `security_id` that already has an open leg
- **THEN** registration raises, a leg-state-diverged alarm is emitted, and the existing leg is left intact

#### Scenario: Broker sign contradicts leg kind

- **WHEN** a leg recorded as a short is found at a positive broker `net_qty` on close
- **THEN** a leg-type-contradicted alarm is emitted and the position is flattened by the broker sign

#### Scenario: Fill confirmed after a failed price read

- **WHEN** the entry price cannot be read within budget and the subsequent cancel finds the order already filled
- **THEN** the leg is registered from the broker's own average fill price, not from a last-traded-price estimate

#### Scenario: Broker holds fewer lots than tracked

- **WHEN** a 6-lot leg is closed but the broker holds only 3 lots
- **THEN** 3 lots are closed, never 6, and the divergence is recorded

### Requirement: Results comparable against the directional strangle

The system SHALL emit backtest results for this strategy in the same shape, through the same
warehouse collections, and against the same metric and verdict definitions used by the
directional-strangle engine, so the two strategies can be compared directly without a bespoke
reconciliation step.

Comparability SHALL cover: the per-day and per-run metric set (net, gross profit, gross loss, profit
factor, win rate, max drawdown, Sharpe, Calmar, trade count); the same commission model; the same
lot-size-by-date resolution so notional sizing is consistent across eras; the same decision-event
vocabulary; and the same PASS/REVIEW verdict thresholds. Runs SHALL be distinguishable by a strategy
identifier so a comparison can select between them.

A comparison MUST NOT be presented as like-for-like across windows whose underlying option-data
coverage differs; the cadence-gap day count SHALL be reported alongside the metrics for every run.

#### Scenario: Side-by-side comparison over one window

- **WHEN** both strategies are backtested over the same underlying and the same date window
- **THEN** their runs expose the same metric fields computed the same way, and can be compared without transformation

#### Scenario: Coverage difference surfaced

- **WHEN** a run's window includes trade days that resolved to a distant expiry because of a data gap
- **THEN** the count of those days is reported with the run's metrics

### Requirement: Registry exposes the new strategy kind

The system SHALL register `intraday_directional` as a strategy kind in the unified strategy registry
so new parameter variants can be created through the registration API and launched as backtests
without a code change or restart, consistent with the existing `strangle` and `supertrend` kinds.

#### Scenario: Variant registered and listed

- **WHEN** a new `intraday_directional` variant is registered with valid params
- **THEN** it appears in the strategy listing with its resolved defaults and param schema

#### Scenario: Invalid params rejected

- **WHEN** a variant is registered with a parameter that fails the engine's validation
- **THEN** registration is rejected with a message naming the offending field
