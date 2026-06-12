## Why

`supertrend_short` gates its trading window with `_now_ist()` — the **wall clock** — while the
backtest gates on each **bar's timestamp**. The two diverge at session boundaries (a bar that
closes at 15:10 may be processed a few seconds later and be treated as past square-off; a
replayed/late bar is judged against the wrong clock), and a wall-clock gate makes the live
strategy impossible to drive deterministically from historical bars. A stable product schedules
on the data it is reacting to, not on when the process happened to run.

## What Changes

- Change `supertrend_short` start-time and square-off gating to use the **closed bar's
  timestamp** (converted to IST) instead of `datetime.now()`.
- Remove the `_now_ist()` wall-clock dependency from the entry/square-off decision path.
- Behavior is otherwise unchanged: no entries before `start_ist`, flatten and stop at
  `square_off_ist`, both compared against the bar time.

## Capabilities

### Modified Capabilities

- `supertrend-strategy`: the trading-window requirement is restated to gate on bar time.

## Impact

- Depends on `supertrend-strategy`; touches only `src/pdp/strategies/supertrend_short.py`.
- Makes live and backtest scheduling identical and lets the live strategy be replayed
  deterministically from historical bars.
