## Why

The multiday backtest reports an implausible **profit factor of 33.5 with a 93% win rate** over 76
traded days. An audit traced this to a **systematic one-bar look-ahead on every SuperTrend flip**,
and flips are where ~100% of the strategy's profit is booked.

The `backtest` spec already mandates fills **at bar close** ("execute them at bar close (OHLC) … the
order at the bar's close price at end of bar processing", `Requirement: Order execution simulation`).
But `backtest_multiday.py` fills flip exits, flip entries, new entries, and scale-ins at the **bar's
open** via `price_at(..., prefer="open")`:

- The bar loop computes `st` from the **current bar's high/low/close** (`tracker.update(...)` at
  `backtest_multiday.py:723`), so `st.flipped` is decided by the bar's **close**.
- On that same flip bar it then closes the position at `price_at(flip_bars, ist_dt, prefer="open")`
  (`:822`) — the open price that existed **before** the close which generated the signal.

For a premium-seller, an ST flip means the underlying has just reversed favorably; booking the exit
at the *pre-reversal* open premium captures a move the strategy could not have known about at fill
time. Per-leg evidence on 2026-02-26 (+39,291 net): every leg exits on `flip`, with winners of
+10,868 / +12,987 / +5,193 against losers of −851 / −591 — the asymmetry is the look-ahead, not edge.

This is an **implementation bug that violates the existing spec**, not a missing capability. The fix
removes the look-ahead so backtest P&L is causally valid and comparable to live/paper, where a signal
from a closed bar can only be acted on at or after that bar's close.

## What Changes

- Make every backtest fill **non-anticipatory**: an action triggered by bar N's close SHALL fill at a
  price not earlier than bar N's close — never bar N's open. Concretely, replace the four
  `price_at(..., prefer="open")` fill sites in `backtest_multiday.py` (flip-close, flip/new entry,
  scale-in, and the squareoff/parity paths) with close-based (or next-bar-open) pricing consistent
  with the spec's "fill at bar close" rule.
- Decide and document the single convention used (fill at the signal bar's **close**), and apply it
  uniformly to entries and exits so no leg is priced off a bar earlier than the one that triggered it.
- Re-run the multiday backtest and record the corrected profit factor / win rate; the previous
  PF 33.5 is expected to fall materially toward a realistic level.

## Capabilities

### Modified Capabilities
- `backtest`: The order-execution-simulation requirement is sharpened to explicitly prohibit
  look-ahead — a fill triggered by a bar's close must not be priced at that bar's open — closing the
  gap between the stated "fill at bar close" rule and the `prefer="open"` implementation.

## Impact

- `backtest_multiday.py` — the four `price_at(..., prefer="open")` fill call sites (flip-close `:822`,
  new/flip entry `:851`, scale-in `:871`, and the squareoff/`_pos_bars` parity paths) switch to
  close-based pricing; `price_at`'s ±15-min nearest-bar tolerance is reviewed so it cannot reach a
  future bar for an exit.
- Result interpretation: the multiday summary's PF / win-rate / net change; prior memory'd figures
  (PF 33.5, +1.78M over 76 days) are superseded by the corrected run.
- No change to live/paper routing or the indicator engine (live already acts on closed bars); this
  brings the backtest into line with that behavior and with the existing spec.
- Tests: a unit test asserting a flip exit is priced at the flip bar's close (not its open), and that
  a synthetic favorable-reversal bar no longer books pre-reversal profit.
