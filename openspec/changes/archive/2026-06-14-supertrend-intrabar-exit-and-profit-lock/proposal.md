## Why

The current strategy waits for a 5-minute bar to close before taking any exit action. Two
gaps follow from that:

1. **ST-touch delay.** A bar whose intra-bar price penetrates the SuperTrend line loses value
   by waiting for the full bar to close. The short leg's premium spikes against the position
   (market moved through ST) during the bar, but we book the exit only at bar close — paying
   the full reversal cost. Exiting the moment the 1-minute sub-bar crosses the ST level cuts
   that cost significantly.

2. **No profit protection.** A short leg can run up a healthy unrealised gain (e.g. ₹3,000
   MTM) and give it all back before the bar-close check fires the exit. There is no trailing
   high-watermark mechanism to lock in at least half the peak profit.

## What Changes

- **ST-touch intra-bar exit.** For each 5-minute signal bar, iterate the 1-minute NIFTY spot
  sub-bars within that window. When the 1-minute bar's extreme (LOW for an uptrend position /
  HIGH for a downtrend position) breaches the prior completed bar's SuperTrend line value
  (`prev_st.value`), close the held option leg immediately at the 1-minute option bar's close
  price. No new position is opened on the same 5-minute bar; the next 5-minute bar's normal
  decision logic resumes.

- **Trailing profit lock.** Track the peak unrealised MTM gain on the held leg. When peak
  reaches `PROFIT_LOCK_TRIGGER` (₹2,000), the lock is armed. On every subsequent bar-close
  check (and intra-bar check), if current MTM has fallen to ≤ `peak_mtm × PROFIT_LOCK_TRAIL`
  (50% of peak), close the leg immediately. The lock floor trails upward as peak rises — a
  peak of ₹3,000 sets the floor at ₹1,500.

## Capabilities

### Modified Capabilities
- `supertrend-strategy`: two new exit rules — ST-touch intra-bar close and trailing profit
  lock — added to the existing exit hierarchy.
- `backtest`: 1-minute option chain store added for intra-bar option pricing at the touch bar.

## Impact

- `backtest_multiday.py`: new `_chain_store_1m` (1-minute option bars pre-loaded alongside
  the existing 5-minute store); `Position` gains `peak_mtm` attribute; bar loop gains (a) a
  1-minute sub-bar sweep for ST-touch detection before the bar-close checks and (b) a
  profit-lock check after the peak MTM update.
- New constants: `PROFIT_LOCK_TRIGGER = 2_000.0`, `PROFIT_LOCK_TRAIL = 0.5`.
- `SuperTrendTracker.update` already emits `st.value` (the active band line); no changes
  to the indicator layer needed.
- The existing leg-stop, flip, roll-up, and squareoff paths are unchanged in semantics;
  ST-touch and profit-lock are new, higher-priority exit branches.
- Live/paper: these are strategy rules; the same exits must be adopted in the live strategy
  for parity (tracked under the live-backtest parity initiative, not this change).
